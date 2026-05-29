"""Library page: GET / (full HTML), GET /search (HTMX fragment + OOB facets)."""

from __future__ import annotations

from pathlib import Path
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates

from app.db import queries
from app.web.deps import get_db_path, get_templates

router = APIRouter()

SortParam = Literal["relevance", "recent", "time", "title"]

# The time-range slider spans 0..TIME_CEILING. The handles at their extremes
# mean "no bound": min at the floor or max at the ceiling removes that side of
# the filter, so recipes with no time or longer than the ceiling can show.
TIME_CEILING = 180


def _resolve_sort(sort: SortParam | None, query: str | None) -> queries.SortKey:
    if sort is None:
        return "relevance" if (query and query.strip()) else "recent"
    return sort


def _gather_view_state(
    db_path: Path,
    *,
    query: str | None,
    tags: list[str],
    cuisines: list[str],
    meal_types: list[str],
    dietary: list[str],
    max_minutes: int | None,
    min_minutes: int | None,
    favorites_only: bool,
    sort: queries.SortKey,
) -> dict[str, object]:
    """Run the library + facet queries and bundle them for the templates."""
    # Slider extremes are "no bound" — drop them so no-time / very-long recipes
    # aren't filtered out, and so the slider shows its open position on return.
    if min_minutes is not None and min_minutes <= 0:
        min_minutes = None
    if max_minutes is not None and max_minutes >= TIME_CEILING:
        max_minutes = None

    results = queries.search_library(
        db_path,
        query=query,
        tags=tags,
        cuisines=cuisines,
        meal_types=meal_types,
        dietary=dietary,
        max_minutes=max_minutes,
        min_minutes=min_minutes,
        favorites_only=favorites_only,
        sort=sort,
    )
    facets = {
        "tags": queries.facet_counts_tags(
            db_path,
            query=query,
            tags=tags,
            cuisines=cuisines,
            meal_types=meal_types,
            dietary=dietary,
            max_minutes=max_minutes,
            min_minutes=min_minutes,
            favorites_only=favorites_only,
        ),
        "cuisines": queries.facet_counts_cuisines(
            db_path,
            query=query,
            tags=tags,
            cuisines=cuisines,
            meal_types=meal_types,
            dietary=dietary,
            max_minutes=max_minutes,
            min_minutes=min_minutes,
            favorites_only=favorites_only,
        ),
        "meal_types": queries.facet_counts_meal_types(
            db_path,
            query=query,
            tags=tags,
            cuisines=cuisines,
            meal_types=meal_types,
            dietary=dietary,
            max_minutes=max_minutes,
            min_minutes=min_minutes,
            favorites_only=favorites_only,
        ),
        "dietary": queries.facet_counts_dietary(
            db_path,
            query=query,
            tags=tags,
            cuisines=cuisines,
            meal_types=meal_types,
            dietary=dietary,
            max_minutes=max_minutes,
            min_minutes=min_minutes,
            favorites_only=favorites_only,
        ),
    }
    selected = {
        "q": query or "",
        "tags": set(tags),
        "cuisines": set(cuisines),
        "meal_types": set(meal_types),
        "dietary": set(dietary),
        "max_minutes": max_minutes,
        "min_minutes": min_minutes,
        "favorites_only": favorites_only,
        "sort": sort,
    }
    return {"results": results, "facets": facets, "selected": selected}


@router.get("/", response_class=HTMLResponse)
def library_page(
    request: Request,
    db_path: Annotated[Path, Depends(get_db_path)],
    templates: Annotated[Jinja2Templates, Depends(get_templates)],
    q: Annotated[str | None, Query()] = None,
    tag: Annotated[list[str] | None, Query()] = None,
    cuisine: Annotated[list[str] | None, Query()] = None,
    meal: Annotated[list[str] | None, Query()] = None,
    diet: Annotated[list[str] | None, Query()] = None,
    max_minutes: Annotated[int | None, Query(ge=0, le=600)] = None,
    min_minutes: Annotated[int | None, Query(ge=0, le=600)] = None,
    favorite: Annotated[bool, Query()] = False,
    sort: Annotated[SortParam | None, Query()] = None,
) -> HTMLResponse:
    resolved_sort = _resolve_sort(sort, q)
    ctx = _gather_view_state(
        db_path,
        query=q,
        tags=tag or [],
        cuisines=cuisine or [],
        meal_types=meal or [],
        dietary=diet or [],
        max_minutes=max_minutes,
        min_minutes=min_minutes,
        favorites_only=favorite,
        sort=resolved_sort,
    )
    return templates.TemplateResponse(request, "index.html", ctx)


@router.get("/search", response_class=HTMLResponse)
def library_search(
    request: Request,
    db_path: Annotated[Path, Depends(get_db_path)],
    templates: Annotated[Jinja2Templates, Depends(get_templates)],
    q: Annotated[str | None, Query()] = None,
    tag: Annotated[list[str] | None, Query()] = None,
    cuisine: Annotated[list[str] | None, Query()] = None,
    meal: Annotated[list[str] | None, Query()] = None,
    diet: Annotated[list[str] | None, Query()] = None,
    max_minutes: Annotated[int | None, Query(ge=0, le=600)] = None,
    min_minutes: Annotated[int | None, Query(ge=0, le=600)] = None,
    favorite: Annotated[bool, Query()] = False,
    sort: Annotated[SortParam | None, Query()] = None,
) -> HTMLResponse:
    resolved_sort = _resolve_sort(sort, q)
    ctx = _gather_view_state(
        db_path,
        query=q,
        tags=tag or [],
        cuisines=cuisine or [],
        meal_types=meal or [],
        dietary=diet or [],
        max_minutes=max_minutes,
        min_minutes=min_minutes,
        favorites_only=favorite,
        sort=resolved_sort,
    )
    return templates.TemplateResponse(request, "_search_response.html", ctx)
