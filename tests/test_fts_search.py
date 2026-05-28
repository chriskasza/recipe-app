"""FTS5 search returns the expected slugs for known queries."""

from __future__ import annotations

from pathlib import Path

from app.db import queries, sync


def test_keyword_returns_expected_recipe(recipes_dir: Path, tmp_db: Path) -> None:
    sync.sync_all(recipes_dir, tmp_db)
    rows = queries.search_recipes(tmp_db, "eggplant")
    slugs = [r.slug for r in rows]
    assert "miso-glazed-eggplant" in slugs


def test_ingredient_match_via_fts(recipes_dir: Path, tmp_db: Path) -> None:
    sync.sync_all(recipes_dir, tmp_db)
    rows = queries.search_recipes(tmp_db, "chickpeas")
    assert any(r.slug == "chickpea-spinach-curry" for r in rows)


def test_multi_word_and_ranking(recipes_dir: Path, tmp_db: Path) -> None:
    sync.sync_all(recipes_dir, tmp_db)
    rows = queries.search_recipes(tmp_db, "tomato sauce")
    slugs = [r.slug for r in rows]
    assert slugs[0] == "simple-tomato-sauce"


def test_empty_query_returns_empty(recipes_dir: Path, tmp_db: Path) -> None:
    sync.sync_all(recipes_dir, tmp_db)
    assert queries.search_recipes(tmp_db, "") == []


def test_quoted_special_characters_dont_break(recipes_dir: Path, tmp_db: Path) -> None:
    """Tokens with single quotes or punctuation must not crash FTS."""
    sync.sync_all(recipes_dir, tmp_db)
    # Should not raise; result count is irrelevant.
    queries.search_recipes(tmp_db, "marcella's tomato")
