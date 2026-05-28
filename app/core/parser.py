"""Markdown ↔ Recipe parser.

Uses ruamel.yaml in roundtrip mode so user formatting (key order, comments, flow vs.
block style, quoting) survives a parse → serialize cycle byte-for-byte.
"""

from __future__ import annotations

import io
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from ruamel.yaml import YAML

from app.core.models import (
    ImageRef,
    Ingredient,
    NutritionInfo,
    Recipe,
    RecipeBody,
    RecipeDocument,
    SourceInfo,
)
from app.core.validator import ValidationIssue, validate_recipe

KNOWN_BODY_SECTIONS: dict[str, str] = {
    "description": "description",
    "instructions": "instructions",
    "notes": "notes",
    "substitutions": "substitutions",
    "make-ahead": "make_ahead",
}


class ParseError(ValueError):
    """Raised when the file is structurally unparseable (no frontmatter, bad YAML)."""


def _yaml() -> YAML:
    y = YAML(typ="rt")
    y.preserve_quotes = True
    y.width = 4096
    y.indent(mapping=2, sequence=4, offset=2)
    return y


def _split_frontmatter(text: str) -> tuple[str, str]:
    """Split a recipe file into (yaml_text, body_text). LF endings only."""
    if not text.startswith("---\n"):
        raise ParseError("recipe file must start with '---' frontmatter delimiter")
    lines = text.split("\n")
    close_idx: int | None = None
    for i in range(1, len(lines)):
        if lines[i] == "---":
            close_idx = i
            break
    if close_idx is None:
        raise ParseError("frontmatter not closed with '---'")
    yaml_text = "\n".join(lines[1:close_idx])
    body_text = "\n".join(lines[close_idx + 1 :])
    return yaml_text, body_text


def _parse_body(body_text: str) -> RecipeBody:
    """Split the body on `## …` headings. Map known headings to typed fields; preserve
    unknown sections under ``extras``. Each section's content is stored verbatim
    (minus the heading line)."""
    sections: dict[str, str] = {}
    current: str | None = None
    buffer: list[str] = []

    def flush() -> None:
        if current is not None:
            sections[current] = "\n".join(buffer).strip("\n")

    for line in body_text.split("\n"):
        if line.startswith("## "):
            flush()
            current = line[3:].strip()
            buffer = []
        else:
            buffer.append(line)
    flush()

    known: dict[str, str | None] = {field_name: None for field_name in KNOWN_BODY_SECTIONS.values()}
    extras: dict[str, str] = {}

    for heading, content in sections.items():
        key = KNOWN_BODY_SECTIONS.get(heading.lower())
        if key is None:
            extras[heading] = content
        else:
            known[key] = content

    return RecipeBody(extras=extras, **known)


def _to_plain(value: Any) -> Any:
    """Recursively coerce ruamel CommentedMap/CommentedSeq into plain dict/list so
    Pydantic validates cleanly."""
    if isinstance(value, dict):
        return {k: _to_plain(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_to_plain(v) for v in value]
    if isinstance(value, datetime) and value.tzinfo is None:
        # Treat naive timestamps as UTC for consistency with serialization.
        return value.replace(tzinfo=UTC)
    return value


def _build_recipe(yaml_data: Any, body: RecipeBody) -> Recipe:
    plain: dict[str, Any] = _to_plain(yaml_data)
    # Coerce nested structured fields explicitly so Pydantic's validation messages stay clear.
    if "ingredients" in plain:
        plain["ingredients"] = [Ingredient.model_validate(i) for i in plain["ingredients"]]
    if "source" in plain and plain["source"] is not None:
        plain["source"] = SourceInfo.model_validate(plain["source"])
    if "nutrition" in plain and plain["nutrition"] is not None:
        plain["nutrition"] = NutritionInfo.model_validate(plain["nutrition"])
    if "images" in plain:
        plain["images"] = [ImageRef.model_validate(i) for i in plain["images"]]
    plain["body"] = body
    return Recipe.model_validate(plain)


def parse_text(
    text: str, source_path: Path | None = None
) -> tuple[RecipeDocument, list[ValidationIssue]]:
    """Parse a recipe file's contents into a typed document plus validation issues."""
    yaml_text, body_text = _split_frontmatter(text)
    data = _yaml().load(io.StringIO(yaml_text))
    if data is None:
        raise ParseError("frontmatter is empty")
    if not isinstance(data, dict):
        raise ParseError(f"frontmatter must be a mapping (got {type(data).__name__})")
    body = _parse_body(body_text)
    recipe = _build_recipe(data, body)
    expected_slug = source_path.stem if source_path is not None else None
    issues = validate_recipe(recipe, expected_slug=expected_slug)
    return (
        RecipeDocument(recipe=recipe, raw_yaml=data, raw_body=body_text, source_path=source_path),
        issues,
    )


def parse_file(path: Path) -> tuple[RecipeDocument, list[ValidationIssue]]:
    text = path.read_text(encoding="utf-8")
    return parse_text(text, source_path=path)
