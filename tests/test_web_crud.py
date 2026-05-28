"""Tests for the Stage 4 CRUD web layer."""

from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

VALID_INGREDIENTS = """\
- name: pasta
  qty: 200
  unit: g
  original: "200 g pasta"
- name: olive oil
  qty: 2
  unit: tbsp
  original: "2 Tbsp olive oil"
"""

VALID_BODY = """\
## Description
A quick weeknight pasta.

## Instructions
1. Cook pasta.
2. Toss with oil.
"""


def _new_form(
    title: str = "Test Pasta",
    summary: str = "Quick and easy",
    meal_type: list[str] | None = None,
    tags: str = "weeknight",
    dietary: list[str] | None = None,
    prep_minutes: str = "5",
    cook_minutes: str = "10",
    total_minutes: str = "15",
    servings: str = "2",
    ingredients_yaml: str = VALID_INGREDIENTS,
    body: str = VALID_BODY,
) -> dict[str, object]:
    data: dict[str, object] = {
        "title": title,
        "summary": summary,
        "tags": tags,
        "prep_minutes": prep_minutes,
        "cook_minutes": cook_minutes,
        "total_minutes": total_minutes,
        "servings": servings,
        "ingredients_yaml": ingredients_yaml,
        "body": body,
    }
    if meal_type:
        data["meal_type"] = meal_type
    if dietary:
        data["dietary"] = dietary
    return data


# ---------------------------------------------------------------------------
# GET /new
# ---------------------------------------------------------------------------


def test_new_get_returns_form(crud_client: TestClient) -> None:
    resp = crud_client.get("/new")
    assert resp.status_code == 200
    body = resp.text
    assert "<form" in body
    assert 'name="title"' in body
    assert 'name="ingredients_yaml"' in body


# ---------------------------------------------------------------------------
# POST /new — happy path
# ---------------------------------------------------------------------------


def test_new_post_happy_path(
    crud_client: TestClient, crud_recipes_dir: Path, crud_db: Path
) -> None:
    resp = crud_client.post("/new", data=_new_form(), follow_redirects=False)
    assert resp.status_code == 303
    location = resp.headers["location"]
    assert location.startswith("/r/test-pasta")

    slug = location.removeprefix("/r/")
    md_path = crud_recipes_dir / f"{slug}.md"
    assert md_path.is_file(), f"expected {md_path} to exist"

    detail = crud_client.get(location)
    assert detail.status_code == 200
    assert "Test Pasta" in detail.text


def test_new_post_with_meal_type_and_dietary(
    crud_client: TestClient, crud_recipes_dir: Path
) -> None:
    resp = crud_client.post(
        "/new",
        data=_new_form(
            title="Vegan Dinner",
            meal_type=["dinner"],
            dietary=["vegan"],
        ),
        follow_redirects=False,
    )
    assert resp.status_code == 303
    slug = resp.headers["location"].removeprefix("/r/")
    text = (crud_recipes_dir / f"{slug}.md").read_text()
    assert "meal_type: [dinner]" in text
    assert "dietary: [vegan]" in text


# ---------------------------------------------------------------------------
# POST /new — validation errors
# ---------------------------------------------------------------------------


def test_new_post_empty_title_error(crud_client: TestClient) -> None:
    resp = crud_client.post("/new", data=_new_form(title=""))
    assert resp.status_code == 200
    assert "Title is required" in resp.text


def test_new_post_empty_title_preserves_summary(crud_client: TestClient) -> None:
    resp = crud_client.post("/new", data=_new_form(title="", summary="Keep this"))
    assert resp.status_code == 200
    assert "Keep this" in resp.text


def test_new_post_slug_collision(
    crud_client: TestClient, crud_recipes_dir: Path
) -> None:
    # "overnight-oats" already exists in the seeded corpus
    resp = crud_client.post("/new", data=_new_form(title="Overnight Oats"))
    assert resp.status_code == 200
    assert "already exists" in resp.text.lower()


def test_new_post_bad_ingredient_yaml(
    crud_client: TestClient, crud_recipes_dir: Path
) -> None:
    resp = crud_client.post(
        "/new",
        data=_new_form(title="Bad Pasta", ingredients_yaml="this is not yaml: ["),
    )
    assert resp.status_code == 200
    assert "ingredients" in resp.text.lower()
    assert not (crud_recipes_dir / "bad-pasta.md").exists()


def test_new_post_ingredient_yaml_not_a_list(
    crud_client: TestClient, crud_recipes_dir: Path
) -> None:
    resp = crud_client.post(
        "/new",
        data=_new_form(title="Oops", ingredients_yaml="name: foo\nqty: 1"),
    )
    assert resp.status_code == 200
    assert "list" in resp.text.lower()
    assert not (crud_recipes_dir / "oops.md").exists()


# ---------------------------------------------------------------------------
# GET /r/{slug}/edit
# ---------------------------------------------------------------------------


def test_edit_get_prefilled(crud_client: TestClient) -> None:
    resp = crud_client.get("/r/overnight-oats/edit")
    assert resp.status_code == 200
    body = resp.text
    assert "Overnight Oats" in body
    assert "oat milk" in body  # from ingredients


def test_edit_get_unknown_404(crud_client: TestClient) -> None:
    resp = crud_client.get("/r/no-such-recipe/edit")
    assert resp.status_code == 404


# ---------------------------------------------------------------------------
# POST /r/{slug}/edit
# ---------------------------------------------------------------------------


