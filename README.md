# PDFLens Replacement

Feasibility implementation for a PDF extraction service that produces page-oriented canonical metadata and a ZIP package. This is an initial project foundation, **not a production-ready PDFLens replacement**: the legacy API/ZIP contract, parser benchmark, model/dependency licensing, corpus quality gates, and platform integrations are still open per the project plan.

## Current implementation

- FastAPI `POST /v1/extract` multipart endpoint (`file`, comma-separated `extraction_fields`, `output_mode`, `ocr_mode`).
- PDF signature and upload-size checks; opaque request ID and SHA-256 source digest.
- Optional Docling adapter with a project-owned canonical metadata model.
- Docling furniture-tree headers and footers, including explicitly labeled text items; page numbers and footnotes are handled separately.
- Output ZIP: the original PDF, `document.docx`, `metadata.json`, `manifest.json`, plus detected crops under `images/` and `tables/` when requested and available. The DOCX is built directly with `python-docx`, using Word heading/list styles, source-page breaks, link targets, and PDF text-line fallback for text Docling omitted. Combined headings are split when separate source lines and structural numbering support the split.
- DOCX is an editable text reconstruction. Images and tables appear as `<doc_ai type="image|table" id="..."/>` tags; their PNG snapshots remain separate ZIP artifacts referenced by canonical metadata. Header, footer, footnote, and verified page-number elements are omitted from the DOCX body.
- `/healthz` liveness endpoint.
- Browser UI at `/ui/` for File Manager uploads and hosted PDFLens submission, result retrieval, and package inventory. It does not store request history.
- Hosted-service adapter routes under `/ui-api/`. These are internal routes for the browser UI; outbound PDFLens calls are limited to submit, result, and health.

The endpoint and archive names are provisional until compared with sanitized PDFLens requests, responses, and ZIPs. It has no authentication, durable job state, object storage, OCR language policy, or production worker isolation. Do not expose it to untrusted networks. Docling must be configured to produce page images for table crops; output paths and cropping need validation against a reviewed corpus.

## Local setup

Requires Python 3.11+. Install the API and parser extra, then start the service:

```sh
uv pip install --python .venv314/bin/python -e '.[docling]'
uvicorn app.main:app --reload
```

Each extraction ZIP includes the original PDF, `document.docx`, and `metadata.json`. The application generates the DOCX directly; it does not create an HTML intermediate.

Swagger UI is available at `/docs`. Example:

```sh
curl -f -X POST http://127.0.0.1:8000/v1/extract \
  -F 'file=@sample.pdf' \
  -F 'extraction_fields=body_text,heading,table,image'
```

The document workspace is available at `/ui/`. It does not call this project's local `POST /v1/extract` parser route. The backend first sends the uploaded PDF to File Manager's multipart upload API using the `files` field. It reads the returned `file_id`, builds the download URL from `FILE_MANAGER_API_DOWNLOAD_URL_TEMPLATE`, and sends that URL as PDFLens's `file_path` with the single `PDFLENS_CONFIG_ID`, selected extraction flags, optional callback URL, and optional inclusive `start_page`/`end_page` range. A callback URL entered in the UI takes precedence over the optional `.env` default. Leave both page fields blank to process the full PDF. The configuration ID is kept server-side and is not shown in the UI. It then calls the hosted PDFLens result and health APIs. Configure both services' URLs, authentication, the one PDFLens configuration ID, optional callback default, request timeout, and result polling in `.env`; copy [.env.example](.env.example) and fill in values from the service administrators. When PDFLens returns a queued or processing status, click Retrieve result to start polling at the configured interval until it gets the ZIP or the maximum wait expires. Poll attempts and elapsed time are shown in the UI and logged server-side. The result is checked as a ZIP archive before download.

The File Manager download URL must be reachable by the PDFLens processor and authorized in a way that processor can use. Set `FILE_MANAGER_JWT_TOKEN` if File Manager uses a different token; otherwise the PDFLens JWT is reused for File Manager uploads. Request IDs are held in page memory only and are lost when the page is reloaded or closed.

To use the UI, configure `.env`, then start the application with `make run` and open `/ui/` on that host. The local `/v1/extract` endpoint remains available for separate replacement-service work; it is not used by the UI.

Docling can require large model downloads and platform-specific dependencies. Pin a tested version and pre-stage approved models before deployment; this initial setup does not lock model artifacts. The default adapter currently emits a warning that parser and coordinate mappings require corpus verification.

Running headers and footers are collected by recursively resolving references in Docling’s furniture tree, then checking `doc.texts` for explicit `page_header` and `page_footer` labels. Results are deduplicated by reference, label, text, and provenance. No position-based or repeated-text inference is used for headers or footers. Explicit Docling heading labels remain headings. Footnotes use parser labels or marker patterns, while page numbers are extracted separately from PDF text spans. Hyperlinks come from PDF link annotations; visible link text is matched to overlapping PDF characters when available.

## Configuration

| Variable | Default | Purpose |
|---|---:|---|
| `PDFLENS_MAX_UPLOAD_BYTES` | 52428800 | Maximum uploaded PDF size |
| `PDFLENS_MAX_PAGES` | 500 | Maximum parsed page count |
| `LOG_LEVEL` | `INFO` | Application log level |

Hosted PDFLens and File Manager gateway settings are documented with safe placeholders in [.env.example](.env.example). Set the service endpoint URLs, JWTs, upload field name, single PDFLens configuration ID, optional callback URL, timeout, result poll interval and maximum wait, and maximum result ZIP size. The backend adds the configured Bearer prefix and does not send credentials to browser code. Replace the endpoint and configuration values with values from the service administrators.

## Repository map

- `app/`: FastAPI application, parser adapter, schemas, artifact generation, and browser UI.
- `app/ui/`: same-origin HTML, CSS, and JavaScript served at `/ui/`.
- `chunking_strategy/`: section-aware DOCX chunking helpers.
- `docs/`: API, architecture, benchmark, mapping, licensing, and operations documentation.
- `docs/plans/`: project plans and validation/remediation plans.
- `fixtures/`: small reference fixtures used for manual review.
- `notebooks/`: active extraction and chunking experiments.
- `notebooks/archive/`: older POC versions retained for reference.
- `schemas/`: JSON Schema contracts.
- `scripts/`: standalone support utilities.
- `tests/`: reserved for automated tests (no test source files are currently committed).

The top level is reserved for project configuration (`pyproject.toml`, `uv.lock`, `Makefile`, `Dockerfile`) and this README.

## Development status and next gates

See [architecture](docs/architecture.md), [API contract](docs/api-contract.md), [data mapping](docs/data-mapping.md), [operations runbook](docs/operations-runbook.md), [license inventory](docs/license-inventory.md), and the [plan index](docs/plans/README.md). The next project gate is to obtain representative PDFs and matching PDFLens outputs, then benchmark Docling and MinerU and replace all provisional contract choices with evidence.
