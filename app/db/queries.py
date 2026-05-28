"""Typed read helpers used by the CLI and (later) the web layer."""

from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from app.db.connection import connection

SortKey = Literal["relevance", "recent", "time", "title"]


@dataclass(frozen=True)
class RecipeRow:
    id: str
    slug: str
    title: str
    summary: str | None
    cuisine: str | None
    servings: int | None
    prep_minutes: int | None
    cook_minutes: int | None
    total_minutes: int | None
    archived: bool
    updated_at: str
    file_path: str


@dataclass(frozen=True)
class RecipeIngredientRow:
    position: int
    name: str
    qty: float | None
    unit: str | None
    prep: str | None
    optional: bool
    original_text: str


@dataclass(frozen=True)
class LibraryRow:
    """Compact row used by the library card grid."""

    id: str
    slug: str
    title: str
    summary: str | None
    cuisine: str | None
    total_minutes: int | None
    updated_at: str
    tags: tuple[str, ...]
    dietary: tuple[str, ...]
    meal_types: tuple[str, ...]


@dataclass(frozen=True)
class FacetCount:
    name: str
    count: int


@dataclass(frozen=True)
class RecipeDetail:
    """Everything the recipe detail page needs in one bundle."""

    recipe: RecipeRow
    body_markdown: str
    frontmatter: dict[str, object]
    source_url: str | None
    source_attribution: str | None
    ingredients: list[RecipeIngredientRow]
    tags: list[str]
    meal_types: list[str]
    dietary: list[str]
    equipment: list[str]


def _row_to_recipe(row: sqlite3.Row) -> RecipeRow:
    return RecipeRow(
        id=row["id"],
        slug=row["slug"],
        title=row["title"],
        summary=row["summary"],
        cuisine=row["cuisine"],
        servings=row["servings"],
        prep_minutes=row["prep_minutes"],
        cook_minutes=row["cook_minutes"],
        total_minutes=row["total_minutes"],
        archived=bool(row["archived"]),
        updated_at=row["updated_at"],
        file_path=row["file_path"],
    )


def get_recipe_by_slug(db_path: Path, slug: str) -> RecipeRow | None:
    with connection(db_path) as conn:
        row = conn.execute(
            "SELECT * FROM recipes WHERE slug = ?", (slug,)
        ).fetchone()
        return _row_to_recipe(row) if row else None


def get_ingredients(db_path: Path, recipe_id: str) -> list[RecipeIngredientRow]:
    with connection(db_path) as conn:
        rows = conn.execute(
            """
            SELECT ri.position, i.name, ri.qty, ri.unit, ri.prep, ri.optional, ri.original_text
            FROM recipe_ingredients ri
            JOIN ingredients i ON i.id = ri.ingredient_id
            WHERE ri.recipe_id = ?
            ORDER BY ri.position
            """,
            (recipe_id,),
        ).fetchall()
        return [
            RecipeIngredientRow(
                position=int(r["position"]),
                name=str(r["name"]),
                qty=float(r["qty"]) if r["qty"] is not None else None,
                unit=r["unit"],
                prep=r["prep"],
                optional=bool(r["optional"]),
                original_text=str(r["original_text"]),
            )
            for r in rows
        ]


def _list_linked_names(
    db_path: Path,
    recipe_id: str,
    name_table: str,
    link_table: str,
    fk_column: str,
) -> list[str]:
    with connection(db_path) as conn:
        rows = conn.execute(
            f"""
            SELECT n.name FROM {name_table} n
            JOIN {link_table} link ON link.{fk_column} = n.id
            WHERE link.recipe_id = ?
            ORDER BY n.name
            """,
            (recipe_id,),
        ).fetchall()
        return [str(r["name"]) for r in rows]


def list_tags(db_path: Path, recipe_id: str) -> list[str]:
    return _list_linked_names(db_path, recipe_id, "tags", "recipe_tags", "tag_id")


def list_meal_types(db_path: Path, recipe_id: str) -> list[str]:
    return _list_linked_names(
        db_path, recipe_id, "meal_types", "recipe_meal_types", "meal_type_id"
    )


def list_dietary(db_path: Path, recipe_id: str) -> list[str]:
    return _list_linked_names(
        db_path, recipe_id, "dietary_flags", "recipe_dietary", "dietary_id"
    )


