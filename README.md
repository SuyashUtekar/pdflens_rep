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
- Browser UI at `/ui/` for the hosted PDFLens API: file staging, submit, result retrieval, and package inventory. It does not store request history.
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

The document workspace is available at `/ui/`. It does not call this project's local `POST /v1/extract` parser route. Its backend stages the uploaded PDF in a shared directory, then calls only the hosted PDFLens submit, result, and health APIs. The API URLs, authentication, valid configuration IDs, optional callback URL, request timeout, result poll interval and maximum wait, shared storage location, and retention period are read from `.env`; copy [.env.example](.env.example) and fill in values from your PDFLens administrator. The submit request uses the specified fields: `file_path`, `config_id`, the six extraction flags, and `callback_url` when configured. When the result API reports queued/processing, the UI repeats the result request at the configured interval until it gets the ZIP or the maximum wait expires. Poll attempts and elapsed time are shown in the UI and logged server-side. The result is checked as a ZIP archive before download.

The directory in `PDFLENS_SHARED_STORAGE_DIR` must be readable at the same path by the hosted PDFLens process. If the UI backend and PDFLens run in different hosts or containers, mount the same storage volume into both and configure group ownership/permissions so the PDFLens process can traverse directories and read files. Defaults are directory mode `0750` and file mode `0640`; use a shared group or setgid parent directory where needed. Staging cleanup runs before each new upload and removes folders older than the configured retention. If no later upload occurs, old staged files remain until cleanup runs again. The UI displays the status returned by the submit API; after the user starts result retrieval, it polls the get-result API for a ZIP response. It does not call a separate status endpoint. Request IDs are held in page memory only and are lost when the page is reloaded or closed.

To use the UI, configure `.env`, then start the application with `make run` and open `/ui/` on that host. The local `/v1/extract` endpoint remains available for separate replacement-service work; it is not used by the UI.

Docling can require large model downloads and platform-specific dependencies. Pin a tested version and pre-stage approved models before deployment; this initial setup does not lock model artifacts. The default adapter currently emits a warning that parser and coordinate mappings require corpus verification.

Running headers and footers are collected by recursively resolving references in Docling’s furniture tree, then checking `doc.texts` for explicit `page_header` and `page_footer` labels. Results are deduplicated by reference, label, text, and provenance. No position-based or repeated-text inference is used for headers or footers. Explicit Docling heading labels remain headings. Footnotes use parser labels or marker patterns, while page numbers are extracted separately from PDF text spans. Hyperlinks come from PDF link annotations; visible link text is matched to overlapping PDF characters when available.

## Configuration

| Variable | Default | Purpose |
|---|---:|---|
| `PDFLENS_MAX_UPLOAD_BYTES` | 52428800 | Maximum uploaded PDF size |
| `PDFLENS_MAX_PAGES` | 500 | Maximum parsed page count |
| `LOG_LEVEL` | `INFO` | Application log level |

Hosted PDFLens gateway settings are documented with safe placeholders in [.env.example](.env.example). Set the submit, result, and health URLs; the raw PDFLENS_JWT_TOKEN; authorization header and prefix; result/health methods; approved configuration list; optional callback URL; per-call timeout; result poll interval and maximum wait; shared file staging directory; staging retention; and maximum result ZIP size. The backend adds the configured Bearer prefix and does not send the token to browser code. Replace the endpoint and configuration values with values from the deployment administrator.

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
