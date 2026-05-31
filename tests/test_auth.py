"""Auth: store roundtrip, login flow, and the CRUD gate."""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.auth import store
from tests.conftest import TEST_PASSWORD, TEST_USERNAME

# ---------------------------------------------------------------------------
# Store
# ---------------------------------------------------------------------------


def test_store_roundtrip(tmp_path: Path) -> None:
    path = tmp_path / "auth.json"
    store.set_password(path, "alice", "hunter2")
    assert store.verify(path, "alice", "hunter2") is True
    assert store.verify(path, "alice", "wrong") is False
    assert store.verify(path, "bob", "hunter2") is False  # unknown user


def test_store_update_and_delete(tmp_path: Path) -> None:
    path = tmp_path / "auth.json"
    store.set_password(path, "alice", "one")
    store.set_password(path, "alice", "two")  # update
    assert store.verify(path, "alice", "one") is False
    assert store.verify(path, "alice", "two") is True
    assert store.delete_user(path, "alice") is True
    assert store.verify(path, "alice", "two") is False
    assert store.delete_user(path, "alice") is False  # already gone


def test_store_missing_file_is_empty(tmp_path: Path) -> None:
    assert store.load_users(tmp_path / "nope.json") == {}


# ---------------------------------------------------------------------------
# Login flow
# ---------------------------------------------------------------------------


def test_login_page_renders(anon_client: TestClient) -> None:
    resp = anon_client.get("/login")
    assert resp.status_code == 200
    assert "Log in" in resp.text


def test_login_wrong_password_no_session(anon_client: TestClient) -> None:
    resp = anon_client.post(
        "/login",
        data={"username": TEST_USERNAME, "password": "nope"},
        follow_redirects=False,
    )
    assert resp.status_code == 401
    assert "Invalid username or password" in resp.text
    # still locked out
    assert anon_client.get("/new", follow_redirects=False).status_code == 303


def test_login_success_then_access(anon_client: TestClient) -> None:
    resp = anon_client.post(
        "/login",
        data={"username": TEST_USERNAME, "password": TEST_PASSWORD},
        follow_redirects=False,
    )
    assert resp.status_code == 303
    assert anon_client.get("/new").status_code == 200


def test_login_honors_safe_next(anon_client: TestClient) -> None:
    resp = anon_client.post(
        "/login",
        data={"username": TEST_USERNAME, "password": TEST_PASSWORD, "next": "/r/x/edit"},
        follow_redirects=False,
    )
    assert resp.headers["location"] == "/r/x/edit"


def test_login_rejects_offsite_next(anon_client: TestClient) -> None:
    resp = anon_client.post(
        "/login",
        data={"username": TEST_USERNAME, "password": TEST_PASSWORD, "next": "//evil.com"},
        follow_redirects=False,
    )
    assert resp.headers["location"] == "/"


def test_logout_clears_session(crud_client: TestClient) -> None:
    assert crud_client.get("/new").status_code == 200  # logged in via fixture
    assert crud_client.post("/logout", follow_redirects=False).status_code == 303
    assert crud_client.get("/new", follow_redirects=False).status_code == 303


# ---------------------------------------------------------------------------
# The gate
# ---------------------------------------------------------------------------

WRITE_GETS = ["/new", "/r/anything/edit"]
WRITE_POSTS = [
    "/new",
    "/r/anything/edit",
    "/r/anything/archive",
    "/r/anything/unarchive",
    "/r/anything/favorite",
    "/r/anything/unfavorite",
]


@pytest.mark.parametrize("path", WRITE_GETS)
def test_anon_get_redirects_to_login(anon_client: TestClient, path: str) -> None:
    resp = anon_client.get(path, follow_redirects=False)
    assert resp.status_code == 303
    assert resp.headers["location"].startswith("/login?next=")


@pytest.mark.parametrize("path", WRITE_POSTS)
def test_anon_post_redirects_to_login(anon_client: TestClient, path: str) -> None:
    resp = anon_client.post(path, follow_redirects=False)
    assert resp.status_code == 303
    assert resp.headers["location"].startswith("/login?next=")


def test_anon_post_new_writes_nothing(anon_client: TestClient, crud_recipes_dir: Path) -> None:
    before = {p.name for p in crud_recipes_dir.rglob("*.md")}
    anon_client.post(
        "/new",
        data={"title": "Should Not Exist", "ingredients_yaml": "", "body": ""},
        follow_redirects=False,
    )
    after = {p.name for p in crud_recipes_dir.rglob("*.md")}
    assert before == after


def test_public_reads_stay_open(anon_client: TestClient) -> None:
    assert anon_client.get("/").status_code == 200
    assert anon_client.get("/search?q=").status_code == 200
