"""Serialize a RecipeDocument back to Markdown.

For unmodified documents this is byte-stable with the original on-disk content. When
the caller has mutated ``raw_yaml`` (via ruamel-aware edits in the web layer), only
the changed keys are reformatted; the rest of the file's formatting is preserved.
"""

from __future__ import annotations

import io

from ruamel.yaml import YAML

from app.core.models import RecipeDocument


def _yaml() -> YAML:
    y = YAML(typ="rt")
    y.preserve_quotes = True
    y.width = 4096
    y.indent(mapping=2, sequence=4, offset=2)
    y.explicit_end = False
    y.explicit_start = False
    return y


def serialize(doc: RecipeDocument) -> str:
    """Return the canonical Markdown rendering of ``doc``."""
    buf = io.StringIO()
    buf.write("---\n")
    _yaml().dump(doc.raw_yaml, buf)
    buf.write("---\n")
    if doc.raw_body:
        buf.write(doc.raw_body)
    return buf.getvalue()