def list_equipment(db_path: Path, recipe_id: str) -> list[str]:
    return _list_linked_names(
        db_path, recipe_id, "equipment", "recipe_equipment", "equipment_id"
    )


def count_recipes(db_path: Path) -> int:
    with connection(db_path) as conn:
        row = conn.execute("SELECT count(*) AS n FROM recipes").fetchone()
        return int(row["n"])


def count_fts_rows(db_path: Path) -> int:
    with connection(db_path) as conn:
        row = conn.execute("SELECT count(*) AS n FROM recipes_fts").fetchone()
        return int(row["n"])


def last_sync_run(db_path: Path) -> dict[str, object] | None:
    with connection(db_path) as conn:
        row = conn.execute(
            "SELECT * FROM sync_runs ORDER BY id DESC LIMIT 1"
        ).fetchone()
        if row is None:
            return None
        d = dict(row)
        if d.get("errors_json"):
            try:
                d["errors"] = json.loads(d["errors_json"])
            except json.JSONDecodeError:
                d["errors"] = [d["errors_json"]]
        return d


def _fts_match_query(query: str) -> str:
    """Escape user input for FTS5 by wrapping each token as a literal phrase."""
    tokens = [tok.replace('"', '""') for tok in query.split()]
    return " ".join(f'"{tok}"' for tok in tokens)


def search_recipes(db_path: Path, query: str, *, limit: int = 25) -> list[RecipeRow]:
    """FTS5 search. Special characters are escaped by wrapping each token as a phrase."""
    if not query.strip():
        return []
    with connection(db_path) as conn:
        rows = conn.execute(
            """
            SELECT r.*
            FROM recipes_fts f
            JOIN recipes r ON r.rowid = f.rowid
            WHERE recipes_fts MATCH ?
            ORDER BY rank
            LIMIT ?
            """,
            (_fts_match_query(query), limit),
        ).fetchall()
        return [_row_to_recipe(r) for r in rows]


# ---------------------------------------------------------------------------
# Library: combined search + facets + sort
# ---------------------------------------------------------------------------

# Each facet group: (parameter list, link table, fk column, vocab table).
_FACET_GROUPS: dict[str, tuple[str, str, str]] = {
    "tags": ("recipe_tags", "tag_id", "tags"),
    "meal_types": ("recipe_meal_types", "meal_type_id", "meal_types"),
    "dietary": ("recipe_dietary", "dietary_id", "dietary_flags"),
    "equipment": ("recipe_equipment", "equipment_id", "equipment"),
}


def _build_filters(
    *,
    query: str | None,
    tags: list[str],
    cuisines: list[str],
    meal_types: list[str],
    dietary: list[str],
    max_minutes: int | None,
    exclude_group: str | None = None,
) -> tuple[list[str], list[object], bool]:
    """Build the shared WHERE fragments and params used by library + facet queries.

    Returns (where_clauses, params, has_fts). ``exclude_group`` lets a facet helper
    skip its own group so checking a value within a facet still shows the rest of
    that facet's options."""

    where: list[str] = ["r.archived = 0"]
    params: list[object] = []
    has_fts = bool(query and query.strip())

    if has_fts:
        # Joined as a CTE in the caller; the placeholder is added there.
        pass

    facet_values: dict[str, list[str]] = {
        "tags": tags,
        "meal_types": meal_types,
        "dietary": dietary,
    }
    for group, values in facet_values.items():
        if group == exclude_group or not values:
            continue
        link, fk, vocab = _FACET_GROUPS[group]
        placeholders = ", ".join("?" for _ in values)
        where.append(
            f"EXISTS (SELECT 1 FROM {link} link JOIN {vocab} v ON v.id = link.{fk} "
            f"WHERE link.recipe_id = r.id AND v.name IN ({placeholders}))"
        )
        params.extend(values)

    if exclude_group != "cuisines" and cuisines:
        placeholders = ", ".join("?" for _ in cuisines)
        where.append(f"r.cuisine IN ({placeholders})")
        params.extend(cuisines)

    if max_minutes is not None:
        where.append("r.total_minutes IS NOT NULL AND r.total_minutes <= ?")
        params.append(max_minutes)

    return where, params, has_fts


