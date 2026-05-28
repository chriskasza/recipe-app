"""Shared pytest fixtures."""

from __future__ import annotations

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
