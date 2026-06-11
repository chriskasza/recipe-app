"""Tests for the read-only JSON API: /api/v1/recipes, /api/v1/facets, /api/v1/recipes/{slug}."""

from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient


def test_list_recipes_basic(client: TestClient, recipes_dir: Path) -> None:
    resp = client.get("/api/v1/recipes")
    assert resp.status_code == 200
    body = resp.json()
    expected_total = len(list(recipes_dir.rglob("*.md")))
    assert body["total"] == expected_total
    assert body["page"] == 1
    assert body["page_size"] == 24
    assert len(body["items"]) == expected_total
    slugs = {item["slug"] for item in body["items"]}
    assert "miso-glazed-eggplant" in slugs


def test_list_recipes_search_query(client: TestClient) -> None:
    resp = client.get("/api/v1/recipes", params={"q": "eggplant"})
    assert resp.status_code == 200
    body = resp.json()
    slugs = {item["slug"] for item in body["items"]}
    assert "miso-glazed-eggplant" in slugs


def test_list_recipes_filter_by_tag(client: TestClient) -> None:
    resp = client.get("/api/v1/recipes", params={"tag": "weeknight"})
    body = resp.json()
    slugs = {item["slug"] for item in body["items"]}
    assert "miso-glazed-eggplant" in slugs
    assert "lemon-garlic-roast-chicken" not in slugs


def test_list_recipes_pagination(client: TestClient, recipes_dir: Path) -> None:
    total = len(list(recipes_dir.rglob("*.md")))
    resp = client.get("/api/v1/recipes", params={"page_size": 1, "page": 1})
    body = resp.json()
    assert body["total"] == total
    assert body["page_size"] == 1
    assert len(body["items"]) == 1
    assert body["total_pages"] == total


def test_list_recipes_page_size_bounds(client: TestClient) -> None:
    assert client.get("/api/v1/recipes", params={"page_size": 0}).status_code == 422
    assert client.get("/api/v1/recipes", params={"page_size": 101}).status_code == 422


def test_facets_endpoint(client: TestClient) -> None:
    resp = client.get("/api/v1/facets")
    assert resp.status_code == 200
    body = resp.json()
    assert set(body.keys()) == {"tags", "cuisines", "meal_types", "dietary"}
    tag_names = {f["name"] for f in body["tags"]}
    assert "weeknight" in tag_names


def test_recipe_detail(client: TestClient) -> None:
    resp = client.get("/api/v1/recipes/miso-glazed-eggplant")
    assert resp.status_code == 200
    body = resp.json()
    assert body["slug"] == "miso-glazed-eggplant"
    assert body["title"]
    assert isinstance(body["ingredients"], list)
    assert len(body["ingredients"]) > 0
    assert "body_markdown" in body


def test_recipe_detail_404(client: TestClient) -> None:
    resp = client.get("/api/v1/recipes/no-such-recipe")
    assert resp.status_code == 404
