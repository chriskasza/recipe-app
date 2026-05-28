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
- `app/db/` — `schema.sql` (single DDL file for now; migrations come if/when the schema needs to evolve in production), `connection.py`, `sync.py`, `queries.py` (typed read helpers including `search_library`, `facet_counts_*`, `get_recipe_detail`).
- `app/web/` — FastAPI router + Jinja templates + Markdown filter.
  - `library.py` (`GET /` full page, `GET /search` HTMX fragment with OOB facets), `recipe.py` (`GET /r/{slug}`), `deps.py` (cached `Settings` / `db_path` / `Jinja2Templates` providers — tests override `get_db_path`), `markdown.py` (singleton `MarkdownIt` + `md` Jinja filter), `__init__.py` (combined router).
- `app/templates/` — `base.html` (Pico.css + HTMX + Alpine via pinned CDN versions), `index.html`, `_facets.html`, `_results.html`, `_search_response.html` (OOB wrapper for `/search`), `recipe.html`.
- `app/static/style.css` — card grid, chips, `@media print` rules. Pico.css covers the rest of the chrome.
- `app/importer/` — URL → canonical draft (Stage 5, not yet created).
- `app/ai/` — `LLMProvider` protocol + Ollama impl + retrieval/grounding (Stage 7, not yet created).
- `app/cli.py` — operator surface (Typer): `validate`, `sync`, `rebuild-index`, `search`, `show`, `doctor`, `run-dev`.
- `app/config.py` — env-driven paths (`RECIPES_DIR`, `DATA_DIR`).
- `recipes/` — canonical Markdown corpus. Hand-edited or written via the canonical pipeline.
- `data/` — SQLite DB. Gitignored. Wiped freely; `recipes rebuild-index` reproduces it.
- `tmp/` — local scratch for log captures and transient outputs. Gitignored.
- `tests/` — `test_parser_roundtrip.py`, `test_validator.py`, `test_sync_idempotent.py`, `test_fts_search.py`, `test_healthz.py`, `test_db_queries_library.py`, `test_web_library.py`, `test_web_recipe.py`. `conftest.py` provides `recipes_dir`, `tmp_db`, `populated_db` (runs `sync_all` against the seed corpus), and `client` (TestClient with `get_db_path` overridden).

## Recipe format

See `docs/recipe-format.md`. Structured fields (ingredients, times, tags) live in YAML frontmatter; prose lives in the Markdown body under `## Description`, `## Instructions`, `## Notes`, `## Substitutions`, `## Make-ahead`. The parser preserves unknown sections under `body.extras`.

## Web layer conventions (Stage 3)

- `GET /` always returns the full HTML shell. `GET /search` always returns just a fragment (`_results.html` + an OOB `<aside id="facets" hx-swap-oob="true">…</aside>`). Keep the split — no `HX-Request` sniffing.
- Facet semantics: AND across groups, OR within a group, AND with the FTS query. `archived = 0` is always applied in the library; `/r/{slug}` still serves archived recipes so existing links keep working. `_build_filters` in `app/db/queries.py` is the single chokepoint — extend it there, don't open-code WHERE clauses in new endpoints.
- The detail page renders entirely from DB columns (`body_markdown`, `frontmatter_json`). Do not re-parse the source Markdown file on the request path.
- Markdown → HTML goes through the `| md` Jinja filter (singleton `MarkdownIt` in `app/web/markdown.py`). Templates use `{{ ... | md | safe }}` because the corpus is trusted; if untrusted Markdown is ever ingested, add sanitization in that one file.
- Tests use `client` fixture (TestClient + `get_db_path` override → `populated_db`). Don't monkey-patch `load_settings`.
- Test counts that depend on the seed corpus should derive from `recipes_dir.glob("*.md")`, not hardcode a number — the corpus grows.

## Process

- Deliver in validated stages. Don't try to implement the whole roadmap in one pass.
- The roadmap lives in `TODO.md`. Update it when stages complete or scope shifts.
- For multi-step work, use a task list.
- Architectural tradeoffs go in `docs/architecture.md` so they survive future sessions.
