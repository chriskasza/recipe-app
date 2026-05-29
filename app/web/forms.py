"""Form decoding and Markdown generation for the CRUD layer.

All writes flow through ``build_markdown`` which produces a canonical file text
using the same ruamel settings as the serializer, ensuring the output is
roundtrip-stable from the moment it hits disk.
"""

from __future__ import annotations

import io
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from ruamel.yaml.comments import CommentedMap, CommentedSeq

from app.core.ids import new_ulid
from app.core.serializer import _yaml
from app.core.validator import IssueLevel, ValidationIssue


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
        # No strip: preserve leading/trailing newlines in multi-line fields
        ingredients_yaml=raw.get("ingredients_yaml") or "",
        body=raw.get("body") or "",
    )


def slug_in_use(recipes_dir: Path, slug: str) -> bool:
    return slug != "" and (recipes_dir / f"{slug}.md").exists()


def _parse_int(value: str) -> int | None:
    stripped = value.strip()
    if not stripped:
        return None
    try:
        return int(stripped)
    except ValueError:
        return None


def _split_csv(value: str) -> list[str]:
    return [v.strip() for v in value.split(",") if v.strip()]


def _flow_seq(items: list[str]) -> CommentedSeq:
    s = CommentedSeq(items)
    s.fa.set_flow_style()
    return s


def build_markdown(
    form: FormData,
    *,
    slug: str,
    existing_id: str | None,
    existing_created_at: datetime | None,
    existing_archived: bool,
    existing_nutrition: Any,
) -> tuple[str, list[ValidationIssue]]:
    """Build the canonical Markdown file text from form data.

    Returns ``(text, pre_errors)``. If pre_errors is non-empty, text is ``""``
    and the caller should re-render the form without touching the filesystem.

    We use the same ``_yaml()`` settings as ``serializer.py`` so the output is
    roundtrip-stable: parse → serialize produces byte-identical output.
    """
    pre_errors: list[ValidationIssue] = []

    # Parse ingredients YAML first — fail fast before building anything else
    ingredients_seq: CommentedSeq | None = None
    if form.ingredients_yaml.strip():
        try:
            parsed = _yaml().load(io.StringIO(form.ingredients_yaml))
            if not isinstance(parsed, list):
                raise ValueError("expected a YAML list of ingredient mappings")
            seq = CommentedSeq(parsed)
            seq.fa.set_block_style()
            for item in seq:
                if hasattr(item, "fa"):
                    item.fa.set_block_style()
            ingredients_seq = seq
        except Exception as exc:
            pre_errors.append(
                ValidationIssue(
                    IssueLevel.ERROR,
                    "ingredients.yaml",
                    f"could not parse ingredients YAML: {exc}",
                    "ingredients",
                )
            )

    if pre_errors:
        return "", pre_errors

    now_str = datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
    recipe_id = existing_id if existing_id is not None else new_ulid()
    created_at_str = (
        existing_created_at.strftime("%Y-%m-%dT%H:%M:%SZ")
        if existing_created_at is not None
        else now_str
    )

    # Build the CommentedMap in canonical field order matching the seed corpus
    cm = CommentedMap()
    cm["id"] = recipe_id
    cm["slug"] = slug
    cm["title"] = form.title

    if form.summary:
        cm["summary"] = form.summary
    if form.cuisine:
        cm["cuisine"] = form.cuisine

    meal_type = form.meal_type
    tags = _split_csv(form.tags)
    dietary = form.dietary
    equipment = _split_csv(form.equipment)

    # Flow-style for short lists of plain scalars (matches corpus style)
    if meal_type:
        cm["meal_type"] = _flow_seq(meal_type)
    if tags:
        cm["tags"] = _flow_seq(tags)
    if dietary:
        cm["dietary"] = _flow_seq(dietary)

    prep = _parse_int(form.prep_minutes)
    cook = _parse_int(form.cook_minutes)
    total = _parse_int(form.total_minutes)
    servings = _parse_int(form.servings)

    if prep is not None:
        cm["prep_minutes"] = prep
    if cook is not None:
        cm["cook_minutes"] = cook
    if total is not None:
        cm["total_minutes"] = total
    if servings is not None:
        cm["servings"] = servings
    if form.yield_note:
        cm["yield_note"] = form.yield_note

    if equipment:
        cm["equipment"] = _flow_seq(equipment)
    if ingredients_seq is not None:
        cm["ingredients"] = ingredients_seq
    if existing_nutrition is not None:
        cm["nutrition"] = existing_nutrition

    source_url = form.source_url
    source_attr = form.source_attribution
    if source_url or source_attr:
        src = CommentedMap()
        if source_url:
            src["url"] = source_url
        if source_attr:
            src["attribution"] = source_attr
        cm["source"] = src

    # Single hero image. Stored as a block-style list of {path} mappings to
    # match the corpus shape; carries an existing image through edits so the
    # write path no longer strips it.
    if form.image_url:
        img = CommentedMap()
        img["path"] = form.image_url
        images_seq = CommentedSeq([img])
        images_seq.fa.set_block_style()
        img.fa.set_block_style()
        cm["images"] = images_seq

    cm["created_at"] = created_at_str
    cm["updated_at"] = now_str
    cm["archived"] = existing_archived
    cm["favorite"] = form.favorite

    buf = io.StringIO()
    _yaml().dump(cm, buf)
    return f"---\n{buf.getvalue()}---\n{form.body}", []
