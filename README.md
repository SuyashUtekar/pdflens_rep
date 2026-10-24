# PDFLens Replacement

Feasibility implementation for a PDF extraction service that produces page-oriented canonical metadata and a ZIP package. This is an initial project foundation, **not a production-ready PDFLens replacement**: the legacy API/ZIP contract, parser benchmark, model/dependency licensing, corpus quality gates, and platform integrations are still open per the project plan.

## Current implementation

- FastAPI `POST /v1/extract` multipart endpoint (`file`, comma-separated `extraction_fields`, `output_mode`, `ocr_mode`).
- PDF signature and upload-size checks; opaque request ID and SHA-256 source digest.
- Optional Docling adapter with a project-owned canonical metadata model.
- Docling furniture-tree headers and footers, supplemented by repeated text at consistent page edges; page labels and footnotes are tracked separately.
- Per-page source-text counts, normalized body-text counts/ratios, explicit field statuses, and a provenance-marked pypdf fallback when Docling emits no body text for a page with a text layer.
- Table cell structures when Docling exposes them; otherwise table snapshots are labeled `visual_only`. Repeated identical image snapshots are flagged without removing page-specific files.
- Output ZIP: the original PDF, `document.docx`, `metadata.json`, `manifest.json`, plus detected crops under `images/` and `tables/` when requested and available. The DOCX is built from an in-memory structured HTML representation that preserves headings, reading order, page boundaries, links, and asset references; no HTML file is written to disk or included in the ZIP.
- DOCX is an editable text reconstruction. Image and table snapshots are separate PNG artifacts linked from their canonical metadata elements.
- `/healthz` liveness and `/readyz` parser-package readiness endpoints. Readiness does not download or warm model weights.
- Lazily initialized Docling converters are reused across requests. Model inference is serialized per process, and excess uploads receive HTTP 503 instead of accumulating in an unbounded application queue.
- Completion logs include request ID, input/output bytes, page count, final quality status, and elapsed time; document text is never logged.

The endpoint and archive names are provisional until compared with sanitized PDFLens requests, responses, and ZIPs. It has no authentication, durable job state, object storage, OCR language policy, or production worker isolation. Do not expose it to untrusted networks. Docling must be configured to produce page images for table crops; output paths and cropping need validation against a reviewed corpus.

## Local setup

Requires Python 3.11+. Install the API and parser extra, then start the service:

```sh
uv pip install --python .venv314/bin/python -e '.[docling]'
uvicorn app.main:app --reload
```

Each extraction ZIP includes the original PDF, `document.docx`, and `metadata.json`; the intermediate HTML used to format the DOCX is kept in memory and is not emitted as a file.

Run `make test` for the focused regression suite. Run `make inventory` to inspect the PDFs under `rbi_docs`; this reports page and text-layer availability and does not assess semantic extraction quality.

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
| `PDFLENS_MAX_CONCURRENT_EXTRACTIONS` | 1 | In-flight request limit per process; excess requests receive 503 with `Retry-After` |
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

See [architecture](docs/architecture.md), [API contract](docs/api-contract.md), [data mapping](docs/data-mapping.md), [operations runbook](docs/operations-runbook.md), and [license inventory](docs/license-inventory.md). This upgrade improves local service reliability; it does not claim production approval or PDFLens parity without corpus baselines and deployment decisions.
