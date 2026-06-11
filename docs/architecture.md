# Architecture

recipe-app is a **modular system layered on one durable core**: a repository of Markdown recipe
files. The corpus is the only source of truth. Everything else is an optional module that reads
(and, through the canonical pipeline, writes) that corpus. Modules can be added, removed, or
swapped without touching the recipes.

## Module map

```
┌──────────────────────────────────────────────────────────────────────────┐
│  Layer 0 — RECIPE CORPUS  ($RECIPES_DIR)                       ← CANONICAL │
│  A directory of Markdown recipe files. Human-editable, git-versioned,      │
│  optionally organized into subdirectories. The ONLY source of truth.       │
│  Usable with nothing but a text editor + git.                              │
└───────────────────────────────┬──────────────────────────────────────────┘
                                 │  parse · validate · serialize
                  ┌──────────────┴───────────────────────┐
                  │  Shared infrastructure — app/core/    │  (not a module;
                  │  models · parser · serializer ·       │   every module
                  │  validator   (pure lib, zero coupling)│   depends on it)
                  └──────────────┬───────────────────────┘
                                 │
   ┌───────────────┬─────────────┴──────────────┬───────────────┬───────────────┐
   ▼               ▼                             ▼               ▼               ▼
┌─────────┐  ┌───────────────────────────┐  ┌──────────┐  ┌───────────┐  ┌────────────┐
│  Static │  │      Dynamic app          │  │   URL    │  │   Meal    │  │     AI     │
│  Site   │  │  SQLite/FTS5 mirror + sync│  │ importer │  │  planner  │  │ assistance │
│  Gen.   │  │  ├─ REST/JSON API      ✅ │  │          │  │           │  │            │
│ (static │  │  ├─ Web UI HTMX/Jinja  ✅ │  │ skill    │  │ SQLite-   │  │ LLM +      │
│  HTML)  │  │  └─ React SPA       (plan)│  │ (interim)│  │ only state│  │ retrieval  │
│ planned │  │                           │  │          │  │  planned  │  │  planned   │
└─────────┘  └───────────────────────────┘  └──────────┘  └───────────┘  └────────────┘

   ✅ available now   ·   (plan) planned   ·   each module is optional, toggled at
   deploy time via a docker-compose profile + a pyproject optional-dependency group.
```

### Module status

| Module | What it is | Status |
|---|---|---|
| **Recipe corpus** (Layer 0) | Markdown files; the source of truth | ✅ available (recursive discovery; subdirectories organize) |
| `app/core/` (shared infra) | Schema, parse, serialize, validate | ✅ available |
| **Dynamic app** — SQLite mirror + sync | Derived FTS5 index, idempotent sync | ✅ available |
| **Dynamic app** — Web UI (HTMX/Jinja) | Default zero-build frontend | ✅ available |
| **Dynamic app** — Auth (`app/auth/`) | Public read; login-gated CRUD. File-backed users outside the rebuildable DB | ✅ available |
| **Dynamic app** — REST/JSON API | Shared data contract for frontends | ✅ available (`app/api/`, full CRUD parity, Bearer-token writes) |
| **Dynamic app** — React SPA | Optional richer frontend on the API | 🔜 planned |
| **Static Site Generator** | Renders the corpus → static HTML, no DB | 🔜 planned |
| **URL importer** | URL → recipe file | 🟡 write half in-app (`recipes save-recipe` / `app/importer/save.py`); the `recipe-from-url` skill still does fetch + extraction. Deterministic in-app URL extraction planned |
| **Meal planner** | Weekly scheduling, shopping lists | 🔜 planned |
| **AI assistance** | LLM provider + retrieval + grounding | 🔜 planned |

## Source-of-truth model (inside the dynamic app)

The dynamic app keeps a derived SQLite/FTS5 mirror of the corpus. All writes flow one way —
through the canonical pipeline — and the mirror is always rebuildable from the files.

```
                  ┌──────────────────────────────────────────────┐
                  │                                              │
                  │    Markdown recipe files  ($RECIPES_DIR)     │  ← CANONICAL
                  │       The only durable source of truth       │
                  │  (gitignored ./recipes/ in dev; point at     │
                  │   any directory of .md files to rebuild)     │
                  └────────────┬─────────────────────┬───────────┘
                               │                     │
                  parse +      │                     │  read for grounding
                  validate     ▼                     │  (AI / rendering)
                       ┌───────────────┐             │
                       │ Recipe model  │             │
                       │  (Pydantic)   │             │
                       └───────┬───────┘             │
                               │ serialize           │
                               ▼                     │
                       ┌────────────────┐            │
                       │  Markdown disk │ ◀──────────┘
                       └───────┬────────┘
                               │ sync (idempotent)
                               ▼
                  ┌──────────────────────────────────┐
                  │   SQLite mirror + FTS5  (data/)  │  ← DERIVED, rebuildable
                  └──────────────────────────────────┘
                               │
                       reads ◀─┘
                               │
                  ┌─────────────────────────────┐
                  │  API · Web UI · SPA · AI    │  ← DERIVED layers (removable)
                  └─────────────────────────────┘
```

