"""Build a recipe draft from an extracted payload, using the canonical pipeline.

Given a JSON-style payload describing one recipe, this module:

1. Generates a fresh ULID, normalizes the slug, and stamps created_at/updated_at (UTC).
2. Renders Markdown text in the canonical field order and block-style ingredients.
3. Parses + validates via ``app.core.parser.parse_text`` — schema errors abort the write.
4. Roundtrips through ``app.core.serializer.serialize`` to confirm byte-stability.
5. Writes the result to ``<drafts_dir>/<slug>.md``.

This is the canonical write path for the ``recipe-from-url`` skill (driven via the
``recipes build-draft`` CLI command). Everything flows through here so the
source-of-truth model in CLAUDE.md is preserved — no hand-rolled Markdown writes.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from app.core.ids import new_ulid, normalize_slug
from app.core.parser import ParseError, parse_text
from app.core.serializer import serialize
from app.core.validator import IssueLevel

_YAML_SPECIAL_PREFIXES = ("-", "?", ":", "[", "{", "!", "&", "*", "|", ">", "'", '"', "%", "@", "`", "#", " ")


def _quote(s: str) -> str:
    """Double-quote a YAML scalar if it might be misinterpreted, otherwise return as-is.

    Quoting rules are intentionally conservative — the parser will catch anything that
    slips through, and conservative quoting produces noisy diffs but never wrong files.
    """
    text = str(s)
    if not text:
        return '""'
    needs_quote = (
        text.startswith(_YAML_SPECIAL_PREFIXES)
        or text.endswith(" ")
        or ": " in text
        or text.endswith(":")
        or " #" in text
        or "\n" in text
    )
    if not needs_quote:
        return text
    escaped = text.replace("\\", "\\\\").replace('"', '\\"')
    return f'"{escaped}"'


def _flow_list(items: list[str]) -> str:
    """Render a short primitive list in flow style: ``[a, b, c]``."""
    return "[" + ", ".join(items) + "]"


def build_markdown(data: dict[str, Any]) -> tuple[str, str]:
    """Return ``(markdown_text, slug)`` for the given payload.

    Raises ``ValueError`` on missing required fields (title, ingredient name/original).
    """
    title = data.get("title")
    if not title or not str(title).strip():
        raise ValueError("payload missing required field 'title'")

    rid = new_ulid()
    slug = data.get("slug") or normalize_slug(str(title))
    if not slug:
        raise ValueError(f"could not derive a slug from title {title!r}")
    now = datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")

    out: list[str] = ["---"]
    out.append(f"id: {rid}")
    out.append(f"slug: {slug}")
    out.append(f"title: {_quote(title)}")

    if summary := data.get("summary"):
        out.append(f"summary: {_quote(summary)}")
    if cuisine := data.get("cuisine"):
        out.append(f"cuisine: {_quote(cuisine)}")
    if mt := data.get("meal_type"):
        out.append(f"meal_type: {_flow_list([str(x) for x in mt])}")
    if tags := data.get("tags"):
        out.append(f"tags: {_flow_list([str(x) for x in tags])}")
    if dietary := data.get("dietary"):
        out.append(f"dietary: {_flow_list([str(x) for x in dietary])}")

    for key in ("prep_minutes", "cook_minutes", "total_minutes", "servings"):
        if data.get(key) is not None:
            out.append(f"{key}: {int(data[key])}")

    if yn := data.get("yield_note"):
        out.append(f"yield_note: {_quote(yn)}")

    if (source := data.get("source")) and (source.get("url") or source.get("attribution")):
        out.append("source:")
        if source.get("url"):
            out.append(f"  url: {source['url']}")
        if source.get("attribution"):
            out.append(f"  attribution: {_quote(source['attribution'])}")

    if eq := data.get("equipment"):
        out.append(f"equipment: {_flow_list([str(x) for x in eq])}")

    if ings := data.get("ingredients"):
        out.append("ingredients:")
        for ing in ings:
            name = ing.get("name")
            original = ing.get("original")
            if not name or not original:
                raise ValueError(f"ingredient missing required name/original: {ing!r}")
            out.append(f"  - name: {_quote(name)}")
            if ing.get("qty") is not None:
                qty = ing["qty"]
                # Render integers without decimal point; floats as-is.
                qty_str = str(int(qty)) if isinstance(qty, (int, float)) and float(qty).is_integer() else str(qty)
                out.append(f"    qty: {qty_str}")
            if ing.get("unit"):
                out.append(f"    unit: {_quote(ing['unit'])}")
            if ing.get("prep"):
                out.append(f"    prep: {_quote(ing['prep'])}")
            if ing.get("optional"):
                out.append("    optional: true")
            out.append(f"    original: {_quote(original)}")

    if nut := data.get("nutrition"):
        out.append("nutrition:")
        for k, v in nut.items():
            if v is None:
                continue
            out.append(f"  {k}: {v}")

    if imgs := data.get("images"):
        out.append("images:")
        for img in imgs:
            if not img.get("path"):
                continue
            out.append(f"  - path: {img['path']}")
            if img.get("alt"):
                out.append(f"    alt: {_quote(img['alt'])}")

    out.append(f"created_at: {now}")
    out.append(f"updated_at: {now}")
    out.append("archived: false")
    out.append("---")
    out.append("")

    body = data.get("body") or {}
    body_sections = [
        ("Description", "description"),
        ("Instructions", "instructions"),
        ("Notes", "notes"),
        ("Substitutions", "substitutions"),
        ("Make-ahead", "make_ahead"),
    ]
    for heading, key in body_sections:
        content = body.get(key)
        if not content or not str(content).strip():
            continue
        out.append(f"## {heading}")
        out.append(str(content).rstrip())
        out.append("")

    text = "\n".join(out)
    if not text.endswith("\n"):
        text += "\n"
    return text, slug


@dataclass
class DraftReport:
    """Outcome of a draft build. ``status`` is ``"ok"`` or ``"error"``.

    On error, ``stage`` is one of ``json`` (caller's concern), ``build`` (missing
    required field), ``parse`` (malformed YAML/body), ``validate`` (schema error),
    or ``write`` (draft already exists). Mirrors the report shape the skill reads.
    """

    status: str
    stage: str | None = None
    path: str | None = None
    slug: str | None = None
    id: str | None = None
    message: str | None = None
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    roundtrip_byte_stable: bool | None = None
    draft: str | None = None

    def to_dict(self) -> dict[str, Any]:
        """JSON-ready dict, dropping unset (None) and empty-list fields."""
        result: dict[str, Any] = {"status": self.status}
        for key in ("stage", "path", "slug", "id", "message", "roundtrip_byte_stable"):
            value = getattr(self, key)
            if value is not None:
                result[key] = value
        for key in ("errors", "warnings"):
            value = getattr(self, key)
            if value:
                result[key] = value
        if self.draft is not None:
            result["draft"] = self.draft
        return result


def build_draft(data: dict[str, Any], drafts_dir: Path, *, rel_to: Path | None = None) -> DraftReport:
    """Build, validate, and write a draft to ``drafts_dir``; return a structured report.

    ``rel_to`` controls how the written path is reported: if the draft lives under it,
    the report carries the relative path (e.g. ``recipes/_drafts/foo.md``); otherwise
    the absolute path. The file is never written when ``status == "error"``.
    """

    def _rel(p: Path) -> str:
        if rel_to is not None:
            try:
                return str(p.relative_to(rel_to))
            except ValueError:
                pass
        return str(p)

    try:
        text, slug = build_markdown(data)
    except (ValueError, KeyError) as e:
        return DraftReport(status="error", stage="build", message=str(e))

    try:
        doc, issues = parse_text(text)
    except ParseError as e:
        return DraftReport(status="error", stage="parse", message=str(e), draft=text)

    errors = [str(i) for i in issues if i.level is IssueLevel.ERROR]
    warnings = [str(i) for i in issues if i.level is IssueLevel.WARNING]
    if errors:
        return DraftReport(status="error", stage="validate", errors=errors, warnings=warnings, draft=text)

    canonical = serialize(doc)
    roundtrip_clean = canonical == text

    out_path = drafts_dir / f"{slug}.md"
    if out_path.exists():
        return DraftReport(
            status="error",
            stage="write",
            message=f"draft already exists: {_rel(out_path)}",
            warnings=warnings,
        )

    drafts_dir.mkdir(parents=True, exist_ok=True)
    out_path.write_text(canonical, encoding="utf-8")

    return DraftReport(
        status="ok",
        path=_rel(out_path),
        slug=slug,
        id=doc.recipe.id,
        roundtrip_byte_stable=roundtrip_clean,
        warnings=warnings,
    )
