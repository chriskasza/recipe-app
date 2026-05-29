"""Test the `recipes build-draft` CLI honours RECIPES_DIR and emits a JSON report.

This covers the end-to-end path the recipe-from-url skill drives (stdin → CLI →
draft under $RECIPES_DIR/_drafts). The builder logic itself lives in
app/importer/draft.py and is exercised in test_importer_draft.py.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any

_MINIMAL_PAYLOAD = {
    "title": "Test Soup",
    "body": {"instructions": "1. Boil water.\n2. Add noodles."},
    "ingredients": [{"name": "water", "original": "1 cup water"}],
}


def _run(tmp_path: Path) -> dict[str, Any]:
    result = subprocess.run(
        [sys.executable, "-m", "app.cli", "build-draft"],
        input=json.dumps(_MINIMAL_PAYLOAD),
        capture_output=True,
        text=True,
        env={**os.environ, "RECIPES_DIR": str(tmp_path), "DATA_DIR": str(tmp_path / "data")},
    )
    return json.loads(result.stdout)  # type: ignore[no-any-return]


def test_build_draft_honours_recipes_dir(tmp_path: Path) -> None:
    report = _run(tmp_path)
    assert report["status"] == "ok", report
    assert "warnings" not in report  # clean payload → no warnings key

    draft = tmp_path / "_drafts" / f"{report['slug']}.md"
    assert draft.exists(), f"expected draft at {draft}"
    content = draft.read_text()
    assert "title: Test Soup" in content
    assert "## Instructions" in content


def test_build_draft_existing_slug_returns_error(tmp_path: Path) -> None:
    first = _run(tmp_path)
    assert first["status"] == "ok"

    second = _run(tmp_path)
    assert second["status"] == "error"
    assert second["stage"] == "write"
