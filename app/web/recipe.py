"""Recipe detail page: GET /r/{slug}."""

from __future__ import annotations

from pathlib import Path
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates

from app.db import queries
from app.web.deps import get_db_path, get_templates

router = APIRouter()


@router.get("/r/{slug}", response_class=HTMLResponse)
def recipe_page(
    slug: str,
    request: Request,
    db_path: Annotated[Path, Depends(get_db_path)],
    templates: Annotated[Jinja2Templates, Depends(get_templates)],
) -> HTMLResponse:
    detail = queries.get_recipe_detail(db_path, slug)
    if detail is None:
        raise HTTPException(status_code=404, detail=f"No recipe with slug {slug!r}")
    return templates.TemplateResponse(request, "recipe.html", {"d": detail})
