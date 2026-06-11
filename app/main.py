"""FastAPI entrypoint. Stage 3 mounts /static and the web router."""

from __future__ import annotations

from pathlib import Path
from urllib.parse import urlencode

from fastapi import FastAPI, Request
from fastapi.responses import RedirectResponse
from fastapi.staticfiles import StaticFiles
from starlette.middleware.sessions import SessionMiddleware

from app.api import router as api_router
from app.config import load_settings
from app.web import router as web_router
from app.web.deps import AuthRequiredError

STATIC_DIR = Path(__file__).resolve().parent / "static"

_settings = load_settings()

app = FastAPI(title="Recipe App", version="0.1.0")
app.add_middleware(
    SessionMiddleware,
    secret_key=_settings.session_secret,
    https_only=_settings.cookie_secure,
    same_site="lax",
)
app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")
app.include_router(web_router)
app.include_router(api_router)


@app.exception_handler(AuthRequiredError)
async def _auth_required_handler(request: Request, exc: AuthRequiredError) -> RedirectResponse:
    """Send unauthenticated write attempts to the login page."""
    return RedirectResponse(f"/login?{urlencode({'next': exc.next_path})}", status_code=303)


@app.get("/healthz")
def healthz() -> dict[str, str]:
    """Liveness probe used by Docker and CI smoke tests."""
    return {"status": "ok"}
