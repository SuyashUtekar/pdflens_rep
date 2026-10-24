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
- `/healthz` liveness and `/readyz` parser-package readiness endpoints. Readiness does not warm models.
- Reused Docling pipelines, serialized model inference, and aggregate quality warnings with page counts to identify without flooding logs.
- Metadata schema 1.2 records run/build identity, UTC processing time, extraction configuration, runtime dependency versions, warning counts, per-page review states, and checksums.
- Fallback text removes exact spans already emitted as typed elements; repeated body blocks are removed and counted. Uncertain footnote candidates stay in body text.
- Repeated identical image/table bytes are packaged once while each occurrence keeps its page element and bounding box. Generated PNG and DOCX structure are checked before ZIP creation.

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

Running headers and footers are collected from Docling’s furniture tree and explicit page-furniture labels. Repeated, position-matched PDF text supplements that signal only when it recurs across a configurable share of pages; one-off page titles are not promoted. Explicit Docling heading labels remain headings. Low-confidence footnote candidates are also retained in body text. Page labels are separate from physical indices; hyperlink targets come from PDF annotations and adjacent visible character fragments are joined using geometry.

## Configuration

| Variable | Default | Purpose |
|---|---:|---|
| `PDFLENS_MAX_UPLOAD_BYTES` | 52428800 | Maximum uploaded PDF size |
| `PDFLENS_MAX_PAGES` | 500 | Maximum parsed page count |
| `PDFLENS_FURNITURE_ZONE_FRACTION` | 0.12 | Page-edge zone used when assessing repeating headers and footers |
| `PDFLENS_FURNITURE_REPEAT_FRACTION` | 0.10 | Minimum fraction of pages on which edge text must repeat to classify as running furniture (at least two pages) |
| `PDFLENS_FOOTNOTE_ZONE_START` | 0.78 | Lower-page boundary used as one footnote-classification signal |
| `PDFLENS_BUILD_ID` | adapter build ID | Override for identifying the exact service build in metadata |
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
