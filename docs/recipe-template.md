# Recipe template

A copy-me starting point for a new recipe. The full field reference (types, controlled vocab,
validation levels) lives in [`recipe-format.md`](recipe-format.md); the day-to-day workflow is in
[`managing-recipes.md`](managing-recipes.md).

## Two easy ways to create a recipe

- **Web UI** — click **New recipe**. It generates the `id` and timestamps and writes a
  canonical, byte-stable file for you.
- **`recipe-from-url` skill** — paste a URL; it fetches, maps fields, and writes the recipe
  straight to `recipes/<slug>.md`.

Both handle the machine fields automatically. Use the template below when you'd rather **author by
hand**.

## Authoring by hand

1. Copy the block below into `recipes/<your-slug>.md` (the filename stem **must** equal the `slug`).
2. Generate the required machine fields:
   - **`id`** — a ULID (stable identity that survives renames). For example:
     ```bash
     python -c "from ulid import ULID; print(ULID())"
     ```
     Every recipe needs its **own** id — don't reuse the placeholder.
   - **`created_at` / `updated_at`** — current UTC time, ending in `Z`:
     ```bash
     date -u +%Y-%m-%dT%H:%M:%SZ
     ```
3. Fill in the rest. Delete any optional fields you don't need, and the `# …` comments once you're
   done (ruamel preserves them if you keep them, but they add noise to diffs).
4. `recipes validate` to check it, then `recipes sync` (or just save in the UI).

### Style rules that keep diffs clean

- **Block style for `ingredients`** — one field per line, as shown. Flow-style mappings get their
  inner spaces stripped on save.
- **Flow style for short primitive lists** — `tags: [weeknight, vegan]`, `meal_type: [dinner]`.
- **Quote strings containing `:`** — `summary: "Sauce: butter, onion, tomato."`
- **UTC timestamps ending in `Z`**.

### The template

```markdown
---
# id — REQUIRED. A ULID; stable identity. Generate your own (see above); never reuse this one.
id: 00000000000000000000000000
# slug — REQUIRED. ^[a-z0-9][a-z0-9-]{0,79}$  and must equal the filename stem.
slug: my-recipe
title: My Recipe                          # REQUIRED.
summary: "One sentence; quote it if it contains a colon."   # optional
cuisine: italian                          # optional, free-form
meal_type: [dinner]                       # optional, controlled vocab
tags: [weeknight]                         # optional, free-form
dietary: [vegetarian]                     # optional, controlled vocab (vegan, gluten-free, …)
prep_minutes: 10                          # optional, integer ≥ 0
cook_minutes: 20                          # optional, integer ≥ 0
total_minutes: 30                         # optional; if all three present, prep + cook should == total
servings: 4                               # optional, integer ≥ 0
yield_note: "Serves 4 as a main"          # optional, free-form
source:                                   # optional
  url: https://example.com/recipe         #   optional
  attribution: "Adapted from …"           #   optional
equipment: [saucepan]                     # optional, short list → flow style
ingredients:                              # optional; BLOCK style (one field per line)
  - name: olive oil                       #   name: REQUIRED
    qty: 2                                #   qty: optional number (decimals ok)
    unit: tbsp                            #   unit: optional controlled vocab (g, tbsp, cup, clove, …)
    original: "2 Tbsp olive oil"          #   original: REQUIRED — exact wording for a printed list
  - name: garlic
    qty: 2
    unit: clove
    prep: minced                          #   prep: optional
    optional: true                        #   optional: defaults false
    original: "2 cloves garlic, minced (optional)"
nutrition:                                # optional, open mapping
  calories: 250
created_at: 2026-01-01T00:00:00Z          # REQUIRED, UTC, ends with Z
updated_at: 2026-01-01T00:00:00Z          # REQUIRED, UTC, ends with Z; bump on every edit
archived: false                           # REQUIRED; true hides it from the library but keeps the file
---

## Description
A sentence or two about the dish.

## Instructions
1. First step.
2. Second step.

## Notes
- Anything worth remembering.

## Substitutions
- Swap X for Y.

## Make-ahead
How to store and how far ahead it keeps.
```
