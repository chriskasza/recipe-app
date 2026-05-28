# Project conventions

This file gives AI assistants the rules of the road for working in this repo.

## Source-of-truth model (non-negotiable)

- `recipes/*.md` is the **only** durable source of truth.
- Every other artifact (SQLite DB, FTS5 index, web UI state) is derived and rebuildable.
- All writes flow through ONE pipeline: `app.core.models.Recipe → app.core.serializer.serialize → write Markdown → app.db.sync.sync_one`. Never write to SQLite without first updating the Markdown file.
- Sync is idempotent. Two consecutive `recipes sync` runs must produce zero changes. The test `tests/test_sync_idempotent.py` enforces this.
- The parser/serializer roundtrip is byte-stable for every file in the seed corpus. The test `tests/test_parser_roundtrip.py` enforces this. Do not let the serializer reformat user-authored YAML or prose. If you need to change formatting, change the test first and justify it.
- Ingredients live in **block-style YAML** (one field per line) — ruamel collapses inner spaces from flow-style mappings on roundtrip, which breaks byte-stability. Flow style is fine for short primitive lists (`tags: [vegan, weeknight]`).

## Tooling

- Python 3.12. Strong typing throughout: `mypy --strict` must pass on `app/`.
- Pydantic v2 for all schemas; `StrEnum` over `(str, Enum)`.
- `ruff check` clean. The repo's ruff rules include `E F I B UP SIM RUF`.
- `pytest` for everything. Required suites: parser roundtrip, sync idempotency, FTS search, validator. Add a suite alongside each new layer.
- Dependencies declared in `pyproject.toml` (no `requirements.txt`). Dev deps in the `[dev]` optional group.

## Code style

- Prefer clear, boring, maintainable code. No clever abstractions without a concrete second use case.
- Keep functions small enough that types tell most of the story; comments only when the WHY is non-obvious.
- Errors should be surfaced, not swallowed. `ValidationIssue` distinguishes warnings (recoverable) from errors (block writes).
- No silent mutation of recipe files. If a write changes a recipe, it goes through the serializer.

## Layout (where things live)

- `app/core/` — canonical pipeline. `models.py` (Pydantic), `parser.py`, `serializer.py`, `validator.py`, `vocab.py`, `ids.py`.
- `app/db/` — `schema.sql` (single DDL file for now; migrations come if/when the schema needs to evolve in production), `connection.py`, `sync.py`, `queries.py`.
- `app/web/` — FastAPI routes and Jinja templates (Stage 3+; currently only `/healthz` in `app/main.py`).
- `app/importer/` — URL → canonical draft (Stage 5, not yet created).
- `app/ai/` — `LLMProvider` protocol + Ollama impl + retrieval/grounding (Stage 7, not yet created).
- `app/cli.py` — operator surface (Typer): `validate`, `sync`, `rebuild-index`, `search`, `show`, `doctor`, `run-dev`.
- `app/config.py` — env-driven paths (`RECIPES_DIR`, `DATA_DIR`).
- `recipes/` — canonical Markdown corpus. Hand-edited or written via the canonical pipeline.
- `data/` — SQLite DB. Gitignored. Wiped freely; `recipes rebuild-index` reproduces it.
- `tests/` — `test_parser_roundtrip.py`, `test_validator.py`, `test_sync_idempotent.py`, `test_fts_search.py`, `test_healthz.py`.

## Recipe format

See `docs/recipe-format.md`. Structured fields (ingredients, times, tags) live in YAML frontmatter; prose lives in the Markdown body under `## Description`, `## Instructions`, `## Notes`, `## Substitutions`, `## Make-ahead`. The parser preserves unknown sections under `body.extras`.

## Process

- Deliver in validated stages. Don't try to implement the whole roadmap in one pass.
- The roadmap lives in `TODO.md`. Update it when stages complete or scope shifts.
- For multi-step work, use a task list.
- Architectural tradeoffs go in `docs/architecture.md` so they survive future sessions.
