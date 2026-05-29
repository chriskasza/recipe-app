"""Sync the canonical Markdown corpus into the SQLite mirror.

Design:
- Walk ``recipes/*.md`` (skipping ``recipes/_drafts/``).
- Parse + validate each. Files with ERROR-level issues are skipped and surfaced.
- Use file mtime to short-circuit unchanged files unless ``force=True``.
- Upsert is delete-then-insert (with FK cascade clearing child tables); FTS5 triggers
  keep the search index aligned.
- After processing, recipes in the DB whose id no longer appears in the corpus are
  removed.
"""

from __future__ import annotations

import json
import sqlite3
from collections.abc import Iterable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path

from app.core.models import RecipeDocument
from app.core.parser import ParseError, parse_file
from app.core.validator import ValidationIssue, has_errors
from app.db.connection import connection, init_schema, schema_present

DRAFTS_DIR_NAME = "_drafts"


@dataclass
class SyncFileResult:
    path: Path
    recipe_id: str | None = None
    changed: bool = False
    skipped_reason: str | None = None
    issues: list[ValidationIssue] = field(default_factory=list)


@dataclass
class SyncReport:
    files_seen: int = 0
    files_changed: int = 0
    files_removed: int = 0
    file_results: list[SyncFileResult] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.errors


def _iter_recipe_files(recipes_dir: Path) -> Iterable[Path]:
    for path in sorted(recipes_dir.glob("*.md")):
        if DRAFTS_DIR_NAME in path.parts:
            continue
        yield path


def _ensure_schema(conn: sqlite3.Connection) -> None:
    if not schema_present(conn):
        init_schema(conn)


def _name_id(conn: sqlite3.Connection, table: str, name: str) -> int:
    """Get-or-create a row in a normalized name table; return its id."""
    conn.execute(f"INSERT OR IGNORE INTO {table}(name) VALUES (?)", (name,))
    row = conn.execute(f"SELECT id FROM {table} WHERE name = ?", (name,)).fetchone()
    return int(row["id"])


def _delete_recipe(conn: sqlite3.Connection, recipe_id: str) -> None:
    conn.execute("DELETE FROM recipes WHERE id = ?", (recipe_id,))


def _upsert_recipe(
    conn: sqlite3.Connection, doc: RecipeDocument, path: Path, mtime: float
) -> None:
    """Replace the recipe row and all child rows. FK cascade clears children."""
    recipe = doc.recipe
    _delete_recipe(conn, recipe.id)

    ingredient_names = " ".join(ing.name for ing in recipe.ingredients)
    frontmatter_json = json.dumps(
        recipe.model_dump(mode="json", exclude={"body"}), sort_keys=True
    )

    conn.execute(
        """
        INSERT INTO recipes (
          id, slug, title, summary, cuisine, servings,
          prep_minutes, cook_minutes, total_minutes,
          source_url, source_attribution,
          archived, favorite, created_at, updated_at,
          file_path, file_mtime,
          body_markdown, ingredient_names, frontmatter_json
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            recipe.id,
            recipe.slug,
            recipe.title,
            recipe.summary,
            recipe.cuisine,
            recipe.servings,
            recipe.prep_minutes,
            recipe.cook_minutes,
            recipe.total_minutes,
            recipe.source.url if recipe.source else None,
            recipe.source.attribution if recipe.source else None,
            1 if recipe.archived else 0,
            1 if recipe.favorite else 0,
            _iso(recipe.created_at),
            _iso(recipe.updated_at),
            str(path),
            mtime,
            doc.raw_body,
            ingredient_names,
            frontmatter_json,
        ),
    )

    for position, ing in enumerate(recipe.ingredients):
        ingredient_id = _name_id(conn, "ingredients", ing.name.strip().lower())
        conn.execute(
            """
            INSERT INTO recipe_ingredients (
              recipe_id, position, ingredient_id, qty, unit, prep, optional, original_text
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                recipe.id,
                position,
                ingredient_id,
                ing.qty,
                ing.unit,
                ing.prep,
                1 if ing.optional else 0,
                ing.original,
            ),
        )

    _link_names(conn, recipe.id, "tags", "recipe_tags", "tag_id", recipe.tags)
    _link_names(
        conn, recipe.id, "meal_types", "recipe_meal_types", "meal_type_id", recipe.meal_type
    )
    _link_names(
        conn,
        recipe.id,
        "dietary_flags",
        "recipe_dietary",
        "dietary_id",
        recipe.dietary,
    )
    _link_names(
        conn, recipe.id, "equipment", "recipe_equipment", "equipment_id", recipe.equipment
    )


def _link_names(
    conn: sqlite3.Connection,
    recipe_id: str,
    name_table: str,
    link_table: str,
    fk_column: str,
    values: list[str],
) -> None:
    for raw in values:
        name = raw.strip().lower()
        if not name:
            continue
        name_id = _name_id(conn, name_table, name)
        conn.execute(
            f"INSERT OR IGNORE INTO {link_table}(recipe_id, {fk_column}) VALUES (?, ?)",
            (recipe_id, name_id),
        )


def _iso(dt: datetime) -> str:
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)
    return dt.astimezone(UTC).isoformat().replace("+00:00", "Z")


