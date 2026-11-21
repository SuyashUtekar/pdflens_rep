# PDFLens UI package for the organization PC

This folder is a standalone copy of the PDFLens browser UI and the small FastAPI gateway it needs. It does not include the local PDF parser or unrelated project notebooks and tools.

## Included

- `app/ui/` — HTML, CSS, and JavaScript interface
- `app/api/ui_gateway.py` — UI upload, configuration, health, submit, and result routes
- `app/integrations/pdflens.py` — calls the hosted PDFLens submit, health, and result APIs
- `app/config.py` — reads server-side `.env` settings
- `app/security/pdf.py` — validates and safely names uploaded PDFs
- `app/main.py` — serves the UI at `/ui/` and mounts the gateway routes
- `pyproject.toml`, `Makefile`, `.env.example` — install, run, and configuration files

## Setup with uv

1. Copy this folder to the organization PC.
2. Install `uv` and use a supported Python version (3.11 or newer).
3. In this folder, copy `.env.example` to `.env` and enter the exact API URLs, raw JWT in PDFLENS_JWT_TOKEN, valid configuration IDs, and shared storage path supplied by your PDFLens administrator. The backend adds the Bearer prefix; do not put the prefix inside the token value. Restart the app after replacing an expired token.
4. Make sure the hosted PDFLens service can read files at the configured shared storage path. If the UI and PDFLens run in different machines or containers, mount the same storage location at the configured path on both sides.
5. Run:

   ```sh
   make install
   make run
   ```

6. Open `http://localhost:8000/ui/` on that PC. Set `HOST` and `PORT` when running `make run` if needed. The default listens only on that PC; use `HOST=0.0.0.0` only if the UI must be reachable from another machine and your network policy permits it.

The browser calls this app's same-origin `/ui-api/*` routes. The backend sends the PDFLens request and API credentials; these values are not exposed in browser JavaScript. If result retrieval reports queued/processing, the browser retries at the configured interval until a ZIP arrives or the maximum wait expires. The interface shows elapsed time and attempt number; server logs record the request ID, attempt, upstream state, and duration. No request history is saved; the current request is held in page memory only until the page is reloaded or closed.

Do not copy real credentials into `.env.example` or share a populated `.env`. The `.env` file is ignored by version control by convention; protect it according to your organization’s secret-handling rules.
