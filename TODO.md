# Roadmap

Work is delivered in validated stages. Each stage ends with a working commit and a verification checklist.

## Module architecture

The project is a **modular system layered on one durable core** — a repository of Markdown recipe
files (the only source of truth). Each capability is an optional module that reads/writes the
corpus through the canonical pipeline. See [`docs/architecture.md`](docs/architecture.md) for the
module map, statuses, and decision records, and [`GETTING-STARTED.md`](GETTING-STARTED.md) for how
modules are (eventually) toggled per deployment.

Architectural principles apply to every stage:
1. `$RECIPES_DIR/**/*.md` is the only source of truth.
2. All writes go through the canonical pipeline: `Recipe → serialize → Markdown → sync SQLite`.
3. Sync is idempotent and the DB is fully rebuildable from the corpus.
4. Serializer roundtrip is byte-stable.
5. Modules are optional and removable; `app/core/` stays a dependency-free library.

---

# Completed

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

## Stage 4 — CRUD ✅

- `GET /new`, `POST /new` create with inline validation.
- `GET /r/{slug}/edit`, `POST /r/{slug}/edit` edit — writes Markdown first, then `sync_one`. Slug immutable on edit.
- `POST /r/{slug}/archive` / `POST /r/{slug}/unarchive` toggle archived flag via ruamel in-place mutation + serialize.
- `app/web/forms.py` — `FormData`, `parse_form`, `build_markdown` (ruamel CommentedMap, flow-style primitive lists, block-style ingredients).
- `app/web/crud.py` — five routes + `_write_and_sync` (restores original on failure).
- `app/web/deps.py` — `get_recipes_dir` provider; tests override it alongside `get_db_path`.
- `app/templates/edit.html` + `_form.html` (shared form partial with inline error display).
- `python-multipart` added as runtime dep for form parsing.
- `tests/conftest.py` — `crud_recipes_dir`, `crud_db`, `crud_client` fixtures (copy seed corpus to tmp dir).
- `tests/test_web_crud.py` — 20 tests: create/edit/archive happy paths + collision/YAML/404 errors + roundtrip stability + sync idempotency.

## CI/CD — Docker publish to GHCR ✅ (2026-05-29)

`.github/workflows/docker-publish.yml` builds and pushes the image to
`ghcr.io/chriskasza/recipe-app` on every push to `main`. Tags: `latest` + `sha-<commit>`.
GHA layer cache (`type=gha`) warms subsequent builds. Image is private (inherited from repo).
`GETTING-STARTED.md` and `README.md` updated to use the published image as the primary Docker path.

## CI/CD — Quality gates workflow ✅ (2026-05-30)

`.github/workflows/ci.yml` runs on every push and pull request. Separate steps for:
`ruff check`, `ruff format --check`, `mypy --strict app/`, `recipes validate`
(against `tests/fixtures/recipes/`), and `pytest` with coverage (summary in log +
`coverage.xml` artifact). Concurrency control cancels superseded runs on the same ref.
Tools invoked via `.venv/bin/` per project conventions. `pytest-cov` added to the
`[dev]` group. Action pins bumped to latest (`checkout@v6`, `setup-python@v6`,
`build-push-action@v6`). `README.md` updated with a CI badge and aligned local-dev
gate commands.

## Docs & planning — Modular restructure ✅ (2026-05-29)

Re-framed the project as a modular system (no app-code changes). Module map + decision records in
`docs/architecture.md`; this roadmap recast around modules; base-corpus guide
`docs/managing-recipes.md` + copyable `docs/recipe-template.md`; `GETTING-STARTED.md` for
deployment/module toggling; `README.md` and `CLAUDE.md` updated. Decisions locked: keep both
frontends on a shared REST API, monorepo, folder = organization-only.

## UI restyle — "Skillet" wireframes (HTMX/Jinja) ✅ (2026-05-29)

