"""Shared pytest fixtures."""

from __future__ import annotations

import os
import shutil
from collections.abc import Iterator
from pathlib import Path

# Set before any `from app.main import app` so SessionMiddleware is built with a
# stable secret and allows cookies over the test client's plain-http transport.
os.environ.setdefault("SESSION_SECRET", "test-secret")
os.environ.setdefault("COOKIE_SECURE", "false")

import pytest
from fastapi.testclient import TestClient

PROJECT_ROOT = Path(__file__).resolve().parent.parent

TEST_USERNAME = "tester"
TEST_PASSWORD = "s3cret-pw"


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
    for src in recipes_dir.rglob("*.md"):
        rel = src.relative_to(recipes_dir)
        dest_path = dest / rel
        dest_path.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dest_path)
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
def auth_users_path(tmp_path: Path) -> Path:
    """A temp auth.json seeded with one known test user."""
    from app.auth import store

    path = tmp_path / "auth.json"
    store.set_password(path, TEST_USERNAME, TEST_PASSWORD)
    return path


def _crud_overrides(crud_db: Path, crud_recipes_dir: Path, auth_users_path: Path) -> None:
    from app.main import app
    from app.web.deps import get_db_path, get_recipes_dir, get_users_path

    app.dependency_overrides[get_db_path] = lambda: crud_db
    app.dependency_overrides[get_recipes_dir] = lambda: crud_recipes_dir
    app.dependency_overrides[get_users_path] = lambda: auth_users_path


@pytest.fixture
def anon_client(
    crud_db: Path, crud_recipes_dir: Path, auth_users_path: Path
) -> Iterator[TestClient]:
    """CRUD overrides applied but no login — for testing the auth gate."""
    from app.main import app

    _crud_overrides(crud_db, crud_recipes_dir, auth_users_path)
    try:
        yield TestClient(app)
    finally:
        app.dependency_overrides.clear()


@pytest.fixture
def crud_client(
    crud_db: Path, crud_recipes_dir: Path, auth_users_path: Path
) -> Iterator[TestClient]:
    """Authenticated TestClient: db + recipes dir + users path overridden, logged in."""
    from app.main import app

    _crud_overrides(crud_db, crud_recipes_dir, auth_users_path)
    try:
        client = TestClient(app)
        resp = client.post(
            "/login",
            data={"username": TEST_USERNAME, "password": TEST_PASSWORD},
            follow_redirects=False,
        )
        assert resp.status_code == 303, "test login should succeed"
        yield client
    finally:
        app.dependency_overrides.clear()


# ---------------------------------------------------------------------------
# API fixtures — Bearer token auth, no session cookie
# ---------------------------------------------------------------------------


@pytest.fixture
def api_tokens_path(tmp_path: Path) -> tuple[Path, str]:
    """A temp api_tokens.json seeded with one token. Returns (path, plaintext)."""
    from app.auth import tokens

    path = tmp_path / "api_tokens.json"
    plaintext = tokens.create_token(path, "test")
    return path, plaintext


@pytest.fixture
def api_client(
    crud_db: Path,
    crud_recipes_dir: Path,
    auth_users_path: Path,
    api_tokens_path: tuple[Path, str],
) -> Iterator[tuple[TestClient, str]]:
    """TestClient with API overrides applied, no session login. Yields (client, token)."""
    from app.main import app
    from app.web.deps import get_tokens_path

    _crud_overrides(crud_db, crud_recipes_dir, auth_users_path)
    tokens_path, plaintext = api_tokens_path
    app.dependency_overrides[get_tokens_path] = lambda: tokens_path
    try:
        yield TestClient(app), plaintext
    finally:
        app.dependency_overrides.clear()
