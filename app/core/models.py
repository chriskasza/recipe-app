"""Pydantic models for the canonical recipe schema.

These models are the **contract** between every layer. Parser produces them, serializer
consumes them, SQLite sync reads from them, the web UI binds to them.

Body prose is kept as raw section strings rather than further-parsed structures so the
serializer can reproduce the original Markdown byte-for-byte. Future stages may add
structured parsing (e.g. step lists) without changing storage.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class Ingredient(BaseModel):
    """A single ingredient entry. ``original`` preserves the user's free text so it can
    be re-displayed verbatim even if normalization changes."""

    model_config = ConfigDict(extra="forbid")

    name: str
    qty: float | None = None
    unit: str | None = None
    prep: str | None = None
    optional: bool = False
    original: str


class SourceInfo(BaseModel):
    model_config = ConfigDict(extra="forbid")

    url: str | None = None
    attribution: str | None = None


class NutritionInfo(BaseModel):
    model_config = ConfigDict(extra="allow")  # nutrition fields evolve; don't reject extras

    calories: float | None = None
    protein_g: float | None = None
    carbs_g: float | None = None
    fat_g: float | None = None
    fiber_g: float | None = None
    sodium_mg: float | None = None


class ImageRef(BaseModel):
    model_config = ConfigDict(extra="forbid")

    path: str
    alt: str | None = None


class RecipeBody(BaseModel):
    """Parsed Markdown body sections. Each known section is a raw string preserving the
    user's formatting. Unknown ``## …`` headings are kept under ``extras`` so they
    survive a roundtrip."""

    model_config = ConfigDict(extra="forbid")

    description: str | None = None
    instructions: str | None = None
    notes: str | None = None
    substitutions: str | None = None
    make_ahead: str | None = None
    extras: dict[str, str] = Field(default_factory=dict)


class Recipe(BaseModel):
    """The canonical recipe. One file ↔ one Recipe."""

    model_config = ConfigDict(extra="forbid", validate_assignment=True)

    id: str
    slug: str
    title: str
    summary: str | None = None
    cuisine: str | None = None
    meal_type: list[str] = Field(default_factory=list)
    tags: list[str] = Field(default_factory=list)
    dietary: list[str] = Field(default_factory=list)
    prep_minutes: int | None = None
    cook_minutes: int | None = None
    total_minutes: int | None = None
    servings: int | None = None
    yield_note: str | None = None
    source: SourceInfo | None = None
    equipment: list[str] = Field(default_factory=list)
    ingredients: list[Ingredient] = Field(default_factory=list)
    nutrition: NutritionInfo | None = None
    images: list[ImageRef] = Field(default_factory=list)
    created_at: datetime
    updated_at: datetime
    archived: bool = False
    favorite: bool = False
    body: RecipeBody = Field(default_factory=RecipeBody)


@dataclass
class RecipeDocument:
    """Bundle of typed model + raw artifacts used to preserve on-disk formatting.

    The serializer writes from ``raw_yaml`` (a ruamel CommentedMap that preserves
    comments, key order, and quoting) and ``raw_body`` (the original section text
    after the closing ``---``). This is what makes the roundtrip byte-stable.
    """

    recipe: Recipe
    raw_yaml: Any  # ruamel.yaml.comments.CommentedMap — kept untyped to avoid coupling
    raw_body: str
    source_path: Path | None = None
    extras_order: list[str] = field(default_factory=list)