def _current_db_state(conn: sqlite3.Connection) -> dict[str, tuple[float, str]]:
    """Map recipe id → (file_mtime, slug) for cheap mtime comparison."""
    rows = conn.execute("SELECT id, file_mtime, slug FROM recipes").fetchall()
    return {r["id"]: (float(r["file_mtime"]), str(r["slug"])) for r in rows}


def sync_all(recipes_dir: Path, db_path: Path, *, force: bool = False) -> SyncReport:
    """Sync the entire corpus. Returns a report; partial failures don't abort the run."""
    report = SyncReport()

    with connection(db_path) as conn:
        _ensure_schema(conn)
        run_started = _now_iso()
        cursor = conn.execute(
            "INSERT INTO sync_runs(started_at) VALUES (?)", (run_started,)
        )
        run_id = cursor.lastrowid

        previous = _current_db_state(conn)
        seen_ids: set[str] = set()

        for path in _iter_recipe_files(recipes_dir):
            report.files_seen += 1
            result = SyncFileResult(path=path)

            try:
                doc, issues = parse_file(path)
            except ParseError as exc:
                msg = f"{path}: {exc}"
                report.errors.append(msg)
                result.skipped_reason = f"parse error: {exc}"
                report.file_results.append(result)
                continue
            except Exception as exc:
                msg = f"{path}: {exc}"
                report.errors.append(msg)
                result.skipped_reason = f"validation error: {exc}"
                report.file_results.append(result)
                continue

            result.recipe_id = doc.recipe.id
            result.issues = issues
            seen_ids.add(doc.recipe.id)

            if has_errors(issues):
                msg = f"{path}: {sum(1 for i in issues if i.level.value == 'error')} validation error(s)"
                report.errors.append(msg)
                result.skipped_reason = "validation errors"
                report.file_results.append(result)
                continue

            mtime = path.stat().st_mtime
            prev = previous.get(doc.recipe.id)
            if not force and prev is not None and abs(prev[0] - mtime) < 1e-6:
                result.skipped_reason = "unchanged"
                report.file_results.append(result)
                continue

            try:
                _upsert_recipe(conn, doc, path, mtime)
                conn.commit()
                result.changed = True
                report.files_changed += 1
            except Exception as exc:
                conn.rollback()
                msg = f"{path}: upsert failed: {exc}"
                report.errors.append(msg)
                result.skipped_reason = "upsert failed"

            report.file_results.append(result)

        # Sweep: anything in the DB that isn't in the corpus anymore.
        orphans = [rid for rid in previous if rid not in seen_ids]
        for rid in orphans:
            _delete_recipe(conn, rid)
            report.files_removed += 1
        conn.commit()

        conn.execute(
            """
            UPDATE sync_runs SET finished_at=?, files_seen=?, files_changed=?,
              files_removed=?, errors_json=? WHERE id=?
            """,
            (
                _now_iso(),
                report.files_seen,
                report.files_changed,
                report.files_removed,
                json.dumps(report.errors),
                run_id,
            ),
        )
        conn.commit()

    return report


def sync_one(path: Path, recipes_dir: Path, db_path: Path) -> SyncReport:
    """Sync a single file through the same pipeline. Used by the web write-path."""
    report = SyncReport()
    with connection(db_path) as conn:
        _ensure_schema(conn)
        result = SyncFileResult(path=path)
        report.files_seen = 1

        if not path.is_file():
            report.errors.append(f"{path}: not a file")
            return report

        try:
            doc, issues = parse_file(path)
        except (ParseError, Exception) as exc:
            report.errors.append(f"{path}: {exc}")
            return report

        result.recipe_id = doc.recipe.id
        result.issues = issues
        if has_errors(issues):
            report.errors.append(f"{path}: validation errors")
            return report

        try:
            _upsert_recipe(conn, doc, path, path.stat().st_mtime)
            conn.commit()
            result.changed = True
            report.files_changed = 1
        except Exception as exc:
            conn.rollback()
            report.errors.append(f"{path}: upsert failed: {exc}")
        report.file_results.append(result)

    return report


def rebuild_index(recipes_dir: Path, db_path: Path) -> SyncReport:
    """Drop the DB file and re-sync from scratch."""
    if db_path.exists():
        db_path.unlink()
    for sidecar in (db_path.with_suffix(db_path.suffix + "-wal"), db_path.with_suffix(db_path.suffix + "-shm")):
        if sidecar.exists():
            sidecar.unlink()
    return sync_all(recipes_dir, db_path, force=True)


def validate_all(recipes_dir: Path) -> list[tuple[Path, list[ValidationIssue]]]:
    """Parse + validate every recipe without touching the DB.

    Files that fail to parse appear in the result with a single synthesized error issue,
    so callers don't need to special-case parse exceptions.
    """
    from app.core.validator import IssueLevel  # local import to avoid cycle at module load

    results: list[tuple[Path, list[ValidationIssue]]] = []
    for path in _iter_recipe_files(recipes_dir):
        try:
            _, issues = parse_file(path)
        except Exception as exc:
            issues = [
                ValidationIssue(IssueLevel.ERROR, "parse.error", str(exc), "")
            ]
        results.append((path, issues))
    return results


def _now_iso() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")
