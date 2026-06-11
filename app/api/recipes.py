"""Read-only JSON API endpoints: search, facets, recipe detail."""

from __future__ import annotations

from pathlib import Path
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, Response

from app.api.deps import require_token
from app.api.schemas import (
    FacetCountOut,
    FacetsResponse,
    FlagRequest,
    RecipeDetailResponse,
    RecipeWriteRequest,
    SearchResponse,
    WriteResponse,
)
from app.core.validator import ValidationIssue
from app.db import queries
from app.services.recipes import (
    RecipeNotFoundError,
    WriteOutcome,
    create_recipe,
    set_archived,
    set_favorite,
    update_recipe,
)
from app.web.deps import get_db_path, get_recipes_dir
from app.web.library import TIME_CEILING, SortParam, _resolve_sort

router = APIRouter(prefix="/api/v1")

DEFAULT_PAGE_SIZE = 24
MAX_PAGE_SIZE = 100


def _normalize_minutes(
    max_minutes: int | None, min_minutes: int | None
) -> tuple[int | None, int | None]:
    """Slider extremes mean "no bound" — drop them, mirroring the web library."""
    if min_minutes is not None and min_minutes <= 0:
        min_minutes = None
    if max_minutes is not None and max_minutes >= TIME_CEILING:
        max_minutes = None
    return max_minutes, min_minutes


@router.get("/recipes")
def list_recipes(
    db_path: Annotated[Path, Depends(get_db_path)],
    q: Annotated[str | None, Query()] = None,
    tag: Annotated[list[str] | None, Query()] = None,
    cuisine: Annotated[list[str] | None, Query()] = None,
    meal: Annotated[list[str] | None, Query()] = None,
    diet: Annotated[list[str] | None, Query()] = None,
    max_minutes: Annotated[int | None, Query(ge=0, le=600)] = None,
    min_minutes: Annotated[int | None, Query(ge=0, le=600)] = None,
    favorite: Annotated[bool, Query()] = False,
    sort: Annotated[SortParam | None, Query()] = None,
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1, le=MAX_PAGE_SIZE)] = DEFAULT_PAGE_SIZE,
) -> SearchResponse:
    resolved_sort = _resolve_sort(sort, q)
    bounded_max, bounded_min = _normalize_minutes(max_minutes, min_minutes)
    search_page = queries.search_library(
        db_path,
        query=q,
        tags=tag or [],
        cuisines=cuisine or [],
        meal_types=meal or [],
        dietary=diet or [],
        max_minutes=bounded_max,
        min_minutes=bounded_min,
        favorites_only=favorite,
        sort=resolved_sort,
        limit=page_size,
        offset=(page - 1) * page_size,
    )
    return SearchResponse.from_page(search_page, page_num=page, page_size=page_size)


@router.get("/facets")
def facets(
    db_path: Annotated[Path, Depends(get_db_path)],
    q: Annotated[str | None, Query()] = None,
    tag: Annotated[list[str] | None, Query()] = None,
    cuisine: Annotated[list[str] | None, Query()] = None,
    meal: Annotated[list[str] | None, Query()] = None,
    diet: Annotated[list[str] | None, Query()] = None,
    max_minutes: Annotated[int | None, Query(ge=0, le=600)] = None,
    min_minutes: Annotated[int | None, Query(ge=0, le=600)] = None,
    favorite: Annotated[bool, Query()] = False,
) -> FacetsResponse:
    bounded_max, bounded_min = _normalize_minutes(max_minutes, min_minutes)
    tags = tag or []
    cuisines = cuisine or []
    meal_types = meal or []
    dietary = diet or []

    def _counts(group: str) -> list[FacetCountOut]:
        fn = {
            "tags": queries.facet_counts_tags,
            "cuisines": queries.facet_counts_cuisines,
            "meal_types": queries.facet_counts_meal_types,
            "dietary": queries.facet_counts_dietary,
        }[group]
        return [
            FacetCountOut.from_facet(f)
            for f in fn(
                db_path,
                query=q,
                tags=tags,
                cuisines=cuisines,
                meal_types=meal_types,
                dietary=dietary,
                max_minutes=bounded_max,
                min_minutes=bounded_min,
                favorites_only=favorite,
            )
        ]

    return FacetsResponse(
        tags=_counts("tags"),
        cuisines=_counts("cuisines"),
        meal_types=_counts("meal_types"),
        dietary=_counts("dietary"),
    )


