"""File-backed API token store.

Tokens live in a JSON object ``{name: {"sha256": hex, "created_at": iso}}`` at
``settings.tokens_path`` (``DATA_DIR/api_tokens.json``). Like ``auth.json``,
this is kept out of the rebuildable SQLite mirror. Writes are atomic (temp
file + ``os.replace``).

Tokens are high-entropy random secrets (``recipes_`` + 32 bytes of
``token_urlsafe``), so a SHA-256 digest is sufficient for storage — there is
no brute-force surface to slow down with argon2, and verification stays O(1).
"""

from __future__ import annotations

import hashlib
import hmac
import json
import os
import secrets
from datetime import UTC, datetime
from pathlib import Path


def load_tokens(path: Path) -> dict[str, dict[str, str]]:
    """Return the ``{name: {"sha256": ..., "created_at": ...}}`` map; empty if absent."""
    if not path.is_file():
        return {}
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError(f"{path} must contain a JSON object of name -> token info")
    return {str(k): {str(ik): str(iv) for ik, iv in v.items()} for k, v in data.items()}


def _save_tokens(path: Path, tokens: dict[str, dict[str, str]]) -> None:
    """Atomically write the token map to ``path``."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(tokens, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    os.replace(tmp, path)


def create_token(path: Path, name: str) -> str:
    """Create a new token named ``name``. Returns the plaintext (shown once).

    Raises ``ValueError`` if ``name`` is already in use.
    """
    tokens = load_tokens(path)
    if name in tokens:
        raise ValueError(f"a token named {name!r} already exists")
    plaintext = "recipes_" + secrets.token_urlsafe(32)
    tokens[name] = {
        "sha256": hashlib.sha256(plaintext.encode("utf-8")).hexdigest(),
        "created_at": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
    }
    _save_tokens(path, tokens)
    return plaintext


def revoke_token(path: Path, name: str) -> bool:
    """Remove the token named ``name``. Returns False if it did not exist."""
    tokens = load_tokens(path)
    if name not in tokens:
        return False
    del tokens[name]
    _save_tokens(path, tokens)
    return True


def verify_token(path: Path, token: str) -> str | None:
    """Return the token's name if ``token`` matches a stored hash, else None."""
    digest = hashlib.sha256(token.encode("utf-8")).hexdigest()
    for name, info in load_tokens(path).items():
        if hmac.compare_digest(info.get("sha256", ""), digest):
            return name
    return None
