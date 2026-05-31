# Project conventions

This file gives AI assistants the rules of the road for working in this repo.

## Module architecture

This project is a modular system on one core (a Markdown recipe corpus). See [`docs/architecture.md`](docs/architecture.md) for the module map, per-module status, and decision records, and [`TODO.md`](TODO.md) for the staged roadmap. Locked decisions: keep **both** the HTMX/Jinja UI and a (planned) React SPA on a single shared REST API; **monorepo** with module boundaries; recipe subdirectories are **organization-only**.

## Source-of-truth model (non-negotiable)

- Markdown recipe files at `$RECIPES_DIR` are the **only** durable source of truth. In this repo `recipes/` is a gitignored dev scratch dir; the frozen test corpus lives in `tests/fixtures/recipes/`.
- **Recipe directories are organization-only.** Subdirectories may group recipes, but the folder is never identity: the `slug` is the filename stem and must be globally unique across the tree, and `/r/{slug}` URLs stay stable across moves. Never introduce path-based slugs. Discovery is **recursive** (`rglob("*.md")` in `app.db.sync._iter_recipe_files`, skipping the `_drafts/` and `images/` helper dirs via `EXCLUDED_DIRS`). Global slug-uniqueness is enforced in `sync_all`/`validate_all` (duplicate stems are reported and skipped). The write path resolves a slug to its file with `app.web.forms.find_recipe_file` (tree-wide `rglob`) — never assume `recipes_dir/{slug}.md`.
- Every other artifact (SQLite DB, FTS5 index, web UI state) is derived and rebuildable.
- All writes flow through ONE pipeline: `app.core.models.Recipe → app.core.serializer.serialize → write Markdown → app.db.sync.sync_one`. Never write to SQLite without first updating the Markdown file.
- Sync is idempotent. Two consecutive `recipes sync` runs must produce zero changes. The test `tests/test_sync_idempotent.py` enforces this.
- The parser/serializer roundtrip is byte-stable for every file in the seed corpus. The test `tests/test_parser_roundtrip.py` enforces this. Do not let the serializer reformat user-authored YAML or prose. If you need to change formatting, change the test first and justify it.
- Ingredients live in **block-style YAML** (one field per line) — ruamel collapses inner spaces from flow-style mappings on roundtrip, which breaks byte-stability. Flow style is fine for short primitive lists (`tags: [vegan, weeknight]`).

## Tooling

- Python 3.11. Strong typing throughout: `mypy --strict` must pass on `app/`.
- Pydantic v2 for all schemas; `StrEnum` over `(str, Enum)`.
- `ruff check` clean. The repo's ruff rules include `E F I B UP SIM RUF`.
- `pytest` for everything. Required suites: parser roundtrip, sync idempotency, FTS search, validator. Add a suite alongside each new layer.
- Dependencies declared in `pyproject.toml` (no `requirements.txt`). Dev deps in the `[dev]` optional group.
- Run tools via `.venv/bin/` directly (e.g. `.venv/bin/pytest`, `.venv/bin/mypy`, `.venv/bin/ruff`). Never call them as `python -m <tool>` or `python pytest ...`.
- `curl_cffi` is a **runtime dependency of the default Docker image**, not of `app/`. Nothing under `app/` imports it, but the bundled `recipe-from-url` skill (`.claude/skills/recipe-from-url/SKILL.md`) does `from curl_cffi import requests` and runs it **inside the running `app` container** via `docker compose exec app ... python tmp/fetch.py`. When splitting dependencies into optional extras, keep `curl_cffi` installed in the default/web image — don't demote it to an opt-in extra the web image skips. Likewise keep the compose service named `app`: the skill and docs call `docker compose exec app`.

## Code style

- Prefer clear, boring, maintainable code. No clever abstractions without a concrete second use case.
- Keep functions small enough that types tell most of the story; comments only when the WHY is non-obvious.
- Errors should be surfaced, not swallowed. `ValidationIssue` distinguishes warnings (recoverable) from errors (block writes).
- No silent mutation of recipe files. If a write changes a recipe, it goes through the serializer.