def test_edit_post_updates_summary(
    crud_client: TestClient, crud_recipes_dir: Path
) -> None:
    resp = crud_client.get("/r/overnight-oats/edit")
    assert resp.status_code == 200

    # Fetch current form values from the edit page (we reuse the prefilled form)
    # Build edit form data manually:
    form_data = {
        "title": "Overnight Oats",
        "summary": "Updated summary for testing",
        "cuisine": "american",
        "prep_minutes": "5",
        "cook_minutes": "0",
        "total_minutes": "5",
        "servings": "1",
        "yield_note": "1 jar",
        "meal_type": ["breakfast"],
        "dietary": ["vegan", "dairy-free"],
        "tags": "no-cook, meal-prep, fast",
        "equipment": "pint jar with lid",
        "ingredients_yaml": VALID_INGREDIENTS,
        "body": VALID_BODY,
    }
    resp2 = crud_client.post(
        "/r/overnight-oats/edit", data=form_data, follow_redirects=False
    )
    assert resp2.status_code == 303

    md_text = (crud_recipes_dir / "overnight-oats.md").read_text()
    assert "Updated summary for testing" in md_text


def test_edit_post_preserves_id_and_created_at(
    crud_client: TestClient, crud_recipes_dir: Path
) -> None:
    from app.core.parser import parse_file

    original_path = crud_recipes_dir / "overnight-oats.md"
    original_doc, _ = parse_file(original_path)
    original_id = original_doc.recipe.id
    original_created_at = original_doc.recipe.created_at
    original_updated_at = original_doc.recipe.updated_at

    form_data = {
        "title": "Overnight Oats",
        "summary": "Changed again",
        "cuisine": "american",
        "prep_minutes": "5",
        "cook_minutes": "0",
        "total_minutes": "5",
        "servings": "1",
        "meal_type": ["breakfast"],
        "dietary": ["vegan", "dairy-free"],
        "tags": "no-cook",
        "ingredients_yaml": VALID_INGREDIENTS,
        "body": VALID_BODY,
    }
    resp = crud_client.post(
        "/r/overnight-oats/edit", data=form_data, follow_redirects=False
    )
    assert resp.status_code == 303

    updated_doc, _ = parse_file(original_path)
    assert updated_doc.recipe.id == original_id
    assert updated_doc.recipe.created_at == original_created_at
    assert updated_doc.recipe.updated_at > original_updated_at
    assert updated_doc.recipe.summary == "Changed again"


def test_edit_post_unknown_slug_404(crud_client: TestClient) -> None:
    resp = crud_client.post(
        "/r/no-such-recipe/edit",
        data=_new_form(),
        follow_redirects=False,
    )
    assert resp.status_code == 404


# ---------------------------------------------------------------------------
# Archive / unarchive
# ---------------------------------------------------------------------------


def test_archive_hides_from_library(crud_client: TestClient) -> None:
    resp = crud_client.post("/r/overnight-oats/archive", follow_redirects=False)
    assert resp.status_code == 303

    library = crud_client.get("/")
    assert "Overnight Oats" not in library.text


def test_archived_recipe_still_accessible_on_detail(crud_client: TestClient) -> None:
    crud_client.post("/r/overnight-oats/archive")
    resp = crud_client.get("/r/overnight-oats")
    assert resp.status_code == 200


def test_unarchive_restores_to_library(crud_client: TestClient) -> None:
    crud_client.post("/r/overnight-oats/archive")
    assert "Overnight Oats" not in crud_client.get("/").text

    crud_client.post("/r/overnight-oats/unarchive")
    assert "Overnight Oats" in crud_client.get("/").text


def test_archive_unknown_slug_404(crud_client: TestClient) -> None:
    resp = crud_client.post("/r/no-such/archive", follow_redirects=False)
    assert resp.status_code == 404


def test_unarchive_unknown_slug_404(crud_client: TestClient) -> None:
    resp = crud_client.post("/r/no-such/unarchive", follow_redirects=False)
    assert resp.status_code == 404


# ---------------------------------------------------------------------------
# Roundtrip stability
# ---------------------------------------------------------------------------


def test_generated_file_is_roundtrip_stable(
    crud_client: TestClient, crud_recipes_dir: Path
) -> None:
    """File written by POST /new must be byte-identical after parse → serialize."""
    from app.core.parser import parse_text
    from app.core.serializer import serialize

    resp = crud_client.post("/new", data=_new_form(), follow_redirects=False)
    assert resp.status_code == 303
    slug = resp.headers["location"].removeprefix("/r/")

    original_text = (crud_recipes_dir / f"{slug}.md").read_text()
    doc, issues = parse_text(original_text)
    # No errors expected
    from app.core.validator import has_errors
    assert not has_errors(issues)

    reserialized = serialize(doc)
    assert reserialized == original_text, (
        "Generated Markdown is not roundtrip-stable.\n"
        f"Original:\n{original_text}\n\nReserialized:\n{reserialized}"
    )


def test_sync_idempotent_after_new(
    crud_client: TestClient, crud_recipes_dir: Path, crud_db: Path
) -> None:
    """After POST /new, a second sync_all run must report zero changes."""
    from app.db import sync

    crud_client.post("/new", data=_new_form(), follow_redirects=False)

    report = sync.sync_all(crud_recipes_dir, crud_db)
    assert not report.errors
    assert report.files_changed == 0
