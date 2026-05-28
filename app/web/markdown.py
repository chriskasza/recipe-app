"""Markdown renderer used by templates. Singleton MarkdownIt + Jinja filter."""

from __future__ import annotations

from markdown_it import MarkdownIt

_md = MarkdownIt(
    "commonmark", {"breaks": False, "linkify": False, "typographer": False}
).enable("table")


def render_markdown(text: str | None) -> str:
    if not text:
        return ""
    return str(_md.render(text))
