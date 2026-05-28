# recipe-app

A personal recipe management system. **Markdown recipe files are the source of truth.** Everything else — the SQLite mirror, the FTS5 index, the web UI, the importer, the AI assistance layer — is a derived, rebuildable projection of that corpus.

The app reads recipes from `$RECIPES_DIR` (default `./recipes/`, gitignored dev scratch). Point it at any directory of Markdown files and it rebuilds its entire derived state from there.

## Why this design

- **Canonical Markdown + Git.** Recipes survive any future tool. Diffs are human-readable. Backup = git push.
- **SQLite as a derived mirror.** Fast structured queries (tags, time, ingredients) and full-text search via FTS5, without making a database the system of record.
- **One canonical pipeline.** All writes — UI, importer, AI drafts — go through `RecipeModel → serialize → write Markdown → sync SQLite`. Never the reverse.
- **Idempotent sync.** `rm data/recipes.db && recipes sync` always reproduces identical derived state.
- **Removable layers.** Web UI, AI, importer can all be ripped out without touching the corpus.

## Stack

- Python 3.12 + FastAPI + Jinja2
- Pydantic v2, `mypy --strict`, `ruff`
- SQLite + FTS5
- HTMX + Alpine.js + Pico.css (via CDN) for the UI
- (later) Ollama (`llama3.2:3b`) as the default local LLM

## Project status

**Stage 1 — scaffold ✅** Project skeleton, `/healthz`, CLI stub, Docker, tooling (`mypy --strict`, `ruff`, `pytest`).

**Stage 2 — storage layer ✅** Pydantic recipe schema, ruamel-based parser/serializer (byte-stable roundtrip), SQLite schema with FTS5 + triggers, idempotent sync pipeline, seed recipes, CLI verbs.

**Stage 3 — simple visualization layer ✅** Read-only web UI. `GET /` library with search box, facet checkboxes (tags / cuisine / meal type / dietary), max-time slider, sort dropdown. `GET /search` returns an HTMX fragment with out-of-band facet refresh. `GET /r/{slug}` renders the recipe with Markdown body via `markdown-it-py` and a print-friendly stylesheet. Templates use Pico.css + HTMX + Alpine via CDN; one `app/static/style.css` for cards/chips/print. 48 tests.

**Stage 4 — CRUD ✅** `GET/POST /new`, `GET/POST /r/{slug}/edit`, `POST /r/{slug}/archive|unarchive`. Hybrid form (structured metadata + Markdown body textarea + YAML ingredient textarea). All writes go through `build_markdown → write file → sync_one`. Slug immutable on edit. 68 tests.

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

## Docker

```bash
docker compose build
docker compose up -d
curl http://localhost:3141/healthz
```

`./recipes/` and `./data/` are bind-mounted from the host. Drop recipe files into `./recipes/`; the app picks them up on the next sync.

## Layout

```
recipe-app/
├── app/
│   ├── core/         # canonical pipeline (Pydantic, parser, serializer)  — Stage 2
│   ├── db/           # SQLite schema, sync, FTS5, library + facet queries — Stage 2–3
│   ├── web/          # FastAPI routes, Jinja templates, MarkdownIt filter — Stage 3–4
│   │   ├── forms.py  # FormData, parse_form, build_markdown               — Stage 4
│   │   └── crud.py   # /new, /r/{slug}/edit, /archive, /unarchive         — Stage 4
│   ├── templates/    # base, index, _facets, _results, recipe, edit, _form — Stage 3–4
│   ├── static/       # style.css (cards / chips / form layout / print)    — Stage 3–4
│   ├── cli.py        # operator CLI (Typer)
│   ├── config.py     # path/env settings
│   └── main.py       # FastAPI app — /healthz, /static, web router
├── recipes/          # dev scratch — gitignored, populated via recipe-from-url skill
├── data/             # DERIVED — SQLite DB, not committed
├── docs/             # architecture, recipe format
└── tests/
    └── fixtures/recipes/  # frozen test corpus — committed, byte-stable
```

## Docs

- [`docs/architecture.md`](docs/architecture.md) — principles and layer responsibilities
- [`docs/recipe-format.md`](docs/recipe-format.md) — canonical Markdown format
- [`CLAUDE.md`](CLAUDE.md) — project conventions for AI-assisted work
