"""FastAPI dependencies for the web layer.

Tests override ``get_db_path`` via ``app.dependency_overrides`` to point at a
populated temp DB without monkey-patching ``load_settings``."""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Annotated

from fastapi import Depends
from fastapi.templating import Jinja2Templates

from app.config import Settings, load_settings
from app.web.markdown import render_markdown

TEMPLATES_DIR = Path(__file__).resolve().parent.parent / "templates"


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return load_settings()


def get_db_path(settings: Annotated[Settings, Depends(get_settings)]) -> Path:
    return settings.db_path


def get_recipes_dir(settings: Annotated[Settings, Depends(get_settings)]) -> Path:
    return settings.recipes_dir


@lru_cache(maxsize=1)
def get_templates() -> Jinja2Templates:
    templates = Jinja2Templates(directory=str(TEMPLATES_DIR))
    templates.env.filters["md"] = render_markdown
    return templates
