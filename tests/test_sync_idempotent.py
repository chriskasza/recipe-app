"""Sync must be idempotent: a second consecutive run reports zero changes."""

from __future__ import annotations

from pathlib import Path

from app.db import sync
from app.db.connection import connection
from app.db.queries import count_fts_rows, count_recipes


def _corpus_size(recipes_dir: Path) -> int:
    return sum(1 for _ in sync._iter_recipe_files(recipes_dir))


def test_sync_then_sync_is_noop(recipes_dir: Path, tmp_db: Path) -> None:
    n = _corpus_size(recipes_dir)
    first = sync.sync_all(recipes_dir, tmp_db)
    assert first.ok, first.errors
    assert first.files_changed == n
    assert count_recipes(tmp_db) == n

    second = sync.sync_all(recipes_dir, tmp_db)
    assert second.ok, second.errors
    assert second.files_changed == 0
    assert second.files_removed == 0


def test_force_resyncs_all(recipes_dir: Path, tmp_db: Path) -> None:
    n = _corpus_size(recipes_dir)
    sync.sync_all(recipes_dir, tmp_db)
    forced = sync.sync_all(recipes_dir, tmp_db, force=True)
    assert forced.files_changed == n


def test_rebuild_recreates_everything(recipes_dir: Path, tmp_db: Path) -> None:
    n = _corpus_size(recipes_dir)
    sync.sync_all(recipes_dir, tmp_db)
    pre = count_recipes(tmp_db)
    pre_fts = count_fts_rows(tmp_db)
    report = sync.rebuild_index(recipes_dir, tmp_db)
    assert report.ok
    assert count_recipes(tmp_db) == pre == n
    assert count_fts_rows(tmp_db) == pre_fts == n


def test_orphan_is_removed(recipes_dir: Path, tmp_db: Path, tmp_path: Path) -> None:
    # Copy seeds into a scratch dir so we can delete one without touching the real corpus.
    scratch = tmp_path / "recipes"
    scratch.mkdir()
    for src in recipes_dir.rglob("*.md"):
        dest = scratch / src.relative_to(recipes_dir)
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_text(src.read_text())

    n = _corpus_size(scratch)
    sync.sync_all(scratch, tmp_db)
    assert count_recipes(tmp_db) == n

    (scratch / "overnight-oats.md").unlink()
    report = sync.sync_all(scratch, tmp_db)
    assert report.files_removed == 1
    assert count_recipes(tmp_db) == n - 1

    with connection(tmp_db) as conn:
        row = conn.execute(
            "SELECT count(*) AS n FROM recipes WHERE slug = ?", ("overnight-oats",)
        ).fetchone()
        assert row["n"] == 0


def test_nested_recipe_is_discovered_and_idempotent(recipes_dir: Path, tmp_db: Path) -> None:
    """Recipes in subdirectories are synced, and a re-sync is still a no-op."""
    sync.sync_all(recipes_dir, tmp_db)
    with connection(tmp_db) as conn:
        row = conn.execute(
            "SELECT count(*) AS n FROM recipes WHERE slug = ?", ("morning-seed-jar",)
        ).fetchone()
        assert row["n"] == 1, "nested recipe should be discovered via rglob"

    second = sync.sync_all(recipes_dir, tmp_db)
    assert second.files_changed == 0
    assert second.files_removed == 0


def test_duplicate_slug_across_dirs_errors(tmp_path: Path, tmp_db: Path) -> None:
    """Two files sharing a stem in different folders is a hard error; the
    second file is skipped so the DB keeps a single slug→path mapping."""
    corpus = tmp_path / "recipes"
    (corpus / "a").mkdir(parents=True)
    (corpus / "b").mkdir(parents=True)
    body = (
        "---\n"
        "id: {id}\n"
        "slug: dup-recipe\n"
        "title: Dup Recipe\n"
        "created_at: 2026-05-28T10:00:00Z\n"
        "updated_at: 2026-05-28T10:00:00Z\n"
        "archived: false\n"
        "---\n\n## Instructions\n1. Stir.\n"
    )
    (corpus / "a" / "dup-recipe.md").write_text(body.format(id="01KSQ4XNTY2CEAHB1P63YJYN6T"))
    (corpus / "b" / "dup-recipe.md").write_text(body.format(id="01KSQ4XNTY2CEAHB1P63YJYN7V"))

    report = sync.sync_all(corpus, tmp_db)
    assert not report.ok
    assert any("duplicate slug" in e for e in report.errors)
    # First file by sorted path wins: a/dup-recipe.md sorts before b/.
    assert count_recipes(tmp_db) == 1
    with connection(tmp_db) as conn:
        kept = conn.execute("SELECT file_path FROM recipes").fetchone()["file_path"]
    assert kept.endswith(str(Path("a") / "dup-recipe.md"))

    results = sync.validate_all(corpus)
    flagged = {
        path for path, issues in results for issue in issues if issue.code == "slug.duplicate"
    }
    # Both participants are flagged, not just the second.
    assert flagged == {
        corpus / "a" / "dup-recipe.md",
        corpus / "b" / "dup-recipe.md",
    }
