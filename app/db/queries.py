"""Typed read helpers used by the CLI and (later) the web layer."""

from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass
from pathlib import Path

from app.db.connection import connection


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


def list_tags(db_path: Path, recipe_id: str) -> list[str]:
    with connection(db_path) as conn:
        rows = conn.execute(
            """
            SELECT t.name FROM tags t
            JOIN recipe_tags rt ON rt.tag_id = t.id
            WHERE rt.recipe_id = ?
            ORDER BY t.name
            """,
            (recipe_id,),
        ).fetchall()
        return [str(r["name"]) for r in rows]


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


def search_recipes(db_path: Path, query: str, *, limit: int = 25) -> list[RecipeRow]:
    """FTS5 search. Special characters are escaped by wrapping each token as a phrase."""
    if not query.strip():
        return []
    # Wrap each whitespace-split token in double quotes to keep it a literal phrase
    # and let FTS5's prefix/AND semantics handle multi-word queries.
    tokens = [tok.replace('"', '""') for tok in query.split()]
    fts_query = " ".join(f'"{tok}"' for tok in tokens)
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
            (fts_query, limit),
        ).fetchall()
        return [_row_to_recipe(r) for r in rows]
