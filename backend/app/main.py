"""FastAPI application: API routes plus the built frontend served from the same origin."""

import shutil

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from app.config import get_settings

settings = get_settings()

app = FastAPI(title="LabelLens", version="0.1.0")


@app.get("/api/health")
def health() -> dict[str, object]:
    tesseract = settings.tesseract_cmd or shutil.which("tesseract")
    return {"status": "ok", "tesseract_available": tesseract is not None}


# Mounted last so it never shadows /api routes. Skipped in dev, where Vite serves the frontend.
if settings.frontend_dist.is_dir():
    app.mount("/", StaticFiles(directory=settings.frontend_dist, html=True), name="frontend")
