"""Shared constants for the canonical pipeline.

Kept in ``app.core`` so both the DB and web layers can depend on them without
the web layer reaching into ``app.db`` (a layering inversion).
"""

from __future__ import annotations

# Helper directories that live inside the corpus tree but never hold recipe
# files: drafts staged by the importer, and image sidecars. Discovery and the
# slug→path resolver skip any path that descends through one of these.
EXCLUDED_DIRS = frozenset({"_drafts", "images"})
