# A Recipe App (Plated)

[![CI](https://github.com/chriskasza/recipe-app/actions/workflows/ci.yml/badge.svg)](https://github.com/chriskasza/recipe-app/actions/workflows/ci.yml)

A personal recipe management system, built as **optional modules layered on one durable core**: a
repository of Markdown recipe files. **The Markdown files are the only source of truth.** Everything
else — the SQLite mirror, the FTS5 index, the web UI, the REST API, the static-site generator, the
importer, the AI layer — is a derived, rebuildable projection you can add, remove, or swap without
touching your recipes.

The app reads recipes from `$RECIPES_DIR` (default `./recipes/`, gitignored dev scratch). Point it
at any directory of Markdown files and it rebuilds its entire derived state from there.

## Why this design

- **Canonical Markdown + Git.** Recipes survive any future tool, diff cleanly, and back up with `git push`.
- **SQLite as a derived mirror.** Fast structured queries and FTS5 search, without a database as the system of record.
- **One canonical pipeline.** All writes go through `Recipe → serialize → write Markdown → sync SQLite`. Never the reverse.
- **Modular & removable.** Each module is optional; the core corpus stands on its own.

See [`docs/architecture.md`](docs/architecture.md) for the full module map, principles, and decision records.

## What works today

Available now: the recipe corpus, `app/core` (parse/serialize/validate), the SQLite/FTS5 mirror
with idempotent sync, the HTMX/Jinja web UI with full CRUD, and a REST/JSON API (`/api/v1`, OpenAPI
docs at `/docs`) with full CRUD parity. Browsing and API reads are public; creating and editing
recipes is gated behind a login on the web (see [Authentication](docs/running.md#authentication))
and behind a Bearer token on the API (`recipes create-token`), so the app is safe to expose on the
internet behind an HTTPS reverse proxy. Planned: a React SPA, a static-site generator, an in-app
URL importer (interim: the `recipe-from-url` skill), a meal planner, and AI assistance. See the
[module status table](docs/architecture.md#module-status) for the authoritative breakdown.

## Stack

- Python 3.11 + FastAPI + Jinja2
- Pydantic v2, `mypy --strict`, `ruff`
- SQLite + FTS5
- HTMX + Alpine.js + Pico.css (via CDN) for the UI
- argon2 password hashing + signed-cookie sessions for login-gated CRUD
- (later) React SPA on a REST API; Ollama (`llama3.2:3b`) as the default local LLM

## Quick start

The app ships as a Docker image on GitHub Container Registry — no clone or Python toolchain needed.

```bash
# 1. Authenticate to GHCR once (a GitHub account with image access is required)
echo $(gh auth token) | docker login ghcr.io -u chriskasza --password-stdin

# 2. In a new project directory, create a docker-compose.yml (see docs/running.md),
#    bind-mounting ./recipes and ./data, then:
docker compose pull
docker compose up -d
curl http://localhost:3141/healthz   # → ok — the app is at http://localhost:3141/
```

Your recipes live in `./recipes/` (Markdown, the source of truth) and the derived SQLite DB in
`./data/`, both bind-mounted from your project directory.

See [`docs/running.md`](docs/running.md) for the full guide — the compose file, authentication,
the URL importer, and choosing which modules to run — or [`CONTRIBUTING.md`](CONTRIBUTING.md) to run
from source for development.

## Status

For what's shipped, see [`docs/architecture.md`](docs/architecture.md); for what's next, see
[`TODO.md`](TODO.md).

## Docs

- [`docs/running.md`](docs/running.md) — run the app over your library; choose modules
- [`CONTRIBUTING.md`](CONTRIBUTING.md) — dev setup, quality gates, project layout
- [`docs/managing-recipes.md`](docs/managing-recipes.md) — author and organize your recipe library
- [`docs/recipe-template.md`](docs/recipe-template.md) — copy-me recipe skeleton
- [`docs/recipe-format.md`](docs/recipe-format.md) — canonical Markdown format reference
- [`docs/architecture.md`](docs/architecture.md) — module map, principles, decision records
- [`CLAUDE.md`](CLAUDE.md) — project conventions for AI-assisted work
