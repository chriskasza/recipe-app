# Contributing

How to develop against recipe-app. For running the app over your own recipe library, see
[`docs/running.md`](docs/running.md).

## Dev setup

```bash
python3.11 -m venv .venv
source .venv/bin/activate
pip install -e ".[all,dev]"
```

Run tools via `.venv/bin/` directly (e.g. `.venv/bin/pytest`) — never as `python -m <tool>`.

## Quality gates

These mirror the CI workflow; all must pass before a PR merges:

```bash
ruff check .
ruff format --check .
mypy --strict app/
RECIPES_DIR=tests/fixtures/recipes recipes validate
pytest
```

Add a test suite alongside each new layer. The required suites are the parser roundtrip, sync
idempotency, FTS search, and validator.

## Running locally

```bash
# Populate ./recipes/ with content (e.g. via the recipe-from-url skill),
# then sync into SQLite and start the dev server:
recipes sync
recipes run-dev           # http://127.0.0.1:3142/
recipes doctor            # versions, recipe count, db count, last sync
```

To build and run the Docker image from source:

```bash
docker compose build
docker compose up -d      # publishes on http://localhost:3142/ (see .env.example)
curl http://localhost:3142/healthz
```

### Port convention

| Port | Role |
|------|------|
| 3141 | Production Docker instance (e.g. `~/code/recipes`) |
| 3142 | Development — `recipes run-dev` default and `docker compose up` in this repo |

The `docker-compose.yml` in this repo reads `RECIPE_APP_PORT` from `.env` (gitignored; copy from
`.env.example`). The default falls back to 3141 so a standalone deployment without a `.env` still
works on the canonical port.

## Project layout

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
│   ├── importer/     # payload → recipe file (recipes save-recipe)         — write half done
│   ├── ai/           # LLM provider, retrieval, grounding                  — planned
│   ├── cli.py        # operator CLI (Typer)
│   ├── config.py     # path/env settings
│   └── main.py       # FastAPI app — /healthz, /static, web router
├── web-spa/          # React SPA on the REST API                          — planned
├── ssg/              # static-site generator (corpus → HTML)              — planned
├── recipes/          # dev scratch — gitignored, populated via recipe-from-url skill
├── data/             # DERIVED — SQLite DB, not committed
├── docs/             # architecture, recipe format, managing recipes, running, template
└── tests/
    └── fixtures/recipes/  # frozen test corpus — committed, byte-stable
```

## Conventions

- [`CLAUDE.md`](CLAUDE.md) — the rules of the road: source-of-truth model, the canonical write
  pipeline, code style, and where things live.
- [`docs/architecture.md`](docs/architecture.md) — module map, design principles, decision records.
- [`TODO.md`](TODO.md) — the staged roadmap. Deliver in validated stages; update it as scope shifts.
