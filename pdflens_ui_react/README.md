# PDFLens React UI

A new React + TypeScript + Vite browser app for the hosted PDFLens API workflow. It uses the existing FastAPI adapter at `/ui-api/*`; PDFLens credentials and shared-storage settings stay in the backend `.env`.

## Requirements

- Node.js 20.19+ or 22.12+
- `npm`
- The PDFLens UI backend running on `http://127.0.0.1:8000` (see `../share_with_org_pc/`)

## Development

From this folder, start the backend in one terminal:

```sh
cd ../share_with_org_pc
make install
make run
```

Then start the React app in another terminal:

```sh
cd ../pdflens_ui_react
npm install
npm run dev
```

Open the URL printed by Vite (usually `http://localhost:5173/ui/`). Vite proxies `/ui-api/*` requests to the FastAPI backend. To use a different backend address for development, set `UI_BACKEND_ORIGIN` in a local `.env.development` file; this value is only used by Vite's development proxy and must not contain credentials.

## Production build

```sh
npm run build
```

The static site is written to `dist/`. Serve that output under `/ui/` and configure the web server to forward `/ui-api/*` to the FastAPI backend. Keep the frontend and API on the same origin so browser requests work without exposing API credentials or adding unnecessary cross-origin configuration. The existing FastAPI app currently serves the legacy UI at `/ui/`; a production deployment must route `/ui/` to this build when switching to the new UI.

The dashboard shows request and ZIP-download totals plus the latest requests. The Request History view stores each successful submission's request ID, returned status, filename, size, configuration, extraction options, and ZIP download record in this browser's local storage, so the history remains after refresh in the same browser profile. It does not synchronize to other devices or store PDF/ZIP contents. Results are retrieved manually by request ID; the app does not poll for status or claim progress the hosted API does not provide.
