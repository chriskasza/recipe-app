# Running recipe-app

How to run recipe-app over your recipe library, and how you'll choose which modules to include.

The system is built from optional [modules](architecture.md) layered on one core: a folder of
Markdown recipe files. For authoring and organizing that folder, see
[`managing-recipes.md`](managing-recipes.md). This guide is about **running** the
software.

> **Module status legend:** ✅ available now · 🔜 planned (mechanism designed, not yet built).

## Prerequisites

- Docker + Docker Compose.
- A GitHub account with access to the published image (for authenticating to GHCR).
- A directory of recipe files for `$RECIPES_DIR` (can start empty).

Developing against the app instead? See [`../CONTRIBUTING.md`](../CONTRIBUTING.md) for the
from-source path (Python 3.11 + a clone).

## Port convention

| Port | Role |
|------|------|
| 3141 | Production — the canonical port for a standalone deployment |
| 3142 | Development — `recipes run-dev` default |

If you run both a production instance and a local development build on the same machine, keep
them on their respective ports to avoid collisions. The repo's `docker-compose.yml` reads
`RECIPE_APP_PORT` from `.env` and defaults to 3141; copy `.env.example` to `.env` to get the 3142 
development default. See [`../CONTRIBUTING.md`](../CONTRIBUTING.md) for the dev setup details.

## Quick start — Docker ✅

Docker is the recommended way to run the app. The image is published to GitHub Container Registry
on every push to `main` — no need to clone this repo or install a Python toolchain. Authenticate
once, then run from any machine.

### 1. Authenticate to GHCR (once per machine)

Using the GitHub CLI (easiest):
```bash
echo $(gh auth token) | docker login ghcr.io -u chriskasza --password-stdin
```

