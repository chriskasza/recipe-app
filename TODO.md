# Roadmap

Work is delivered in validated stages. Each stage ends with a working commit and a verification checklist.

Architectural principles apply to every stage:
1. `recipes/*.md` is the only source of truth.
2. All writes go through the canonical pipeline: `Recipe → serialize → Markdown → sync SQLite`.
3. Sync is idempotent and the DB is fully rebuildable from the corpus.
4. Serializer roundtrip is byte-stable.

## Stage 1 — Scaffold ✅

Project skeleton, tooling, Docker, healthz, CLI stub.

- `pyproject.toml` with `mypy --strict`, `ruff`, `pytest` configured.
- `Dockerfile` (multi-stage) + `docker-compose.yml` with host-mounted `recipes/` and `data/`.
- `app/main.py` FastAPI + `/healthz`.
- `app/cli.py` Typer stub (`doctor`, `run-dev`).
- `app/config.py` env-driven paths.
- `tests/test_healthz.py`.
- `README.md`, `CLAUDE.md`, `docs/architecture.md`.

## Stage 2 — Storage layer ✅

Canonical Markdown ↔ SQLite mirror with FTS5. Exercisable via CLI.

- `app/core/` — Pydantic `Recipe` schema, controlled vocab, ruamel-based parser, roundtrip-safe serializer, validator with WARNING/ERROR levels.
- `app/db/schema.sql` — `recipes`, `recipe_ingredients`, `ingredients`, `tags`, `meal_types`, `dietary_flags`, `equipment`, `sync_runs` + FTS5 external-content `recipes_fts` with AFTER INSERT/UPDATE/DELETE triggers.
- `app/db/sync.py` — `sync_all` (mtime-incremental), `sync_one`, `rebuild_index`, `validate_all`. Idempotent.
- `app/db/queries.py` — typed read helpers (`get_recipe_by_slug`, `get_ingredients`, `list_tags`, `search_recipes`, `count_recipes`, `count_fts_rows`, `last_sync_run`).
- `app/cli.py` — `validate`, `sync [--force]`, `rebuild-index`, `search`, `show`, `doctor`.
- `recipes/` — 6 hand-authored seed recipes spanning Japanese, Indian, French, American, and Italian cuisines, vegan/vegetarian/gluten-free/dairy-free flags, 5–90 min total times.
- `tests/` — parser roundtrip (byte-identical), validator, sync idempotency + orphan removal, FTS5 search. 24 tests total.
- `docs/recipe-format.md` — full schema, vocab, style conventions, roundtrip guarantee documented.

## Stage 3 — Simple visualization layer ✅

Read-only library + recipe detail pages, served from the existing SQLite/FTS5 mirror.

- `app/db/queries.py` — `search_library` (FTS + AND-across/OR-within facets + sort), `facet_counts_{tags,cuisines,meal_types,dietary}` (counts re-scope under other filters), `list_meal_types`/`list_dietary`/`list_equipment`, `get_recipe_detail` facade.
- `app/web/` — `library.py` (`GET /` full page, `GET /search` HTMX fragment with OOB facets), `recipe.py` (`GET /r/{slug}`), `deps.py` (cached `Settings` / `db_path` / `Jinja2Templates` providers; tests override `get_db_path`), `markdown.py` (singleton `MarkdownIt` + `md` Jinja filter).
- `app/templates/` — `base.html` (Pico.css + HTMX + Alpine via CDN), `index.html`, `_facets.html` (search + sort + max-time slider + facet checkboxes), `_results.html` (recipe-card grid), `_search_response.html` (fragment + OOB facets), `recipe.html` (header chips, ingredients, body via `| md | safe`, optional nutrition, print button).
- `app/static/style.css` — card grid, chips, `@media print`.
- `app/main.py` — mounts `/static`, includes web router; `/healthz` unchanged.
- `tests/` — `test_db_queries_library.py`, `test_web_library.py`, `test_web_recipe.py`; `conftest.py` gains `populated_db` + `client` fixtures. `test_sync_idempotent.py` derives recipe count from the corpus instead of hardcoding (corpus has grown to 7). 48 tests total.

## Stage 3.5 — Test fixture split ✅

Separated the frozen test corpus from the dev-runtime scratch directory.

- `tests/fixtures/recipes/` — 7 seed recipes committed to the repo; byte-stable; pinned by `test_parser_roundtrip.py` and `test_sync_idempotent.py`. Do not casually edit.
- `recipes/` — gitignored dev scratch. Populated via the `recipe-from-url` skill to validate app functionality. `RECIPES_DIR` defaults here so `recipes run-dev` picks it up.
- `conftest.py` `recipes_dir` fixture and `test_parser_roundtrip.py` parametrize lookup both updated to point at `tests/fixtures/recipes/`.

## Stage 4 — CRUD (next)

- `GET /new`, `POST /new` create with inline validation.
- `GET /r/{slug}/edit`, `POST /r/{slug}` edit — writes Markdown first, then `sync_one`.
- `POST /r/{slug}/archive` toggles `archived: true`.
- Tests through FastAPI TestClient covering happy paths and validation errors.

## Stage 5 — URL importer

- `httpx` fetcher with timeout + UA.
- JSON-LD `Recipe` extractor (handles the majority of sites).
- HTML heuristic fallback.
- `app/importer/pipeline.py` returns a draft `Recipe` model; UI presents an editable form before saving.
- Drafts written to `recipes/_drafts/`; only "Save" moves them into the canonical corpus.
- `recipes import-url <url>` CLI verb.
- Fixture-based tests covering at least 2 site formats.

## Stage 6 — Meal planner

- `meal_plans` and `meal_plan_items` tables (SQLite only — meal plans are personal scheduling state, not corpus knowledge; documented in architecture.md).
- `GET /plan` weekly grid (Mon–Sun × breakfast/lunch/dinner/snack).
- Drag-drop assignment via Alpine.js.
- Optional shopping-list view aggregating ingredients across the week.

## Stage 7 — AI assistance

- `LLMProvider` protocol with implementations: `OllamaProvider` (default), `AnthropicProvider` (env-gated), `NullProvider` (tests).
- Add `ollama` service to `docker-compose.yml`.
- `Retriever` protocol; first implementation is `FTSRetriever`. Leaves room for a future `EmbeddingRetriever`.
- `grounding.py` loads canonical Markdown for shortlist → compact context.
- Assistants: discovery ("what can I cook with..."), constrained meal planning, similar-recipes.
- Tests use `NullProvider` to lock the prompt-building behavior.

## Stage 8 — Polish (nice-to-haves)

- Image handling and thumbnails.
- Related-recipe recommendations from shared ingredients/tags.
- Duplicate detection for imports.
- Ingredient alias mapping (e.g. "scallion" ≡ "green onion").
- Recipe scaling (multiply quantities by a target servings number).
- Print-friendly view tweaks.
- Optional semantic search via `sqlite-vec` + a small sentence-transformer.

## Out of scope (for now)

- Multi-user accounts / sharing.
- Cloud hosting / sync beyond `git push`.
- Mobile-native clients.
