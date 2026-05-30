"""Direct tests for the library + facet query helpers."""

from __future__ import annotations

from pathlib import Path

from app.db import queries


def test_search_library_no_filters_returns_all(populated_db: Path) -> None:
    page = queries.search_library(populated_db)
    rows = page.rows
    slugs = {r.slug for r in rows}
    assert "miso-glazed-eggplant" in slugs
    assert "overnight-oats" in slugs
    assert "lemon-garlic-roast-chicken" in slugs
    assert len(rows) == queries.count_recipes(populated_db)
    assert page.total == queries.count_recipes(populated_db)


def test_search_library_fts_query(populated_db: Path) -> None:
    rows = queries.search_library(populated_db, query="eggplant", sort="relevance").rows
    assert any(r.slug == "miso-glazed-eggplant" for r in rows)


def test_search_library_or_within_facet(populated_db: Path) -> None:
    rows = queries.search_library(populated_db, dietary=["vegan", "vegetarian"]).rows
    slugs = {r.slug for r in rows}
    # Vegan: miso-eggplant, chickpea curry, overnight-oats.
    # Vegetarian: tomato sauce, french omelette, fire cider.
    assert {"miso-glazed-eggplant", "chickpea-spinach-curry", "overnight-oats"} <= slugs
    assert {"simple-tomato-sauce", "classic-french-omelette"} <= slugs


def test_search_library_and_across_groups(populated_db: Path) -> None:
    rows = queries.search_library(populated_db, dietary=["vegan"], cuisines=["indian"]).rows
    slugs = {r.slug for r in rows}
    assert slugs == {"chickpea-spinach-curry"}


def test_search_library_max_minutes_excludes_nulls(populated_db: Path) -> None:
    rows = queries.search_library(populated_db, max_minutes=10).rows
    slugs = {r.slug for r in rows}
    # Fast: omelette (5), overnight-oats (5).
    assert "classic-french-omelette" in slugs
    assert "overnight-oats" in slugs
    # Long-cook recipes excluded.
    assert "lemon-garlic-roast-chicken" not in slugs
    assert "simple-tomato-sauce" not in slugs
    # Fire cider has no total_minutes; should be excluded when max_minutes is set.
    assert "fire-cider" not in slugs


def test_search_library_min_minutes_excludes_nulls(populated_db: Path) -> None:
    rows = queries.search_library(populated_db, min_minutes=40).rows
    slugs = {r.slug for r in rows}
    # Long: tomato sauce (45), roast chicken (90).
    assert "simple-tomato-sauce" in slugs
    assert "lemon-garlic-roast-chicken" in slugs
    # Quicker recipes excluded.
    assert "classic-french-omelette" not in slugs
    assert "miso-glazed-eggplant" not in slugs
    # Fire cider has no total_minutes; excluded when min_minutes is set.
    assert "fire-cider" not in slugs


def test_search_library_min_max_minutes_window(populated_db: Path) -> None:
    rows = queries.search_library(populated_db, min_minutes=30, max_minutes=35).rows
    slugs = {r.slug for r in rows}
    assert slugs == {"miso-glazed-eggplant", "chickpea-spinach-curry"}


def test_search_library_favorites_only_empty_when_none(populated_db: Path) -> None:
    # No fixture recipe is favorited, so the favorites view is empty while the
    # unfiltered view returns the full corpus.
    assert queries.search_library(populated_db, favorites_only=True).rows == []
    assert queries.search_library(populated_db).rows != []


def test_search_library_sort_time_puts_nulls_last(populated_db: Path) -> None:
    rows = queries.search_library(populated_db, sort="time").rows
    times = [r.total_minutes for r in rows]
    # Non-null prefix is ascending.
    non_null = [t for t in times if t is not None]
    assert non_null == sorted(non_null)
    # Any None entries appear after all non-null ones.
    if None in times:
        first_none = times.index(None)
        assert all(t is None for t in times[first_none:])


def test_search_library_sort_title(populated_db: Path) -> None:
    rows = queries.search_library(populated_db, sort="title").rows
    titles = [r.title.lower() for r in rows]
    assert titles == sorted(titles)


def test_search_library_sort_recent(populated_db: Path) -> None:
    rows = queries.search_library(populated_db, sort="recent").rows
    updated = [r.updated_at for r in rows]
    assert updated == sorted(updated, reverse=True)


def test_search_library_relevance_falls_back_to_recent_without_query(populated_db: Path) -> None:
    relevance = queries.search_library(populated_db, sort="relevance").rows
    recent = queries.search_library(populated_db, sort="recent").rows
    assert [r.slug for r in relevance] == [r.slug for r in recent]


def test_search_library_paginates_with_limit_offset(populated_db: Path) -> None:
    total = queries.count_recipes(populated_db)
    assert total > 4, "fixture corpus too small to exercise paging"

    first = queries.search_library(populated_db, sort="title", limit=3, offset=0)
    assert first.total == total
    assert len(first.rows) == 3

    second = queries.search_library(populated_db, sort="title", limit=3, offset=3)
    assert second.total == total
    # No overlap between the two pages.
    assert {r.slug for r in first.rows}.isdisjoint({r.slug for r in second.rows})

    # Last page holds the remainder (fewer than the limit), total stays full.
    last_offset = (total - 1) // 3 * 3
    last = queries.search_library(populated_db, sort="title", limit=3, offset=last_offset)
    assert last.total == total
    assert 0 < len(last.rows) <= 3


def test_search_library_offset_past_end_is_empty(populated_db: Path) -> None:
    page = queries.search_library(populated_db, limit=24, offset=1000)
    assert page.rows == []
    # No rows means no window-function row to read the count from.
    assert page.total == 0


def test_facet_counts_reflect_other_filters(populated_db: Path) -> None:
    # Without filters, "weeknight" should be present in tag facets.
    unfiltered = {fc.name: fc.count for fc in queries.facet_counts_tags(populated_db)}
    assert "weeknight" in unfiltered
    # Filter to indian; weeknight count should drop (only chickpea curry has it).
    indian = {
        fc.name: fc.count for fc in queries.facet_counts_tags(populated_db, cuisines=["indian"])
    }
    assert indian.get("weeknight", 0) == 1


def test_facet_counts_exclude_own_group(populated_db: Path) -> None:
    # Even if a tag is already checked, the tag facet should still list all tags
    # available among recipes that satisfy the OTHER filters.
    selected = queries.facet_counts_tags(populated_db, tags=["weeknight"])
    names = {fc.name for fc in selected}
    # Should include tags other than weeknight (e.g., pantry).
    assert names - {"weeknight"}


def test_get_recipe_detail_bundles_everything(populated_db: Path) -> None:
    detail = queries.get_recipe_detail(populated_db, "miso-glazed-eggplant")
    assert detail is not None
    assert detail.recipe.title == "Miso-Glazed Eggplant"
    assert detail.body_markdown  # parsed body present
    assert detail.ingredients
    assert "vegan" in detail.dietary
    assert "dinner" in detail.meal_types or "side" in detail.meal_types
    assert detail.source_url


def test_get_recipe_detail_unknown_returns_none(populated_db: Path) -> None:
    assert queries.get_recipe_detail(populated_db, "no-such-slug") is None
