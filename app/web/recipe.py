"""Recipe detail page: GET /r/{slug}."""

from __future__ import annotations

from pathlib import Path
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import FileResponse, HTMLResponse
from fastapi.templating import Jinja2Templates

from app.db import queries
from app.web.deps import get_db_path, get_recipes_dir, get_templates

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


@router.get("/media/{path:path}")
def recipe_media(
    path: str,
    recipes_dir: Annotated[Path, Depends(get_recipes_dir)],
) -> FileResponse:
    """Serve a recipe-relative image (e.g. ``images/x.jpg``) from the corpus.

    Display-only for hero/thumbnail images referenced in recipe frontmatter.
    The resolved file must stay inside ``recipes_dir`` to block path traversal.
    """
    base = recipes_dir.resolve()
    target = (base / path).resolve()
    if base not in target.parents or not target.is_file():
        raise HTTPException(status_code=404, detail="No such media file")
    return FileResponse(target)