Re-skinned the HTMX/Jinja UI to the `ui-prototype/` wireframes (Young Serif + Outfit, warm
stone/rose palette, light/dark/auto), and added the data the design needed:

- `favorite` boolean: optional Markdown frontmatter field synced to a `recipes.favorite` column
  (mirrors `archived`). Full pipeline — `models.py`, `schema.sql`, `sync.py`, `queries.py`
  (`RecipeRow`/`LibraryRow` + `favorites_only` filter), `forms.py`/`crud.py`
  (`POST /r/{slug}/favorite|unfavorite` via shared `_flip_bool_field`, `?next=` same-origin redirect),
  `library.py` (`?favorite=1`). "My recipes" nav links to the favorites view.
- Static hero/thumbnail images from frontmatter `images[0].path`, served by `GET /media/{path}`
  (traversal-guarded, under `RECIPES_DIR`); gradient/glyph fallback when absent or broken.
- Dual min–max total-time filter (`min_minutes` added to `_build_filters` + facets + `library.py`).
- Ratings/reviews dropped (no data; out of scope). Excluded the prototype's `image-slot.js` drag-drop
  and React tweaks panel (depend on the Claude artifact host bridge).
- Templates reworked: `base.html` (header, fonts, theme attrs, Pico dropped), `index.html`
  (`.page` grid + sort), `_facets.html` (collapsible sidebar, time range), `_results.html` (cards +
  favorite heart, no ratings), `recipe.html` (hero, stats, Save, prep callout). `app/static/style.css`
  rewritten from the prototype + form basics. OOB-facets contract preserved.
- Tests: favorite toggle + `?next=` safety (`test_web_crud.py`), `min_minutes`/`favorites_only`
  (`test_db_queries_library.py`). 78 tests pass; `mypy --strict` + `ruff` clean.

React SPA still deferred — needs Stage M3 (REST API) then M4 (SPA scaffold); the same wireframes
port directly once those exist.

## Stage M2 — Hierarchical corpus support ✅ (2026-05-29)

Subdirectories are now honored as organization-only; discovery recurses the tree.

- Discovery: `app/db/sync.py::_iter_recipe_files` uses `rglob("*.md")`, skipping the `_drafts/`
  and `images/` helper dirs via a shared `EXCLUDED_DIRS` frozenset. `app/cli.py doctor` reuses the
  same iterator for its count.
- Global slug-uniqueness: `sync_all` reports a duplicate-slug error and skips the second file so the
  DB keeps one slug→path mapping; `validate_all` emits a `slug.duplicate` ERROR. The per-file
  `slug == stem` invariant is unchanged.
- Write path: `app/web/forms.py::find_recipe_file` resolves a slug to its file anywhere in the tree
  (`slug_in_use` is now global). `crud.py` edit/edit_submit/archive/favorite resolve via the tree and
  rewrite in place, preserving the file's subdirectory.
- New recipes: optional `folder` field on the new-recipe form, validated by `resolve_new_recipe_path`
  (rejects absolute/`..`/reserved-dir paths, traversal-guarded), with `mkdir(parents=True)` on write.
- Docs: dropped the flat-only caveat in `docs/managing-recipes.md`; softened the path line in
  `docs/recipe-format.md`; updated `CLAUDE.md`.
- Tests: nested fixture `tests/fixtures/recipes/breakfast/seedy-overnight-oats.md`; roundtrip +
  idempotency helpers now recurse; new nested-discovery, duplicate-slug, and CRUD folder/subdir cases
  (`test_sync_idempotent.py`, `test_web_crud.py`); `crud_recipes_dir` fixture copies recursively.

---

# Modularization track

These enabling stages make the system genuinely modular. They unblock the frontend and renderer
modules below.

## Stage M1 — Modular foundations (enabling)

Make modules selectable without changing the default single-service behavior.

