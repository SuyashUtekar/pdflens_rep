# PDFLens Replacement

Feasibility implementation for a PDF extraction service that produces page-oriented canonical metadata and a ZIP package. This is an initial project foundation, **not a production-ready PDFLens replacement**: the legacy API/ZIP contract, parser benchmark, model/dependency licensing, corpus quality gates, and platform integrations are still open per the project plan.

## Current implementation

- FastAPI `POST /v1/extract` multipart endpoint (`file`, comma-separated `extraction_fields`, `output_mode`, `ocr_mode`).
- PDF signature and upload-size checks; opaque request ID and SHA-256 source digest.
- Optional Docling adapter with a project-owned canonical metadata model.
- Docling furniture-tree headers and footers, including explicitly labeled text items; page numbers and footnotes are handled separately.
- Output ZIP: the original PDF, `document.docx`, `metadata.json`, `manifest.json`, plus detected crops under `images/` and `tables/` when requested and available. The DOCX is built from an in-memory structured HTML representation that preserves headings, reading order, page boundaries, links, and asset references; no HTML file is written to disk or included in the ZIP.
- DOCX is an editable text reconstruction. Image and table snapshots are separate PNG artifacts linked from their canonical metadata elements.
- `/healthz` liveness endpoint.

The endpoint and archive names are provisional until compared with sanitized PDFLens requests, responses, and ZIPs. It has no authentication, durable job state, object storage, OCR language policy, or production worker isolation. Do not expose it to untrusted networks. Docling must be configured to produce page images for table crops; output paths and cropping need validation against a reviewed corpus.

## Local setup

Requires Python 3.11+. Install the API and parser extra, then start the service:

```sh
uv pip install --python .venv314/bin/python -e '.[docling]'
uvicorn app.main:app --reload
```

Each extraction ZIP includes the original PDF, `document.docx`, and `metadata.json`; the intermediate HTML used to format the DOCX is kept in memory and is not emitted as a file.

Swagger UI is available at `/docs`. Example:

```sh
curl -f -X POST http://127.0.0.1:8000/v1/extract \
  -F 'file=@sample.pdf' \
  -F 'extraction_fields=body_text,heading,table,image'
```

Docling can require large model downloads and platform-specific dependencies. Pin a tested version and pre-stage approved models before deployment; this initial setup does not lock model artifacts. The default adapter currently emits a warning that parser and coordinate mappings require corpus verification.

Running headers and footers are collected by recursively resolving references in Docling’s furniture tree, then checking `doc.texts` for explicit `page_header` and `page_footer` labels. Results are deduplicated by reference, label, text, and provenance. No position-based or repeated-text inference is used for headers or footers. Explicit Docling heading labels remain headings. Footnotes use parser labels or marker patterns, while page numbers are extracted separately from PDF text spans. Hyperlinks come from PDF link annotations; visible link text is matched to overlapping PDF characters when available.

## Configuration

| Variable | Default | Purpose |
|---|---:|---|
| `PDFLENS_MAX_UPLOAD_BYTES` | 52428800 | Maximum uploaded PDF size |
| `PDFLENS_MAX_PAGES` | 500 | Maximum parsed page count |
| `LOG_LEVEL` | `INFO` | Application log level |

## Repository map

- `app/main.py`: API intake and orchestration.
- `app/parsers/`: parser interface and Docling adapter.
- `app/schemas/models.py`: canonical v1 Pydantic models.
- `app/artifacts/`: DOCX and deterministic package metadata generation.
- `app/security/`: upload validation and filename handling.
- `schemas/`: JSON Schema contracts.
- `docs/`: architecture, decisions, mapping, operations, and licensing notes.

## Development status and next gates

See [architecture](docs/architecture.md), [API contract](docs/api-contract.md), [data mapping](docs/data-mapping.md), [operations runbook](docs/operations-runbook.md), and [license inventory](docs/license-inventory.md). The next project gate is to obtain representative PDFs and matching PDFLens outputs, then benchmark Docling and MinerU and replace all provisional contract choices with evidence.
