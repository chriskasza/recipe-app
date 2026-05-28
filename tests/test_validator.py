"""Validator tests use synthetic recipes constructed in-memory."""

from __future__ import annotations

from datetime import UTC, datetime

from app.core.models import Ingredient, Recipe, SourceInfo
from app.core.validator import IssueLevel, has_errors, validate_recipe


def _base() -> Recipe:
    return Recipe(
        id="01HX7K3M8QZJW2YV4P0NT5RBSA",
        slug="ok",
        title="Test",
        ingredients=[Ingredient(name="water", qty=1, unit="cup", original="1 cup water")],
        created_at=datetime(2026, 1, 1, tzinfo=UTC),
        updated_at=datetime(2026, 1, 1, tzinfo=UTC),
    )


def test_clean_recipe_has_no_issues() -> None:
    assert validate_recipe(_base()) == []


def test_bad_ulid_is_error() -> None:
    bad = _base().model_copy(update={"id": "not-a-ulid"})
    issues = validate_recipe(bad)
    assert has_errors(issues)
    assert any(i.code == "id.invalid" for i in issues)


def test_bad_slug_is_error() -> None:
    bad = _base().model_copy(update={"slug": "BadSlug"})
    issues = validate_recipe(bad)
    assert has_errors(issues)


def test_slug_mismatch_with_filename_is_error() -> None:
    issues = validate_recipe(_base(), expected_slug="different")
    assert has_errors(issues)
    assert any(i.code == "slug.mismatch" for i in issues)


def test_unknown_dietary_is_warning_not_error() -> None:
    rec = _base().model_copy(update={"dietary": ["paleo", "fakediet"]})
    issues = validate_recipe(rec)
    assert not has_errors(issues)
    assert any(i.level is IssueLevel.WARNING and "fakediet" in i.message for i in issues)


def test_time_math_warning() -> None:
    rec = _base().model_copy(
        update={"prep_minutes": 10, "cook_minutes": 20, "total_minutes": 99}
    )
    issues = validate_recipe(rec)
    assert any(i.code == "time.math" for i in issues)
    assert not has_errors(issues)


def test_source_url_scheme_warning() -> None:
    rec = _base().model_copy(update={"source": SourceInfo(url="example.com")})
    issues = validate_recipe(rec)
    assert any(i.code == "source.url.scheme" for i in issues)
