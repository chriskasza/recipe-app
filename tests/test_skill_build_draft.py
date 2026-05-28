"""Test build_draft.py honours RECIPES_DIR and produces a valid canonical draft."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

_SCRIPT = Path(__file__).parents[1] / ".claude/skills/recipe-from-url/scripts/build_draft.py"
_MINIMAL_PAYLOAD = {
    "title": "Test Soup",
    "body": {"instructions": "1. Boil water.\n2. Add noodles."},
    "ingredients": [{"name": "water", "original": "1 cup water"}],
}


def test_build_draft_honours_recipes_dir(tmp_path: Path) -> None:
    result = subprocess.run(
        [sys.executable, str(_SCRIPT)],
        input=json.dumps(_MINIMAL_PAYLOAD),
        capture_output=True,
        text=True,
        env={"RECIPES_DIR": str(tmp_path), "PATH": "/usr/bin:/bin"},
    )
    report = json.loads(result.stdout)
    assert report["status"] == "ok", report
    assert report["warnings"] == []

    draft = tmp_path / "_drafts" / f"{report['slug']}.md"
    assert draft.exists(), f"expected draft at {draft}"
    content = draft.read_text()
    assert "title: Test Soup" in content
    assert "## Instructions" in content


def test_build_draft_existing_slug_returns_error(tmp_path: Path) -> None:
    def _run() -> dict:
        result = subprocess.run(
            [sys.executable, str(_SCRIPT)],
            input=json.dumps(_MINIMAL_PAYLOAD),
            capture_output=True,
            text=True,
            env={"RECIPES_DIR": str(tmp_path), "PATH": "/usr/bin:/bin"},
        )
        return json.loads(result.stdout)

    first = _run()
    assert first["status"] == "ok"

    second = _run()
    assert second["status"] == "error"
    assert second["stage"] == "write"
