"""Form decoding for the web CRUD layer.

The shared write plumbing (Markdown generation, file resolution, and the
write-then-sync pipeline) lives in ``app.services.recipes`` so it can be
reused by the JSON API. The names below are re-exported here for backward
compatibility with existing imports in ``app.web.crud``.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from app.services.recipes import (
    _flow_seq,
    _parse_int,
    _split_csv,
    _validate_url,
    build_markdown,
    find_recipe_file,
    resolve_new_recipe_path,
    slug_in_use,
)

__all__ = [
    "FormData",
    "_flow_seq",
    "_parse_int",
    "_split_csv",
    "_validate_url",
    "build_markdown",
    "find_recipe_file",
    "parse_form",
    "resolve_new_recipe_path",
    "slug_in_use",
]


@dataclass
class FormData:
    title: str = ""
    summary: str = ""
    cuisine: str = ""
    prep_minutes: str = ""
    cook_minutes: str = ""
    total_minutes: str = ""
    servings: str = ""
    yield_note: str = ""
    meal_type: list[str] = field(default_factory=list)
    tags: str = ""
    dietary: list[str] = field(default_factory=list)
    equipment: str = ""
    source_url: str = ""
    source_attribution: str = ""
    image_url: str = ""
    favorite: bool = False
    folder: str = ""
    ingredients_yaml: str = ""
    body: str = ""

    def as_dict(self) -> dict[str, Any]:
        return {
            "title": self.title,
            "summary": self.summary,
            "cuisine": self.cuisine,
            "prep_minutes": self.prep_minutes,
            "cook_minutes": self.cook_minutes,
            "total_minutes": self.total_minutes,
            "servings": self.servings,
            "yield_note": self.yield_note,
            "meal_type": self.meal_type,
            "tags": self.tags,
            "dietary": self.dietary,
            "equipment": self.equipment,
            "source_url": self.source_url,
            "source_attribution": self.source_attribution,
            "image_url": self.image_url,
            "favorite": self.favorite,
            "folder": self.folder,
            "ingredients_yaml": self.ingredients_yaml,
            "body": self.body,
        }


def parse_form(raw: Any) -> FormData:
    """Decode an ImmutableMultiDict from ``request.form()`` into FormData."""

    def get(key: str) -> str:
        v = raw.get(key)
        return v.strip() if v else ""

    def getlist(key: str) -> list[str]:
        return [v for v in raw.getlist(key) if v]

    return FormData(
        title=get("title"),
        summary=get("summary"),
        cuisine=get("cuisine"),
        prep_minutes=get("prep_minutes"),
        cook_minutes=get("cook_minutes"),
        total_minutes=get("total_minutes"),
        servings=get("servings"),
        yield_note=get("yield_note"),
        meal_type=getlist("meal_type"),
        tags=get("tags"),
        dietary=getlist("dietary"),
        equipment=get("equipment"),
        source_url=get("source_url"),
        source_attribution=get("source_attribution"),
        image_url=get("image_url"),
        favorite=bool(raw.get("favorite")),
        folder=get("folder"),
        # No strip: preserve leading/trailing newlines in multi-line fields
        ingredients_yaml=raw.get("ingredients_yaml") or "",
        body=raw.get("body") or "",
    )
