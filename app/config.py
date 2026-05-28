"""Runtime configuration. Reads paths from env vars with sensible local defaults."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class Settings:
    """Process-wide settings derived from env vars."""

    recipes_dir: Path
    data_dir: Path

    @property
    def db_path(self) -> Path:
        return self.data_dir / "recipes.db"


def load_settings() -> Settings:
    """Resolve settings from env vars with project-root defaults."""
    project_root = Path(__file__).resolve().parent.parent
    recipes_dir = Path(os.environ.get("RECIPES_DIR", project_root / "recipes"))
    data_dir = Path(os.environ.get("DATA_DIR", project_root / "data"))
    return Settings(recipes_dir=recipes_dir.resolve(), data_dir=data_dir.resolve())
