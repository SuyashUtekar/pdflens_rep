from __future__ import annotations

import json
import urllib.error
import urllib.parse
import urllib.request
import zipfile
from io import BytesIO
from typing import Any

from app.config import settings
from app.utils.log_utils import get_app_logger, info, warning

logger = get_app_logger()


class PdfLensUpstreamError(RuntimeError):
    def __init__(
        self,
        message: str,
        *,
        status_code: int = 502,
        retryable: bool = False,
        upstream_status: int | None = None,
    ) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.retryable = retryable
        self.upstream_status = upstream_status


def _headers() -> dict[str, str]:
    headers = {"Accept": "application/json, application/zip"}
    if settings.auth_token:
        prefix = f"{settings.jwt_prefix} " if settings.jwt_prefix else ""
        headers[settings.jwt_header or "Authorization"] = prefix + settings.auth_token
    return headers


def _request(
    url: str,
    method: str,
    body: dict[str, Any] | None = None,
    *,
    max_bytes: int = 2 * 1024 * 1024,
) -> tuple[bytes, dict[str, str], int]:
    if not url:
        raise PdfLensUpstreamError("PDFLens endpoint URL is not configured. Set it in the .env file.", status_code=503)
    headers = _headers()
    payload = None
    if body is not None:
        payload = json.dumps(body, ensure_ascii=False).encode("utf-8")
        headers["Content-Type"] = "application/json"
    request = urllib.request.Request(url, data=payload, headers=headers, method=method)
    try:
        with urllib.request.urlopen(request, timeout=settings.timeout_seconds) as response:
            data = response.read(max_bytes + 1)
            if len(data) > max_bytes:
                raise PdfLensUpstreamError("PDFLens response exceeded the configured size limit.", status_code=502)
            return data, dict(response.headers.items()), response.status
    except urllib.error.HTTPError as exc:
        if exc.code in {401, 403}:
            message = "PDFLens did not authorize the request. Check the JWT and authorization header settings."
        elif exc.code == 404:
            message = "PDFLens returned HTTP 404. Check the endpoint URL and request ID."
        elif exc.code in {408, 429, 500, 502, 503, 504}:
            message = "PDFLens could not complete the request right now. Retry when the service is ready."
        else:
            message = f"PDFLens returned an unsuccessful response (HTTP {exc.code})."
        warning(logger, "upstream_http_error", method=method, status=exc.code)
        raise PdfLensUpstreamError(
            message,
            status_code=502,
            retryable=exc.code in {408, 429, 500, 502, 503, 504},
            upstream_status=exc.code,
        ) from exc
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        warning(logger, "upstream_connection_error", method=method, error_type=type(exc).__name__)
        raise PdfLensUpstreamError(
            "Could not reach PDFLens. Check the service URL, network connection, and timeout settings.",
            status_code=504 if isinstance(exc, TimeoutError) else 502,
            retryable=True,
        ) from exc


def health_check() -> dict[str, bool]:
    if settings.health_method not in {"GET", "POST"}:
        raise PdfLensUpstreamError("PDFLENS_API_HEALTH_METHOD must be GET or POST.", status_code=503)
    _data, _headers_out, status = _request(settings.health_url, settings.health_method)
    return {"available": 200 <= status < 300}


