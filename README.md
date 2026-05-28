# recipe-app

A personal recipe management system. **Markdown files in `recipes/` are the source of truth.** Everything else — the SQLite mirror, the FTS5 index, the web UI, the importer, the AI assistance layer — is a derived, rebuildable projection of that corpus.

If every service is deleted tomorrow, `git clone` of `recipes/` still gives you every recipe in a portable, hand-editable format.

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
- (later) HTMX + Alpine.js for the UI
- (later) Ollama (`llama3.2:3b`) as the default local LLM

## Project status

**Stage 1 — scaffold ✅** Project skeleton, `/healthz`, CLI stub, Docker, tooling (`mypy --strict`, `ruff`, `pytest`).

**Stage 2 — storage layer ✅** Pydantic recipe schema, ruamel-based parser/serializer (byte-stable roundtrip), SQLite schema with FTS5 + triggers, idempotent sync pipeline, 6 seed recipes, 24 tests, CLI verbs.

**Stage 3 — simple visualization layer (next).** `/r/{slug}` read view and library listing with HTMX search.

See [`TODO.md`](TODO.md) for the full roadmap and [`docs/architecture.md`](docs/architecture.md) for the principles.

## Local development

```bash
# Create a venv and install dev deps
python3.12 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"

# Run tests / lint / types
pytest                    # 24 tests
ruff check
mypy --strict app/

# Run the dev server (Stage 3+ will add real routes; today this only exposes /healthz)
recipes run-dev

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

Recipes live under [`recipes/`](recipes/) and the SQLite mirror at `data/recipes.db` (gitignored). Wipe `data/recipes.db` any time — `recipes sync` reproduces it.

## Docker

```bash
docker compose build
docker compose up -d
curl http://localhost:8000/healthz
```

`recipes/` and `data/` are bind-mounted from the host. Edit recipes from your editor outside the container; the app sees changes immediately.

## Layout

```
recipe-app/
├── app/
│   ├── core/         # canonical pipeline (Pydantic, parser, serializer)  — Stage 2
│   ├── db/           # SQLite schema, sync, FTS5                          — Stage 2
│   ├── web/          # FastAPI routes, Jinja templates                    — Stage 3+
│   ├── cli.py        # operator CLI (Typer)
│   ├── config.py     # path/env settings
│   └── main.py       # FastAPI app
├── recipes/          # CANONICAL — Markdown files, git-tracked
├── data/             # DERIVED — SQLite DB, not committed
├── docs/             # architecture, recipe format
└── tests/
```

## Docs

- [`docs/architecture.md`](docs/architecture.md) — principles and layer responsibilities
- [`docs/recipe-format.md`](docs/recipe-format.md) — canonical Markdown format
- [`CLAUDE.md`](CLAUDE.md) — project conventions for AI-assisted work
