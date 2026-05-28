"""Tests for the recipe detail page (GET /r/{slug})."""

from __future__ import annotations

from fastapi.testclient import TestClient


def test_recipe_page_renders(client: TestClient) -> None:
    resp = client.get("/r/simple-tomato-sauce")
    assert resp.status_code == 200
    body = resp.text
    assert "Simple Tomato Sauce" in body
    # An ingredient's original_text should be in the page.
    assert "San Marzano" in body
    # Source attribution appears.
    assert "Marcella Hazan" in body


def test_recipe_page_renders_markdown_body(client: TestClient) -> None:
    resp = client.get("/r/chickpea-spinach-curry")
    assert resp.status_code == 200
    body = resp.text
    # Markdown body sections should be rendered to HTML — instructions are numbered,
    # so an <ol> should appear.
    assert "<ol>" in body
    assert "<li>" in body


def test_recipe_page_with_source_url(client: TestClient) -> None:
    resp = client.get("/r/miso-glazed-eggplant")
    assert resp.status_code == 200
    body = resp.text
    assert 'href="https://example.com/miso-eggplant"' in body


def test_recipe_page_404(client: TestClient) -> None:
    resp = client.get("/r/no-such-recipe")
    assert resp.status_code == 404
