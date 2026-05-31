"""Login / logout routes. Public read access is unaffected; these gate CRUD."""

from __future__ import annotations

from pathlib import Path
from typing import Annotated

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse, Response
from fastapi.templating import Jinja2Templates

from app.auth import store
from app.web.deps import get_templates, get_users_path

router = APIRouter()


def _safe_next(next_url: str, fallback: str) -> str:
    """Only honor same-origin relative redirects (must start with a single '/')."""
    if next_url.startswith("/") and not next_url.startswith("//"):
        return next_url
    return fallback


@router.get("/login", response_class=HTMLResponse)
def login_form(
    request: Request,
    templates: Annotated[Jinja2Templates, Depends(get_templates)],
    next: str = "",
) -> HTMLResponse:
    return templates.TemplateResponse(
        request,
        "login.html",
        {"next": next, "error": None},
    )


@router.post("/login", response_class=HTMLResponse)
def login_submit(
    request: Request,
    templates: Annotated[Jinja2Templates, Depends(get_templates)],
    users_path: Annotated[Path, Depends(get_users_path)],
    username: Annotated[str, Form()],
    password: Annotated[str, Form()],
    next: Annotated[str, Form()] = "",
) -> Response:
    if store.verify(users_path, username, password):
        request.session.clear()  # fresh session on login (defense against fixation)
        request.session["user"] = username
        return RedirectResponse(_safe_next(next, "/"), status_code=303)
    return templates.TemplateResponse(
        request,
        "login.html",
        {"next": next, "error": "Invalid username or password."},
        status_code=401,
    )


@router.post("/logout")
def logout(request: Request) -> RedirectResponse:
    request.session.clear()
    return RedirectResponse("/", status_code=303)
