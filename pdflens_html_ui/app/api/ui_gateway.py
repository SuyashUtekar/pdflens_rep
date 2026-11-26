from __future__ import annotations

import asyncio
import hmac
import json
import time
from datetime import datetime, timezone
from urllib.parse import parse_qs, quote, urljoin, urlsplit

from fastapi import APIRouter, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import JSONResponse, Response, StreamingResponse
from pydantic import BaseModel, Field, field_validator
from starlette.concurrency import run_in_threadpool

from app.config import settings
from app.integrations.file_manager import FileManagerError, upload_file
from app.integrations.pdflens import PdfLensUpstreamError, health_check, retrieve_result, submit_pdf
from app.security.pdf import MAX_UPLOAD_BYTES, count_pdf_pages, safe_filename, validate_pdf
from app.utils.log_utils import get_app_logger, info, warning

logger = get_app_logger()
router = APIRouter(prefix="/ui-api", tags=["PDFLens UI gateway"])
_webhook_events: dict[str, list[dict[str, object]]] = {}
_webhook_subscribers: dict[str, set[asyncio.Queue[dict[str, object]]]] = {}
_webhook_event_id = 0
_MAX_WEBHOOK_REQUESTS = 500
_MAX_WEBHOOK_EVENTS_PER_REQUEST = 200
_WEBHOOK_QUERY_PARAMETER = "token"
_WEBHOOK_HEADER = "X-PDFLens-Webhook-Token"
_REQUEST_ID_FIELDS = {"request_id", "requestid"}
_STATUS_FIELDS = {"status", "state", "processing_status", "processingstatus"}


def _default_webhook_url() -> str:
    if not settings.webhook_public_base_url or not settings.webhook_secret:
        return ""
    try:
        base = urlsplit(settings.webhook_public_base_url)
        if (
            base.scheme not in {"http", "https"}
            or not base.hostname
            or base.username is not None
            or base.password is not None
            or (base.port is not None and not 1 <= base.port <= 65535)
        ):
            return ""
        endpoint = urljoin(f"{settings.webhook_public_base_url}/", "ui-api/webhook")
        query_key = quote(_WEBHOOK_QUERY_PARAMETER, safe="")
        return f"{endpoint}?{query_key}={quote(settings.webhook_secret, safe='')}"
    except ValueError:
        return ""


def _is_ui_webhook_url(value: str) -> bool:
    if not settings.webhook_secret:
        return False
    try:
        candidate = urlsplit(value)
        expected = urlsplit(_default_webhook_url())
        candidate_token = parse_qs(candidate.query).get(_WEBHOOK_QUERY_PARAMETER, [""])[0]
        return bool(
            expected.hostname
            and candidate.scheme in {"http", "https"}
            and candidate.hostname.casefold() == expected.hostname.casefold()
            and candidate.port == expected.port
            and candidate.path.rstrip("/") == expected.path.rstrip("/")
            and (not candidate_token or hmac.compare_digest(candidate_token, settings.webhook_secret))
        )
    except ValueError:
        return False


def _callback_field(payload: object, names: set[str]) -> str:
    if isinstance(payload, dict):
        for key, value in payload.items():
            normalized = str(key).casefold().replace("-", "_")
            compact = normalized.replace("_", "")
            if (normalized in names or compact in names) and isinstance(value, (str, int)):
                value = str(value).strip()
                if value:
                    return value
        nested_keys = {"data", "event", "payload", "result", "detail"}
        for key, nested in payload.items():
            if str(key).casefold() in nested_keys:
                found = _callback_field(nested, names)
                if found:
                    return found
    return ""


