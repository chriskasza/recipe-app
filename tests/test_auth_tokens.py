"""API token store: create/verify/revoke roundtrip."""

from __future__ import annotations

from pathlib import Path

from app.auth import tokens


def test_create_verify_revoke_roundtrip(tmp_path: Path) -> None:
    path = tmp_path / "api_tokens.json"
    plaintext = tokens.create_token(path, "ci")

    assert plaintext.startswith("recipes_")
    assert tokens.verify_token(path, plaintext) == "ci"
    assert tokens.verify_token(path, "recipes_not-a-real-token") is None

    assert tokens.revoke_token(path, "ci") is True
    assert tokens.verify_token(path, plaintext) is None
    assert tokens.revoke_token(path, "ci") is False  # already gone


def test_create_duplicate_name_raises(tmp_path: Path) -> None:
    path = tmp_path / "api_tokens.json"
    tokens.create_token(path, "ci")
    try:
        tokens.create_token(path, "ci")
    except ValueError:
        pass
    else:
        raise AssertionError("expected ValueError for duplicate token name")


def test_plaintext_not_stored(tmp_path: Path) -> None:
    path = tmp_path / "api_tokens.json"
    plaintext = tokens.create_token(path, "ci")
    raw = path.read_text(encoding="utf-8")
    assert plaintext not in raw
    assert "sha256" in raw


def test_load_missing_file_is_empty(tmp_path: Path) -> None:
    assert tokens.load_tokens(tmp_path / "nope.json") == {}


def test_verify_missing_file_returns_none(tmp_path: Path) -> None:
    assert tokens.verify_token(tmp_path / "nope.json", "recipes_whatever") is None