def submit_pdf(body: dict[str, Any]) -> dict[str, Any]:
    data, _headers_out, _status = _request(settings.submit_url, "POST", body)
    try:
        payload = json.loads(data.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise PdfLensUpstreamError("PDFLens returned a response that was not valid JSON.") from exc
    if not isinstance(payload, dict):
        raise PdfLensUpstreamError("PDFLens returned an incomplete submission response.")
    request_id = payload.get("request_id", payload.get("Request_id", payload.get("RequestId")))
    status = payload.get("status", payload.get("Status"))
    if not isinstance(request_id, (str, int)) or not str(request_id).strip() or status is None:
        raise PdfLensUpstreamError("PDFLens submission response must include request_id and status.")
    return {"request_id": str(request_id), "status": status}


def _response_status(payload: Any) -> str | None:
    if isinstance(payload, str):
        return payload.strip() or None
    if not isinstance(payload, dict):
        return None
    status_keys = {"status", "state", "processing_status", "request_status", "status_code", "code"}
    nested_keys = {"detail", "data", "result", "message"}
    for key, value in payload.items():
        if str(key).casefold() in status_keys and isinstance(value, (str, int)) and str(value).strip():
            return str(value).strip()
    for key, value in payload.items():
        if str(key).casefold() in nested_keys and isinstance(value, (dict, str)):
            nested = _response_status(value)
            if nested:
                return nested
    return None


def _is_pending_status(value: str) -> bool:
    normalized = value.casefold().replace("-", "_").replace(" ", "_")
    return any(token in normalized for token in (
        "queue", "pending", "process", "in_progress", "running", "accepted", "submitted", "started",
        "not_ready", "not_available", "unavailable",
    ))


def _is_failed_status(value: str) -> bool:
    normalized = value.casefold()
    return any(token in normalized for token in (
        "fail", "error", "reject", "cancel", "expired", "dead_letter",
    ))


def retrieve_result(request_id: str) -> tuple[bytes | None, str | None, str | None]:
    """Make one result request; return a pending status until the upstream returns a ZIP."""
    method = settings.result_method
    if method not in {"GET", "POST"}:
        raise PdfLensUpstreamError("PDFLENS_API_RESULT_METHOD must be GET or POST.", status_code=503)
    try:
        info(logger, "pdflens_result_request_started", request_id=request_id, method=method)
        if method == "GET":
            separator = "&" if "?" in settings.result_url else "?"
            url = settings.result_url + separator + urllib.parse.urlencode({"request_id": request_id})
            data, headers, response_status = _request(url, "GET", max_bytes=settings.max_result_bytes)
        else:
            data, headers, response_status = _request(
                settings.result_url, "POST", {"request_id": request_id}, max_bytes=settings.max_result_bytes,
            )
    except PdfLensUpstreamError as exc:
        if not exc.retryable:
            raise
        warning(
            logger,
            "result_poll_transient_error",
            request_id=request_id,
            http_status=exc.upstream_status or exc.status_code,
            method=method,
        )
        return None, None, "retrying"

    content_type = headers.get("Content-Type", "").lower()
    if data.startswith((b"PK\x03\x04", b"PK\x05\x06")) or "zip" in content_type:
        validate_result_zip(data)
        filename = _zip_filename(headers.get("Content-Disposition", ""), request_id)
        info(logger, "result_poll_zip_ready", request_id=request_id, http_status=response_status, method=method)
        return data, filename, None

    try:
        payload = json.loads(data.decode("utf-8")) if data else {}
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise PdfLensUpstreamError("PDFLens returned neither a ZIP file nor a readable processing status.") from exc
    status = _response_status(payload)
    if response_status == 202:
        status = status or "processing"
        info(logger, "result_poll_pending", request_id=request_id, upstream_status=status[:80],
             http_status=response_status, method=method)
        return None, None, status
    if status and _is_pending_status(status):
        info(logger, "result_poll_pending", request_id=request_id, upstream_status=status[:80],
             http_status=response_status, method=method)
        return None, None, status
    if status and _is_failed_status(status):
        warning(logger, "result_poll_failed", request_id=request_id, upstream_status=status[:80], method=method)
        raise PdfLensUpstreamError(f"PDFLens reported a terminal processing status: {status[:80]}.", status_code=502)
    raise PdfLensUpstreamError("PDFLens has not returned a ZIP or a recognized queued/processing status.")


def validate_result_zip(data: bytes) -> list[str]:
    try:
        with zipfile.ZipFile(BytesIO(data)) as archive:
            members = archive.infolist()
            if len(members) > 2000:
                raise PdfLensUpstreamError("The result ZIP contains too many files.")
            expanded_size = 0
            names: list[str] = []
            for member in members:
                name = member.filename.replace("\\", "/")
                parts = name.split("/")
                if name.startswith("/") or ".." in parts or (parts and ":" in parts[0]):
                    raise PdfLensUpstreamError("The result ZIP contains an unsafe file path.")
                if (member.external_attr >> 16) & 0o170000 == 0o120000:
                    raise PdfLensUpstreamError("The result ZIP contains a symbolic link.")
                expanded_size += member.file_size
                if expanded_size > 1024 * 1024 * 1024:
                    raise PdfLensUpstreamError("The result ZIP expands beyond the allowed size.")
                if member.file_size and (not member.compress_size or member.file_size / member.compress_size > 1000):
                    raise PdfLensUpstreamError("The result ZIP contains an unsafe compression ratio.")
                if not member.is_dir():
                    names.append(name)
            if not names:
                raise PdfLensUpstreamError("The result ZIP does not contain any files.")
            return names
    except zipfile.BadZipFile as exc:
        raise PdfLensUpstreamError("PDFLens returned a damaged or invalid ZIP package.") from exc


def _zip_filename(disposition: str, request_id: str) -> str:
    import re

    match = re.search(r"filename\*?=(?:UTF-8''|\")?([^\";]+)", disposition, re.IGNORECASE)
    candidate = match.group(1).strip().strip('"') if match else f"pdflens-{request_id[:12]}.zip"
    candidate = candidate.replace("\\", "/").split("/")[-1]
    candidate = re.sub(r"[^A-Za-z0-9._-]", "_", candidate)[:180]
    return candidate if candidate.lower().endswith(".zip") else f"{candidate}.zip"