def _publish_webhook_event(request_id: str, status: str) -> dict[str, object]:
    global _webhook_event_id
    if request_id not in _webhook_events and len(_webhook_events) >= _MAX_WEBHOOK_REQUESTS:
        oldest_request_id = next(iter(_webhook_events))
        _webhook_events.pop(oldest_request_id, None)
        _webhook_subscribers.pop(oldest_request_id, None)
    _webhook_event_id += 1
    event = {
        "event_id": _webhook_event_id,
        "request_id": request_id,
        "status": status,
        "received_at": datetime.now(timezone.utc).isoformat(),
    }
    events = _webhook_events.setdefault(request_id, [])
    events.append(event)
    if len(events) > _MAX_WEBHOOK_EVENTS_PER_REQUEST:
        del events[:-_MAX_WEBHOOK_EVENTS_PER_REQUEST]
    for queue in tuple(_webhook_subscribers.get(request_id, set())):
        if queue.full():
            try:
                queue.get_nowait()
            except asyncio.QueueEmpty:
                pass
        queue.put_nowait(event)
    return event


class ResultRequest(BaseModel):
    request_id: str = Field(min_length=1, max_length=300)
    attempt: int = Field(default=1, ge=1, le=100000)

    @field_validator("request_id")
    @classmethod
    def non_blank_request_id(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("request_id cannot be blank")
        return value


@router.get("/settings")
def ui_settings() -> dict[str, object]:
    callback_configured = bool(_default_webhook_url())
    return {
        "configured": bool(settings.config_id),
        "file_manager_configured": bool(
            settings.file_manager_upload_url and "{file_id}" in settings.file_manager_download_url_template
        ),
        "callback_configured": callback_configured,
        "webhook_receiver_ready": bool(_default_webhook_url()),
        "callback_uses_app_receiver_by_default": bool(_default_webhook_url()),
        "result_poll_interval_seconds": settings.result_poll_interval_seconds,
        "result_poll_max_wait_seconds": settings.result_poll_max_wait_seconds,
    }


@router.get("/health")
def remote_health() -> dict[str, object]:
    try:
        return health_check()
    except PdfLensUpstreamError as exc:
        return {"available": False, "message": str(exc)}


@router.post("/pdf-info")
async def inspect_pdf(file: UploadFile = File(...)) -> dict[str, object]:
    content = await file.read(MAX_UPLOAD_BYTES + 1)
    try:
        validate_pdf(content)
    except OverflowError as exc:
        raise HTTPException(status_code=413, detail="This PDF exceeds the upload limit.") from exc
    except ValueError as exc:
        raise HTTPException(status_code=415, detail="Choose a valid PDF file.") from exc
    page_count = await run_in_threadpool(count_pdf_pages, content)
    info(logger, "pdf_page_count_inspected", filename=safe_filename(file.filename), page_count=page_count)
    return {
        "filename": safe_filename(file.filename),
        "page_count": page_count,
        "page_count_available": page_count is not None,
    }


@router.post("/jobs")
async def submit_job(
    file: UploadFile = File(...),
    extract_tables: bool = Form(True),
    extract_images: bool = Form(True),
    extract_header: bool = Form(True),
    extract_footer: bool = Form(True),
    extract_hyperlinks: bool = Form(True),
    extract_footnotes: bool = Form(False),
    start_page: int | None = Form(None),
    end_page: int | None = Form(None),
) -> dict[str, object]:
    if not settings.config_id:
        raise HTTPException(status_code=503, detail="PDFLENS_CONFIG_ID is not configured on the UI service.")
    if (start_page is None) != (end_page is None):
        raise HTTPException(status_code=422, detail="Provide both start_page and end_page, or leave both blank.")
    if start_page is not None and end_page is not None:
        if start_page < 1 or end_page < 1:
            raise HTTPException(status_code=422, detail="Page numbers must be 1 or greater.")
        if start_page > end_page:
            raise HTTPException(status_code=422, detail="start_page must be less than or equal to end_page.")

    content = await file.read(MAX_UPLOAD_BYTES + 1)
    try:
        validate_pdf(content)
    except OverflowError as exc:
        raise HTTPException(status_code=413, detail="This PDF exceeds the upload limit.") from exc
    except ValueError as exc:
        raise HTTPException(status_code=415, detail="Choose a valid PDF file.") from exc
    page_count = await run_in_threadpool(count_pdf_pages, content)
    if start_page is not None and end_page is not None:
        if page_count is None:
            raise HTTPException(status_code=422, detail="The PDF page count could not be read, so a page range cannot be verified.")
        if end_page > page_count:
            raise HTTPException(
                status_code=422,
                detail=f"End page cannot exceed this PDF's {page_count}-page limit.",
            )

    selected_callback_url = _default_webhook_url()
    if selected_callback_url:
        try:
            callback_parts = urlsplit(selected_callback_url)
            valid_callback_url = (
                callback_parts.scheme in {"http", "https"}
                and bool(callback_parts.hostname)
                and callback_parts.username is None
                and callback_parts.password is None
                and (callback_parts.port is None or 1 <= callback_parts.port <= 65535)
            )
        except ValueError:
            valid_callback_url = False
        if not valid_callback_url:
            raise HTTPException(status_code=422, detail="Callback URL must be a valid HTTP or HTTPS URL without embedded credentials.")

    try:
        file_record = await run_in_threadpool(
            upload_file,
            content,
            safe_filename(file.filename),
            file.content_type or "application/pdf",
        )
    except FileManagerError as exc:
        warning(logger, "file_manager_upload_failed", error=exc)
        raise HTTPException(
            status_code=exc.status_code,
            detail=str(exc),
        ) from exc

    # PDFLens receives File Manager's download URL, never a browser or local filesystem path.
    upstream_body = {
        "file_path": file_record["download_url"],
        "config_id": settings.config_id,
        "extract_tables": extract_tables,
        "extract_images": extract_images,
        "extract_header": extract_header,
        "extract_footer": extract_footer,
        "extract_hyperlinks": extract_hyperlinks,
        "extract_footnotes": extract_footnotes,
    }
    if start_page is not None and end_page is not None:
        upstream_body["start_page"] = start_page
        upstream_body["end_page"] = end_page
    if selected_callback_url:
        upstream_body["callback_url"] = selected_callback_url
    info(logger, "pdflens_submit_started", file_id=file_record["file_id"],
         extract_tables=extract_tables, extract_images=extract_images,
         extract_header=extract_header, extract_footer=extract_footer,
         extract_hyperlinks=extract_hyperlinks, extract_footnotes=extract_footnotes,
         start_page=start_page, end_page=end_page, pdf_page_count=page_count,
         callback_url_provided=bool(selected_callback_url))
    try:
        result = await run_in_threadpool(submit_pdf, upstream_body)
    except PdfLensUpstreamError as exc:
        warning(logger, "pdflens_submit_failed", error=exc)
        raise HTTPException(status_code=exc.status_code, detail=str(exc)) from exc

    info(logger, "pdflens_submit_accepted", request_id=result["request_id"], file_id=file_record["file_id"])
    return {
        "request_id": result["request_id"],
        "status": result["status"],
        "filename": safe_filename(file.filename),
        "page_count": page_count,
        "submitted_at": datetime.now(timezone.utc).isoformat(),
        "callback_configured": bool(selected_callback_url),
        "webhook_enabled": _is_ui_webhook_url(selected_callback_url),
    }


@router.post("/webhook")
async def receive_pdflens_webhook(
    request: Request,
) -> dict[str, object]:
    """Accept a minimal PDFLens request_id/status callback and publish it to the UI."""
    if not settings.webhook_secret:
        raise HTTPException(status_code=503, detail="PDFLens webhook receiver is not configured.")
    supplied_token = request.query_params.get(_WEBHOOK_QUERY_PARAMETER, "")
    if not supplied_token:
        supplied_token = request.headers.get(_WEBHOOK_HEADER, "")
        if not supplied_token:
            authorization = request.headers.get("Authorization", "")
            if authorization.lower().startswith("bearer "):
                supplied_token = authorization[7:].strip()
    if not hmac.compare_digest(supplied_token, settings.webhook_secret):
        warning(logger, "pdflens_webhook_rejected", reason="invalid_token")
        raise HTTPException(status_code=401, detail="Webhook authentication failed.")
    raw_body = await request.body()
    if len(raw_body) > 64 * 1024:
        raise HTTPException(status_code=413, detail="Webhook payload is too large.")
    try:
        payload = json.loads(raw_body.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise HTTPException(status_code=400, detail="Webhook payload must be valid JSON.") from exc
    request_id = _callback_field(payload, _REQUEST_ID_FIELDS)[:300]
    status = _callback_field(payload, _STATUS_FIELDS)[:100]
    if not request_id or not status:
        raise HTTPException(status_code=422, detail="Webhook payload must contain request_id and status.")
    event = _publish_webhook_event(request_id, status)
    info(logger, "pdflens_webhook_received", request_id=request_id, upstream_status=status[:80], event_id=event["event_id"])
    return {"received": True, "request_id": request_id}


@router.get("/webhook-events/{request_id}")
async def stream_webhook_events(request_id: str) -> StreamingResponse:
    """Stream callbacks to the open UI without repeatedly requesting PDFLens status."""
    request_id = request_id.strip()
    if not request_id or len(request_id) > 300:
        raise HTTPException(status_code=422, detail="Invalid request ID.")

    async def event_stream():
        queue: asyncio.Queue[dict[str, object]] = asyncio.Queue(maxsize=100)
        _webhook_subscribers.setdefault(request_id, set()).add(queue)
        last_event_id = 0
        try:
            yield ": connected\n\n"
            for event in list(_webhook_events.get(request_id, [])):
                event_id = int(event["event_id"])
                if event_id > last_event_id:
                    last_event_id = event_id
                    yield f"event: status\ndata: {json.dumps(event, ensure_ascii=False)}\n\n"
            while True:
                try:
                    event = await asyncio.wait_for(queue.get(), timeout=20)
                except asyncio.TimeoutError:
                    yield ": keep-alive\n\n"
                    continue
                event_id = int(event["event_id"])
                if event_id <= last_event_id:
                    continue
                last_event_id = event_id
                yield f"event: status\ndata: {json.dumps(event, ensure_ascii=False)}\n\n"
        finally:
            subscribers = _webhook_subscribers.get(request_id)
            if subscribers:
                subscribers.discard(queue)
                if not subscribers:
                    _webhook_subscribers.pop(request_id, None)

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@router.post("/results")
async def get_result(request: ResultRequest) -> Response:
    started = time.monotonic()
    info(logger, "pdflens_result_poll_started", request_id=request.request_id, attempt=request.attempt)
    try:
        data, filename, upstream_state = await run_in_threadpool(retrieve_result, request.request_id.strip())
    except PdfLensUpstreamError as exc:
        warning(logger, "pdflens_result_unavailable", request_id=request.request_id, reason=exc)
        raise HTTPException(status_code=exc.status_code, detail=str(exc)) from exc
    elapsed = round(time.monotonic() - started, 3)
    if data is None:
        state = upstream_state or "processing"
        info(logger, "pdflens_result_poll", request_id=request.request_id, attempt=request.attempt,
             upstream_state=state[:80], elapsed_seconds=elapsed)
        return JSONResponse(
            status_code=202,
            content={
                "request_id": request.request_id,
                "attempt": request.attempt,
                "status": state,
                "message": "PDFLens is still processing this request.",
            },
        )
    info(logger, "pdflens_result_retrieved", request_id=request.request_id, attempt=request.attempt,
         bytes=len(data), elapsed_seconds=elapsed)
    return Response(
        content=data,
        media_type="application/zip",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )
