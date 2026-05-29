"""Tests for the draft builder (app/importer/draft.py)."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from app.core.parser import parse_text
from app.core.serializer import serialize
from app.importer import build_draft, build_markdown


def _payload(**overrides: Any) -> dict[str, Any]:
    data: dict[str, Any] = {
        "title": "Test Skillet Beans",
        "summary": "A quick weeknight pot of beans.",
        "cuisine": "american",
        "meal_type": ["dinner"],
        "tags": ["weeknight", "one-pot"],
        "dietary": ["vegan"],
        "prep_minutes": 10,
        "cook_minutes": 20,
        "total_minutes": 30,
        "servings": 4,
        "source": {"url": "https://example.com/beans", "attribution": "Example Cook, 2024"},
        "ingredients": [
            {"name": "olive oil", "qty": 2, "unit": "tbsp", "original": "2 Tbsp olive oil"},
            {"name": "garlic", "qty": 3, "unit": "clove", "prep": "minced", "original": "3 garlic cloves, minced"},
            {"name": "fresh thyme", "optional": True, "original": "A few sprigs of fresh thyme (optional)"},
        ],
        "body": {
            "description": "Cozy beans.",
            "instructions": "1. Heat oil.\n2. Add garlic.\n3. Simmer.",
        },
    }
    data.update(overrides)
    return data


def test_ok_writes_validated_byte_stable_draft(tmp_path: Path) -> None:
    drafts = tmp_path / "_drafts"
    report = build_draft(_payload(), drafts, rel_to=tmp_path)

    assert report.status == "ok"
    assert report.slug == "test-skillet-beans"
    assert report.roundtrip_byte_stable is True
    assert report.id and len(report.id) == 26

    out = drafts / "test-skillet-beans.md"
    assert out.exists()
    # The written file roundtrips byte-for-byte through parse → serialize.
    doc, issues = parse_text(out.read_text(encoding="utf-8"))
    assert not [i for i in issues if i.level.name == "ERROR"]
    assert serialize(doc) == out.read_text(encoding="utf-8")


def test_path_reported_relative_to_rel_to(tmp_path: Path) -> None:
    drafts = tmp_path / "recipes" / "_drafts"
    report = build_draft(_payload(), drafts, rel_to=tmp_path / "recipes")
    assert report.path == "_drafts/test-skillet-beans.md"


def test_missing_title_is_build_error(tmp_path: Path) -> None:
    report = build_draft({"ingredients": []}, tmp_path)
    assert report.status == "error"
    assert report.stage == "build"
    assert "title" in (report.message or "")


def test_ingredient_missing_original_is_build_error(tmp_path: Path) -> None:
    report = build_draft(
        _payload(ingredients=[{"name": "salt"}]),
        tmp_path,
    )
    assert report.status == "error"
    assert report.stage == "build"


def test_existing_draft_is_write_error(tmp_path: Path) -> None:
    drafts = tmp_path / "_drafts"
    first = build_draft(_payload(), drafts)
    assert first.status == "ok"
    second = build_draft(_payload(), drafts)
    assert second.status == "error"
    assert second.stage == "write"
    # The clashing file is left untouched (no second write).
    assert "test-skillet-beans" in (second.message or "")


def test_explicit_slug_overrides_title_derivation(tmp_path: Path) -> None:
    report = build_draft(_payload(slug="custom-slug"), tmp_path)
    assert report.status == "ok"
    assert report.slug == "custom-slug"
    assert (tmp_path / "custom-slug.md").exists()


def test_unknown_unit_surfaces_as_warning_not_error(tmp_path: Path) -> None:
    report = build_draft(
        _payload(ingredients=[{"name": "lime", "qty": 1, "unit": "wedge", "original": "1 lime wedge"}]),
        tmp_path,
    )
    assert report.status == "ok"
    assert any("unit" in w for w in report.warnings)


def test_to_dict_drops_empty_fields(tmp_path: Path) -> None:
    report = build_draft(_payload(), tmp_path / "_drafts")
    d = report.to_dict()
    assert d["status"] == "ok"
    assert "message" not in d  # None dropped
    assert "errors" not in d  # empty list dropped
    assert d["slug"] == "test-skillet-beans"


def test_build_markdown_omits_absent_optional_fields() -> None:
    text, slug = build_markdown({"title": "Bare", "ingredients": [{"name": "x", "original": "x"}]})
    assert slug == "bare"
    assert "summary:" not in text
    assert "cuisine:" not in text
    assert "nutrition:" not in text
    assert text.endswith("\n")


def test_underivable_slug_raises(tmp_path: Path) -> None:
    # A title that ASCII-folds to nothing yields no slug; surfaced as a build error.
    report = build_draft(
        {"title": "中文", "ingredients": [{"name": "x", "original": "x"}]},
        tmp_path,
    )
    assert report.status == "error"
    assert report.stage == "build"


@pytest.mark.parametrize("qty,expected", [(2, "qty: 2"), (0.5, "qty: 0.5"), (1.0, "qty: 1")])
def test_qty_rendering(qty: float, expected: str) -> None:
    text, _ = build_markdown(
        {"title": "Q", "ingredients": [{"name": "x", "qty": qty, "unit": "cup", "original": "x"}]}
    )
    assert expected in text
