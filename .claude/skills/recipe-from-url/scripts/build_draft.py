"""Build a recipe draft from a JSON payload, using the project's canonical pipeline.

Reads a JSON object describing one recipe (from a file path argument, or stdin if no
argument is given), then:

1. Generates a fresh ULID, normalizes the slug, and stamps created_at/updated_at (UTC).
2. Renders Markdown text in the canonical field order and block-style ingredients.
3. Parses + validates via ``app.core.parser.parse_text`` — schema errors abort the write.
4. Roundtrips through ``app.core.serializer.serialize`` to confirm byte-stability.
5. Writes the result to ``recipes/_drafts/<slug>.md`` under the project root.
6. Prints a JSON report on stdout: ``{"status": "ok" | "error", ...}``.

This script is the canonical write path for the recipe-from-url skill. Skill prose
should NOT use the Write tool to produce recipe files directly — everything must flow
through here so the source-of-truth model in CLAUDE.md is preserved.
"""

from __future__ import annotations

import json
import os
import sys
from datetime import UTC, datetime
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(PROJECT_ROOT))

from app.core.ids import new_ulid, normalize_slug  # noqa: E402
from app.core.parser import ParseError, parse_text  # noqa: E402
from app.core.serializer import serialize  # noqa: E402
from app.core.validator import IssueLevel  # noqa: E402

_recipes_base = (
    Path(os.environ["RECIPES_DIR"]) if "RECIPES_DIR" in os.environ else PROJECT_ROOT / "recipes"
)
DRAFTS_DIR = _recipes_base / "_drafts"

_YAML_SPECIAL_PREFIXES = (
    "-",
    "?",
    ":",
    "[",
    "{",
    "!",
    "&",
    "*",
    "|",
    ">",
    "'",
    '"',
    "%",
    "@",
    "`",
    "#",
    " ",
)


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


def build_markdown(data: dict) -> tuple[str, str]:
    """Return ``(markdown_text, slug)`` for the given payload."""
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
                qty_str = (
                    str(int(qty))
                    if isinstance(qty, (int, float)) and float(qty).is_integer()
                    else str(qty)
                )
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


def _report(payload: dict, *, exit_code: int = 0) -> None:
    print(json.dumps(payload, indent=2))
    sys.exit(exit_code)


def main() -> None:
    raw = Path(sys.argv[1]).read_text(encoding="utf-8") if len(sys.argv) > 1 else sys.stdin.read()
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as e:
        _report({"status": "error", "stage": "json", "message": str(e)}, exit_code=1)

    try:
        text, slug = build_markdown(data)
    except (ValueError, KeyError) as e:
        _report({"status": "error", "stage": "build", "message": str(e)}, exit_code=1)

    try:
        doc, issues = parse_text(text)
    except ParseError as e:
        _report(
            {"status": "error", "stage": "parse", "message": str(e), "draft": text},
            exit_code=1,
        )

    errors = [str(i) for i in issues if i.level is IssueLevel.ERROR]
    warnings = [str(i) for i in issues if i.level is IssueLevel.WARNING]
    if errors:
        _report(
            {
                "status": "error",
                "stage": "validate",
                "errors": errors,
                "warnings": warnings,
                "draft": text,
            },
            exit_code=1,
        )

    canonical = serialize(doc)
    roundtrip_clean = canonical == text

    out_path = DRAFTS_DIR / f"{slug}.md"

    def _rel(p: Path) -> str:
        try:
            return str(p.relative_to(PROJECT_ROOT))
        except ValueError:
            return str(p)

    if out_path.exists():
        _report(
            {
                "status": "error",
                "stage": "write",
                "message": f"draft already exists: {_rel(out_path)}",
                "warnings": warnings,
            },
            exit_code=1,
        )

    DRAFTS_DIR.mkdir(parents=True, exist_ok=True)
    out_path.write_text(canonical, encoding="utf-8")

    _report(
        {
            "status": "ok",
            "path": _rel(out_path),
            "slug": slug,
            "id": doc.recipe.id,
            "roundtrip_byte_stable": roundtrip_clean,
            "warnings": warnings,
        }
    )


if __name__ == "__main__":
    main()
