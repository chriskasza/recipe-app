"""CRUD routes: create, edit, archive, and unarchive recipes."""

from __future__ import annotations

import io
from pathlib import Path
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import HTMLResponse, RedirectResponse, Response
from fastapi.templating import Jinja2Templates

from app.core.ids import normalize_slug
from app.core.parser import parse_file
from app.core.serializer import _yaml
from app.core.validator import IssueLevel, ValidationIssue
from app.core.vocab import DIETARY_FLAGS, MEAL_TYPES
from app.services.recipes import _flip_bool_field, _write_and_sync
from app.web.deps import get_db_path, get_recipes_dir, get_templates, require_user
from app.web.forms import (
    FormData,
    build_markdown,
    find_recipe_file,
    form_to_draft,
    parse_form,
    resolve_new_recipe_path,
    slug_in_use,
)

router = APIRouter()


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _form_ctx(
    *,
    mode: str,
    form: dict[str, Any],
    errors: list[dict[str, str]],
    warnings: list[dict[str, str]],
    action_url: str,
    slug: str = "",
    recipe_title: str = "",
) -> dict[str, Any]:
    return {
        "mode": mode,
        "form": form,
        "errors": errors,
        "warnings": warnings,
        "action_url": action_url,
        "slug": slug,
        "recipe_title": recipe_title,
        "meal_types": sorted(MEAL_TYPES),
        "dietary_flags": sorted(DIETARY_FLAGS),
    }


def _issues_to_dicts(issues: list[ValidationIssue]) -> list[dict[str, str]]:
    return [
        {"level": str(i.level), "code": i.code, "message": i.message, "path": i.path}
        for i in issues
    ]


def _split_issues(
    issues: list[ValidationIssue],
) -> tuple[list[dict[str, str]], list[dict[str, str]]]:
    errors = _issues_to_dicts([i for i in issues if i.level is IssueLevel.ERROR])
    warnings = _issues_to_dicts([i for i in issues if i.level is IssueLevel.WARNING])
    return errors, warnings


def _ingredients_to_yaml(doc: Any) -> str:
    """Dump the raw ingredients list from a parsed document back to YAML text."""
    raw_ings = doc.raw_yaml.get("ingredients")
    if not raw_ings:
        return ""
    buf = io.StringIO()
    _yaml().dump(raw_ings, buf)
    return buf.getvalue().rstrip()


def _prefill_form(doc: Any) -> FormData:
    """Build a FormData pre-filled from a parsed RecipeDocument."""
    r = doc.recipe
    src = r.source
    return FormData(
        title=r.title,
        summary=r.summary or "",
        cuisine=r.cuisine or "",
        prep_minutes=str(r.prep_minutes) if r.prep_minutes is not None else "",
        cook_minutes=str(r.cook_minutes) if r.cook_minutes is not None else "",
        total_minutes=str(r.total_minutes) if r.total_minutes is not None else "",
        servings=str(r.servings) if r.servings is not None else "",
        yield_note=r.yield_note or "",
        meal_type=list(r.meal_type),
        tags=", ".join(r.tags),
        dietary=list(r.dietary),
        equipment=", ".join(r.equipment),
        source_url=(src.url or "") if src else "",
        source_attribution=(src.attribution or "") if src else "",
        image_url=r.images[0].path if r.images else "",
        favorite=r.favorite,
        ingredients_yaml=_ingredients_to_yaml(doc),
        body=doc.raw_body or "",
    )


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------


@router.get("/new", response_class=HTMLResponse)
def new_form(
    request: Request,
    user: Annotated[str, Depends(require_user)],
    templates: Annotated[Jinja2Templates, Depends(get_templates)],
) -> HTMLResponse:
    return templates.TemplateResponse(
        request,
        "edit.html",
        _form_ctx(
            mode="new",
            form=FormData().as_dict(),
            errors=[],
            warnings=[],
            action_url="/new",
        ),
    )


@router.post("/new", response_class=HTMLResponse)
async def new_submit(
    request: Request,
    user: Annotated[str, Depends(require_user)],
    recipes_dir: Annotated[Path, Depends(get_recipes_dir)],
    db_path: Annotated[Path, Depends(get_db_path)],
    templates: Annotated[Jinja2Templates, Depends(get_templates)],
) -> Response:
    raw = await request.form()
    form = parse_form(raw)
    slug = normalize_slug(form.title) if form.title.strip() else ""

    pre_errors: list[ValidationIssue] = []
    if not form.title.strip():
        pre_errors.append(
            ValidationIssue(IssueLevel.ERROR, "title.empty", "Title is required", "title")
        )
    elif not slug:
        pre_errors.append(
            ValidationIssue(
                IssueLevel.ERROR,
                "slug.invalid",
                "Could not derive a valid slug from the title",
                "title",
            )
        )
    elif slug_in_use(recipes_dir, slug):
        pre_errors.append(
            ValidationIssue(
                IssueLevel.ERROR,
                "slug.collision",
                f"A recipe with slug '{slug}' already exists",
                "slug",
            )
        )

    if pre_errors:
        errors, warnings = _split_issues(pre_errors)
        return templates.TemplateResponse(
            request,
            "edit.html",
            _form_ctx(
                mode="new",
                form=form.as_dict(),
                errors=errors,
                warnings=warnings,
                action_url="/new",
                slug=slug,
            ),
        )

    draft, draft_issues = form_to_draft(form)
    if draft is None:
        errors, warnings = _split_issues(draft_issues)
        return templates.TemplateResponse(
            request,
            "edit.html",
            _form_ctx(
                mode="new",
                form=form.as_dict(),
                errors=errors,
                warnings=warnings,
                action_url="/new",
                slug=slug,
            ),
        )

    text, build_errors = build_markdown(
        draft,
        slug=slug,
        existing_id=None,
        existing_created_at=None,
        existing_archived=False,
        existing_nutrition=None,
    )
    if build_errors:
        errors, warnings = _split_issues(build_errors)
        return templates.TemplateResponse(
            request,
            "edit.html",
            _form_ctx(
                mode="new",
                form=form.as_dict(),
                errors=errors,
                warnings=warnings,
                action_url="/new",
                slug=slug,
            ),
        )

    path, folder_issue = resolve_new_recipe_path(recipes_dir, slug, form.folder)
    if folder_issue is not None:
        errors, warnings = _split_issues([folder_issue])
        return templates.TemplateResponse(
            request,
            "edit.html",
            _form_ctx(
                mode="new",
                form=form.as_dict(),
                errors=errors,
                warnings=warnings,
                action_url="/new",
                slug=slug,
            ),
        )
    assert path is not None
    path.parent.mkdir(parents=True, exist_ok=True)
    sync_errors = _write_and_sync(path, text, recipes_dir, db_path)
    if sync_errors:
        error_dicts = [
            {"level": "error", "code": "sync", "message": e, "path": ""} for e in sync_errors
        ]
        return templates.TemplateResponse(
            request,
            "edit.html",
            _form_ctx(
                mode="new",
                form=form.as_dict(),
                errors=error_dicts,
                warnings=[],
                action_url="/new",
                slug=slug,
            ),
        )

    return RedirectResponse(f"/r/{slug}", status_code=303)


@router.get("/r/{slug}/edit", response_class=HTMLResponse)
def edit_form(
    slug: str,
    request: Request,
    user: Annotated[str, Depends(require_user)],
    recipes_dir: Annotated[Path, Depends(get_recipes_dir)],
    templates: Annotated[Jinja2Templates, Depends(get_templates)],
) -> HTMLResponse:
    path = find_recipe_file(recipes_dir, slug)
    if path is None:
        raise HTTPException(status_code=404, detail=f"No recipe file for slug {slug!r}")
    doc, _ = parse_file(path)
    form = _prefill_form(doc)
    return templates.TemplateResponse(
        request,
        "edit.html",
        _form_ctx(
            mode="edit",
            form=form.as_dict(),
            errors=[],
            warnings=[],
            action_url=f"/r/{slug}/edit",
            slug=slug,
            recipe_title=doc.recipe.title,
        ),
    )


