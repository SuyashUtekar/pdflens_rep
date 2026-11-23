# PDFLens UI share package

This folder contains the browser UI files for sharing or reviewing the PDFLens interface:

- `index.html` — page structure
- `styles.css` and `core.css` — visual styles
- `app.js` — browser interactions

## Run it with the project

The UI expects the same-origin backend adapter routes `/ui-api/settings`, `/ui-api/health`, `/ui-api/jobs`, and `/ui-api/results`. These are provided by this project's FastAPI application. Configure that server with its own `.env` using `.env.example`, then serve the interface from `/ui/`.

Opening `index.html` directly or hosting these files as a static site will not process PDFs: browser code deliberately does not contain PDFLens endpoint URLs, credentials, or shared-storage paths. Keep real `.env` values on the server and never include them in a shared UI folder.

The source of truth remains `app/ui/`. If the interface changes, copy the updated files from `app/ui/` into this folder before sharing it.
