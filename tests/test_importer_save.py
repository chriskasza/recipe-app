"""Tests for the recipe writer (``recipes save-recipe`` / app.importer.save)."""

from __future__ import annotations

import json
from pathlib import Path

from typer.testing import CliRunner

from app.cli import app
from app.core.ids import is_ulid
from app.core.parser import parse_text
from app.importer.save import RecipePayload, save_recipe, to_report

runner = CliRunner()


def _minimal_payload(**overrides: object) -> RecipePayload:
    data: dict[str, object] = {
        "title": "Chickpea & Spinach Curry",
        "ingredients": [
            {"name": "olive oil", "qty": 2, "unit": "tbsp", "original": "2 Tbsp olive oil"}
        ],
        "body": {"instructions": "1. Warm the oil.\n2. Add chickpeas."},
    }
    data.update(overrides)
    return RecipePayload.model_validate(data)


def test_save_recipe_happy_path(tmp_path: Path) -> None:
    result = save_recipe(_minimal_payload(), tmp_path)

    assert result.ok
    assert result.slug == "chickpea-spinach-curry"
    assert result.id is not None and is_ulid(result.id)
    assert result.roundtrip_byte_stable is True

    out_path = tmp_path / "chickpea-spinach-curry.md"
    assert result.path == str(out_path)
    text = out_path.read_text(encoding="utf-8")
    assert text.startswith("---\n")
    assert "title: Chickpea & Spinach Curry\n" in text
    assert "## Instructions\n" in text

    # The written file parses cleanly through the canonical pipeline.
    doc, issues = parse_text(text)
    assert doc.recipe.slug == "chickpea-spinach-curry"
    assert not [i for i in issues if i.level.value == "error"]


def test_save_recipe_explicit_slug(tmp_path: Path) -> None:
    result = save_recipe(_minimal_payload(slug="my-custom-slug"), tmp_path)

    assert result.ok
    assert result.slug == "my-custom-slug"
    assert (tmp_path / "my-custom-slug.md").exists()


def test_save_recipe_unknown_unit_warns_but_writes(tmp_path: Path) -> None:
    payload = _minimal_payload(
        ingredients=[{"name": "lemon", "qty": 1, "unit": "wedge", "original": "1 lemon wedge"}]
    )
    result = save_recipe(payload, tmp_path)

    assert result.ok  # warnings don't block the write
    assert any("unit.unknown" in w for w in result.warnings)
    assert (tmp_path / "chickpea-spinach-curry.md").exists()


def test_save_recipe_empty_title_is_build_error(tmp_path: Path) -> None:
    result = save_recipe(_minimal_payload(title="   "), tmp_path)

    assert not result.ok
    assert result.stage == "build"
    assert not (tmp_path / "chickpea-spinach-curry.md").exists()


def test_save_recipe_blank_ingredient_original_is_validate_error(tmp_path: Path) -> None:
    # A whitespace-only `original` slips past the renderer but the validator rejects it.
    payload = _minimal_payload(ingredients=[{"name": "salt", "original": "   "}])
    result = save_recipe(payload, tmp_path)

    assert not result.ok
    assert result.stage == "validate"
    assert any("ingredient.original" in e for e in result.errors)


def test_save_recipe_duplicate_slug_is_write_error(tmp_path: Path) -> None:
    first = save_recipe(_minimal_payload(), tmp_path)
    assert first.ok

    second = save_recipe(_minimal_payload(), tmp_path)
    assert not second.ok
    assert second.stage == "write"
    assert second.slug == "chickpea-spinach-curry"


def test_save_recipe_duplicate_slug_in_subdir_is_write_error(tmp_path: Path) -> None:
    # Folders are organization-only; a clash anywhere in the tree blocks the write.
    subdir = tmp_path / "weeknight"
    subdir.mkdir()
    first = save_recipe(_minimal_payload(), subdir)
    assert first.ok

    second = save_recipe(_minimal_payload(), tmp_path)
    assert not second.ok
    assert second.stage == "write"


def test_to_report_ok_shape(tmp_path: Path) -> None:
    result = save_recipe(_minimal_payload(), tmp_path)
    report = to_report(result)

    assert report["status"] == "ok"
    assert report["slug"] == "chickpea-spinach-curry"
    assert report["roundtrip_byte_stable"] is True
    assert set(report) == {"status", "path", "slug", "id", "roundtrip_byte_stable", "warnings"}


# --- CLI surface --------------------------------------------------------------


def _payload_json() -> str:
    return json.dumps(
        {
            "title": "Test Curry",
            "ingredients": [
                {"name": "olive oil", "qty": 2, "unit": "tbsp", "original": "2 Tbsp olive oil"}
            ],
            "body": {"instructions": "1. Cook."},
        }
    )


def test_cli_save_recipe_json(tmp_path: Path, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    monkeypatch.setenv("RECIPES_DIR", str(tmp_path))
    result = runner.invoke(app, ["save-recipe", "--json"], input=_payload_json())

    assert result.exit_code == 0, result.output
    report = json.loads(result.output)
    assert report["status"] == "ok"
    assert report["slug"] == "test-curry"
    assert (tmp_path / "test-curry.md").exists()


def test_cli_save_recipe_human_output(tmp_path: Path, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    monkeypatch.setenv("RECIPES_DIR", str(tmp_path))
    result = runner.invoke(app, ["save-recipe"], input=_payload_json())

    assert result.exit_code == 0, result.output
    assert "wrote recipe" in result.output
    assert "test-curry" in result.output


def test_cli_save_recipe_bad_json(tmp_path: Path, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    monkeypatch.setenv("RECIPES_DIR", str(tmp_path))
    result = runner.invoke(app, ["save-recipe", "--json"], input="{not json")

    assert result.exit_code == 1
    report = json.loads(result.output)
    assert report["status"] == "error"
    assert report["stage"] == "json"
