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
│  Gen.   │  │  ├─ REST/JSON API   (plan)│  │          │  │           │  │            │
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
| **Dynamic app** — REST/JSON API | Shared data contract for frontends | 🔜 planned |
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
| `app/api/` (planned) | REST/JSON contract | Reuses `app/db/queries.py` for reads and a shared write/service layer (extracted from `app/web/`) for writes. The data contract both frontends consume. |
| `ssg/` (planned) | Static HTML from the corpus | The "simple renderer." Reads files directly; no DB. |
| `web-spa/` (planned) | React SPA | Optional frontend; talks only to `app/api/`. |
| `app/importer/` | payload → Recipe file | `save.py` backs `recipes save-recipe`: renders a `RecipePayload` through the canonical pipeline and writes `<slug>.md` straight into the corpus. URL fetch/extraction still done by the `recipe-from-url` skill. |
| `app/ai/` (planned) | LLM provider, retrieval, grounding | Retrieves from DB; grounds answers on canonical Markdown. |
| `app/cli.py` | Operator commands | `validate`, `sync`, `rebuild-index`, `search`, `show`, `doctor`. |

## Architectural decisions

### Why ingredients live in YAML frontmatter

Ingredients need structure (meal planning, pantry awareness, shopping lists, scaling). Free-form Markdown lists are too fragile to parse reliably. Keeping the structured ingredient list in YAML frontmatter and the instructions/notes in the Markdown body gives us both: a machine-readable contract and a comfortable hand-editing surface.

### Why SQLite + FTS5 instead of an external search engine

Personal-scale (1–10k recipes). FTS5 is built into SQLite, requires no extra service, and is plenty fast at this scale. Replacing it later is straightforward because the retrieval layer (AI module) is behind a `Retriever` protocol.

### Why meal plans live only in SQLite (not as canonical Markdown)

Meal plans are personal scheduling state. They reference recipes but don't describe them. The corpus value is the recipe knowledge; meal plans are cheap to recreate and don't benefit from Git history. If a future need arises (e.g. exporting historical plans), we can re-emit them as `meal-plans/*.yaml` without restructuring anything.

### Why two frontends on one shared REST API

We keep **both** an HTMX/Jinja UI and a React SPA, and both consume a single REST/JSON API
(`app/api/`, planned).

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

### How modules are toggled at deploy time (planned mechanism)

Two coordinated switches let a deployment include only the modules it wants:

- **`pyproject.toml` optional-dependency groups** (`core`, `web`, `api`, `cli`, `ai`, …) keep heavy
  deps (FastAPI, the LLM client, …) out of a lean install. `core` carries only Pydantic + ruamel +
  ulid.
- **`docker-compose.yml` profiles** select which services run (e.g.
  `docker compose --profile web --profile api up`). The Dockerfile's entrypoint is parameterized so
  one image can run as the web app, the API, a CLI/worker, or the SSG build.

This mechanism is **not yet implemented** — today the image runs a single combined service. See
[`running.md`](running.md) for current vs. target usage and [`TODO.md`](../TODO.md)
for the enabling stage.