## Layout (where things live)

- `app/core/` — canonical pipeline. `models.py` (Pydantic), `parser.py`, `serializer.py`, `validator.py`, `vocab.py`, `ids.py`, `constants.py` (`EXCLUDED_DIRS`).
- `app/main.py` — FastAPI entrypoint: builds the app, mounts `/static`, includes the web router, serves `/healthz`.
- `app/db/` — `schema.sql` (single DDL file for now; migrations come if/when the schema needs to evolve in production), `connection.py`, `sync.py`, `queries.py` (typed read helpers including `search_library`, `facet_counts_*`, `get_recipe_detail`).
- `app/web/` — FastAPI router + Jinja templates + Markdown filter.
  - `library.py` (`GET /` full page, `GET /search` HTMX fragment with OOB facets), `recipe.py` (`GET /r/{slug}`), `deps.py` (cached `Settings` / `db_path` / `Jinja2Templates` providers — tests override `get_db_path` **and** `get_recipes_dir`), `markdown.py` (singleton `MarkdownIt` + `md` Jinja filter), `__init__.py` (combined router).
  - `forms.py` — `FormData` dataclass, `parse_form` (decodes `request.form()`), `build_markdown` (assembles canonical file text via ruamel `CommentedMap`), `find_recipe_file` (tree-wide slug→path resolver), `slug_in_use` (now global), `resolve_new_recipe_path` (validates the optional new-recipe folder). Used by the CRUD layer.
  - `crud.py` — `GET/POST /new`, `GET/POST /r/{slug}/edit`, `POST /r/{slug}/archive|unarchive`. All writes call `_write_and_sync` which restores the original file on `sync_one` failure. Every write route depends on `require_user` (see auth conventions below).
  - `auth.py` — `GET/POST /login`, `POST /logout`. Verifies against `app.auth.store`, sets `request.session["user"]`.
- `app/templates/` — `base.html` (Pico.css + HTMX + Alpine via pinned CDN versions), `index.html`, `_facets.html`, `_results.html`, `_pagination.html` (library pagination controls), `_search_response.html` (OOB wrapper for `/search`), `recipe.html`, `edit.html` + `_form.html` (shared form partial for new/edit).
- `app/static/style.css` — card grid, chips, `@media print` rules. Pico.css covers the rest of the chrome.
- `app/importer/` — payload → canonical recipe file. `save.py` (`RecipePayload` Pydantic models + `save_recipe`/`render_markdown`/`to_report`) backs the `recipes save-recipe` CLI command: it renders a JSON payload through the canonical pipeline (ULID, slug, timestamps, parse + validate, serializer roundtrip check) and writes `RECIPES_DIR/<slug>.md` straight into the corpus (tree-wide slug-collision check; no draft staging — mistakes are fixed from the web edit form). The `recipe-from-url` skill does the page fetch + field extraction and feeds the payload in. Deterministic in-app URL fetch/JSON-LD extraction (Stage 5 `import-url`) is still future work.
- `app/ai/` — `LLMProvider` protocol + Ollama impl + retrieval/grounding (Stage 7, not yet created).
- `app/auth/` — login auth. `store.py` (`load_users`/`set_password`/`delete_user`/`verify`; argon2 hashes in `DATA_DIR/auth.json`, atomic writes). Credentials live **outside** the rebuildable `recipes.db` so they survive `recipes rebuild-index`. Login/logout routes are in `app/web/auth.py`.
- `app/cli.py` — operator surface (Typer): `validate`, `sync`, `rebuild-index`, `search`, `show`, `doctor`, `save-recipe`, `set-password`, `list-users`, `delete-user`, `run-dev`.
- `app/config.py` — env-driven paths (`RECIPES_DIR`, `DATA_DIR`) + auth settings (`auth_path`, `session_secret` from `SESSION_SECRET` or a persisted `.session_secret`, `cookie_secure` from `COOKIE_SECURE`).
- `recipes/` — **gitignored** dev scratch workspace. Populated by the `recipe-from-url` skill so developers can validate app functionality with real recipes. Never committed. The app's `RECIPES_DIR` env var defaults here for `recipes run-dev`.
- `tests/fixtures/recipes/` — **frozen test corpus**. The 7 seed recipes committed to the repo. The parser roundtrip test and sync-idempotency test pin their behavior against this exact byte content — don't casually edit these files. Future test-only recipes go here too.
- `data/` — SQLite DB. Gitignored. Wiped freely; `recipes rebuild-index` reproduces it.
- `tmp/` — local scratch for log captures and transient outputs. Gitignored.
- `tests/` — `test_parser_roundtrip.py`, `test_validator.py`, `test_sync_idempotent.py`, `test_fts_search.py`, `test_healthz.py`, `test_importer_save.py`, `test_db_queries_library.py`, `test_web_library.py`, `test_web_recipe.py`, `test_web_crud.py`, `test_auth.py`. `conftest.py` provides `recipes_dir` (→ `tests/fixtures/recipes/`), `tmp_db`, `populated_db`, `client` (read-only; `get_db_path` overridden), `auth_users_path` (temp `auth.json` seeded with `TEST_USERNAME`/`TEST_PASSWORD`), `crud_client` (CRUD; `get_db_path`+`get_recipes_dir`+`get_users_path` overridden, **and logged in** so existing write tests pass), and `anon_client` (same overrides, not logged in — for the auth gate). conftest sets `COOKIE_SECURE=false`/`SESSION_SECRET` before importing the app so the test client's http cookie works.

