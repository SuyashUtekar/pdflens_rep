from __future__ import annotations

import time
from datetime import datetime, timezone
from urllib.parse import urlsplit

from fastapi import APIRouter, File, Form, HTTPException, UploadFile
from fastapi.responses import JSONResponse, Response
from pydantic import BaseModel, Field, field_validator
from starlette.concurrency import run_in_threadpool

from app.config import settings
from app.integrations.file_manager import FileManagerError, upload_file
from app.integrations.pdflens import PdfLensUpstreamError, health_check, retrieve_result, submit_pdf
from app.security.pdf import MAX_UPLOAD_BYTES, count_pdf_pages, safe_filename, validate_pdf
from app.utils.log_utils import get_app_logger, info, warning

logger = get_app_logger()
router = APIRouter(prefix="/ui-api", tags=["PDFLens UI gateway"])


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
    return {
        "configured": bool(settings.config_id),
        "file_manager_configured": bool(
            settings.file_manager_upload_url and "{file_id}" in settings.file_manager_download_url_template
        ),
        "callback_configured": bool(settings.callback_url),
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
    callback_url: str = Form(""),
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

    selected_callback_url = callback_url.strip() or settings.callback_url
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
    }


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
