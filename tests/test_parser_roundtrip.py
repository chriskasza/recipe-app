"""The most important test in the project: parse → serialize must be byte-stable.

If this breaks, fix the serializer or the test recipes — never silently change a
recipe file's formatting on the user.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from app.core.parser import parse_file
from app.core.serializer import serialize
from app.db.sync import _iter_recipe_files

_FIXTURES = Path(__file__).parent / "fixtures" / "recipes"


def _recipe_rel_paths(recipes_dir: Path) -> list[str]:
    """Relative paths (POSIX) of every discoverable recipe, nested included."""
    return sorted(p.relative_to(recipes_dir).as_posix() for p in _iter_recipe_files(recipes_dir))


@pytest.mark.parametrize("recipe_rel_path", _recipe_rel_paths(_FIXTURES))
def test_roundtrip_byte_identical(recipes_dir: Path, recipe_rel_path: str) -> None:
    path = recipes_dir / recipe_rel_path
    original = path.read_text(encoding="utf-8")
    doc, _issues = parse_file(path)
    rendered = serialize(doc)
    assert rendered == original, f"roundtrip drifted for {recipe_rel_path}"


def test_parser_returns_typed_recipe(recipes_dir: Path) -> None:
    """Spot-check that nested structures are typed correctly."""
    doc, issues = parse_file(recipes_dir / "miso-glazed-eggplant.md")
    assert doc.recipe.slug == "miso-glazed-eggplant"
    assert doc.recipe.servings == 2
    assert any(i.name == "white miso" for i in doc.recipe.ingredients)
    assert doc.recipe.body.description is not None
    assert doc.recipe.body.instructions is not None
    # Seed corpus must have zero validation errors.
    errors = [i for i in issues if i.level.value == "error"]
    assert errors == [], errors
