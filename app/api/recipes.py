"""Read-only JSON API endpoints: search, facets, recipe detail."""

from __future__ import annotations

from pathlib import Path
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query

from app.api.schemas import FacetCountOut, FacetsResponse, RecipeDetailResponse, SearchResponse
from app.db import queries
from app.web.deps import get_db_path
from app.web.library import TIME_CEILING, SortParam, _resolve_sort

router = APIRouter(prefix="/api/v1")

DEFAULT_PAGE_SIZE = 24
MAX_PAGE_SIZE = 100


def _normalize_minutes(max_minutes: int | None, min_minutes: int | None) -> tuple[int | None, int | None]:
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
