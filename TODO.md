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

For what has already shipped, see the **Project status** section of [`README.md`](README.md) and the
module-status table in [`docs/architecture.md`](docs/architecture.md). This file tracks only the work
that is still ahead.

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

- Image uploads + generated thumbnails (static display of a frontmatter `images[0].path` hero already ships).
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
