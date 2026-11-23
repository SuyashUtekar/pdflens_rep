from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from app.api.ui_gateway import router as ui_gateway_router
from app.utils.log_utils import get_app_logger, info

logger = get_app_logger()
info(logger, "service_started", service="pdflens-ui")
app = FastAPI(title="PDFLens UI", version="1.0.0")
app.include_router(ui_gateway_router)
app.mount(
    "/ui",
    StaticFiles(directory=Path(__file__).resolve().parent / "ui", html=True),
    name="ui",
)


@app.get("/healthz")
def health() -> dict[str, str]:
    return {"status": "ok", "service": "pdflens-ui"}
