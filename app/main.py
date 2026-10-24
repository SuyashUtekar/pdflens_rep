from __future__ import annotations

import hashlib
import logging
import os
import tempfile
import uuid
from pathlib import Path

from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.responses import Response
from starlette.concurrency import run_in_threadpool

from app.artifacts.package import build_package
from app.parsers.docling_adapter import DoclingAdapter, ParserExecutionError, ParserUnavailableError
from app.schemas.models import (DocumentInfo, ExtractionField, ExtractionRequest,
                                 Metadata, ProcessingInfo)
from app.security.pdf import MAX_UPLOAD_BYTES, safe_filename, validate_pdf

logging.basicConfig(level=os.getenv("LOG_LEVEL", "INFO"))
logger = logging.getLogger("pdflens")
app = FastAPI(title="PDFLens Replacement", version="0.1.0",
              description="Feasibility API; legacy compatibility is pending contract discovery.")
MAX_PAGES = int(os.getenv("PDFLENS_MAX_PAGES", "500"))


@app.get("/healthz")
def health() -> dict[str, str]:
    return {"status": "ok", "service": "pdflens-replacement"}


@app.post("/v1/extract")
async def extract(file: UploadFile = File(...),
                  extraction_fields: str = Form("body_text,heading,header,footer,page_number,footnote,hyperlink,image,table"),
                  output_mode: str = Form("legacy_compatible"),
                  ocr_mode: str = Form("auto")) -> Response:
    request_id = str(uuid.uuid4())
    try:
        fields = [ExtractionField(field.strip()) for field in extraction_fields.split(",") if field.strip()]
        request = ExtractionRequest(extraction_fields=fields, output_mode=output_mode, ocr_mode=ocr_mode)
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
            parsed = await run_in_threadpool(
                DoclingAdapter().parse, str(source), set(request.extraction_fields)
            )
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
        for page in parsed.pages:
            page.elements = [element for element in page.elements if element.type in selected]
        metadata = Metadata(
            document=DocumentInfo(source_filename=filename, source_sha256=source_hash,
                                  page_count=len(parsed.pages), title=parsed.title),
            processing=ProcessingInfo(
                parser_name=parsed.parser_name, parser_version=parsed.parser_version,
                requested_fields=request.extraction_fields,
                extracted_fields=sorted(parsed.extracted_fields, key=lambda x: x.value),
                missing_fields=sorted(selected - parsed.extracted_fields, key=lambda x: x.value),
                status="partial_success" if selected - parsed.extracted_fields else "success",
                warnings=parsed.warnings),
            pages=parsed.pages,
        )
        requested_assets = [asset for asset in parsed.assets
                            if asset.asset_type in selected]
        try:
            build_package(metadata, output, source, requested_assets)
        except Exception as exc:
            logger.error("artifact generation failure request_id=%s error_type=%s",
                         request_id, type(exc).__name__)
            raise HTTPException(500, detail={"code": "ARTIFACT_GENERATION_FAILED",
                                             "request_id": request_id,
                                             "message": "Could not generate the output package."}) from exc
        return Response(content=output.read_bytes(), media_type="application/zip",
                        headers={"Content-Disposition": f'attachment; filename="{archive_filename}"',
                                 "X-Request-ID": request_id})

