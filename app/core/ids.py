"""ULID and slug helpers."""

from __future__ import annotations

import re
import unicodedata

from ulid import ULID

ULID_RE = re.compile(r"^[0-9A-HJKMNP-TV-Z]{26}$")
SLUG_RE = re.compile(r"^[a-z0-9](?:[a-z0-9-]{0,79})$")


def new_ulid() -> str:
    """Return a fresh ULID string (26-char Crockford base32, uppercase)."""
    return str(ULID())


def is_ulid(value: str) -> bool:
    return bool(ULID_RE.match(value))


def normalize_slug(text: str) -> str:
    """Lowercase, ASCII-fold, replace non-alphanumeric runs with single hyphens, trim hyphens."""
    nfkd = unicodedata.normalize("NFKD", text)
    ascii_only = nfkd.encode("ascii", "ignore").decode("ascii")
    lower = ascii_only.lower()
    hyphenated = re.sub(r"[^a-z0-9]+", "-", lower).strip("-")
    return hyphenated[:80]


def is_valid_slug(value: str) -> bool:
    return bool(SLUG_RE.match(value))