def search_library(
    db_path: Path,
    *,
    query: str | None = None,
    tags: list[str] | None = None,
    cuisines: list[str] | None = None,
    meal_types: list[str] | None = None,
    dietary: list[str] | None = None,
    max_minutes: int | None = None,
    sort: SortKey = "recent",
    limit: int = 100,
) -> list[LibraryRow]:
    """Library search combining FTS + facet filters + sort."""
    tags = tags or []
    cuisines = cuisines or []
    meal_types = meal_types or []
    dietary = dietary or []

    where, params, has_fts = _build_filters(
        query=query,
        tags=tags,
        cuisines=cuisines,
        meal_types=meal_types,
        dietary=dietary,
        max_minutes=max_minutes,
    )

    effective_sort: SortKey = sort
    if effective_sort == "relevance" and not has_fts:
        effective_sort = "recent"

    select_cols = [
        "r.id",
        "r.slug",
        "r.title",
        "r.summary",
        "r.cuisine",
        "r.total_minutes",
        "r.updated_at",
        "(SELECT GROUP_CONCAT(t.name, '|') FROM recipe_tags rt JOIN tags t ON t.id = rt.tag_id "
        "WHERE rt.recipe_id = r.id) AS tag_names",
        "(SELECT GROUP_CONCAT(d.name, '|') FROM recipe_dietary rd JOIN dietary_flags d ON d.id = rd.dietary_id "
        "WHERE rd.recipe_id = r.id) AS dietary_names",
        "(SELECT GROUP_CONCAT(m.name, '|') FROM recipe_meal_types rm JOIN meal_types m ON m.id = rm.meal_type_id "
        "WHERE rm.recipe_id = r.id) AS meal_type_names",
    ]

    sort_sql = {
        "recent": "r.updated_at DESC",
        "time": "r.total_minutes IS NULL, r.total_minutes ASC, r.title COLLATE NOCASE ASC",
        "title": "r.title COLLATE NOCASE ASC",
        "relevance": "fts.rank",
    }[effective_sort]

    sql_params: list[object] = []
    if has_fts:
        select_cols.append("fts.rank AS fts_rank")
        sql = (
            "SELECT " + ", ".join(select_cols) + " FROM recipes r "
            "JOIN (SELECT rowid, rank FROM recipes_fts WHERE recipes_fts MATCH ?) fts "
            "ON fts.rowid = r.rowid "
            "WHERE " + " AND ".join(where) + " "
            "ORDER BY " + sort_sql + " "
            "LIMIT ?"
        )
        sql_params.append(_fts_match_query(query or ""))
        sql_params.extend(params)
        sql_params.append(limit)
    else:
        sql = (
            "SELECT " + ", ".join(select_cols) + " FROM recipes r "
            "WHERE " + " AND ".join(where) + " "
            "ORDER BY " + sort_sql + " "
            "LIMIT ?"
        )
        sql_params.extend(params)
        sql_params.append(limit)

    with connection(db_path) as conn:
        rows = conn.execute(sql, sql_params).fetchall()

    def _split(value: object) -> tuple[str, ...]:
        if value is None:
            return ()
        return tuple(sorted(str(value).split("|")))

    return [
        LibraryRow(
            id=str(r["id"]),
            slug=str(r["slug"]),
            title=str(r["title"]),
            summary=r["summary"],
            cuisine=r["cuisine"],
            total_minutes=r["total_minutes"],
            updated_at=str(r["updated_at"]),
            tags=_split(r["tag_names"]),
            dietary=_split(r["dietary_names"]),
            meal_types=_split(r["meal_type_names"]),
        )
        for r in rows
    ]


def _facet_counts(
    db_path: Path,
    *,
    group: str,
    query: str | None,
    tags: list[str],
    cuisines: list[str],
    meal_types: list[str],
    dietary: list[str],
    max_minutes: int | None,
) -> list[FacetCount]:
    """Return name + count for one facet group, scoped to the current filter set
    minus the group's own selection (so counts reflect "what's still available")."""

    where, params, has_fts = _build_filters(
        query=query,
        tags=tags,
        cuisines=cuisines,
        meal_types=meal_types,
        dietary=dietary,
        max_minutes=max_minutes,
        exclude_group=group,
    )

    if group == "cuisines":
        select = (
            "SELECT r.cuisine AS name, COUNT(*) AS n FROM recipes r "
            + ("JOIN (SELECT rowid FROM recipes_fts WHERE recipes_fts MATCH ?) fts ON fts.rowid = r.rowid " if has_fts else "")
            + "WHERE " + " AND ".join([*where, "r.cuisine IS NOT NULL"]) + " "
            "GROUP BY r.cuisine ORDER BY n DESC, name ASC"
        )
    else:
        link, fk, vocab = _FACET_GROUPS[group]
        select = (
            "SELECT v.name AS name, COUNT(DISTINCT r.id) AS n "
            "FROM recipes r "
            + ("JOIN (SELECT rowid FROM recipes_fts WHERE recipes_fts MATCH ?) fts ON fts.rowid = r.rowid " if has_fts else "")
            + f"JOIN {link} link ON link.recipe_id = r.id "
            f"JOIN {vocab} v ON v.id = link.{fk} "
            f"WHERE " + " AND ".join(where) + " "
            "GROUP BY v.name ORDER BY n DESC, name ASC"
        )

    sql_params: list[object] = []
    if has_fts:
        sql_params.append(_fts_match_query(query or ""))
    sql_params.extend(params)

    with connection(db_path) as conn:
        rows = conn.execute(select, sql_params).fetchall()
    return [FacetCount(name=str(r["name"]), count=int(r["n"])) for r in rows]


