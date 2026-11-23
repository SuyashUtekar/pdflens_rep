# API contract (provisional)

The existing PDFLens interface is not present in this repository. This is a development contract only and must be mapped to the existing consumer interface before compatibility is claimed.

## `POST /v1/extract`

Multipart form fields:

- `file`: required PDF upload.
- `extraction_fields`: comma-separated canonical field names; default is body text, headings, headers, footers, footnotes, hyperlinks, images, and tables.
- `output_mode`: currently accepted as a compatibility placeholder.
- `ocr_mode`: currently accepted as a placeholder; OCR behavior is controlled by parser defaults.

Successful response: `application/zip` with the original uploaded PDF, `document.docx`, `metadata.json`, `manifest.json`, and requested image/table PNGs when Docling can produce them. The DOCX is generated directly with Word paragraph and heading styles, source-page sections, and preserved hyperlinks. Tables and images are represented by `<doc_ai>` tags, with snapshots separately stored under `tables/` and `images/`; their paths are referenced by `artifact_path` in metadata. Header/footer, footnote, and verified page-number elements are excluded from the DOCX body. Selectable PDF lines omitted by Docling are restored when they are not already represented or inside a structured table/image region. Errors use FastAPI's `detail` object containing `code`, `message`, and `request_id`; status/code mapping is provisional. `GET /healthz` reports this application's liveness. No `/readyz` or capacity endpoint is currently implemented.

Per-page metadata includes the one-based physical index, printed page label when found, source/body text counts and ratio, field statuses, and review warnings. A pypdf fallback is used only when Docling emits no body text for a page with extractable text; the fallback source and reason are recorded on its element. Table cells are included when exposed by Docling and are marked `needs_review`; table snapshots without cell data are marked `visual_only`. A document with quality warnings is returned as `partial_success` with its ZIP so callers can inspect and decide how to handle it.

## Hosted PDFLens APIs used by the browser UI

The browser UI does not call this project's local `POST /v1/extract`. On upload, the UI gateway first calls the configured File Manager upload API using multipart field `files`. It reads the returned `file_id`, inserts it into `FILE_MANAGER_API_DOWNLOAD_URL_TEMPLATE`, and uses the resulting URL for PDFLens `file_path`. The UI gateway then calls the three hosted PDFLens APIs configured in `.env.example`:

1. Submit: `POST` JSON containing `file_path`, the server-configured `PDFLENS_CONFIG_ID`, the extraction booleans, optional `start_page` and `end_page`, and optional `callback_url`; the response supplies `request_id` and `status`. The page range is inclusive; omit both page fields to process the full PDF. The configuration ID is never sent from or displayed in the browser UI.
2. Result: configured method and URL, sending `request_id`; the response may first be JSON with a queued/processing state (including HTTP 202), and later returns a ZIP archive.
3. Health: configured method and URL, defaulting to `GET`.

File Manager and PDFLens endpoint URLs, authentication, the single `PDFLENS_CONFIG_ID`, result/health methods, callback URL, timeouts, result polling interval, and maximum polling wait come from `.env`. The generated File Manager download URL must be reachable and usable by the PDFLens processor. File Manager may use a separate JWT; if `FILE_MANAGER_JWT_TOKEN` is blank, the PDFLens JWT is reused. The result is checked for ZIP structure, unsafe paths, symlinks, member count, expanded size, and compression ratios before the gateway returns it.

The gateway's `/ui-api/settings`, `/ui-api/health`, `/ui-api/jobs`, and `/ui-api/results` routes are application adapter routes for the browser. They are not additional PDFLens APIs. The user starts result retrieval with the request ID; while the hosted get-result API reports queued/processing (or a retryable transient failure), the browser repeats that same get-result request at the configured interval until a ZIP arrives or the configured maximum wait expires. No separate status endpoint is called and no request history is stored. The local replacement endpoint and hosted PDFLens service are separate integrations.

Before production use, map the exact endpoint URLs, authentication, request/response fields, status vocabulary, error body, ZIP member paths, page index convention, and all keys consumed by Intelligent Search. Keep the public API backward compatible where possible and version necessary breaks explicitly.
