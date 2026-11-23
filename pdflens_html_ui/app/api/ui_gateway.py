from __future__ import annotations

import time
from datetime import datetime, timezone

from fastapi import APIRouter, File, Form, HTTPException, UploadFile
from fastapi.responses import JSONResponse, Response
from pydantic import BaseModel, Field, field_validator
from starlette.concurrency import run_in_threadpool

from app.config import settings
from app.integrations.file_manager import FileManagerError, upload_file
from app.integrations.pdflens import PdfLensUpstreamError, health_check, retrieve_result, submit_pdf
from app.security.pdf import MAX_UPLOAD_BYTES, safe_filename, validate_pdf
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


@router.post("/jobs")
async def submit_job(
    file: UploadFile = File(...),
    extract_tables: bool = Form(True),
    extract_images: bool = Form(True),
    extract_header: bool = Form(True),
    extract_footer: bool = Form(True),
    extract_hyperlinks: bool = Form(True),
    extract_footnotes: bool = Form(False),
) -> dict[str, object]:
    if not settings.config_id:
        raise HTTPException(status_code=503, detail="PDFLENS_CONFIG_ID is not configured on the UI service.")

    content = await file.read(MAX_UPLOAD_BYTES + 1)
    try:
        validate_pdf(content)
    except OverflowError as exc:
        raise HTTPException(status_code=413, detail="This PDF exceeds the upload limit.") from exc
    except ValueError as exc:
        raise HTTPException(status_code=415, detail="Choose a valid PDF file.") from exc

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
    if settings.callback_url:
        upstream_body["callback_url"] = settings.callback_url
    info(logger, "pdflens_submit_started", file_id=file_record["file_id"],
         extract_tables=extract_tables, extract_images=extract_images,
         extract_header=extract_header, extract_footer=extract_footer,
         extract_hyperlinks=extract_hyperlinks, extract_footnotes=extract_footnotes)
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
        "submitted_at": datetime.now(timezone.utc).isoformat(),
        "callback_configured": bool(settings.callback_url),
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
