"""File-backed user credential store.

Users live in a JSON object ``{username: argon2_hash}`` at ``settings.auth_path``
(``DATA_DIR/auth.json``). This is deliberately separate from the SQLite mirror so
credentials survive ``recipes rebuild-index``. Writes are atomic (temp file +
``os.replace``) so a crash mid-write can't corrupt the store.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

from argon2 import PasswordHasher
from argon2.exceptions import VerifyMismatchError

_hasher = PasswordHasher()


def load_users(path: Path) -> dict[str, str]:
    """Return the ``{username: password_hash}`` map; empty if the file is absent."""
    if not path.is_file():
        return {}
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError(f"{path} must contain a JSON object of username -> hash")
    return {str(k): str(v) for k, v in data.items()}


def _save_users(path: Path, users: dict[str, str]) -> None:
    """Atomically write the user map to ``path``."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(users, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    os.replace(tmp, path)


def set_password(path: Path, username: str, password: str) -> None:
    """Create or update ``username`` with an argon2 hash of ``password``."""
    users = load_users(path)
    users[username] = _hasher.hash(password)
    _save_users(path, users)


def delete_user(path: Path, username: str) -> bool:
    """Remove ``username``. Returns False if the user did not exist."""
    users = load_users(path)
    if username not in users:
        return False
    del users[username]
    _save_users(path, users)
    return True


def verify(path: Path, username: str, password: str) -> bool:
    """Return True iff ``username`` exists and ``password`` matches its hash."""
    users = load_users(path)
    stored = users.get(username)
    if stored is None:
        return False
    try:
        return _hasher.verify(stored, password)
    except VerifyMismatchError:
        return False