def facet_counts_tags(
    db_path: Path,
    *,
    query: str | None = None,
    tags: list[str] | None = None,
    cuisines: list[str] | None = None,
    meal_types: list[str] | None = None,
    dietary: list[str] | None = None,
    max_minutes: int | None = None,
) -> list[FacetCount]:
    return _facet_counts(
        db_path,
        group="tags",
        query=query,
        tags=tags or [],
        cuisines=cuisines or [],
        meal_types=meal_types or [],
        dietary=dietary or [],
        max_minutes=max_minutes,
    )


def facet_counts_cuisines(
    db_path: Path,
    *,
    query: str | None = None,
    tags: list[str] | None = None,
    cuisines: list[str] | None = None,
    meal_types: list[str] | None = None,
    dietary: list[str] | None = None,
    max_minutes: int | None = None,
) -> list[FacetCount]:
    return _facet_counts(
        db_path,
        group="cuisines",
        query=query,
        tags=tags or [],
        cuisines=cuisines or [],
        meal_types=meal_types or [],
        dietary=dietary or [],
        max_minutes=max_minutes,
    )


def facet_counts_meal_types(
    db_path: Path,
    *,
    query: str | None = None,
    tags: list[str] | None = None,
    cuisines: list[str] | None = None,
    meal_types: list[str] | None = None,
    dietary: list[str] | None = None,
    max_minutes: int | None = None,
) -> list[FacetCount]:
    return _facet_counts(
        db_path,
        group="meal_types",
        query=query,
        tags=tags or [],
        cuisines=cuisines or [],
        meal_types=meal_types or [],
        dietary=dietary or [],
        max_minutes=max_minutes,
    )


def facet_counts_dietary(
    db_path: Path,
    *,
    query: str | None = None,
    tags: list[str] | None = None,
    cuisines: list[str] | None = None,
    meal_types: list[str] | None = None,
    dietary: list[str] | None = None,
    max_minutes: int | None = None,
) -> list[FacetCount]:
    return _facet_counts(
        db_path,
        group="dietary",
        query=query,
        tags=tags or [],
        cuisines=cuisines or [],
        meal_types=meal_types or [],
        dietary=dietary or [],
        max_minutes=max_minutes,
    )


def get_recipe_detail(db_path: Path, slug: str) -> RecipeDetail | None:
    """Bundle everything the recipe detail page needs in a single facade."""
    with connection(db_path) as conn:
        row = conn.execute(
            "SELECT * FROM recipes WHERE slug = ?", (slug,)
        ).fetchone()
        if row is None:
            return None
        recipe = _row_to_recipe(row)
        body_markdown = str(row["body_markdown"])
        try:
            frontmatter = json.loads(row["frontmatter_json"])
            if not isinstance(frontmatter, dict):
                frontmatter = {}
        except json.JSONDecodeError:
            frontmatter = {}
        source_url = row["source_url"]
        source_attribution = row["source_attribution"]

    return RecipeDetail(
        recipe=recipe,
        body_markdown=body_markdown,
        frontmatter=frontmatter,
        source_url=source_url,
        source_attribution=source_attribution,
        ingredients=get_ingredients(db_path, recipe.id),
        tags=list_tags(db_path, recipe.id),
        meal_types=list_meal_types(db_path, recipe.id),
        dietary=list_dietary(db_path, recipe.id),
        equipment=list_equipment(db_path, recipe.id),
    )