## Layer responsibilities

| Layer | Owns | Notes |
|---|---|---|
| `$RECIPES_DIR/**/*.md` | Canonical content | Edited by humans. In dev: `./recipes/` (gitignored scratch). Frozen test corpus in `tests/fixtures/recipes/`. Subdirectories organize; they do not change identity. |
| `app/core/` | Schema, parsing, serialization, validation | The contract. Roundtrip is byte-stable. No web/db dependencies. |
| `app/db/` | Derived SQLite tables + FTS5 | Wiped freely. `rebuild-index` recreates from scratch. `queries.py` is the typed read interface reused by the CLI, web layer, and (planned) API. |
| `app/web/` | HTTP, HTML rendering, forms (HTMX/Jinja UI) | Reads from DB via `queries.py`. Writes go through `forms.build_markdown → core.serializer → db.sync.sync_one`. |
| `app/api/` | REST/JSON contract (`/api/v1`) | Reuses `app/db/queries.py` for reads and `app/services/recipes.py` (shared with `app/web/`) for writes. Reads are public; writes require a Bearer token (`app/api/deps.py::require_token`). The data contract both frontends consume. |
| `app/services/` | Shared write/service layer | `recipes.py`: `build_markdown`, `_write_and_sync`, `create_recipe`/`update_recipe`/`set_archived`/`set_favorite` returning `WriteOutcome`/raising `RecipeNotFoundError`. Used by both `app/web/crud.py` and `app/api/recipes.py` — one write path through the canonical pipeline. |
| `ssg/` (planned) | Static HTML from the corpus | The "simple renderer." Reads files directly; no DB. |
| `web-spa/` (planned) | React SPA | Optional frontend; talks only to `app/api/`. |
| `app/importer/` | payload → Recipe file | `save.py` backs `recipes save-recipe`: renders a `RecipePayload` through the canonical pipeline and writes `<slug>.md` straight into the corpus. URL fetch/extraction still done by the `recipe-from-url` skill. |
| `app/ai/` (planned) | LLM provider, retrieval, grounding | Retrieves from DB; grounds answers on canonical Markdown. |
| `app/auth/` | Login credential store | `{username: argon2_hash}` in `data/auth.json` (atomic writes). Outside the rebuildable DB. Read/written via `app/auth/store.py`; login/logout routes in `app/web/auth.py`. |
| `app/cli.py` | Operator commands | `validate`, `sync`, `rebuild-index`, `search`, `show`, `doctor`, `save-recipe`, `set-password`, `list-users`, `delete-user`, `create-token`, `list-tokens`, `revoke-token`. |

## Architectural decisions

### Why ingredients live in YAML frontmatter

Ingredients need structure (meal planning, pantry awareness, shopping lists, scaling). Free-form Markdown lists are too fragile to parse reliably. Keeping the structured ingredient list in YAML frontmatter and the instructions/notes in the Markdown body gives us both: a machine-readable contract and a comfortable hand-editing surface.

### Why SQLite + FTS5 instead of an external search engine

Personal-scale (1–10k recipes). FTS5 is built into SQLite, requires no extra service, and is plenty fast at this scale. Replacing it later is straightforward because the retrieval layer (AI module) is behind a `Retriever` protocol.

### Why meal plans live only in SQLite (not as canonical Markdown)

Meal plans are personal scheduling state. They reference recipes but don't describe them. The corpus value is the recipe knowledge; meal plans are cheap to recreate and don't benefit from Git history. If a future need arises (e.g. exporting historical plans), we can re-emit them as `meal-plans/*.yaml` without restructuring anything.

### Why two frontends on one shared REST API

We keep **both** an HTMX/Jinja UI and a React SPA, and both consume a single REST/JSON API
(`app/api/`).

- The **HTMX/Jinja UI** needs no JavaScript build step and renders server-side. It is the
  lowest-friction default — it works in a stripped deployment, prints well, and is easy to reason
  about. It stays the default frontend.
- The **React SPA** is an opt-in module for richer client-side interaction. It owns no data logic;
  it talks only to the API.
- A **single API** is the contract both frontends share, so there is exactly one read path
  (`app/db/queries.py`) and one write/service path. No second data path to keep honest.

