"""FastAPI entrypoint. Stage 3 mounts /static and the web router."""

from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from app.web import router as web_router

STATIC_DIR = Path(__file__).resolve().parent / "static"

app = FastAPI(title="Recipe App", version="0.1.0")
app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")
app.include_router(web_router)


@app.get("/healthz")
def healthz() -> dict[str, str]:
    """Liveness probe used by Docker and CI smoke tests."""
    return {"status": "ok"}