@router.get("/recipes/{slug}")
def get_recipe(slug: str, db_path: Annotated[Path, Depends(get_db_path)]) -> RecipeDetailResponse:
    detail = queries.get_recipe_detail(db_path, slug)
    if detail is None:
        raise HTTPException(status_code=404, detail=f"No recipe with slug {slug!r}")
    return RecipeDetailResponse.from_detail(detail)


# ---------------------------------------------------------------------------
# Write endpoints (Bearer token required)
# ---------------------------------------------------------------------------


def _issue_dict(issue: ValidationIssue) -> dict[str, str]:
    return {
        "level": str(issue.level),
        "code": issue.code,
        "message": issue.message,
        "path": issue.path,
    }


def _raise_for_outcome(outcome: WriteOutcome) -> None:
    """Raise the appropriate HTTPException for a failed ``WriteOutcome``. No-op if ok."""
    if outcome.sync_errors:
        raise HTTPException(
            status_code=500,
            detail={"code": "sync_error", "message": "; ".join(outcome.sync_errors)},
        )
    if outcome.issues:
        status = 409 if any(i.code == "slug.collision" for i in outcome.issues) else 422
        raise HTTPException(
            status_code=status,
            detail={
                "code": "validation_error",
                "message": "Recipe could not be saved",
                "issues": [_issue_dict(i) for i in outcome.issues],
            },
        )


def _write_response(outcome: WriteOutcome, recipes_dir: Path) -> WriteResponse:
    assert outcome.path is not None
    return WriteResponse(slug=outcome.slug, path=str(outcome.path.relative_to(recipes_dir)))


@router.post("/recipes", status_code=201)
def create_recipe_endpoint(
    payload: RecipeWriteRequest,
    response: Response,
    recipes_dir: Annotated[Path, Depends(get_recipes_dir)],
    db_path: Annotated[Path, Depends(get_db_path)],
    token_name: Annotated[str, Depends(require_token)],
) -> WriteResponse:
    outcome = create_recipe(payload.to_draft(), recipes_dir=recipes_dir, db_path=db_path)
    _raise_for_outcome(outcome)
    response.headers["Location"] = f"/api/v1/recipes/{outcome.slug}"
    return _write_response(outcome, recipes_dir)


@router.put("/recipes/{slug}")
def update_recipe_endpoint(
    slug: str,
    payload: RecipeWriteRequest,
    recipes_dir: Annotated[Path, Depends(get_recipes_dir)],
    db_path: Annotated[Path, Depends(get_db_path)],
    token_name: Annotated[str, Depends(require_token)],
) -> WriteResponse:
    try:
        outcome = update_recipe(slug, payload.to_draft(), recipes_dir=recipes_dir, db_path=db_path)
    except RecipeNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    _raise_for_outcome(outcome)
    return _write_response(outcome, recipes_dir)


@router.put("/recipes/{slug}/archived")
def set_archived_endpoint(
    slug: str,
    payload: FlagRequest,
    recipes_dir: Annotated[Path, Depends(get_recipes_dir)],
    db_path: Annotated[Path, Depends(get_db_path)],
    token_name: Annotated[str, Depends(require_token)],
) -> WriteResponse:
    try:
        outcome = set_archived(slug, payload.value, recipes_dir=recipes_dir, db_path=db_path)
    except RecipeNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    _raise_for_outcome(outcome)
    return _write_response(outcome, recipes_dir)


@router.put("/recipes/{slug}/favorite")
def set_favorite_endpoint(
    slug: str,
    payload: FlagRequest,
    recipes_dir: Annotated[Path, Depends(get_recipes_dir)],
    db_path: Annotated[Path, Depends(get_db_path)],
    token_name: Annotated[str, Depends(require_token)],
) -> WriteResponse:
    try:
        outcome = set_favorite(slug, payload.value, recipes_dir=recipes_dir, db_path=db_path)
    except RecipeNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    _raise_for_outcome(outcome)
    return _write_response(outcome, recipes_dir)