## Recipe format

See `docs/recipe-format.md`. Structured fields (ingredients, times, tags) live in YAML frontmatter; prose lives in the Markdown body under `## Description`, `## Instructions`, `## Notes`, `## Substitutions`, `## Make-ahead`. The parser preserves unknown sections under `body.extras`.

## Web layer conventions (Stage 3)

- `GET /` always returns the full HTML shell. `GET /search` always returns just a fragment (`_results.html` + an OOB `<aside id="facets" hx-swap-oob="true">…</aside>`). Keep the split — no `HX-Request` sniffing.
- Both `GET /` and `GET /search` paginate via a `page` query param (`PAGE_SIZE = 24`, a module global in `app/web/library.py`). The view passes `page`/`total_pages`/`has_prev`/`has_next`/`start`/`end` to the templates; `_pagination.html` renders the controls. Facet AND/OR semantics apply before pagination (total is the unpaginated match count).
- Facet semantics: AND across groups, OR within a group, AND with the FTS query. `archived = 0` is always applied in the library; `/r/{slug}` still serves archived recipes so existing links keep working. `_build_filters` in `app/db/queries.py` is the single chokepoint — extend it there, don't open-code WHERE clauses in new endpoints.
- The detail page renders entirely from DB columns (`body_markdown`, `frontmatter_json`). Do not re-parse the source Markdown file on the request path.
- Markdown → HTML goes through the `| md` Jinja filter (singleton `MarkdownIt` in `app/web/markdown.py`). Templates use `{{ ... | md | safe }}` because the corpus is trusted; if untrusted Markdown is ever ingested, add sanitization in that one file.
- Tests use `client` fixture (TestClient + `get_db_path` override → `populated_db`). Don't monkey-patch `load_settings`.
- Test counts that depend on the seed corpus should derive from `recipes_dir.glob("*.md")`, not hardcode a number — the corpus grows.

## CRUD write conventions (Stage 4)

