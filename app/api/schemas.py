"""Pydantic response schemas for the JSON API. Mirrors `app/db/queries.py` rows."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict

from app.db.queries import FacetCount, LibraryRow, RecipeDetail, RecipeIngredientRow, SearchPage


class RecipeSummary(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    slug: str
    title: str
    summary: str | None
    cuisine: str | None
    total_minutes: int | None
    updated_at: str
    favorite: bool
    hero_path: str | None
    tags: tuple[str, ...]
    dietary: tuple[str, ...]
    meal_types: tuple[str, ...]

    @classmethod
    def from_row(cls, row: LibraryRow) -> RecipeSummary:
        return cls(
            id=row.id,
            slug=row.slug,
            title=row.title,
            summary=row.summary,
            cuisine=row.cuisine,
            total_minutes=row.total_minutes,
            updated_at=row.updated_at,
            favorite=row.favorite,
            hero_path=row.hero_path,
            tags=row.tags,
            dietary=row.dietary,
            meal_types=row.meal_types,
        )


class SearchResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    items: list[RecipeSummary]
    total: int
    page: int
    page_size: int
    total_pages: int

    @classmethod
    def from_page(cls, page: SearchPage, *, page_num: int, page_size: int) -> SearchResponse:
        total_pages = max(1, -(-page.total // page_size))  # ceil division
        return cls(
            items=[RecipeSummary.from_row(r) for r in page.rows],
            total=page.total,
            page=page_num,
            page_size=page_size,
            total_pages=total_pages,
        )


class FacetCountOut(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str
    count: int

    @classmethod
    def from_facet(cls, facet: FacetCount) -> FacetCountOut:
        return cls(name=facet.name, count=facet.count)


class FacetsResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    tags: list[FacetCountOut]
    cuisines: list[FacetCountOut]
    meal_types: list[FacetCountOut]
    dietary: list[FacetCountOut]


class IngredientOut(BaseModel):
    model_config = ConfigDict(extra="forbid")

    position: int
    name: str
    qty: float | None
    unit: str | None
    prep: str | None
    optional: bool
    original_text: str

    @classmethod
    def from_row(cls, row: RecipeIngredientRow) -> IngredientOut:
        return cls(
            position=row.position,
            name=row.name,
            qty=row.qty,
            unit=row.unit,
            prep=row.prep,
            optional=row.optional,
            original_text=row.original_text,
        )


class RecipeDetailResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    slug: str
    title: str
    summary: str | None
    cuisine: str | None
    servings: int | None
    prep_minutes: int | None
    cook_minutes: int | None
    total_minutes: int | None
    archived: bool
    favorite: bool
    updated_at: str
    body_markdown: str
    frontmatter: dict[str, object]
    source_url: str | None
    source_attribution: str | None
    ingredients: list[IngredientOut]
    tags: list[str]
    meal_types: list[str]
    dietary: list[str]
    equipment: list[str]

    @classmethod
    def from_detail(cls, detail: RecipeDetail) -> RecipeDetailResponse:
        r = detail.recipe
        return cls(
            id=r.id,
            slug=r.slug,
            title=r.title,
            summary=r.summary,
            cuisine=r.cuisine,
            servings=r.servings,
            prep_minutes=r.prep_minutes,
            cook_minutes=r.cook_minutes,
            total_minutes=r.total_minutes,
            archived=r.archived,
            favorite=r.favorite,
            updated_at=r.updated_at,
            body_markdown=detail.body_markdown,
            frontmatter=detail.frontmatter,
            source_url=detail.source_url,
            source_attribution=detail.source_attribution,
            ingredients=[IngredientOut.from_row(i) for i in detail.ingredients],
            tags=detail.tags,
            meal_types=detail.meal_types,
            dietary=detail.dietary,
            equipment=detail.equipment,
        )


class ErrorDetail(BaseModel):
    model_config = ConfigDict(extra="forbid")

    code: str
    message: str
