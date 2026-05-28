"""Shared pytest fixtures."""

from __future__ import annotations

import shutil
from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

PROJECT_ROOT = Path(__file__).resolve().parent.parent


@pytest.fixture
def recipes_dir() -> Path:
    """The canonical seed recipes directory shipped with the project."""
    return PROJECT_ROOT / "tests" / "fixtures" / "recipes"


@pytest.fixture
def tmp_db(tmp_path: Path) -> Path:
    """A fresh SQLite DB path inside a temp dir."""
    return tmp_path / "recipes.db"


@pytest.fixture
def populated_db(recipes_dir: Path, tmp_db: Path) -> Path:
    """A SQLite DB populated by syncing the seed corpus."""
    from app.db import sync

    report = sync.sync_all(recipes_dir, tmp_db)
    assert not report.errors, f"seed sync should be clean, got: {report.errors}"
    return tmp_db


@pytest.fixture
def client(populated_db: Path) -> Iterator[TestClient]:
    """TestClient with get_db_path overridden to a populated temp DB."""
    from app.main import app
    from app.web.deps import get_db_path

    app.dependency_overrides[get_db_path] = lambda: populated_db
    try:
        yield TestClient(app)
    finally:
        app.dependency_overrides.clear()


# ---------------------------------------------------------------------------
# CRUD fixtures — writable temp recipes dir + seeded DB
# ---------------------------------------------------------------------------


@pytest.fixture
def crud_recipes_dir(recipes_dir: Path, tmp_path: Path) -> Path:
    """A writable temp dir seeded with a copy of the fixture corpus."""
    dest = tmp_path / "recipes"
    dest.mkdir()
    for src in recipes_dir.glob("*.md"):
        shutil.copy2(src, dest / src.name)
    return dest


@pytest.fixture
def crud_db(crud_recipes_dir: Path, tmp_path: Path) -> Path:
    """A fresh SQLite DB synced from the writable corpus copy."""
    from app.db import sync

    db_path = tmp_path / "crud_recipes.db"
    report = sync.sync_all(crud_recipes_dir, db_path)
    assert not report.errors, f"crud seed sync failed: {report.errors}"
    return db_path


@pytest.fixture
def crud_client(crud_db: Path, crud_recipes_dir: Path) -> Iterator[TestClient]:
    """TestClient with both get_db_path and get_recipes_dir overridden to temp paths."""
    from app.main import app
    from app.web.deps import get_db_path, get_recipes_dir

    app.dependency_overrides[get_db_path] = lambda: crud_db
    app.dependency_overrides[get_recipes_dir] = lambda: crud_recipes_dir
    try:
        yield TestClient(app)
    finally:
        app.dependency_overrides.clear()
