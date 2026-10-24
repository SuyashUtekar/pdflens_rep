from __future__ import annotations

import os
import re
from pathlib import Path

MAX_UPLOAD_BYTES = int(os.getenv("PDFLENS_MAX_UPLOAD_BYTES", str(50 * 1024 * 1024)))
MAX_FILENAME_LENGTH = 255
PDF_MAGIC = b"%PDF-"


def safe_filename(filename: str | None) -> str:
    value = Path(filename or "document.pdf").name
    value = re.sub(r"[^A-Za-z0-9._-]", "_", value)[:MAX_FILENAME_LENGTH]
    return value if value.lower().endswith(".pdf") else f"{value}.pdf"


def validate_pdf(data: bytes) -> None:
    if not data:
        raise ValueError("PDF is empty")
    if len(data) > MAX_UPLOAD_BYTES:
        raise OverflowError(f"PDF exceeds the {MAX_UPLOAD_BYTES}-byte upload limit")
    if PDF_MAGIC not in data[:1024]:
        raise ValueError("Upload does not have a valid PDF signature")
