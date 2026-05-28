"""Shared pytest fixtures."""

from __future__ import annotations

from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parent.parent


@pytest.fixture
def recipes_dir() -> Path:
    """The canonical seed recipes directory shipped with the project."""
    return PROJECT_ROOT / "recipes"


@pytest.fixture
def tmp_db(tmp_path: Path) -> Path:
    """A fresh SQLite DB path inside a temp dir."""
    return tmp_path / "recipes.db"
