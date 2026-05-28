"""Sync must be idempotent: a second consecutive run reports zero changes."""

from __future__ import annotations

from pathlib import Path

from app.db import sync
from app.db.connection import connection
from app.db.queries import count_fts_rows, count_recipes


def test_sync_then_sync_is_noop(recipes_dir: Path, tmp_db: Path) -> None:
    first = sync.sync_all(recipes_dir, tmp_db)
    assert first.ok, first.errors
    assert first.files_changed == 6
    assert count_recipes(tmp_db) == 6

    second = sync.sync_all(recipes_dir, tmp_db)
    assert second.ok, second.errors
    assert second.files_changed == 0
    assert second.files_removed == 0


def test_force_resyncs_all(recipes_dir: Path, tmp_db: Path) -> None:
    sync.sync_all(recipes_dir, tmp_db)
    forced = sync.sync_all(recipes_dir, tmp_db, force=True)
    assert forced.files_changed == 6


def test_rebuild_recreates_everything(recipes_dir: Path, tmp_db: Path) -> None:
    sync.sync_all(recipes_dir, tmp_db)
    pre = count_recipes(tmp_db)
    pre_fts = count_fts_rows(tmp_db)
    report = sync.rebuild_index(recipes_dir, tmp_db)
    assert report.ok
    assert count_recipes(tmp_db) == pre == 6
    assert count_fts_rows(tmp_db) == pre_fts == 6


def test_orphan_is_removed(recipes_dir: Path, tmp_db: Path, tmp_path: Path) -> None:
    # Copy seeds into a scratch dir so we can delete one without touching the real corpus.
    scratch = tmp_path / "recipes"
    scratch.mkdir()
    for src in recipes_dir.glob("*.md"):
        (scratch / src.name).write_text(src.read_text())

    sync.sync_all(scratch, tmp_db)
    assert count_recipes(tmp_db) == 6

    (scratch / "overnight-oats.md").unlink()
    report = sync.sync_all(scratch, tmp_db)
    assert report.files_removed == 1
    assert count_recipes(tmp_db) == 5

    with connection(tmp_db) as conn:
        row = conn.execute(
            "SELECT count(*) AS n FROM recipes WHERE slug = ?", ("overnight-oats",)
        ).fetchone()
        assert row["n"] == 0