Or with a [Personal Access Token](https://github.com/settings/tokens) (needs `read:packages` scope):
```bash
echo YOUR_PAT | docker login ghcr.io -u chriskasza --password-stdin
```

### 2. Create your recipes project

Create a directory anywhere — say `~/my-recipes/` — with this `docker-compose.yml`:

```yaml
services:
  app:
    image: ghcr.io/chriskasza/recipe-app:latest
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

### 3. Start it

```bash
docker compose pull      # fetch the latest image from GHCR
docker compose up -d
curl http://localhost:3141/healthz
```

Your recipes live in `./recipes/` and the derived SQLite DB in `./data/`, both bind-mounted from
your project directory. To update to a newer image:
```bash
docker compose pull && docker compose up -d
```

## Running from source (development)

To develop against the app — a local venv install, the operator CLI without the `docker compose
exec` prefix, building the image from source, and the quality gates — see
[`../CONTRIBUTING.md`](../CONTRIBUTING.md).

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
   docker compose exec -T app recipes save-recipe --json < tmp/recipe-payload.json
   ```
   The recipe lands directly at `./recipes/<slug>.md` via the mounted volume; the skill then runs
   `recipes sync` so the library picks it up. Notice an issue? Fix it from the web UI's edit form.

A fully in-app URL importer is planned (see [`../TODO.md`](../TODO.md)); this skill is the interim path.

## Authentication ✅

Read access (browsing, search, recipe pages) is **public**. Every write — adding,
editing, archiving, or favoriting recipes — requires a login. This is what makes it
safe to expose the app on the internet.

Credentials live in `$DATA_DIR/auth.json` (argon2 password hashes), **not** the
SQLite mirror — so they survive `recipes rebuild-index`. Create an account with the
operator CLI:

```bash
docker compose exec app recipes set-password kasza   # prompts for a password
docker compose exec app recipes list-users
docker compose exec app recipes delete-user kasza
```

Then visit `/login` (or click **Log in**) to unlock the Add / Edit / favorite
controls. Log out from the avatar button in the header.

### Sessions and HTTPS

Two env vars (wired through `docker-compose.yml`):

| Var | Default | Purpose |
|-----|---------|---------|
| `SESSION_SECRET` | auto-generated | Signs the session cookie. **Set this in production** to a strong random value (e.g. `openssl rand -base64 32`) so logins survive restarts and redeploys. If unset, a random secret is generated and persisted to `$DATA_DIR/.session_secret`. |
| `COOKIE_SECURE` | `true` | Marks the session cookie `Secure` (HTTPS-only). Keep `true` in production; set `false` only for local plain-http testing. |

The app does **not** terminate TLS itself. Put it behind a reverse proxy
(Caddy, nginx, Cloudflare Tunnel, …) that handles HTTPS and forwards to the
container's port 3141:

```
Internet ──▶ [Caddy/nginx : HTTPS] ──▶ app:3141 (http)
```

With `COOKIE_SECURE=true` the login cookie is only sent over HTTPS, so make sure
your proxy is serving the app over `https://` before exposing it.

### Brute-force protection

The app does not rate-limit `/login` itself (argon2 makes each guess slow, but
that is not a substitute for throttling). Rate-limit it at the reverse proxy,
which blocks abuse before it reaches the app — e.g. Caddy's `rate_limit`
directive or nginx's `limit_req` on the `/login` path.

## Choosing which modules to run ✅

The image runs the **web UI + SQLite mirror** by default (`docker compose up`), and additional
services are available as opt-in Docker Compose profiles. This is the *Modular foundations* stage
landed in [`../TODO.md`](../TODO.md). It works through two coordinated switches:

### 1. docker-compose profiles

The `app` service is always on. Opt-in services are guarded by a profile, so you run only what you
want:

```yaml
services:
  app:                       # default frontend (HTMX/Jinja web UI) — always on
    build: .
    image: recipe-app
    # …

  cli:                       # operator CLI as a one-shot
    image: recipe-app        # reuses the app image
    profiles: ["cli"]
    # …

  # api / ai: planned (Stage M3 / AI stage)
```

```bash
# Default: just start the web UI
docker compose up -d

# Opt-in CLI one-shot (skips boot sync; runs a single command then exits)
docker compose --profile cli run --rm cli recipes validate
docker compose --profile cli run --rm cli recipes doctor
```

### 2. pyproject optional-dependency groups

Dependencies are split into extras so you don't pull FastAPI or an LLM client unless you need them:

```bash
pip install -e ".[core]"        # parser/serializer/validator only — no web stack
pip install -e ".[web]"         # the HTMX/Jinja app (includes cli + importer)
pip install -e ".[importer]"    # recipe payload writer + curl_cffi (for the URL skill)
pip install -e ".[all,dev]"     # everything, for development
```

`.[api]` is a placeholder for Stage M3 (routers not yet built). There is no `.[ai]` extra yet.

Modules and how you enable them:

| Module | Status | Enabled by |
|---|---|---|
| Web UI (HTMX/Jinja) | ✅ | `docker compose up` / `.[web]` |
| SQLite mirror + sync | ✅ | bundled with web/api |
| Operator CLI | ✅ | `--profile cli` / `.[cli]` |
| REST/JSON API | 🔜 | `--profile api` / `.[api]` (Stage M3) |
| React SPA | 🔜 | served by web or its own profile |
| Static Site Generator | 🔜 | `recipes build-site` (no service) |
| URL importer (in-app) | 🔜 | bundled; interim = `recipe-from-url` skill |
| Meal planner | 🔜 | bundled with web/api |
| AI assistance | 🔜 | `--profile ai` / `.[ai]` (AI stage) |

## The operator CLI

`recipes` is the operator surface for the corpus and its derived state. Run it inside the container
with `docker compose exec app`:

```bash
docker compose exec app recipes validate    # parse + validate every recipe; nonzero exit on errors
docker compose exec app recipes sync         # build the SQLite mirror from $RECIPES_DIR
docker compose exec app recipes sync         # idempotent — second run reports 0 changes
docker compose exec app recipes rebuild-index            # drop the DB and rebuild from scratch
docker compose exec app recipes search eggplant          # FTS5 query
docker compose exec app recipes search "tomato sauce"    # multi-word, rank-ordered
docker compose exec app recipes show miso-glazed-eggplant # pretty-print a recipe from the DB
docker compose exec app recipes doctor       # versions, recipe count, db count, last sync
```

The container runs `recipes sync` automatically on startup, so the library reflects your files
without a manual step. The SQLite mirror lives at `$DATA_DIR/recipes.db` (bind-mounted to `./data/`).
Wipe it any time — the next `recipes sync` reproduces it from `$RECIPES_DIR`.

(Running from source instead? Drop the `docker compose exec app` prefix — see
[`../CONTRIBUTING.md`](../CONTRIBUTING.md).)

## Next steps

- [`managing-recipes.md`](managing-recipes.md) — author and organize your library.
- [`recipe-template.md`](recipe-template.md) — copy-me recipe skeleton.
- [`architecture.md`](architecture.md) — the module map and decision records.
- [`../TODO.md`](../TODO.md) — the roadmap and what's coming next.
