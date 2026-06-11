"""FastAPI dependencies for the web layer.

Tests override ``get_db_path``/``get_recipes_dir``/``get_users_path`` via
``app.dependency_overrides`` to point at temp paths without monkey-patching
``load_settings``."""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Annotated

from fastapi import Depends, Request
from fastapi.templating import Jinja2Templates

from app.config import Settings, load_settings
from app.web.markdown import render_markdown

TEMPLATES_DIR = Path(__file__).resolve().parent.parent / "templates"


class AuthRequiredError(Exception):
    """Raised by ``require_user`` when a write route is hit without a session.

    ``app.main`` registers a handler that turns this into a redirect to /login.
    """

    def __init__(self, next_path: str) -> None:
        self.next_path = next_path
        super().__init__("authentication required")


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return load_settings()


def get_db_path(settings: Annotated[Settings, Depends(get_settings)]) -> Path:
    return settings.db_path


def get_recipes_dir(settings: Annotated[Settings, Depends(get_settings)]) -> Path:
    return settings.recipes_dir


def get_users_path(settings: Annotated[Settings, Depends(get_settings)]) -> Path:
    return settings.auth_path


def get_tokens_path(settings: Annotated[Settings, Depends(get_settings)]) -> Path:
    return settings.tokens_path


def current_user(request: Request) -> str | None:
    """The logged-in username, or None. Safe to call without a session."""
    return request.session.get("user")


def require_user(request: Request) -> str:
    """Return the logged-in username or raise ``AuthRequiredError``."""
    user = current_user(request)
    if user is None:
        raise AuthRequiredError(next_path=request.url.path)
    return user


def _inject_current_user(request: Request) -> dict[str, str | None]:
    """Context processor: expose ``current_user`` to every template render."""
    return {"current_user": current_user(request)}


@lru_cache(maxsize=1)
def get_templates() -> Jinja2Templates:
    templates = Jinja2Templates(
        directory=str(TEMPLATES_DIR),
        context_processors=[_inject_current_user],
    )
    templates.env.filters["md"] = render_markdown
    return templates
