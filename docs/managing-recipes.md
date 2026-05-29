# Managing your recipe library

Your recipe library is **just a folder of Markdown files**. That folder is the only thing that
matters — every other part of this project (the SQLite mirror, the web UI, search, the planned
static-site generator and AI) is a derived, rebuildable view of it. You can read, edit, back up,
and move your recipes with nothing but a text editor and `git`. The app is a convenience on top,
never a dependency.

This guide covers the base solution. For the exact field schema see
[`recipe-format.md`](recipe-format.md); for a copy-me starting point see
[`recipe-template.md`](recipe-template.md).

## The layout

- **One file per recipe**, named `<slug>.md` — e.g. `simple-tomato-sauce.md`.
- The **filename stem must equal the `slug`** in the frontmatter.
- Structured data (ingredients, times, tags) lives in the YAML frontmatter; prose lives in the
  Markdown body (`## Description`, `## Instructions`, `## Notes`, `## Substitutions`,
  `## Make-ahead`).

```
recipes/
├── simple-tomato-sauce.md
├── miso-glazed-eggplant.md
└── …
```

### Organizing with subdirectories

You can group recipes into folders however you like — by course, cuisine, season, whatever:

```
recipes/
├── breakfast/
│   └── buttermilk-pancakes.md
├── dinner/
│   ├── miso-glazed-eggplant.md
│   └── simple-tomato-sauce.md
└── baking/
    └── sourdough.md
```

The **folder is organization only**. A recipe's identity is its `id` (a ULID) and its public handle
is its `slug`; the path is just where the file happens to sit. Moving a recipe between folders does
**not** change its slug or its `/r/{slug}` URL. (Slugs must still be unique across the whole tree —
you can't have `dinner/pasta.md` and `lunch/pasta.md`.)

> ⚠️ **Current limitation.** The SQLite-backed app today discovers only **top-level** `recipes/*.md`
> — it does not yet recurse into subdirectories. Folders are safe for hand-reading and git right
> now, but the dynamic app (library, search, CRUD) will only pick up nested files once the
> *Hierarchical corpus support* stage lands (see [`../TODO.md`](../TODO.md)). Until then, keep files
> you want the app to index at the top level.

## Everyday tasks

### Add a recipe
1. Copy the block from [`recipe-template.md`](recipe-template.md) into `recipes/<your-slug>.md`.
2. Generate the `id` (a ULID) and the `created_at` / `updated_at` timestamps — the template shows
   the one-line commands. (Or just use **New recipe** in the web UI, which fills these in for you.)
3. `recipes validate` to check it, then `recipes sync` to update the mirror.

### Edit a recipe
Open the file, change what you need, and **bump `updated_at`** to the current UTC time. Then
`recipes sync`. Editing through the web UI does this for you and keeps the file byte-stable.

### Rename a recipe
- Changing the **title** only: edit `title`; the slug and URL stay the same.
- Changing the **slug**: rename the file *and* the `slug` field together (they must match). The
  `id` stays the same, so the recipe keeps its identity even though its URL changes.

### Archive a recipe
Set `archived: true`. The file stays in your library and at its `/r/{slug}` URL, but it drops out
of the main library listing. Set it back to `false` to restore it. (The web UI has Archive /
Unarchive buttons for this.)

### Delete a recipe
Delete the file. On the next `recipes sync` it's removed from the mirror too. Because the corpus is
the source of truth, that's all there is to it.

## Backup and history with git

```bash
cd recipes/          # or wherever your $RECIPES_DIR points
git init
git add .
git commit -m "My recipes"
git remote add origin <your-remote>
git push -u origin main
```

Backup is `git push`. History is `git log`. Diffs stay human-readable because writes go through a
roundtrip-stable serializer — editing one field touches only that field.

## How this relates to the app

- **`$RECIPES_DIR/**/*.md`** — canonical. The only thing you back up.
- **`data/` (SQLite)** — derived and disposable. Delete it any time; `recipes sync` (or
  `recipes rebuild-index`) reproduces it exactly from your files.
- **One-way writes.** The app never edits the database behind your files' backs — every change goes
  `Recipe → serialize → Markdown → sync`. Your files are always the truth.

See [`../GETTING-STARTED.md`](../GETTING-STARTED.md) to run the app over your library, and
[`architecture.md`](architecture.md) for the full module map.
