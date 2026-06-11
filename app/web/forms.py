"""Form decoding for the web CRUD layer.

The shared write plumbing (Markdown generation, file resolution, and the
write-then-sync pipeline) lives in ``app.services.recipes`` so it can be
reused by the JSON API. The names below are re-exported here for backward
compatibility with existing imports in ``app.web.crud``.
"""

from __future__ import annotations

import io
from dataclasses import dataclass, field
from typing import Any

from pydantic import ValidationError as PydanticValidationError

from app.core.serializer import _yaml
from app.core.validator import IssueLevel, ValidationIssue
from app.services.recipes import (
    RecipeDraft,
    _parse_int,
    _split_csv,
    build_markdown,
    find_recipe_file,
    resolve_new_recipe_path,
    slug_in_use,
)

__all__ = [
    "FormData",
    "build_markdown",
    "find_recipe_file",
    "form_to_draft",
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


def form_to_draft(form: FormData) -> tuple[RecipeDraft | None, list[ValidationIssue]]:
    """Convert HTML form input into a JSON-native ``RecipeDraft``.

    Parses the ingredients YAML textarea and the comma-separated tags/
    equipment fields, and converts numeric fields from strings. Returns
    ``(None, issues)`` if the ingredients YAML fails to parse; the caller
    should re-render the form without touching the filesystem.
    """
    ingredients: list[dict[str, Any]] = []
    if form.ingredients_yaml.strip():
        try:
            parsed = _yaml().load(io.StringIO(form.ingredients_yaml))
            if not isinstance(parsed, list):
                raise ValueError("expected a YAML list of ingredient mappings")
            ingredients = [dict(item) for item in parsed]
        except Exception as exc:
            return None, [
                ValidationIssue(
                    IssueLevel.ERROR,
                    "ingredients.yaml",
                    f"could not parse ingredients YAML: {exc}",
                    "ingredients",
                )
            ]

    try:
        draft = RecipeDraft(
            title=form.title,
            summary=form.summary or None,
            cuisine=form.cuisine or None,
            meal_type=form.meal_type,
            tags=_split_csv(form.tags),
            dietary=form.dietary,
            equipment=_split_csv(form.equipment),
            prep_minutes=_parse_int(form.prep_minutes),
            cook_minutes=_parse_int(form.cook_minutes),
            total_minutes=_parse_int(form.total_minutes),
            servings=_parse_int(form.servings),
            yield_note=form.yield_note or None,
            source_url=form.source_url or None,
            source_attribution=form.source_attribution or None,
            image_url=form.image_url or None,
            favorite=form.favorite,
            folder=form.folder,
            ingredients=ingredients,
            body=form.body,
        )
    except PydanticValidationError as exc:
        issues = [
            ValidationIssue(
                IssueLevel.ERROR,
                "field.invalid",
                err["msg"],
                ".".join(str(p) for p in err["loc"]),
            )
            for err in exc.errors()
        ]
        return None, issues
    return draft, []
