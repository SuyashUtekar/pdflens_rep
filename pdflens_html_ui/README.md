# PDFLens standalone HTML UI

This is an isolated, runnable copy of the older HTML/CSS/JavaScript PDFLens UI. It includes the small FastAPI gateway and hosted PDFLens API client required to submit documents and retrieve ZIP results. It does not include the local PDF parser, the React UI, notebooks, or unrelated project code.

## Folder contents

- `app/ui/` — HTML, CSS, and browser JavaScript
- `app/main.py` — serves the UI at `/ui/` and mounts the UI API routes
- `app/api/ui_gateway.py` — validates uploads, coordinates File Manager and PDFLens, and handles UI-facing requests
- `app/integrations/file_manager.py` — uploads the PDF to File Manager and builds its download URL
- `app/integrations/pdflens.py` — calls the hosted submit, result, and health APIs
- `app/configs/log_config.py` and `app/utils/log_utils.py` — configure rotating logs and format/redact event fields
- `app/config.py` — loads server-side settings from `.env`
- `app/security/pdf.py` — PDF upload validation and safe filenames
- `pyproject.toml` and `uv.lock` — Python dependencies and pinned resolution
- `Makefile` — install, run, health-check, and cleanup commands
- `.env.example` — safe configuration template

## Run it

Use Python 3.11 or newer and install `uv`. From this folder:

1. Create `.env` from `.env.example` and fill in the File Manager upload URL, File Manager download URL template, PDFLens endpoint URLs, JWT, and one `PDFLENS_CONFIG_ID`. The configuration ID stays server-side and is not displayed in the UI. Put the raw JWT in `PDFLENS_JWT_TOKEN` without the Bearer prefix; the backend adds the prefix for service calls. If File Manager uses a different token, set `FILE_MANAGER_JWT_TOKEN`.
2. Ensure the File Manager download URL is reachable and authorized for the PDFLens processor, since PDFLens will fetch the PDF from that URL.
3. Install dependencies and start the UI:

   ```sh
   make install
   make run
   ```

4. Open `http://localhost:8000/ui/`.

The browser uses the same-origin `/ui-api/*` routes. The backend keeps credentials off the browser and displays the status returned by the submit API. When result retrieval reports queued/processing, the UI repeats the result call at `PDFLENS_RESULT_POLL_INTERVAL_SECONDS` until it receives a ZIP or reaches `PDFLENS_RESULT_POLL_MAX_WAIT_SECONDS`. The UI shows the current attempt and elapsed time; server logs record each request ID, attempt, upstream state, and duration. No request history is stored in the service or browser. The request ID exists in page memory only and is lost when the page is reloaded or closed.

Backend logs go to standard output and to `LOG_PATH` (default `logs/pdflens.log`), rotating daily and retaining 14 backups. Set `LOG_LEVEL=DEBUG`, `INFO`, `WARNING`, or `ERROR` in `.env` to adjust verbosity. `app/configs/log_config.py` configures logging, while `app/utils/log_utils.py` provides the shared logger and formats event fields while redacting secret-like values. Logs cover File Manager uploads, PDFLens submissions, and each result polling attempt without logging JWTs or endpoint URLs.

Do not place credentials in `.env.example` or share a populated `.env`. For access from another machine, configure `HOST=0.0.0.0` when running `make run` only if your organization permits it, then use that PC's reachable address.
