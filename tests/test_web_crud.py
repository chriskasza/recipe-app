"""Tests for the Stage 4 CRUD web layer."""

from __future__ import annotations

from pathlib import Path

import pytest
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
# Favorite / unfavorite
# ---------------------------------------------------------------------------


def test_favorite_writes_flag_and_shows_in_favorites_view(
    crud_client: TestClient, crud_recipes_dir: Path
) -> None:
    resp = crud_client.post("/r/overnight-oats/favorite", follow_redirects=False)
    assert resp.status_code == 303

    text = (crud_recipes_dir / "overnight-oats.md").read_text()
    assert "favorite: true" in text

    favorites = crud_client.get("/?favorite=1")
    assert "Overnight Oats" in favorites.text
    # A recipe that wasn't favorited should not appear in the favorites view.
    assert "Classic French Omelette" not in favorites.text


def test_unfavorite_removes_from_favorites_view(
    crud_client: TestClient, crud_recipes_dir: Path
) -> None:
    crud_client.post("/r/overnight-oats/favorite")
    assert "Overnight Oats" in crud_client.get("/?favorite=1").text

    resp = crud_client.post("/r/overnight-oats/unfavorite", follow_redirects=False)
    assert resp.status_code == 303
    text = (crud_recipes_dir / "overnight-oats.md").read_text()
    assert "favorite: false" in text
    assert "Overnight Oats" not in crud_client.get("/?favorite=1").text


def test_favorite_honors_safe_next_redirect(crud_client: TestClient) -> None:
    resp = crud_client.post(
        "/r/overnight-oats/favorite?next=/r/overnight-oats", follow_redirects=False
    )
    assert resp.status_code == 303
    assert resp.headers["location"] == "/r/overnight-oats"


def test_favorite_rejects_offsite_next_redirect(crud_client: TestClient) -> None:
    resp = crud_client.post(
        "/r/overnight-oats/favorite?next=https://evil.example", follow_redirects=False
    )
    assert resp.status_code == 303
    # Falls back to the recipe detail page rather than the external URL.
    assert resp.headers["location"] == "/r/overnight-oats"


def test_favorite_unknown_slug_404(crud_client: TestClient) -> None:
    resp = crud_client.post("/r/no-such/favorite", follow_redirects=False)
    assert resp.status_code == 404


# ---------------------------------------------------------------------------
# Image URL
# ---------------------------------------------------------------------------

HERO_URL = "https://example.com/hero.jpg"


def test_new_post_with_image_url_writes_images_and_renders_hero(
    crud_client: TestClient, crud_recipes_dir: Path
) -> None:
    data = _new_form(title="Photo Recipe")
    data["image_url"] = HERO_URL
    resp = crud_client.post("/new", data=data, follow_redirects=False)
    assert resp.status_code == 303
    slug = resp.headers["location"].removeprefix("/r/")

    text = (crud_recipes_dir / f"{slug}.md").read_text()
    assert "images:" in text
    assert HERO_URL in text

    detail = crud_client.get(f"/r/{slug}")
    assert HERO_URL in detail.text  # absolute URL used directly as the hero src


def test_edit_form_prefills_existing_image(crud_client: TestClient) -> None:
    # The miso fixture references a local image path; the edit form should
    # prefill it so saving doesn't drop the hero.
    resp = crud_client.get("/r/miso-glazed-eggplant/edit")
    assert resp.status_code == 200
    assert 'name="image_url"' in resp.text
    assert "images/miso-eggplant.jpg" in resp.text


def test_edit_preserves_then_clears_image(
    crud_client: TestClient, crud_recipes_dir: Path
) -> None:
    # Create with a hero, then an edit that keeps it preserves images[].
    data = _new_form(title="Keeper")
    data["image_url"] = HERO_URL
    slug = crud_client.post(
        "/new", data=data, follow_redirects=False
    ).headers["location"].removeprefix("/r/")

    keep = _new_form(title="Keeper")
    keep["image_url"] = HERO_URL
    crud_client.post(f"/r/{slug}/edit", data=keep, follow_redirects=False)
    assert HERO_URL in (crud_recipes_dir / f"{slug}.md").read_text()

    # An edit with the field blank removes the image.
    crud_client.post(f"/r/{slug}/edit", data=_new_form(title="Keeper"), follow_redirects=False)
    assert "images:" not in (crud_recipes_dir / f"{slug}.md").read_text()


@pytest.mark.parametrize("bad_url", ["javascript:alert(1)", "data:text/html,<h1>hi</h1>", "//evil.com/x.jpg"])
def test_new_post_rejects_invalid_image_url_scheme(crud_client: TestClient, bad_url: str) -> None:
    data = _new_form(title="Bad Image")
    data["image_url"] = bad_url
    resp = crud_client.post("/new", data=data, follow_redirects=False)
    assert resp.status_code == 200
    assert "URL must start with" in resp.text


@pytest.mark.parametrize("bad_url", ["javascript:alert(1)", "data:text/html,<h1>hi</h1>", "//evil.com/"])
def test_new_post_rejects_invalid_source_url_scheme(crud_client: TestClient, bad_url: str) -> None:
    data = _new_form(title="Bad Source")
    data["source_url"] = bad_url
    resp = crud_client.post("/new", data=data, follow_redirects=False)
    assert resp.status_code == 200
    assert "URL must start with" in resp.text


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


