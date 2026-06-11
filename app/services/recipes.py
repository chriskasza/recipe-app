"""Shared recipe write plumbing: Markdown generation, file resolution, and the
canonical write-then-sync pipeline used by both the web UI and the JSON API.

All writes flow through ``build_markdown`` which produces a canonical file text
using the same ruamel settings as the serializer, ensuring the output is
roundtrip-stable from the moment it hits disk.
"""

from __future__ import annotations

import io
import logging
from datetime import UTC, datetime
from pathlib import Path, PureWindowsPath
from typing import Any

from fastapi import HTTPException
from pydantic import BaseModel, ConfigDict, Field
from ruamel.yaml.comments import CommentedMap, CommentedSeq

from app.core.constants import EXCLUDED_DIRS
from app.core.ids import new_ulid
from app.core.parser import parse_file
from app.core.serializer import _yaml, serialize
from app.core.validator import IssueLevel, ValidationIssue
from app.db import sync as db_sync

logger = logging.getLogger(__name__)


class RecipeDraft(BaseModel):
    """JSON-native intermediate form used to build a recipe's Markdown file.

    Produced either by ``app.web.forms.form_to_draft`` (from an HTML form) or
    directly from an API request body. ``build_markdown`` consumes this and
    knows nothing about HTML forms or JSON.
    """

    model_config = ConfigDict(extra="forbid")

    title: str
    summary: str | None = None
    cuisine: str | None = None
    meal_type: list[str] = Field(default_factory=list)
    tags: list[str] = Field(default_factory=list)
    dietary: list[str] = Field(default_factory=list)
    equipment: list[str] = Field(default_factory=list)
    prep_minutes: int | None = Field(default=None, ge=0)
    cook_minutes: int | None = Field(default=None, ge=0)
    total_minutes: int | None = Field(default=None, ge=0)
    servings: int | None = Field(default=None, ge=0)
    yield_note: str | None = None
    source_url: str | None = None
    source_attribution: str | None = None
    image_url: str | None = None
    favorite: bool = False
    folder: str = ""
    ingredients: list[dict[str, Any]] = Field(default_factory=list)
    body: str = ""


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


def _validate_url(value: str | None, field: str) -> ValidationIssue | None:
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
    draft: RecipeDraft,
    *,
    slug: str,
    existing_id: str | None,
    existing_created_at: datetime | None,
    existing_archived: bool,
    existing_nutrition: Any,
) -> tuple[str, list[ValidationIssue]]:
    """Build the canonical Markdown file text from a recipe draft.

    Returns ``(text, pre_errors)``. If pre_errors is non-empty, text is ``""``
    and the caller should report the issues without touching the filesystem.

    We use the same ``_yaml()`` settings as ``serializer.py`` so the output is
    roundtrip-stable: parse → serialize produces byte-identical output.
    """
    pre_errors: list[ValidationIssue] = []

    for url_field, url_value in (
        ("image_url", draft.image_url),
        ("source_url", draft.source_url),
    ):
        issue = _validate_url(url_value, url_field)
        if issue:
            pre_errors.append(issue)

    if pre_errors:
        return "", pre_errors

    ingredients_seq: CommentedSeq | None = None
    if draft.ingredients:
        seq = CommentedSeq()
        for item in draft.ingredients:
            cm_item = CommentedMap(item)
            cm_item.fa.set_block_style()
            seq.append(cm_item)
        seq.fa.set_block_style()
        ingredients_seq = seq

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
    cm["title"] = draft.title

    if draft.summary:
        cm["summary"] = draft.summary
    if draft.cuisine:
        cm["cuisine"] = draft.cuisine

    # Flow-style for short lists of plain scalars (matches corpus style)
    if draft.meal_type:
        cm["meal_type"] = _flow_seq(draft.meal_type)
    if draft.tags:
        cm["tags"] = _flow_seq(draft.tags)
    if draft.dietary:
        cm["dietary"] = _flow_seq(draft.dietary)

    if draft.prep_minutes is not None:
        cm["prep_minutes"] = draft.prep_minutes
    if draft.cook_minutes is not None:
        cm["cook_minutes"] = draft.cook_minutes
    if draft.total_minutes is not None:
        cm["total_minutes"] = draft.total_minutes
    if draft.servings is not None:
        cm["servings"] = draft.servings
    if draft.yield_note:
        cm["yield_note"] = draft.yield_note

    if draft.equipment:
        cm["equipment"] = _flow_seq(draft.equipment)
    if ingredients_seq is not None:
        cm["ingredients"] = ingredients_seq
    if existing_nutrition is not None:
        cm["nutrition"] = existing_nutrition

    if draft.source_url or draft.source_attribution:
        src = CommentedMap()
        if draft.source_url:
            src["url"] = draft.source_url
        if draft.source_attribution:
            src["attribution"] = draft.source_attribution
        cm["source"] = src

    # Single hero image. Stored as a block-style list of {path} mappings to
    # match the corpus shape; carries an existing image through edits so the
    # write path no longer strips it.
    if draft.image_url:
        img = CommentedMap()
        img["path"] = draft.image_url
        images_seq = CommentedSeq([img])
        images_seq.fa.set_block_style()
        img.fa.set_block_style()
        cm["images"] = images_seq

    cm["created_at"] = created_at_str
    cm["updated_at"] = now_str
    cm["archived"] = existing_archived
    cm["favorite"] = draft.favorite

    buf = io.StringIO()
    _yaml().dump(cm, buf)
    return f"---\n{buf.getvalue()}---\n{draft.body}", []


def _write_and_sync(path: Path, text: str, recipes_dir: Path, db_path: Path) -> list[str]:
    """Write text to path, sync to DB, restore original on failure.

    Returns a list of error strings (empty on success).
    """
    original: str | None = None
    if path.is_file():
        original = path.read_text(encoding="utf-8")

    path.write_text(text, encoding="utf-8")
    report = db_sync.sync_one(path, recipes_dir, db_path)
    if not report.ok:
        if original is not None:
            path.write_text(original, encoding="utf-8")
        else:
            path.unlink(missing_ok=True)
        return report.errors
    return []


_BOOL_FIELDS: frozenset[str] = frozenset({"archived", "favorite"})


def _flip_bool_field(
    slug: str, *, field: str, value: bool, recipes_dir: Path, db_path: Path
) -> None:
    """Toggle a boolean frontmatter flag by mutating raw_yaml and re-serializing."""
    if field not in _BOOL_FIELDS:
        raise ValueError(f"field {field!r} is not an allowed boolean frontmatter key")
    path = find_recipe_file(recipes_dir, slug)
    if path is None:
        raise HTTPException(status_code=404, detail=f"No recipe file for slug {slug!r}")

    doc, _ = parse_file(path)
    doc.raw_yaml[field] = value
    doc.raw_yaml["updated_at"] = datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")

    text = serialize(doc)
    sync_errors = _write_and_sync(path, text, recipes_dir, db_path)
    if sync_errors:
        raise HTTPException(status_code=500, detail="; ".join(sync_errors))
