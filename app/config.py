"""Runtime configuration. Reads paths from env vars with sensible local defaults."""

from __future__ import annotations

import os
import secrets
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class Settings:
    """Process-wide settings derived from env vars."""

    recipes_dir: Path
    data_dir: Path
    session_secret: str
    cookie_secure: bool

    @property
    def db_path(self) -> Path:
        return self.data_dir / "recipes.db"

    @property
    def auth_path(self) -> Path:
        """Credential store — kept out of the rebuildable SQLite mirror."""
        return self.data_dir / "auth.json"


def _resolve_session_secret(data_dir: Path) -> str:
    """Use SESSION_SECRET if set, else read-or-create a persisted random secret.

    Persisting it to ``data_dir/.session_secret`` keeps sessions valid across
    restarts without manual configuration. Production deployments should set
    SESSION_SECRET explicitly (e.g. via the compose env) instead.
    """
    env_secret = os.environ.get("SESSION_SECRET")
    if env_secret:
        return env_secret
    secret_file = data_dir / ".session_secret"
    if secret_file.is_file():
        return secret_file.read_text(encoding="utf-8").strip()
    secret = secrets.token_urlsafe(32)
    data_dir.mkdir(parents=True, exist_ok=True)
    secret_file.write_text(secret, encoding="utf-8")
    return secret


def _env_bool(name: str, default: bool) -> bool:
    raw = os.environ.get(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def load_settings() -> Settings:
    """Resolve settings from env vars with project-root defaults."""
    project_root = Path(__file__).resolve().parent.parent
    recipes_dir = Path(os.environ.get("RECIPES_DIR", project_root / "recipes")).resolve()
    data_dir = Path(os.environ.get("DATA_DIR", project_root / "data")).resolve()
    return Settings(
        recipes_dir=recipes_dir,
        data_dir=data_dir,
        session_secret=_resolve_session_secret(data_dir),
        cookie_secure=_env_bool("COOKIE_SECURE", default=True),
    )
