# Architecture

## Source-of-truth model

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
                  │  Web UI · Importer · AI     │  ← DERIVED layers (removable)
                  └─────────────────────────────┘
```

## Layer responsibilities

| Layer | Owns | Notes |
|---|---|---|
| `$RECIPES_DIR/*.md` | Canonical content | Edited by humans. In dev: `./recipes/` (gitignored scratch). Frozen test corpus in `tests/fixtures/recipes/`. |
| `app/core/` | Schema, parsing, serialization, validation | The contract. Roundtrip is byte-stable. |
| `app/db/` | Derived SQLite tables + FTS5 | Wiped freely. `rebuild-index` recreates from scratch. |
| `app/web/` (Stage 3+) | HTTP, HTML rendering, forms | Reads from DB. Writes go through `core.serializer` then `db.sync.sync_one`. |
| `app/importer/` (Stage 5) | URL → draft Recipe | Returns a model; never writes directly. |
| `app/ai/` (Stage 7) | LLM provider, retrieval, grounding | Retrieves from DB; grounds answers on canonical Markdown. |
| `app/cli.py` | Operator commands | `validate`, `sync`, `rebuild-index`, `search`, `show`, `doctor`. |

## Architectural decisions

### Why ingredients live in YAML frontmatter

Ingredients need structure (meal planning, pantry awareness, shopping lists, scaling). Free-form Markdown lists are too fragile to parse reliably. Keeping the structured ingredient list in YAML frontmatter and the instructions/notes in the Markdown body gives us both: a machine-readable contract and a comfortable hand-editing surface.

### Why SQLite + FTS5 instead of an external search engine

Personal-scale (1–10k recipes). FTS5 is built into SQLite, requires no extra service, and is plenty fast at this scale. Replacing it later is straightforward because the retrieval layer (Stage 7) is behind a `Retriever` protocol.

### Why meal plans live only in SQLite (not as canonical Markdown)

Meal plans are personal scheduling state. They reference recipes but don't describe them. The corpus value is the recipe knowledge; meal plans are cheap to recreate and don't benefit from Git history. If a future need arises (e.g. exporting historical plans), we can re-emit them as `meal-plans/*.yaml` without restructuring anything.

### Why two visualization layers

- A **simple renderer** (`/r/{slug}`) over canonical Markdown produces pleasant, print-friendly reading pages. It uses no derived state beyond the file itself, so it works even if the DB is gone.
- The **advanced app** (library, CRUD, planner, AI) uses the DB mirror for fast querying. Both layers share the same templates and `core` schema.

### Why `ruamel.yaml` in roundtrip mode

Vanilla `PyYAML` collapses formatting, reorders keys, and re-quotes strings — turning every save into a noisy diff. `ruamel.yaml` in roundtrip mode preserves user formatting choices, so when the UI updates one field the rest of the file is untouched in `git diff`.

### Why ULIDs as recipe IDs

The slug can change (renaming a recipe). Filenames can move. We need a stable identifier that survives renames and lets us reliably upsert into the SQLite mirror. ULIDs are lexicographically sortable, URL-safe, and free of central allocation.
