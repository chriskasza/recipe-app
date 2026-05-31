"""Save a recipe from a structured payload, via the project's canonical pipeline.

Takes a :class:`RecipePayload` (one recipe), then:

1. Generates a fresh ULID, normalizes the slug, and stamps created_at/updated_at (UTC).
2. Renders Markdown text in the canonical field order and block-style ingredients.
3. Parses + validates via :func:`app.core.parser.parse_text` — schema errors abort the write.
4. Roundtrips through :func:`app.core.serializer.serialize` to confirm byte-stability.
5. Writes the result straight into the corpus at ``<recipes_dir>/<slug>.md``.

This is the canonical write path for the ``recipe-from-url`` skill (exposed as
``recipes save-recipe``). Callers must not hand-write recipe files — everything flows
through here so the source-of-truth model in CLAUDE.md is preserved. The page fetch and
field extraction stay the agent's job; this module only turns a finished payload into a
validated recipe file. Mistakes are corrected afterward from the web UI's edit form.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from app.core.constants import EXCLUDED_DIRS
from app.core.ids import new_ulid, normalize_slug
from app.core.parser import ParseError, parse_text
from app.core.serializer import serialize
from app.core.validator import IssueLevel

_YAML_SPECIAL_PREFIXES = (
    "-",
    "?",
    ":",
    "[",
    "{",
    "!",
    "&",
    "*",
    "|",
    ">",
    "'",
    '"',
    "%",
    "@",
    "`",
    "#",
    " ",
)


class IngredientPayload(BaseModel):
    model_config = ConfigDict(extra="ignore")

    name: str
    original: str
    qty: float | None = None
    unit: str | None = None
    prep: str | None = None
    optional: bool = False


class SourcePayload(BaseModel):
    model_config = ConfigDict(extra="ignore")

    url: str | None = None
    attribution: str | None = None


class ImagePayload(BaseModel):
    model_config = ConfigDict(extra="ignore")

    path: str
    alt: str | None = None


class BodyPayload(BaseModel):
    model_config = ConfigDict(extra="ignore")

    description: str | None = None
    instructions: str | None = None
    notes: str | None = None
    substitutions: str | None = None
    make_ahead: str | None = None


class RecipePayload(BaseModel):
    """One recipe to save. Only ``title`` (and per-ingredient ``name``/``original``)
    is required; everything else is optional and omitted from the file when empty."""

    model_config = ConfigDict(extra="ignore")

    title: str
    slug: str | None = None
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
    source: SourcePayload | None = None
    equipment: list[str] = Field(default_factory=list)
    ingredients: list[IngredientPayload] = Field(default_factory=list)
    nutrition: dict[str, int | float] | None = None
    images: list[ImagePayload] = Field(default_factory=list)
    body: BodyPayload | None = None


@dataclass(frozen=True)
class SaveResult:
    """Outcome of :func:`save_recipe`. ``status`` is ``"ok"`` or ``"error"``."""

    status: str
    stage: str | None = None
    message: str | None = None
    path: str | None = None
    slug: str | None = None
    id: str | None = None
    roundtrip_byte_stable: bool | None = None
    warnings: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    rendered: str | None = None

    @property
    def ok(self) -> bool:
        return self.status == "ok"


def _quote(value: str) -> str:
    """Double-quote a YAML scalar if it might be misinterpreted, otherwise return as-is.

    Quoting rules are intentionally conservative — the parser will catch anything that
    slips through, and conservative quoting produces noisy diffs but never wrong files.
    """
    text = str(value)
    if not text:
        return '""'
    needs_quote = (
        text.startswith(_YAML_SPECIAL_PREFIXES)
        or text.endswith(" ")
        or ": " in text
        or text.endswith(":")
        or " #" in text
        or "\n" in text
    )
    if not needs_quote:
        return text
    escaped = text.replace("\\", "\\\\").replace('"', '\\"')
    return f'"{escaped}"'


def _flow_list(items: list[str]) -> str:
    """Render a short primitive list in flow style: ``[a, b, c]``."""
    return "[" + ", ".join(str(x) for x in items) + "]"


def _format_qty(qty: float) -> str:
    """Render integers without a decimal point; floats as-is."""
    return str(int(qty)) if qty.is_integer() else str(qty)


def render_markdown(payload: RecipePayload) -> tuple[str, str]:
    """Return ``(markdown_text, slug)`` for the given payload.

    Raises :class:`ValueError` for build-stage problems (empty title, underivable slug,
    ingredient missing ``name``/``original``).
    """
    title = payload.title
    if not title.strip():
        raise ValueError("payload missing required field 'title'")

    rid = new_ulid()
    slug = payload.slug or normalize_slug(title)
    if not slug:
        raise ValueError(f"could not derive a slug from title {title!r}")
    now = datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")

    out: list[str] = ["---"]
    out.append(f"id: {rid}")
    out.append(f"slug: {slug}")
    out.append(f"title: {_quote(title)}")

    if payload.summary:
        out.append(f"summary: {_quote(payload.summary)}")
    if payload.cuisine:
        out.append(f"cuisine: {_quote(payload.cuisine)}")
    if payload.meal_type:
        out.append(f"meal_type: {_flow_list(payload.meal_type)}")
    if payload.tags:
        out.append(f"tags: {_flow_list(payload.tags)}")
    if payload.dietary:
        out.append(f"dietary: {_flow_list(payload.dietary)}")

    for key, value in (
        ("prep_minutes", payload.prep_minutes),
        ("cook_minutes", payload.cook_minutes),
        ("total_minutes", payload.total_minutes),
        ("servings", payload.servings),
    ):
        if value is not None:
            out.append(f"{key}: {value}")

    if payload.yield_note:
        out.append(f"yield_note: {_quote(payload.yield_note)}")

    if payload.source and (payload.source.url or payload.source.attribution):
        out.append("source:")
        if payload.source.url:
            out.append(f"  url: {payload.source.url}")
        if payload.source.attribution:
            out.append(f"  attribution: {_quote(payload.source.attribution)}")

    if payload.equipment:
        out.append(f"equipment: {_flow_list(payload.equipment)}")

    if payload.ingredients:
        out.append("ingredients:")
        for ing in payload.ingredients:
            if not ing.name or not ing.original:
                raise ValueError(f"ingredient missing required name/original: {ing!r}")
            out.append(f"  - name: {_quote(ing.name)}")
            if ing.qty is not None:
                out.append(f"    qty: {_format_qty(ing.qty)}")
            if ing.unit:
                out.append(f"    unit: {_quote(ing.unit)}")
            if ing.prep:
                out.append(f"    prep: {_quote(ing.prep)}")
            if ing.optional:
                out.append("    optional: true")
            out.append(f"    original: {_quote(ing.original)}")

    if payload.nutrition:
        out.append("nutrition:")
        for nkey, nval in payload.nutrition.items():
            out.append(f"  {nkey}: {nval}")

    if payload.images:
        out.append("images:")
        for img in payload.images:
            if not img.path:
                continue
            out.append(f"  - path: {img.path}")
            if img.alt:
                out.append(f"    alt: {_quote(img.alt)}")

    out.append(f"created_at: {now}")
    out.append(f"updated_at: {now}")
    out.append("archived: false")
    out.append("---")
    out.append("")

    if payload.body is not None:
        body_sections = [
            ("Description", payload.body.description),
            ("Instructions", payload.body.instructions),
            ("Notes", payload.body.notes),
            ("Substitutions", payload.body.substitutions),
            ("Make-ahead", payload.body.make_ahead),
        ]
        for heading, content in body_sections:
            if not content or not content.strip():
                continue
            out.append(f"## {heading}")
            out.append(content.rstrip())
            out.append("")

    text = "\n".join(out)
    if not text.endswith("\n"):
        text += "\n"
    return text, slug


def _existing_recipe_path(recipes_dir: Path, slug: str) -> Path | None:
    """Return the path of an existing recipe with this slug, anywhere in the tree.

    Slugs are globally unique by invariant, so we scan the whole corpus (skipping
    the helper dirs in ``EXCLUDED_DIRS``) rather than only the target filename.
    """
    return next(
        (
            path
            for path in sorted(recipes_dir.rglob(f"{slug}.md"))
            if EXCLUDED_DIRS.isdisjoint(path.relative_to(recipes_dir).parts)
        ),
        None,
    )


def save_recipe(payload: RecipePayload, recipes_dir: Path) -> SaveResult:
    """Render, validate, roundtrip-check, and write a recipe to ``recipes_dir/<slug>.md``.

    Never raises for expected failures — returns a :class:`SaveResult` whose ``stage`` is
    one of ``build``, ``parse``, ``validate``, or ``write`` on error, or ``ok`` on success.
    """
    try:
        text, slug = render_markdown(payload)
    except ValueError as exc:
        return SaveResult(status="error", stage="build", message=str(exc))

    try:
        doc, issues = parse_text(text)
    except ParseError as exc:
        return SaveResult(status="error", stage="parse", message=str(exc), rendered=text)

    errors = [str(i) for i in issues if i.level is IssueLevel.ERROR]
    warnings = [str(i) for i in issues if i.level is IssueLevel.WARNING]
    if errors:
        return SaveResult(
            status="error", stage="validate", errors=errors, warnings=warnings, rendered=text
        )

    canonical = serialize(doc)
    roundtrip_clean = canonical == text

    existing = _existing_recipe_path(recipes_dir, slug)
    if existing is not None:
        return SaveResult(
            status="error",
            stage="write",
            message=f"recipe already exists: {existing}",
            slug=slug,
            warnings=warnings,
        )

    out_path = recipes_dir / f"{slug}.md"
    recipes_dir.mkdir(parents=True, exist_ok=True)
    out_path.write_text(canonical, encoding="utf-8")

    return SaveResult(
        status="ok",
        path=str(out_path),
        slug=slug,
        id=doc.recipe.id,
        roundtrip_byte_stable=roundtrip_clean,
        warnings=warnings,
    )


def to_report(result: SaveResult) -> dict[str, Any]:
    """Map a :class:`SaveResult` to the machine-readable JSON report the skill parses."""
    if result.ok:
        return {
            "status": "ok",
            "path": result.path,
            "slug": result.slug,
            "id": result.id,
            "roundtrip_byte_stable": result.roundtrip_byte_stable,
            "warnings": result.warnings,
        }

    report: dict[str, Any] = {"status": "error", "stage": result.stage}
    if result.message is not None:
        report["message"] = result.message
    if result.errors:
        report["errors"] = result.errors
    if result.stage in ("validate", "write"):
        report["warnings"] = result.warnings
    if result.rendered is not None:
        report["rendered"] = result.rendered
    return report
