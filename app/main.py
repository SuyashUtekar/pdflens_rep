from __future__ import annotations

import hashlib
import logging
import os
import re
import tempfile
import time
import uuid
from datetime import datetime, timezone
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path

from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.responses import Response
from starlette.concurrency import run_in_threadpool

from app.artifacts.package import build_package
from app.parsers.docling_adapter import (FOOTNOTE_ZONE_START, FURNITURE_REPEAT_FRACTION,
                                         FURNITURE_ZONE_FRACTION, DoclingAdapter,
                                         ParserExecutionError, ParserUnavailableError)
from app.schemas.models import (DocumentInfo, ExtractionField, ExtractionRequest,
                                FieldExtractionStatus, Metadata, ProcessingInfo)
from app.security.pdf import MAX_UPLOAD_BYTES, safe_filename, validate_pdf

ADAPTER_VERSION = "0.3.0"
APP_BUILD_ID = os.getenv("PDFLENS_BUILD_ID", f"pdflens-replacement-adapter-{ADAPTER_VERSION}")
logging.basicConfig(level=os.getenv("LOG_LEVEL", "INFO"))
logger = logging.getLogger("pdflens")
app = FastAPI(title="PDFLens Replacement", version="0.2.0",
              description="PDF extraction evaluation service; legacy compatibility is pending contract discovery.")
MAX_PAGES = int(os.getenv("PDFLENS_MAX_PAGES", "500"))
PARSER = DoclingAdapter()


def _assemble_body_text(page) -> str:
    """Assemble body text and asset markers once, discarding exact duplicate spans."""
    parts: list[str] = []
    seen: set[str] = set()
    duplicate_chars = 0
    extracted_body_chars = 0
    for element in sorted(page.elements, key=lambda item: item.reading_order):
        if element.type == ExtractionField.BODY_TEXT and element.text:
            value = element.text
        elif element.type in {ExtractionField.IMAGE, ExtractionField.TABLE}:
            name = element.artifact_path or element.element_id
            kind = "IMAGE" if element.type == ExtractionField.IMAGE else "TABLE"
            value = f"[[{kind}: {name}]]"
        else:
            continue
        normalized = re.sub(r"\s+", " ", value).strip().casefold()
        if normalized and normalized in seen:
            duplicate_chars += len(value)
            continue
        if normalized:
            seen.add(normalized)
            if element.type == ExtractionField.BODY_TEXT:
                extracted_body_chars += len(value.strip())
        parts.append(value)
    page.duplicate_text_char_count = duplicate_chars
    page.body_text_char_count = extracted_body_chars
    if duplicate_chars:
        page.warnings.append("BODY_TEXT_EXACT_DUPLICATE_REMOVED")
    return "\n".join(parts)


def _dependency_versions() -> dict[str, str]:
    packages = ("docling", "docling-core", "pypdf", "pdfplumber", "python-docx")
    found: dict[str, str] = {}
    for package in packages:
        try:
            found[package] = version(package)
        except PackageNotFoundError:
            found[package] = "not_installed"
    return found


@app.get("/healthz")
def health() -> dict[str, str]:
    return {"status": "ok", "service": "pdflens-replacement"}


@app.get("/readyz")
def readiness() -> Response:
    if not PARSER.check_available():
        return Response(status_code=503,
                        content='{"status":"not_ready","reason":"parser_unavailable"}',
                        media_type="application/json")
    return Response(content='{"status":"ready","service":"pdflens-replacement"}',
                    media_type="application/json")


