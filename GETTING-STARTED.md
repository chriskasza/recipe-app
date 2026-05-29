# Getting started

How to run recipe-app over your recipe library, and how you'll choose which modules to include.

The system is built from optional [modules](docs/architecture.md) layered on one core: a folder of
Markdown recipe files. For authoring and organizing that folder, see
[`docs/managing-recipes.md`](docs/managing-recipes.md). This guide is about **running** the
software.

> **Module status legend:** ✅ available now · 🔜 planned (mechanism designed, not yet built).

## Prerequisites

- A directory of recipe files for `$RECIPES_DIR` (can start empty).
- Either Python 3.12 (local dev) or Docker + Docker Compose.

## Quick start — local dev ✅

```bash
python3.12 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"

# Point at your recipes (defaults to ./recipes/, a gitignored dev scratch dir)
export RECIPES_DIR=./recipes
recipes sync          # build the SQLite mirror from your files
recipes run-dev       # http://127.0.0.1:3141/
recipes doctor        # versions, recipe count, db count, last sync
```

## Quick start — Docker ✅

### From this repo

```bash
docker compose build
docker compose up -d
curl http://localhost:3141/healthz
```

`./recipes/` and `./data/` are bind-mounted from the host. Drop recipe files into `./recipes/`; the
app picks them up on the next sync.

### Using the image for your own recipe collection

The image isn't published to a registry yet, so you build it locally and point a separate project
at it. Both this `recipe-app` repo and your recipes project must live on the **same machine** — the
freshly built image exists only in that machine's local Docker image store.

1. **Build and tag** from this repo (re-run whenever you pull new `recipe-app` changes):
   ```bash
   docker build -t recipe-app:latest .
   ```
2. **Create your recipes project** anywhere on the same machine — say `~/my-recipes/` — with a
   `docker-compose.yml` that *consumes* the local image instead of building it:
   ```yaml
   services:
     app:
       image: recipe-app:latest
       ports:
         - "3141:3141"
       volumes:
         - ./recipes:/app/recipes
         - ./data:/app/data
       environment:
         RECIPES_DIR: /app/recipes
         DATA_DIR: /app/data
       restart: unless-stopped
   ```
3. **Start it** from that project directory:
   ```bash
   docker compose up -d
   curl http://localhost:3141/healthz
   ```
   Your recipes live in `./recipes/` and the derived SQLite DB in `./data/`, both bind-mounted from
   your project. After rebuilding the image (step 1), run `docker compose up -d` again to recreate
   the container.

## Importing recipes with Claude Code (the URL importer, interim) 🟡

The image bundles the `recipe-from-url` skill at `/app/.claude/skills/recipe-from-url/`. The Claude
Code CLI is **not** in the image — it runs on your host with your own account. To wire it up:

1. **Extract the skill** to wherever you run `claude`:
   ```bash
   docker compose cp app:/app/.claude/skills/recipe-from-url .claude/skills
   ```
   Place it under `.claude/skills/` in your working directory, or `~/.claude/skills/` for global use.
2. **Run `claude`** in the directory that contains your `docker-compose.yml`. Paste a recipe URL.
   The skill fetches the page, maps fields, then pipes the payload into the running container:
   ```bash
   docker compose exec -T app python /app/.claude/skills/recipe-from-url/scripts/build_draft.py < tmp/recipe-payload.json
   ```
   The draft lands at `./recipes/_drafts/<slug>.md` via the mounted volume. Review it and move it
   into `./recipes/` when satisfied.

A fully in-app URL importer is planned (see [`TODO.md`](TODO.md)); this skill is the interim path.

## Choosing which modules to run 🔜 (planned)

Today the image runs a **single combined service** (web UI + SQLite mirror), so `docker compose up`
gives you everything. The modular toggling below is the **target design** — it lands with the
*Modular foundations* stage in [`TODO.md`](TODO.md). It will work through two coordinated switches:

### 1. docker-compose profiles

Each module becomes an opt-in service guarded by a profile, so you run only what you want:

```yaml
# Target shape — not yet in docker-compose.yml
services:
  web:                       # HTMX/Jinja UI (default frontend)
    profiles: ["web"]
    # …
  api:                       # REST/JSON API (shared data contract)
    profiles: ["api"]
    # …
  ai:                        # Ollama-backed assistance
    profiles: ["ai"]
    # …
```

```bash
# Pick your modules at launch:
docker compose --profile web up -d                 # just the simple UI
docker compose --profile web --profile api up -d   # UI + REST API
docker compose --profile api --profile ai up -d    # headless API + AI
```

### 2. pyproject optional-dependency groups

For lean local installs, dependencies will be split into extras so you don't pull FastAPI or an LLM
client unless you need them:

```bash
pip install -e ".[core]"        # parser/serializer/validator only — no web stack
pip install -e ".[web]"         # the HTMX/Jinja app
pip install -e ".[api]"         # the REST API
pip install -e ".[all,dev]"     # everything, for development
```

Planned modules and how you'll enable them:

| Module | Status | Enabled by |
|---|---|---|
| Web UI (HTMX/Jinja) | ✅ today: always on | 🔜 `--profile web` / `.[web]` |
| SQLite mirror + sync | ✅ | bundled with web/api |
| REST/JSON API | 🔜 | `--profile api` / `.[api]` |
| React SPA | 🔜 | served by web or its own profile |
| Static Site Generator | 🔜 | `recipes build-site` (no service) |
| URL importer (in-app) | 🔜 | bundled; interim = `recipe-from-url` skill |
| Meal planner | 🔜 | bundled with web/api |
| AI assistance | 🔜 | `--profile ai` / `.[ai]` |

## Next steps

- [`docs/managing-recipes.md`](docs/managing-recipes.md) — author and organize your library.
- [`docs/recipe-template.md`](docs/recipe-template.md) — copy-me recipe skeleton.
- [`docs/architecture.md`](docs/architecture.md) — the module map and decision records.
- [`TODO.md`](TODO.md) — the roadmap and what's coming next.