- Split `pyproject.toml` `[project.dependencies]` into `[project.optional-dependencies]` groups:
  `core` (pydantic, ruamel, python-ulid), `web` (fastapi, uvicorn, jinja2, python-multipart,
  markdown-it-py), `api` (fastapi, uvicorn), `cli` (typer, rich), `ai` (LLM client, later).
  A default extra (or `all`) reproduces today's full install.
- `docker-compose.yml` `profiles:` so services are opt-in (e.g. `--profile web --profile api`).
- Parameterize the Dockerfile entrypoint (env/arg) so one image can run as web / api / cli-worker /
  ssg-build. Default `docker compose up` stays equivalent to today.
- Update `GETTING-STARTED.md` to flip the toggling docs from "Planned" to "Available now".
- Verify: existing single-service run is unchanged; a lean `pip install -e ".[core]"` imports
  `app.core` without FastAPI present.

## Stage M3 — REST/JSON API module

A clean data contract both frontends consume.

- `app/api/` routers reusing `app/db/queries.py` for reads (library search, facets, recipe detail).
- Extract a shared write/service layer from `app/web/crud.py` + `app/web/forms.py` (form/markdown
  build, `_write_and_sync`) so web and API share one write path — no duplicated file I/O or sync.
- JSON schemas from the Pydantic models; OpenAPI served by FastAPI.
- Decide auth posture (likely none / single-user / token) and document it.
- Tests: read endpoints against `populated_db`; write endpoints against the `crud_client` pattern;
  roundtrip + sync idempotency preserved.

## Stage M4 — React SPA module

Optional richer frontend on the API. HTMX/Jinja stays the default.

- `web-spa/` Vite + React app in the monorepo; talks only to `app/api/`.
- Build artifacts served statically by the app or shipped as a separate compose service/profile.
- No data logic in the SPA — it consumes the API contract from Stage M3.

## Stage M5 — Static Site Generator module

The "simple renderer": corpus → static HTML, no DB, no running service.

- `recipes build-site` (or a small `ssg/` package) renders every recipe + an index to static HTML,
  reusing `app/core/` parsing and the `| md` filter. Reads files directly via `rglob`.
- Output is hostable on any static host or opened via `file://`.
- Tests: builds the fixture corpus; output contains every recipe; no DB touched.

---

# Feature modules

## URL importer

The **write half** has landed in-app: `recipes save-recipe` (`app/importer/save.py`) takes a JSON
payload and writes a validated, byte-stable recipe straight into the corpus at `recipes/<slug>.md`.
The `recipe-from-url` skill now feeds its extracted payload to that command instead of a bundled
script. Still planned is the **extraction half** — fetching and parsing the URL deterministically so
the command can take a `<url>`:

- `httpx` fetcher with timeout + UA.
- JSON-LD `Recipe` extractor (handles the majority of sites).
- HTML heuristic fallback.
- An extraction step that produces a `RecipePayload` (reuse `app/importer/save.py` to write); UI presents an editable form before saving.
- `recipes import-url <url>` CLI verb (save-recipe + extraction).
- Fixture-based tests covering at least 2 site formats.

## Meal planner

- `meal_plans` and `meal_plan_items` tables (SQLite only — meal plans are personal scheduling state, not corpus knowledge; documented in architecture.md).
- `GET /plan` weekly grid (Mon–Sun × breakfast/lunch/dinner/snack).
- Drag-drop assignment via Alpine.js (or the SPA, once available).
- Optional shopping-list view aggregating ingredients across the week.

## AI assistance

- `LLMProvider` protocol with implementations: `OllamaProvider` (default), `AnthropicProvider` (env-gated), `NullProvider` (tests).
- Add `ollama` service to `docker-compose.yml` (its own profile).
- `Retriever` protocol; first implementation is `FTSRetriever`. Leaves room for a future `EmbeddingRetriever`.
- `grounding.py` loads canonical Markdown for shortlist → compact context.
- Assistants: discovery ("what can I cook with..."), constrained meal planning, similar-recipes.
- Tests use `NullProvider` to lock the prompt-building behavior.

## Polish (nice-to-haves)

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
