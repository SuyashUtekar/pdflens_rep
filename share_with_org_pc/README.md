# PDFLens UI package for the organization PC

This folder is a standalone copy of the PDFLens browser UI and the small FastAPI gateway it needs. It does not include the local PDF parser or unrelated project notebooks and tools.

## Included

- `app/ui/` — HTML, CSS, and JavaScript interface
- `app/api/ui_gateway.py` — UI settings, upload, health, submit, and result routes
- `app/integrations/pdflens.py` — calls the hosted PDFLens submit, health, and result APIs
- `app/integrations/file_manager.py` — uploads PDFs and creates their download URLs
- `app/configs/log_config.py` and `app/utils/log_utils.py` — rotating logging setup and event formatting
- `app/config.py` — reads server-side `.env` settings
- `app/security/pdf.py` — validates and safely names uploaded PDFs
- `app/main.py` — serves the UI at `/ui/` and mounts the gateway routes
- `pyproject.toml`, `Makefile`, `.env.example` — install, run, and configuration files

## Setup with uv

1. Copy this folder to the organization PC.
2. Install `uv` and use a supported Python version (3.11 or newer).
3. In this folder, copy `.env.example` to `.env` and enter the File Manager upload URL, download URL template, PDFLens API URLs, raw JWT in `PDFLENS_JWT_TOKEN`, and one `PDFLENS_CONFIG_ID`. The ID stays server-side and is not displayed in the UI. Do not include the `Bearer ` prefix in the token; the backend adds it. If File Manager uses a different token, set `FILE_MANAGER_JWT_TOKEN`. To receive status updates in this UI, configure `PDFLENS_WEBHOOK_PUBLIC_BASE_URL` and `PDFLENS_WEBHOOK_SECRET`; PDFLens must be able to reach that base URL.
4. Ensure that PDFLens can reach and use the generated File Manager download URL to fetch each uploaded PDF.
5. Run:

   ```sh
   make install
   make run
   ```

6. Open `http://localhost:8000/ui/` on that PC. Set `HOST` and `PORT` when running `make run` if needed. The default listens only on that PC; use `HOST=0.0.0.0` only if the UI must be reachable from another machine and your network policy permits it.

Logs are written to the terminal and to `LOG_PATH` (default `logs/pdflens.log`), rotating daily with 14 backups. Set `LOG_LEVEL=DEBUG`, `INFO`, `WARNING`, or `ERROR` in `.env` to change verbosity. `app/configs/log_config.py` configures logging and `app/utils/log_utils.py` formats event logs while redacting secret-like fields.

The processed-package page can preview PDFs, DOCX text and tables, JSON, supported image snapshots, and text/CSV/XML files. Package entries can also be downloaded individually. Download DOCX files to view their complete Word styling.

The browser calls this app's same-origin `/ui-api/*` routes. The backend sends the PDFLens request and API credentials; these values are not exposed in browser JavaScript. When the in-app callback receiver is configured, the UI streams PDFLens status events. ZIP callbacks are validated and briefly cached by the receiver, then retrieved through the existing result action; JSON-only status callbacks trigger a result request to PDFLens. You can also make a one-time check. Without the receiver, Retrieve result uses interval-based checks. The interface shows elapsed time and attempt number; server logs record the request ID, attempt, upstream state, and duration. No request history is saved; the current request is held in page memory only until the page is reloaded or closed.

Do not copy real credentials into `.env.example` or share a populated `.env`. The `.env` file is ignored by version control by convention; protect it according to your organization’s secret-handling rules.