@app.post("/v1/extract")
async def extract(file: UploadFile = File(...),
                  extraction_fields: str = Form("body_text,heading,header,footer,page_number,footnote,hyperlink,image,table"),
                  output_mode: str = Form("legacy_compatible"),
                  ocr_mode: str = Form("auto")) -> Response:
    request_id = str(uuid.uuid4())
    started_at = time.perf_counter()
    try:
        fields = [ExtractionField(field.strip()) for field in extraction_fields.split(",")
                  if field.strip()]
        request = ExtractionRequest(extraction_fields=fields, output_mode=output_mode,
                                    ocr_mode=ocr_mode)
    except ValueError as exc:
        raise HTTPException(422, detail={"code": "INVALID_REQUEST", "request_id": request_id,
                                         "message": "Unknown extraction field or invalid request."}) from exc

    data = await file.read(MAX_UPLOAD_BYTES + 1)
    try:
        validate_pdf(data)
    except OverflowError as exc:
        raise HTTPException(413, detail={"code": "FILE_TOO_LARGE", "request_id": request_id,
                                         "message": str(exc)}) from exc
    except ValueError as exc:
        raise HTTPException(415, detail={"code": "INVALID_PDF", "request_id": request_id,
                                         "message": str(exc)}) from exc

    filename = safe_filename(file.filename)
    archive_filename = f"{Path(filename).stem}.zip"
    source_hash = hashlib.sha256(data).hexdigest()
    with tempfile.TemporaryDirectory(prefix="pdflens-") as temporary:
        root = Path(temporary)
        source = root / filename
        output = root / archive_filename
        source.write_bytes(data)
        try:
            parsed = await run_in_threadpool(PARSER.parse, str(source),
                                             set(request.extraction_fields))
        except ParserUnavailableError as exc:
            logger.warning("parser unavailable request_id=%s", request_id)
            raise HTTPException(503, detail={"code": "PARSER_UNAVAILABLE", "request_id": request_id,
                                             "message": "PDF parser is not installed in the active environment."}) from exc
        except ParserExecutionError as exc:
            logger.error("parser failure request_id=%s stage=%s cause_type=%s",
                         request_id, exc.stage, exc.cause_type)
            raise HTTPException(500, detail={"code": "PARSER_FAILURE", "request_id": request_id,
                                             "message": "PDF parsing failed."}) from exc
        except Exception as exc:
            logger.error("parser failure request_id=%s error_type=%s", request_id, type(exc).__name__)
            raise HTTPException(500, detail={"code": "PARSER_FAILURE", "request_id": request_id,
                                             "message": "PDF parsing failed."}) from exc
        if len(parsed.pages) > MAX_PAGES:
            raise HTTPException(413, detail={"code": "PAGE_LIMIT_EXCEEDED", "request_id": request_id,
                                             "message": f"PDF exceeds the {MAX_PAGES}-page limit."})

        selected = set(request.extraction_fields)
        warning_pages: dict[str, set[int]] = {}
        for page in parsed.pages:
            page.elements = [element for element in page.elements if element.type in selected]
            page.body_text = _assemble_body_text(page)
            page.body_text_to_source_text_ratio = (
                page.body_text_char_count / page.source_text_char_count
                if page.source_text_char_count else None
            )
            page_text = "\n".join(element.text or "" for element in page.elements)
            if "\ufffd" in page_text or any(
                ord(character) < 32 and character not in "\n\r\t" for character in page_text
            ) or any(marker in page_text for marker in ("Ã", "Â", "â€", "ï¿½")):
                page.warnings.append("UNICODE_SUSPECT")
            if ExtractionField.PAGE_NUMBER in selected and not page.printed_page_label:
                page.warnings.append("PAGE_LABEL_NOT_DETECTED")

            page.field_status = {}
            for field in ExtractionField:
                if field not in selected:
                    status = FieldExtractionStatus.NOT_REQUESTED
                else:
                    field_elements = [element for element in page.elements if element.type == field]
                    if not field_elements:
                        status = FieldExtractionStatus.NOT_DETECTED
                    elif field == ExtractionField.TABLE and any(
                        element.attributes.get("table_validation_status") != "validated"
                        for element in field_elements
                    ):
                        status = FieldExtractionStatus.NEEDS_REVIEW
                    elif field == ExtractionField.BODY_TEXT and (
                        page.duplicate_text_char_count
                        or any(warning in page.warnings for warning in (
                            "BODY_TEXT_FALLBACK_USED", "BODY_TEXT_FALLBACK_OVERLAP_REMOVED",
                            "BODY_TEXT_EXACT_DUPLICATE_REMOVED", "UNICODE_SUSPECT",
                        ))
                    ):
                        status = FieldExtractionStatus.NEEDS_REVIEW
                    elif field == ExtractionField.FOOTNOTE and any(
                        element.confidence is not None and element.confidence < 0.7
                        for element in field_elements
                    ):
                        status = FieldExtractionStatus.NEEDS_REVIEW
                    else:
                        status = FieldExtractionStatus.EXTRACTED_UNVALIDATED
                page.field_status[field.value] = status

            for warning in page.warnings:
                warning_pages.setdefault(warning, set()).add(page.page_number)

        warning_summary = {code: len(page_numbers)
                           for code, page_numbers in sorted(warning_pages.items())}
        parser_warnings = [warning for warning in parsed.warnings
                           if not re.match(r"^page \d+: ", warning)]
        for code, page_numbers in sorted(warning_pages.items()):
            logger.warning("extraction_quality request_id=%s code=%s page_count=%d pages=%s",
                           request_id, code, len(page_numbers),
                           ",".join(map(str, sorted(page_numbers))))
        parsed.warnings = parser_warnings + [
            f"{code}: {count} page(s) affected" for code, count in warning_summary.items()
        ]
        quality_warnings = bool(warning_summary) or any(
            not warning.startswith(("Parser mapping and coordinate convention",
                                    "Headers and footers use Docling furniture-tree"))
            for warning in parser_warnings
        )
        extracted_fields = {element.type for page in parsed.pages for element in page.elements}
        metadata = Metadata(
            document=DocumentInfo(source_filename=filename, source_sha256=source_hash,
                                  page_count=len(parsed.pages), title=parsed.title),
            processing=ProcessingInfo(
                parser_name=parsed.parser_name,
                parser_version=parsed.parser_version,
                adapter_version=ADAPTER_VERSION,
                run_id=request_id,
                processed_at_utc=datetime.now(timezone.utc).isoformat(),
                build_id=APP_BUILD_ID,
                configuration={
                    "extraction_fields": [field.value for field in request.extraction_fields],
                    "output_mode": request.output_mode,
                    "ocr_mode": request.ocr_mode,
                    "max_pages": MAX_PAGES,
                    "furniture_zone_fraction": FURNITURE_ZONE_FRACTION,
                    "furniture_repeat_fraction": FURNITURE_REPEAT_FRACTION,
                    "footnote_zone_start": FOOTNOTE_ZONE_START,
                },
                dependency_versions=_dependency_versions(),
                requested_fields=request.extraction_fields,
                extracted_fields=sorted(extracted_fields, key=lambda item: item.value),
                missing_fields=sorted(selected - extracted_fields, key=lambda item: item.value),
                status="partial_success" if selected - extracted_fields or quality_warnings else "success",
                warnings=parsed.warnings,
                warning_summary=warning_summary,
            ),
            pages=parsed.pages,
        )
        requested_assets = [asset for asset in parsed.assets if asset.asset_type in selected]
        try:
            build_package(metadata, output, source, requested_assets)
        except Exception as exc:
            logger.error("artifact generation failure request_id=%s error_type=%s",
                         request_id, type(exc).__name__)
            raise HTTPException(500, detail={"code": "ARTIFACT_GENERATION_FAILED",
                                             "request_id": request_id,
                                             "message": "Could not generate the output package."}) from exc
        response_data = output.read_bytes()
        logger.info(
            "extraction_complete request_id=%s build_id=%s file_sha256=%s pages=%d status=%s duration_ms=%d output_bytes=%d",
            request_id, APP_BUILD_ID, source_hash, len(parsed.pages), metadata.processing.status,
            round((time.perf_counter() - started_at) * 1000), len(response_data),
        )
        return Response(content=response_data, media_type="application/zip",
                        headers={"Content-Disposition": f'attachment; filename="{archive_filename}"',
                                 "X-Request-ID": request_id})