- All writes flow through `app/web/forms.py::build_markdown` → `_write_and_sync` → `sync_one`. Never write to SQLite without first updating the Markdown file.
- `build_markdown` constructs a ruamel `CommentedMap` with the same `_yaml()` settings as `serializer.py` (same instance; import `_yaml` from there). This ensures the generated file is roundtrip-stable immediately — no second-pass reformat needed.
- Field order in the generated YAML: `id, slug, title, summary, cuisine, meal_type, tags, dietary, prep_minutes, cook_minutes, total_minutes, servings, yield_note, equipment, ingredients, nutrition, source, images, created_at, updated_at, archived, favorite`. Omit keys whose value is None or an empty list (`archived` and `favorite` are always written). `images` is written as a block-style list of `{path}` mappings when the form's Image URL is set; it carries through edits so the write path no longer strips an existing hero.
- Flow style for short primitive lists (`meal_type`, `tags`, `dietary`, `equipment`); block style for `ingredients` (mappings) — enforced by `seq.fa.set_block_style()` on the parsed CommentedSeq.
- Slug is derived from title via `normalize_slug()` on create; immutable on edit (the route path owns it). Collision check via `slug_in_use(recipes_dir, slug)` (tree-wide) before writing. New recipes may target a subdirectory via the form's optional `folder` field, validated by `resolve_new_recipe_path` (rejects absolute/`..`/reserved-dir paths, traversal-guarded). Edits and bool-field flips resolve the existing file with `find_recipe_file` and rewrite it in place, preserving its subdirectory.
- Archive/unarchive and favorite/unfavorite share `_flip_bool_field`, which mutates `doc.raw_yaml[field]` and `doc.raw_yaml["updated_at"]` in-place, then calls `serialize(doc)`. This is the one place we ruamel-edit rather than rebuild — it preserves all other YAML formatting. The favorite/unfavorite routes accept a `?next=` query param (same-origin only, via `_safe_next`) so the card heart can return to the library.
- `_write_and_sync` saves the original file contents before overwriting and restores them if `sync_one` reports errors.
- Tests for the CRUD layer use the `crud_client` fixture which overrides `get_db_path`, `get_recipes_dir`, and `get_users_path` (and logs in). The read-only `client` fixture must **not** be modified to add these — it intentionally has no writable recipes dir.

## Auth conventions

- **Public read, gated CRUD.** Read routes (`library.py`, `recipe.py`, `/media`, `/healthz`) are open. Every write route in `app/web/crud.py` depends on `require_user` (`app/web/deps.py`); add it to any new write route. Don't gate read routes.
- `require_user` raises `AuthRequiredError`; `app/main.py` registers a handler that redirects to `/login?next=<path>`. `current_user` (used by templates via a Jinja context processor) returns the username or `None` without raising.
- Credentials are a JSON map `{username: argon2_hash}` at `settings.auth_path` (`DATA_DIR/auth.json`) — **never** in `recipes.db` (it's rebuilt by `recipes rebuild-index`). All access goes through `app/auth/store.py`; manage accounts with the `recipes set-password|list-users|delete-user` CLI commands.
- Session is a signed cookie (`SessionMiddleware` in `app/main.py`, built from `load_settings()` at import). `cookie_secure` (env `COOKIE_SECURE`, default true) sets the `Secure` flag — TLS is terminated by a reverse proxy, not the app. Set `SESSION_SECRET` in production.
- Templates gate write affordances on `current_user` (`base.html` header, `recipe.html` Edit/archive/favorite, `_results.html` card heart). The HTMX `/search` fragment also receives `current_user` via the context processor.

## Process

- Deliver in validated stages. Don't try to implement the whole roadmap in one pass.
- The roadmap lives in `TODO.md`. Update it when stages complete or scope shifts.
- For multi-step work, use a task list.
- Architectural tradeoffs go in `docs/architecture.md` so they survive future sessions.
- **Plan with Opus, implement with Sonnet.** The preferred workflow is to do design/planning on the Opus model, then carry out the implementation on Sonnet. When leaving Plan mode, switching the active model to Sonnet automatically is expected and pre-approved.
- For sizeable changes, land the work as a sequence of small, individually-green commits on a feature branch (not directly on `main`), then open one PR.