@router.post("/r/{slug}/edit", response_class=HTMLResponse)
async def edit_submit(
    slug: str,
    request: Request,
    user: Annotated[str, Depends(require_user)],
    recipes_dir: Annotated[Path, Depends(get_recipes_dir)],
    db_path: Annotated[Path, Depends(get_db_path)],
    templates: Annotated[Jinja2Templates, Depends(get_templates)],
) -> Response:
    path = find_recipe_file(recipes_dir, slug)
    if path is None:
        raise HTTPException(status_code=404, detail=f"No recipe file for slug {slug!r}")

    existing_doc, _ = parse_file(path)
    existing_id = existing_doc.recipe.id
    existing_created_at = existing_doc.recipe.created_at
    existing_archived = existing_doc.recipe.archived
    existing_nutrition = existing_doc.raw_yaml.get("nutrition")

    raw = await request.form()
    form = parse_form(raw)

    draft, draft_issues = form_to_draft(form)
    if draft is None:
        errors, warnings = _split_issues(draft_issues)
        return templates.TemplateResponse(
            request,
            "edit.html",
            _form_ctx(
                mode="edit",
                form=form.as_dict(),
                errors=errors,
                warnings=warnings,
                action_url=f"/r/{slug}/edit",
                slug=slug,
                recipe_title=form.title,
            ),
        )

    text, build_errors = build_markdown(
        draft,
        slug=slug,
        existing_id=existing_id,
        existing_created_at=existing_created_at,
        existing_archived=existing_archived,
        existing_nutrition=existing_nutrition,
    )
    if build_errors:
        errors, warnings = _split_issues(build_errors)
        return templates.TemplateResponse(
            request,
            "edit.html",
            _form_ctx(
                mode="edit",
                form=form.as_dict(),
                errors=errors,
                warnings=warnings,
                action_url=f"/r/{slug}/edit",
                slug=slug,
                recipe_title=form.title,
            ),
        )

    sync_errors = _write_and_sync(path, text, recipes_dir, db_path)
    if sync_errors:
        error_dicts = [
            {"level": "error", "code": "sync", "message": e, "path": ""} for e in sync_errors
        ]
        return templates.TemplateResponse(
            request,
            "edit.html",
            _form_ctx(
                mode="edit",
                form=form.as_dict(),
                errors=error_dicts,
                warnings=[],
                action_url=f"/r/{slug}/edit",
                slug=slug,
                recipe_title=form.title,
            ),
        )

    return RedirectResponse(f"/r/{slug}", status_code=303)


@router.post("/r/{slug}/archive")
def archive_recipe(
    slug: str,
    user: Annotated[str, Depends(require_user)],
    recipes_dir: Annotated[Path, Depends(get_recipes_dir)],
    db_path: Annotated[Path, Depends(get_db_path)],
) -> RedirectResponse:
    _flip_archived(slug, archived=True, recipes_dir=recipes_dir, db_path=db_path)
    return RedirectResponse(f"/r/{slug}", status_code=303)


@router.post("/r/{slug}/unarchive")
def unarchive_recipe(
    slug: str,
    user: Annotated[str, Depends(require_user)],
    recipes_dir: Annotated[Path, Depends(get_recipes_dir)],
    db_path: Annotated[Path, Depends(get_db_path)],
) -> RedirectResponse:
    _flip_archived(slug, archived=False, recipes_dir=recipes_dir, db_path=db_path)
    return RedirectResponse(f"/r/{slug}", status_code=303)


def _flip_archived(slug: str, *, archived: bool, recipes_dir: Path, db_path: Path) -> None:
    """Toggle the archived flag by mutating raw_yaml and re-serializing."""
    _flip_bool_field(
        slug, field="archived", value=archived, recipes_dir=recipes_dir, db_path=db_path
    )


@router.post("/r/{slug}/favorite")
def favorite_recipe(
    slug: str,
    user: Annotated[str, Depends(require_user)],
    recipes_dir: Annotated[Path, Depends(get_recipes_dir)],
    db_path: Annotated[Path, Depends(get_db_path)],
    next: Annotated[str, Query()] = "",
) -> RedirectResponse:
    _flip_bool_field(slug, field="favorite", value=True, recipes_dir=recipes_dir, db_path=db_path)
    return RedirectResponse(_safe_next(next, f"/r/{slug}"), status_code=303)


@router.post("/r/{slug}/unfavorite")
def unfavorite_recipe(
    slug: str,
    user: Annotated[str, Depends(require_user)],
    recipes_dir: Annotated[Path, Depends(get_recipes_dir)],
    db_path: Annotated[Path, Depends(get_db_path)],
    next: Annotated[str, Query()] = "",
) -> RedirectResponse:
    _flip_bool_field(slug, field="favorite", value=False, recipes_dir=recipes_dir, db_path=db_path)
    return RedirectResponse(_safe_next(next, f"/r/{slug}"), status_code=303)


def _safe_next(next_url: str, fallback: str) -> str:
    """Only honor same-origin relative redirects (must start with a single '/')."""
    if next_url.startswith("/") and not next_url.startswith("//"):
        return next_url
    return fallback
