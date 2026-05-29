# recipe-app

A personal recipe management system, built as **optional modules layered on one durable core**: a
repository of Markdown recipe files. **The Markdown files are the only source of truth.** Everything
else — the SQLite mirror, the FTS5 index, the web UI, the REST API, the static-site generator, the
importer, the AI layer — is a derived, rebuildable projection you can add, remove, or swap without
touching your recipes.

The app reads recipes from `$RECIPES_DIR` (default `./recipes/`, gitignored dev scratch). Point it
at any directory of Markdown files and it rebuilds its entire derived state from there.

## Why this design

- **Canonical Markdown + Git.** Recipes survive any future tool. Diffs are human-readable. Backup = git push.
- **SQLite as a derived mirror.** Fast structured queries (tags, time, ingredients) and full-text search via FTS5, without making a database the system of record.
- **One canonical pipeline.** All writes — UI, importer, AI drafts — go through `RecipeModel → serialize → write Markdown → sync SQLite`. Never the reverse.
- **Idempotent sync.** `rm data/recipes.db && recipes sync` always reproduces identical derived state.
- **Modular & removable.** Each module is optional; the core corpus stands on its own.

## Modules

| Module | What it is | Status |
|---|---|---|
| **Recipe corpus** | Markdown files — the source of truth | ✅ available (flat dir; nested-dir support planned) |
| `app/core/` | Schema, parse, serialize, validate (shared lib) | ✅ available |
| **SQLite mirror + sync** | Derived FTS5 index, idempotent sync | ✅ available |
| **Web UI** (HTMX/Jinja) | Default zero-build frontend | ✅ available |
| **REST/JSON API** | Shared data contract for frontends | 🔜 planned |
| **React SPA** | Optional richer frontend on the API | 🔜 planned |
| **Static Site Generator** | Corpus → static HTML, no DB | 🔜 planned |
| **URL importer** | URL → draft recipe | 🟡 interim: `recipe-from-url` skill; in-app planned |
| **Meal planner** | Weekly scheduling, shopping lists | 🔜 planned |
| **AI assistance** | LLM + retrieval + grounding | 🔜 planned |

See [`docs/architecture.md`](docs/architecture.md) for the module map and decision records, and
[`GETTING-STARTED.md`](GETTING-STARTED.md) for how modules are (eventually) toggled per deployment.

## Stack

- Python 3.12 + FastAPI + Jinja2
- Pydantic v2, `mypy --strict`, `ruff`
- SQLite + FTS5
- HTMX + Alpine.js + Pico.css (via CDN) for the UI
- (later) React SPA on a REST API; Ollama (`llama3.2:3b`) as the default local LLM

## Project status

**Stage 1 — scaffold ✅** Project skeleton, `/healthz`, CLI stub, Docker, tooling (`mypy --strict`, `ruff`, `pytest`).

**Stage 2 — storage layer ✅** Pydantic recipe schema, ruamel-based parser/serializer (byte-stable roundtrip), SQLite schema with FTS5 + triggers, idempotent sync pipeline, seed recipes, CLI verbs.

**Stage 3 — simple visualization layer ✅** Read-only web UI. `GET /` library with search box, facet checkboxes (tags / cuisine / meal type / dietary), max-time slider, sort dropdown. `GET /search` returns an HTMX fragment with out-of-band facet refresh. `GET /r/{slug}` renders the recipe with Markdown body via `markdown-it-py` and a print-friendly stylesheet.

**Stage 4 — CRUD ✅** `GET/POST /new`, `GET/POST /r/{slug}/edit`, `POST /r/{slug}/archive|unarchive`. All writes go through `build_markdown → write file → sync_one`. Slug immutable on edit. 68 tests.

**Modular restructure ✅** Re-framed the project as optional modules on the corpus core; locked in dual frontends on a shared REST API, monorepo, and folder-as-organization-only. See the roadmap for what's next.

See [`TODO.md`](TODO.md) for the full roadmap and [`docs/architecture.md`](docs/architecture.md) for the principles.

## Local development

```bash
# Create a venv and install dev deps
python3.12 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"

# Run tests / lint / types
pytest                    # 68 tests
ruff check
mypy --strict app/

# Populate ./recipes/ with some content (e.g. via the recipe-from-url skill),
# then sync into SQLite and start the dev server
recipes sync
recipes run-dev           # http://127.0.0.1:3141/

# Inspect the install (versions, recipe count, db count, last sync)
recipes doctor
```

## Try the CLI

```bash
recipes validate                  # parse + validate every recipe; nonzero exit on errors
recipes sync                      # build the SQLite mirror from recipes/*.md
recipes sync                      # idempotent — second run reports 0 changes
recipes rebuild-index             # drop the DB and rebuild from scratch
recipes search eggplant           # FTS5 query
recipes search "tomato sauce"     # multi-word, rank-ordered
recipes show miso-glazed-eggplant # pretty-print a recipe from the DB
```

The SQLite mirror lives at `data/recipes.db` (gitignored). Wipe it any time — `recipes sync` reproduces it from `$RECIPES_DIR`.

## Running with Docker

The image is published to GHCR on every push to `main` — no repo clone required.
See [`GETTING-STARTED.md`](GETTING-STARTED.md) for the full guide (authentication, your own recipes
directory, wiring up the `recipe-from-url` skill, planned module toggling). Quick version:

```bash
# authenticate once
echo $(gh auth token) | docker login ghcr.io -u chriskasza --password-stdin

# create ~/my-recipes/docker-compose.yml pointing at ghcr.io/chriskasza/recipe-app:latest, then:
docker compose pull && docker compose up -d
curl http://localhost:3141/healthz
```

## Layout

```
recipe-app/
├── app/
│   ├── core/         # canonical pipeline (Pydantic, parser, serializer)  — shared lib
│   ├── db/           # SQLite schema, sync, FTS5, library + facet queries
│   ├── web/          # FastAPI routes, Jinja templates, MarkdownIt filter (HTMX UI)
│   │   ├── forms.py  # FormData, parse_form, build_markdown
│   │   └── crud.py   # /new, /r/{slug}/edit, /archive, /unarchive
│   ├── templates/    # base, index, _facets, _results, recipe, edit, _form
│   ├── static/       # style.css (cards / chips / form layout / print)
│   ├── api/          # REST/JSON API                                       — planned
│   ├── importer/     # URL → draft recipe                                  — planned
│   ├── ai/           # LLM provider, retrieval, grounding                  — planned
│   ├── cli.py        # operator CLI (Typer)
│   ├── config.py     # path/env settings
│   └── main.py       # FastAPI app — /healthz, /static, web router
├── web-spa/          # React SPA on the REST API                          — planned
├── ssg/              # static-site generator (corpus → HTML)              — planned
├── recipes/          # dev scratch — gitignored, populated via recipe-from-url skill
├── data/             # DERIVED — SQLite DB, not committed
├── docs/             # architecture, recipe format, managing recipes, template
└── tests/
    └── fixtures/recipes/  # frozen test corpus — committed, byte-stable
```

## Docs

- [`GETTING-STARTED.md`](GETTING-STARTED.md) — run the app; choose modules
- [`docs/managing-recipes.md`](docs/managing-recipes.md) — author and organize your recipe library
- [`docs/recipe-template.md`](docs/recipe-template.md) — copy-me recipe skeleton
- [`docs/recipe-format.md`](docs/recipe-format.md) — canonical Markdown format reference
- [`docs/architecture.md`](docs/architecture.md) — module map, principles, decision records
- [`CLAUDE.md`](CLAUDE.md) — project conventions for AI-assisted work
