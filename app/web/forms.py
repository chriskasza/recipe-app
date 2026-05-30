"""Form decoding and Markdown generation for the CRUD layer.

All writes flow through ``build_markdown`` which produces a canonical file text
using the same ruamel settings as the serializer, ensuring the output is
roundtrip-stable from the moment it hits disk.
"""

from __future__ import annotations

import io
import logging
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path, PureWindowsPath
from typing import Any

from ruamel.yaml.comments import CommentedMap, CommentedSeq

from app.core.ids import new_ulid
from app.core.serializer import _yaml
from app.core.validator import IssueLevel, ValidationIssue
from app.db.sync import EXCLUDED_DIRS

logger = logging.getLogger(__name__)


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


def find_recipe_file(recipes_dir: Path, slug: str) -> Path | None:
    """Locate the single .md file whose stem == slug, anywhere in the tree.

    Folders are organization-only, so a recipe may live in any subdirectory.
    Helper directories (drafts, image sidecars) are skipped. Returns None when
    no matching file exists.

    Slugs are globally unique by invariant (enforced in ``sync_all`` /
    ``validate_all`` and the ``slug_in_use`` collision check). If two files
    nonetheless share a stem — a TOCTOU race or out-of-band filesystem edit —
    we deterministically return the first by sorted path but log a warning so
    the ambiguity is visible rather than silently resolved.
    """
    if not slug:
        return None
    matches = [
        path
        for path in sorted(recipes_dir.rglob(f"{slug}.md"))
        if EXCLUDED_DIRS.isdisjoint(path.relative_to(recipes_dir).parts)
    ]
    if not matches:
        return None
    if len(matches) > 1:
        logger.warning(
            "duplicate slug %r resolves to %d files: %s — using %s",
            slug,
            len(matches),
            ", ".join(str(p) for p in matches),
            matches[0],
        )
    return matches[0]


def slug_in_use(recipes_dir: Path, slug: str) -> bool:
    return find_recipe_file(recipes_dir, slug) is not None


def resolve_new_recipe_path(
    recipes_dir: Path, slug: str, folder: str
) -> tuple[Path | None, ValidationIssue | None]:
    """Resolve the target file path for a new recipe under an optional folder.

    The folder is a free-text relative path. We reject absolute paths, ``..``
    traversal, and the reserved helper directories, and confirm the resolved
    file stays inside ``recipes_dir`` (mirrors the ``/media`` traversal guard).
    Returns ``(path, None)`` on success or ``(None, issue)`` on a bad folder.
    """

    def bad(message: str) -> tuple[None, ValidationIssue]:
        return None, ValidationIssue(IssueLevel.ERROR, "folder.invalid", message, "folder")

    rel = folder.strip()
    if not rel:
        return recipes_dir / f"{slug}.md", None

    candidate = Path(rel)
    # PureWindowsPath catches drive-relative (``C:foo``), UNC (``\\host\share``)
    # and device (``\\?\``) paths that ``Path.is_absolute`` misses on POSIX.
    if candidate.is_absolute() or PureWindowsPath(rel).is_absolute():
        return bad("Folder must be a relative path")
    parts = candidate.parts
    if ".." in parts:
        return bad("Folder must not contain '..'")
    if not EXCLUDED_DIRS.isdisjoint(parts):
        return bad(f"Folder must not use a reserved directory ({', '.join(sorted(EXCLUDED_DIRS))})")

    base = recipes_dir.resolve()
    # ``.resolve()`` follows symlinks, so a symlinked folder component could
    # canonicalize to a target outside ``base``. Reject any existing component
    # that is a symlink before trusting the resolved containment check below.
    probe = base
    for part in parts:
        probe = probe / part
        if probe.is_symlink():
            return bad("Folder must not traverse a symlink")

    target = (base / candidate / f"{slug}.md").resolve()
    if base not in target.parents:
        return bad("Folder must stay inside the recipes directory")
    return target, None


def _parse_int(value: str) -> int | None:
    stripped = value.strip()
    if not stripped:
        return None
    try:
        return int(stripped)
    except ValueError:
        return None


def _validate_url(value: str, field: str) -> ValidationIssue | None:
    """Reject URLs whose scheme is not http or https."""
    if value and not value.startswith(("https://", "http://")):
        return ValidationIssue(
            IssueLevel.ERROR,
            f"{field}.invalid_scheme",
            "URL must start with https:// or http://",
            field,
        )
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

    for url_field, url_value in (("image_url", form.image_url), ("source_url", form.source_url)):
        issue = _validate_url(url_value, url_field)
        if issue:
            pre_errors.append(issue)

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
