"""Tests for the bearer-token-gated JSON API write endpoints."""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

NEW_RECIPE = {
    "title": "API Test Pancakes",
    "summary": "Fluffy test pancakes.",
    "cuisine": "american",
    "meal_type": ["breakfast"],
    "tags": ["quick"],
    "dietary": [],
    "equipment": ["griddle"],
    "prep_minutes": 5,
    "cook_minutes": 10,
    "total_minutes": 15,
    "servings": 4,
    "ingredients": [
        {"name": "flour", "qty": 1, "unit": "cup", "original": "1 cup flour"},
        {"name": "egg", "qty": 1, "unit": "whole", "original": "1 egg"},
    ],
    "body": "## Description\n\nFluffy pancakes for testing.\n",
}


def test_create_recipe_requires_token(api_client: tuple[TestClient, str]) -> None:
    client, _token = api_client
    resp = client.post("/api/v1/recipes", json=NEW_RECIPE)
    assert resp.status_code == 401
    assert resp.headers["www-authenticate"] == "Bearer"


def test_create_recipe_garbage_token_rejected(api_client: tuple[TestClient, str]) -> None:
    client, _token = api_client
    resp = client.post(
        "/api/v1/recipes",
        json=NEW_RECIPE,
        headers={"Authorization": "Bearer recipes_not-a-real-token"},
    )
    assert resp.status_code == 401


def test_session_cookie_alone_is_not_accepted(crud_client: TestClient) -> None:
    """The API must ignore the session cookie even if the user is logged in."""
    resp = crud_client.post("/api/v1/recipes", json=NEW_RECIPE)
    assert resp.status_code == 401


def test_create_recipe_success(api_client: tuple[TestClient, str], crud_recipes_dir: Path) -> None:
    client, token = api_client
    resp = client.post(
        "/api/v1/recipes",
        json=NEW_RECIPE,
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["slug"] == "api-test-pancakes"
    assert resp.headers["location"] == "/api/v1/recipes/api-test-pancakes"

    on_disk = crud_recipes_dir / "api-test-pancakes.md"
    assert on_disk.is_file()

    detail = client.get("/api/v1/recipes/api-test-pancakes")
    assert detail.status_code == 200
    assert detail.json()["title"] == "API Test Pancakes"


def test_create_recipe_duplicate_slug_409(api_client: tuple[TestClient, str]) -> None:
    client, token = api_client
    headers = {"Authorization": f"Bearer {token}"}
    first = client.post("/api/v1/recipes", json=NEW_RECIPE, headers=headers)
    assert first.status_code == 201

    second = client.post("/api/v1/recipes", json=NEW_RECIPE, headers=headers)
    assert second.status_code == 409
    assert second.json()["detail"]["code"] == "validation_error"


def test_create_recipe_bad_url_422(api_client: tuple[TestClient, str]) -> None:
    client, token = api_client
    payload = {**NEW_RECIPE, "title": "Bad URL Recipe", "image_url": "not-a-url"}
    resp = client.post(
        "/api/v1/recipes", json=payload, headers={"Authorization": f"Bearer {token}"}
    )
    assert resp.status_code == 422
    issues = resp.json()["detail"]["issues"]
    assert any(i["path"] == "image_url" for i in issues)


def test_create_recipe_in_folder(
    api_client: tuple[TestClient, str], crud_recipes_dir: Path
) -> None:
    client, token = api_client
    payload = {**NEW_RECIPE, "title": "Folder Pancakes", "folder": "breakfast"}
    resp = client.post(
        "/api/v1/recipes", json=payload, headers={"Authorization": f"Bearer {token}"}
    )
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["path"] == "breakfast/folder-pancakes.md"
    assert (crud_recipes_dir / "breakfast" / "folder-pancakes.md").is_file()


def test_update_recipe_preserves_id_and_created_at(api_client: tuple[TestClient, str]) -> None:
    client, token = api_client
    headers = {"Authorization": f"Bearer {token}"}

    before = client.get("/api/v1/recipes/miso-glazed-eggplant").json()

    update_payload = {**NEW_RECIPE, "title": "Miso-Glazed Eggplant", "summary": "Updated summary."}
    resp = client.put("/api/v1/recipes/miso-glazed-eggplant", json=update_payload, headers=headers)
    assert resp.status_code == 200, resp.text

    after = client.get("/api/v1/recipes/miso-glazed-eggplant").json()
    assert after["id"] == before["id"]
    assert after["summary"] == "Updated summary."


def test_update_unknown_slug_404(api_client: tuple[TestClient, str]) -> None:
    client, token = api_client
    resp = client.put(
        "/api/v1/recipes/no-such-recipe",
        json=NEW_RECIPE,
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 404


@pytest.mark.parametrize("field", ["archived", "favorite"])
def test_set_flag_roundtrip(api_client: tuple[TestClient, str], field: str) -> None:
    client, token = api_client
    headers = {"Authorization": f"Bearer {token}"}

    resp = client.put(
        f"/api/v1/recipes/miso-glazed-eggplant/{field}",
        json={"value": True},
        headers=headers,
    )
    assert resp.status_code == 200, resp.text

    detail = client.get("/api/v1/recipes/miso-glazed-eggplant").json()
    assert detail[field] is True

    resp = client.put(
        f"/api/v1/recipes/miso-glazed-eggplant/{field}",
        json={"value": False},
        headers=headers,
    )
    assert resp.status_code == 200

    detail = client.get("/api/v1/recipes/miso-glazed-eggplant").json()
    assert detail[field] is False


def test_set_flag_unknown_slug_404(api_client: tuple[TestClient, str]) -> None:
    client, token = api_client
    resp = client.put(
        "/api/v1/recipes/no-such-recipe/favorite",
        json={"value": True},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 404


def test_set_flag_requires_token(api_client: tuple[TestClient, str]) -> None:
    client, _token = api_client
    resp = client.put("/api/v1/recipes/miso-glazed-eggplant/favorite", json={"value": True})
    assert resp.status_code == 401