# ---------------------------------------------------------------------------
# Hierarchical corpus (Stage M2) — folders & subdir resolution
# ---------------------------------------------------------------------------


def test_new_post_into_folder(
    crud_client: TestClient, crud_recipes_dir: Path
) -> None:
    """A new recipe with a folder lands in that subdir and /r/{slug} resolves."""
    form = _new_form(title="Folder Pasta")
    form["folder"] = "dinner/quick"
    resp = crud_client.post("/new", data=form, follow_redirects=False)
    assert resp.status_code == 303
    slug = resp.headers["location"].removeprefix("/r/")

    nested = crud_recipes_dir / "dinner" / "quick" / f"{slug}.md"
    assert nested.is_file(), f"expected {nested} to exist"
    assert not (crud_recipes_dir / f"{slug}.md").exists()

    detail = crud_client.get(f"/r/{slug}")
    assert detail.status_code == 200
    assert "Folder Pasta" in detail.text


def test_find_recipe_file_warns_on_duplicate_slug(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    """A stem collision returns the first sorted path but logs a warning."""
    import logging

    from app.web.forms import find_recipe_file

    recipes_dir = tmp_path / "recipes"
    (recipes_dir / "a").mkdir(parents=True)
    (recipes_dir / "b").mkdir(parents=True)
    (recipes_dir / "a" / "dup.md").write_text("x")
    (recipes_dir / "b" / "dup.md").write_text("y")

    with caplog.at_level(logging.WARNING, logger="app.web.forms"):
        found = find_recipe_file(recipes_dir, "dup")

    assert found == recipes_dir / "a" / "dup.md"
    assert any("duplicate slug" in r.message for r in caplog.records)


def test_resolve_new_recipe_path_rejects_symlinked_folder(tmp_path: Path) -> None:
    """A symlinked folder component must not let .resolve() escape the tree."""
    from app.web.forms import resolve_new_recipe_path

    recipes_dir = tmp_path / "recipes"
    recipes_dir.mkdir()
    outside = tmp_path / "outside"
    outside.mkdir()
    (recipes_dir / "escape").symlink_to(outside, target_is_directory=True)

    path, issue = resolve_new_recipe_path(recipes_dir, "evil", "escape")
    assert path is None
    assert issue is not None
    assert issue.code == "folder.invalid"


@pytest.mark.parametrize("folder", ["../escape", "/abs/path", "_drafts", "images", "images/sub"])
def test_new_post_rejects_bad_folder(
    crud_client: TestClient, crud_recipes_dir: Path, folder: str
) -> None:
    form = _new_form(title="Bad Folder")
    form["folder"] = folder
    resp = crud_client.post("/new", data=form)
    assert resp.status_code == 200
    assert "folder" in resp.text.lower()
    # Nothing written anywhere in the tree.
    assert not list(crud_recipes_dir.rglob("bad-folder.md"))


def _seed_nested_recipe(crud_recipes_dir: Path, crud_db: Path) -> str:
    """Move the seeded overnight-oats recipe into a subdir and re-sync. Returns slug."""
    from app.db import sync

    src = crud_recipes_dir / "overnight-oats.md"
    dest_dir = crud_recipes_dir / "breakfast"
    dest_dir.mkdir(exist_ok=True)
    dest = dest_dir / "overnight-oats.md"
    dest.write_text(src.read_text())
    src.unlink()
    report = sync.rebuild_index(crud_recipes_dir, crud_db)
    assert not report.errors, report.errors
    return "overnight-oats"


def test_edit_recipe_in_subdir_rewrites_in_place(
    crud_client: TestClient, crud_recipes_dir: Path, crud_db: Path
) -> None:
    slug = _seed_nested_recipe(crud_recipes_dir, crud_db)
    nested = crud_recipes_dir / "breakfast" / f"{slug}.md"

    edit_form = crud_client.get(f"/r/{slug}/edit")
    assert edit_form.status_code == 200

    form = _new_form(title="Overnight Oats", summary="Edited in place")
    resp = crud_client.post(f"/r/{slug}/edit", data=form, follow_redirects=False)
    assert resp.status_code == 303
    # Still in the subdir, not duplicated at top level.
    assert nested.is_file()
    assert not (crud_recipes_dir / f"{slug}.md").exists()
    assert "Edited in place" in nested.read_text()


def test_favorite_recipe_in_subdir(
    crud_client: TestClient, crud_recipes_dir: Path, crud_db: Path
) -> None:
    slug = _seed_nested_recipe(crud_recipes_dir, crud_db)
    nested = crud_recipes_dir / "breakfast" / f"{slug}.md"

    resp = crud_client.post(f"/r/{slug}/favorite", follow_redirects=False)
    assert resp.status_code == 303
    assert "favorite: true" in nested.read_text()


def test_new_post_slug_collision_across_folders(
    crud_client: TestClient, crud_recipes_dir: Path, crud_db: Path
) -> None:
    """A new slug colliding with a recipe in another folder is rejected."""
    _seed_nested_recipe(crud_recipes_dir, crud_db)
    form = _new_form(title="Overnight Oats")
    form["folder"] = "sides"
    resp = crud_client.post("/new", data=form)
    assert resp.status_code == 200
    assert "already exists" in resp.text.lower()
    assert not (crud_recipes_dir / "sides").exists()
