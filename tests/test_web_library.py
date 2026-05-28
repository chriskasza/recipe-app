"""Tests for the library page (GET /) and HTMX search fragment (GET /search)."""

from __future__ import annotations

import re

from fastapi.testclient import TestClient


def test_library_page_renders_full_html(client: TestClient) -> None:
    resp = client.get("/")
    assert resp.status_code == 200
    body = resp.text
    assert "<html" in body
    assert "Library" in body
    assert 'id="filters"' in body
    # At least one recipe card present.
    assert "/r/miso-glazed-eggplant" in body


def test_search_endpoint_returns_fragment(client: TestClient) -> None:
    resp = client.get("/search", params={"q": "eggplant"})
    assert resp.status_code == 200
    body = resp.text
    # Fragment, not a full page.
    assert "<html" not in body
    assert "/r/miso-glazed-eggplant" in body
    # OOB facets aside is included.
    assert 'id="facets"' in body
    assert 'hx-swap-oob="true"' in body


def test_search_filter_by_tag(client: TestClient) -> None:
    resp = client.get("/search", params={"tag": "weeknight"})
    assert resp.status_code == 200
    body = resp.text
    # weeknight recipes: miso eggplant, chickpea curry, simple tomato sauce.
    assert "/r/miso-glazed-eggplant" in body
    assert "/r/chickpea-spinach-curry" in body
    assert "/r/simple-tomato-sauce" in body
    # Non-weeknight recipes excluded.
    assert "/r/lemon-garlic-roast-chicken" not in body
    assert "/r/overnight-oats" not in body


def test_search_filter_by_max_minutes(client: TestClient) -> None:
    resp = client.get("/search", params={"max_minutes": 10})
    body = resp.text
    assert "/r/overnight-oats" in body
    assert "/r/classic-french-omelette" in body
    assert "/r/lemon-garlic-roast-chicken" not in body


def test_search_sort_title_orders_alphabetically(client: TestClient) -> None:
    resp = client.get("/search", params={"sort": "title"})
    body = resp.text
    # Extract <a href="/r/{slug}">Title</a> from cards, in DOM order.
    titles = re.findall(r'<a href="/r/[^"]+">([^<]+)</a>', body)
    assert titles
    assert titles == sorted(titles, key=str.lower)


def test_search_unknown_combination_returns_empty_message(client: TestClient) -> None:
    resp = client.get(
        "/search",
        params={"tag": ["weeknight"], "cuisine": ["french"]},
    )
    body = resp.text
    assert "No recipes match" in body
