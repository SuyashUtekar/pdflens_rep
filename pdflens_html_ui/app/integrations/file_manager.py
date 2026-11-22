from __future__ import annotations

import json
import logging
import mimetypes
import urllib.error
import urllib.parse
import urllib.request
import uuid
from typing import Any

from app.config import settings

logger = logging.getLogger("pdflens.file_manager")


class FileManagerError(RuntimeError):
    def __init__(self, message: str, *, status_code: int = 502) -> None:
        super().__init__(message)
        self.status_code = status_code


def _auth_headers() -> dict[str, str]:
    headers = {"Accept": "application/json"}
    token = settings.file_manager_auth_token
    if token:
        prefix = f"{settings.file_manager_jwt_prefix} " if settings.file_manager_jwt_prefix else ""
        headers[settings.file_manager_jwt_header or "Authorization"] = prefix + token
    return headers


def upload_file(content: bytes, filename: str, content_type: str) -> dict[str, str]:
    """Upload one PDF as multipart `files` and return its File Manager ID and download URL."""
    if not settings.file_manager_upload_url:
        raise FileManagerError("File Manager upload URL is not configured.", status_code=503)
    template = settings.file_manager_download_url_template
    if "{file_id}" not in template:
        raise FileManagerError(
            "File Manager download URL template must contain the {file_id} placeholder.",
            status_code=503,
        )

    boundary = f"----PDFLensUI{uuid.uuid4().hex}"
    safe_name = filename.replace('"', "_").replace("\r", "_").replace("\n", "_")
    mime_type = content_type or mimetypes.guess_type(safe_name)[0] or "application/pdf"
    field_name = settings.file_manager_upload_field.replace('"', "_")
    body = b"\r\n".join((
        f"--{boundary}".encode(),
        f'Content-Disposition: form-data; name="{field_name}"; filename="{safe_name}"'.encode("utf-8"),
        f"Content-Type: {mime_type}".encode("ascii", errors="replace"),
        b"",
        content,
        f"--{boundary}--".encode(),
        b"",
    ))
    headers = _auth_headers()
    headers["Content-Type"] = f"multipart/form-data; boundary={boundary}"
    request = urllib.request.Request(settings.file_manager_upload_url, data=body, headers=headers, method="POST")
    try:
        with urllib.request.urlopen(request, timeout=settings.timeout_seconds) as response:
            response_body = response.read(2 * 1024 * 1024 + 1)
            if len(response_body) > 2 * 1024 * 1024:
                raise FileManagerError("File Manager returned an oversized upload response.")
    except urllib.error.HTTPError as exc:
        if exc.code in {401, 403}:
            message = "File Manager did not authorize the upload. Check its JWT settings."
        else:
            message = f"File Manager upload failed (HTTP {exc.code})."
        logger.warning("file_manager_upload_http_error status=%s", exc.code)
        raise FileManagerError(message, status_code=502) from exc
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        logger.warning("file_manager_upload_connection_error error_type=%s", type(exc).__name__)
        raise FileManagerError("Could not reach File Manager. Check its URL and network connection.", status_code=502) from exc

    try:
        payload: Any = json.loads(response_body.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise FileManagerError("File Manager returned an invalid JSON upload response.") from exc
    if not isinstance(payload, dict) or str(payload.get("status", "")).casefold() != "success":
        failures = payload.get("failures") if isinstance(payload, dict) else None
        if isinstance(failures, list) and failures:
            raise FileManagerError("File Manager could not store the uploaded PDF.")
        raise FileManagerError("File Manager did not confirm that the upload succeeded.")
    results = payload.get("results")
    if not isinstance(results, list) or not results or not isinstance(results[0], dict):
        raise FileManagerError("File Manager upload response did not include a file_id.")
    file_id = results[0].get("file_id")
    if not isinstance(file_id, (str, int)) or not str(file_id).strip():
        raise FileManagerError("File Manager upload response did not include a valid file_id.")

    file_id_text = str(file_id).strip()
    download_url = template.replace("{file_id}", urllib.parse.quote(file_id_text, safe=""))
    logger.info("file_manager_upload_succeeded file_id=%s", file_id_text)
    return {"file_id": file_id_text, "download_url": download_url}
