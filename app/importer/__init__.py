"""URL → canonical draft.

Today this package hosts the draft builder that turns an extracted recipe payload
(a JSON object) into a validated Markdown draft under ``recipes/_drafts/`` via the
project's canonical pipeline. The ``recipe-from-url`` skill drives it through the
``recipes build-draft`` CLI command. A fetch/extract front end (Stage 5) is planned.
"""

from __future__ import annotations

from app.importer.draft import DraftReport, build_draft, build_markdown

__all__ = ["DraftReport", "build_draft", "build_markdown"]