This is the "two visualization layers" idea made concrete: a static renderer and a dynamic app,
plus two interchangeable frontends over the dynamic app's API.

### Why a static-site generator is its own (simple) renderer

The SSG renders the corpus straight to static HTML with **no database and no running service** —
the simplest possible reader. It survives even if the dynamic app is gone, is trivial to host
(any static host or `file://`), and validates the "corpus is enough on its own" promise. The
dynamic app is the opposite end: fast querying, facets, search, CRUD, AI. Both read the same
`app/core/` schema, so neither owns the format.

### Why hierarchical recipe directories — and why the folder is organization only

Recipes may be organized into subdirectories (`breakfast/`, `dinner/`, …) for human convenience.
The folder is **metadata, not identity**:

- The **slug stays the filename stem** and must be unique across the whole tree.
- `/r/{slug}` **URLs are stable** when a recipe moves between folders — recategorizing never
  breaks a link.
- Identity remains the **ULID** (see below); the slug is the human handle; the path is just where
  the file happens to sit.

This shipped in Stage M2: discovery uses `recipes_dir.rglob("*.md")` (via
`app/db/sync.py::_iter_recipe_files`, reused by `app/cli.py doctor`), skipping the `_drafts/` and
`images/` helper directories through a shared `EXCLUDED_DIRS` frozenset. `sync_all`/`validate_all`
enforce global slug-uniqueness across the tree (duplicate stems are reported and skipped), and the
write path resolves a slug to its file anywhere in the tree via `app/web/forms.py::find_recipe_file`,
rewriting in place so a recipe keeps its subdirectory. New recipes may target an optional `folder`
(validated by `resolve_new_recipe_path`).

### Why `ruamel.yaml` in roundtrip mode

Vanilla `PyYAML` collapses formatting, reorders keys, and re-quotes strings — turning every save into a noisy diff. `ruamel.yaml` in roundtrip mode preserves user formatting choices, so when the UI updates one field the rest of the file is untouched in `git diff`.

### Why ULIDs as recipe IDs

The slug can change (renaming a recipe). Filenames can move (including between folders). We need a stable identifier that survives renames and lets us reliably upsert into the SQLite mirror. ULIDs are lexicographically sortable, URL-safe, and free of central allocation.

### Why monorepo with module boundaries

All modules live in one repository with clear directory/package boundaries (`app/core/`,
`app/api/`, `app/web/`, `ssg/`, `web-spa/`, …). For a single-maintainer project this gives atomic
cross-module commits and one place to test, with none of the submodule/version-pinning friction of
split repos. `app/core/` is written as a dependency-free library, so it can be carved into an
installable package later **without** a repo split if a module ever needs to consume it
standalone.

### How modules are toggled at deploy time

Two coordinated switches let a deployment include only the modules it wants:

