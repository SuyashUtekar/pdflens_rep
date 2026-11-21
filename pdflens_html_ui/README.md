# PDFLens standalone HTML UI

This is an isolated, runnable copy of the older HTML/CSS/JavaScript PDFLens UI. It includes the small FastAPI gateway and hosted PDFLens API client required to submit documents and retrieve ZIP results. It does not include the local PDF parser, the React UI, notebooks, or unrelated project code.

## Folder contents

- `app/ui/` — HTML, CSS, and browser JavaScript
- `app/main.py` — serves the UI at `/ui/` and mounts the UI API routes
- `app/api/ui_gateway.py` — validates and stages uploads, then handles UI-facing requests
- `app/integrations/pdflens.py` — calls the hosted submit, result, and health APIs
- `app/config.py` — loads server-side settings from `.env`
- `app/security/pdf.py` — PDF upload validation and safe filenames
- `pyproject.toml` and `uv.lock` — Python dependencies and pinned resolution
- `Makefile` — install, run, health-check, and cleanup commands
- `.env.example` — safe configuration template

## Run it

Use Python 3.11 or newer and install `uv`. From this folder:

1. Create `.env` from `.env.example` and fill it with the exact endpoint URLs, JWT, configuration IDs, and shared storage path from your PDFLens administrator. Put the raw JWT in PDFLENS_JWT_TOKEN without the Bearer prefix; the backend adds the configured prefix and sends it in the authorization header for hosted API calls. If the JWT expires, replace it in `.env` and restart this app.
2. Ensure the hosted PDFLens service can read the configured shared storage path. If it runs on another machine or container, mount the same storage at the same path there.
3. Install dependencies and start the UI:

   ```sh
   make install
   make run
   ```

4. Open `http://localhost:8000/ui/`.

The browser uses the same-origin `/ui-api/*` routes. The backend keeps credentials off the browser and displays the status returned by the submit API. When result retrieval reports queued/processing, the UI repeats the result call at `PDFLENS_RESULT_POLL_INTERVAL_SECONDS` until it receives a ZIP or reaches `PDFLENS_RESULT_POLL_MAX_WAIT_SECONDS`. The UI shows the current attempt and elapsed time; server logs record each request ID, attempt, upstream state, and duration. No request history is stored in the service or browser. The request ID exists in page memory only and is lost when the page is reloaded or closed.

Do not place credentials in `.env.example` or share a populated `.env`. For access from another machine, configure `HOST=0.0.0.0` when running `make run` only if your organization permits it, then use that PC's reachable address.
