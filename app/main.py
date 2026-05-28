"""FastAPI entrypoint. Stage 1 only exposes /healthz; web routes are added later."""

from __future__ import annotations

from fastapi import FastAPI

app = FastAPI(title="Recipe App", version="0.1.0")


@app.get("/healthz")
def healthz() -> dict[str, str]:
    """Liveness probe used by Docker and CI smoke tests."""
    return {"status": "ok"}