- **`pyproject.toml` optional-dependency extras** — `core`, `cli`, `importer`, `web`, `api`, `all`,
  `dev`. `core` carries only Pydantic + ruamel + ulid. `web` is the default and transitively pulls
  `importer` (so the bundled `recipe-from-url` skill's `curl_cffi` is always in the image). There is
  no `ai` extra yet — it is planned for the AI stage.
- **`docker-compose.yml` profiles** — the default `app` service (web UI) runs with a bare
  `docker compose up`, unchanged. Opt-in services are guarded by a profile: the `cli` one-shot
  service ships today; `api` and `ai` services are planned as commented templates. The Dockerfile is
  parameterized by the `INSTALL_EXTRA` build arg (which extra to install) and the `APP_ROLE` runtime
  env (which gates the boot `recipes sync`: roles `web`/`api` sync on start; `cli` skips it).

Example invocations:

```bash
# Default: start the web UI (no profile needed)
docker compose up -d

# Opt-in CLI one-shot
docker compose --profile cli run --rm cli recipes validate

# ai profile is planned (AI stage); the REST/JSON API is bundled into the
# default app service, no separate profile needed

```

This shipped in the Modular foundations stage. The default `docker compose up` is unchanged for
existing deployments. See [`running.md`](running.md) for the full usage guide.

### Why auth credentials live in a file, not the SQLite mirror

To expose the app on the internet, read access stays public but every write is gated behind a
login. The natural place for `(username, password_hash)` would be a table in `recipes.db` — but
that DB is **derived and rebuildable**: `recipes rebuild-index` drops and recreates it from the
Markdown corpus, which would wipe the credentials. So auth state lives in `$DATA_DIR/auth.json`
(argon2 hashes via `argon2-cffi`), a sibling of `recipes.db` under the persistent data dir.
`recipes set-password` manages it; `app.auth.store` reads/writes it with atomic replacement.

Sessions use a signed cookie (Starlette `SessionMiddleware`, `HttpOnly`/`SameSite=Lax`/`Secure`).
TLS is intentionally **not** handled in-app — a reverse proxy terminates HTTPS in front of port
3141, matching the self-hosting norm. The gate is one dependency, `require_user`, applied to the 8
write routes in `app/web/crud.py`; unauthenticated hits raise `AuthRequiredError`, which an
exception handler turns into a redirect to `/login`. Read routes are untouched.

#### Why no CSRF tokens

CSRF defense rests on two properties rather than synchronizer tokens:

- **`SameSite=Lax` on the session cookie.** Lax withholds the cookie on *all* cross-site
  subrequests — including `fetch`/XHR and form POSTs — and only sends it on top-level GET
  navigations. A forged cross-origin POST therefore arrives with no session and is redirected to
  login.
- **All mutations are POST.** No state changes on GET, so the one request type Lax does allow
  cross-site can't trigger a write. The cookie is also host-only (no `Domain`), so sibling
  subdomains can't ride on it.

This is adequate for a single-corpus app whose only writable content (recipe Markdown, rendered
trusted via `| md | safe`) is authored by logged-in users. Token-based CSRF would be worth adding
if untrusted content ingestion or genuine multi-tenant use is introduced.

#### Hardening notes

- **Login regenerates the session** (`request.session.clear()` before setting the user) as
  defense-in-depth against fixation.
- **Constant-time login** (`app/auth/store.py::verify`): always runs an argon2 verification — against
  a dummy hash when the username is unknown — so response timing doesn't reveal which usernames
  exist.
- **The persisted session secret is written `0o600`.** Set `SESSION_SECRET` explicitly in
  production; otherwise a random secret is generated once and stored at `data/.session_secret`.
- **The `next` redirect target** is validated same-origin (`_safe_next`) and URL-encoded into the
  login URL.
- **Rate limiting** is delegated to the reverse proxy (documented in `running.md`), not done in-app.

### Why the API uses bearer tokens (web keeps cookies)

`app/api/` reads are public, matching the web UI. For writes, the API needs an auth scheme for
non-browser clients (scripts, the future SPA's build tooling, CI) — reusing the session cookie
doesn't fit:

- **No CSRF surface to manage.** The web UI's CSRF story (`SameSite=Lax` + POST-only mutations,
  see above) relies on the browser automatically attaching/withholding a cookie. A JSON API
  consumed by arbitrary HTTP clients doesn't get that for free, and a bearer token in an
  `Authorization` header is never sent automatically by a browser, so there's no analogous forgery
  vector to defend against.
- **Independent of login sessions.** A token can be minted for one script/integration and revoked
  without touching user accounts or invalidating browser sessions.
- **Explicit, auditable surface.** Tokens are named (`recipes_<random>`), listed via
  `recipes list-tokens`, and revoked individually via `recipes revoke-token <name>`.

`app/api/deps.py::require_token` uses `HTTPBearer(auto_error=False)` (documents the scheme in
OpenAPI) and **ignores the session cookie entirely** — a logged-in browser session does not grant
API write access; `tests/test_api_write.py` asserts this explicitly.

**Storage: SHA-256, not argon2.** Unlike passwords, API tokens are high-entropy random secrets
(`recipes_` + 32 bytes from `secrets.token_urlsafe`) chosen by the server, not low-entropy
human-chosen strings. There's no brute-force surface to slow down with a deliberately expensive
hash, so a SHA-256 digest (`hmac.compare_digest` for constant-time comparison) gives O(1)
verification without the per-request argon2 CPU cost. `app/auth/tokens.py` mirrors
`app/auth/store.py`'s atomic-write pattern; tokens live in `DATA_DIR/api_tokens.json`, a sibling of
`auth.json`, for the same reason — outside the rebuildable SQLite mirror.

**`app/importer/save.py::RecipePayload` was examined and not reused** for the API's write schema.
Its shape diverges from the shared web/API write path: it allows a slug override, structures the
body as discrete sections rather than a single Markdown blob, has its own render pipeline (not
`app.services.recipes.build_markdown`), and has no `favorite`/`folder` fields. `app/api/schemas.py`
defines `RecipeWriteRequest`/`IngredientIn` instead, mirroring `RecipeDraft` so `to_draft()` feeds
the same `create_recipe`/`update_recipe` functions the web CRUD layer uses.

**SPA token acquisition is deferred to Stage M4.** The React SPA will need its own way to obtain
write credentials (likely reusing the session cookie via a same-origin proxy, or a
user-facing "create API token" UI) — not yet decided.
