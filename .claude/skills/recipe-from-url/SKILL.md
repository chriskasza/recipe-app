---
name: recipe-from-url
description: Given a URL, verify the page contains a single meal recipe, extract its content, and write a validated draft at recipes/_drafts/<slug>.md following the project's canonical schema. Use whenever the user pastes a recipe link, says "import this recipe", "save this from <url>", "add <recipe-page> to my cookbook", "scrape this recipe", or otherwise asks to bring a web recipe into this repo — even if they don't explicitly mention "draft" or "import".
---

# Recipe from URL

## What this does

Given a URL like `https://example.com/grandmas-cookies`, this skill:

1. Fetches the page and confirms it's a single complete meal recipe (not a roundup, not a blog post, not a paywalled stub).
2. Extracts structured recipe data — preferring schema.org JSON-LD `Recipe` markup when present, falling back to the visible HTML otherwise.
3. Maps that data to the project's canonical recipe schema (`docs/recipe-format.md`).
4. Downloads the hero image to `recipes/images/<slug>.<ext>` and wires it into the frontmatter `images`.
5. Writes a draft to `recipes/_drafts/<slug>.md` via the project's canonical pipeline so the file gets a fresh ULID + UTC timestamps, validates clean, and is byte-stable on parse/serialize roundtrip.

This is the manual bridge until `recipes import-url <url>` (TODO.md Stage 5) is built. The draft lives under `_drafts/` so the user can review and edit before promoting it to the canonical `recipes/` directory.

## Why a script, not direct file writing

The project's source-of-truth rule (CLAUDE.md) is that all writes flow through the canonical pipeline: `Recipe model → serializer → Markdown`. Hand-rolled Markdown can drift from the parser's expectations and break `parse → serialize` byte-stability.

So this skill **always** writes through `scripts/build_draft.py`. That script generates the ULID, normalizes the slug, stamps timestamps, builds the Markdown text in canonical field order, parses + validates it, roundtrips through the serializer to confirm stability, and only then writes the file. Do not use the `Write` tool to produce recipe files in this skill.

## Workflow

### Step 1: Fetch the page

**Primary path — `curl`.** Fetch the raw HTML into the project `tmp/` dir (create it if missing):

```bash
curl -sL --compressed \
  -A 'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36' \
  '<url>' -o tmp/recipe-page.html
```

Curl is preferred over `WebFetch` here for two reasons:

- **It dodges UA-based blocking.** `WebFetch` sends a fixed bot user agent with no way to override it (its only parameters are `url` and `prompt`), so bot-protected sites reject it. Curl lets us present a browser user agent.
- **It preserves JSON-LD verbatim.** `WebFetch` converts the page to markdown with a small model, which routinely drops or mangles `<script type="application/ld+json">` blocks — exactly the structured data this skill wants. Raw HTML from curl keeps it intact.

Then `Read` `tmp/recipe-page.html` (or `grep` for the `application/ld+json` block) to inspect the content yourself.

**Fallback path — `WebFetch`.** If curl returns an HTTP error, an empty/near-empty body, a bot-challenge/CAPTCHA page, or HTML with no usable recipe content (a JS-rendered page that hydrates client-side), fall back to `WebFetch` with a prompt that returns BOTH (a) a yes/no recipe verdict with reasoning AND (b) the raw recipe content:

> "Examine this page. Answer two things:
> (1) Does it contain a single, complete meal recipe with both an ingredient list and step-by-step instructions? Reply 'RECIPE: yes' or 'RECIPE: no' and one short sentence of reasoning.
> (2) If yes: extract the recipe data. Prefer the JSON-LD `<script type=\"application/ld+json\">` block verbatim if present. Otherwise dump the recipe title, ingredient list, instructions, prep/cook/total time, yield, author, hero image URL, description, and any tips / notes / substitutions / make-ahead text. Be literal — don't summarize."

If both curl and WebFetch fail to yield usable content, **stop and tell the user** — name what happened (blocked, JS-only, paywalled) and link them back to the URL.

### Step 1b: Verify the URL points at a single complete recipe

Whichever fetch path succeeded, treat the page as a recipe only if:

- It clearly describes **one dish** (not "25 best chocolate chip cookies", not a navigation page).
- It has both an ingredient list AND numbered/step-by-step instructions visible (or in the JSON-LD).
- It's not behind a paywall stub (only the first paragraph available).

If any of those fails, **stop and tell the user why** — name the specific reason and link them back to the URL. Don't fabricate a draft from an inadequate source.

### Step 2: Map fields to the canonical schema

Read `docs/recipe-format.md` if you need a refresher on the schema. The mapping below covers the common case.

| Source | Canonical | Notes |
|---|---|---|
| JSON-LD `name` / page `<h1>` | `title` | Required. |
| JSON-LD `description` (one sentence) | `summary` | Longer descriptions go to the `## Description` body section instead. |
| JSON-LD `recipeCuisine` | `cuisine` | Free-form, lowercase. |
| JSON-LD `recipeCategory` / `keywords` | split: `meal_type` (controlled vocab) + `tags` (free-form) | |
| JSON-LD `suitableForDiet` | `dietary` | Map to controlled vocab. |
| ISO 8601 `prepTime` (e.g. `PT15M`) | `prep_minutes: 15` | Convert from duration. |
| ISO 8601 `cookTime` | `cook_minutes` | |
| ISO 8601 `totalTime` | `total_minutes` | If only one of prep/cook/total is given, populate only that field — don't infer the others. The validator only flags time-math when all three are present. |
| JSON-LD `recipeYield` (numeric) | `servings` | |
| JSON-LD `recipeYield` (e.g. `"1 loaf"`, `"24 cookies"`) | `yield_note` | |
| Page URL + JSON-LD `author.name` | `source: { url, attribution }` | Attribution is free-form, e.g. `"Sam Sifton, NYT Cooking, 2023"`. |
| `recipeIngredient` line (raw string) | one `ingredients[]` entry | See "Ingredient parsing" below. |
| `recipeInstructions` | `## Instructions` body section | Preserve numbered or bulleted structure. |
| Long-form `description` | `## Description` body section | |
| Tips / cook's notes | `## Notes` body section | |
| Substitution suggestions | `## Substitutions` body section | |
| Make-ahead / storage info | `## Make-ahead` body section | |
| JSON-LD `nutrition.*` | `nutrition.*` | Strip units from values ("220 kcal" → `220`). |
| JSON-LD `image` / hero `<img>` | download → `images[]` | Download the file (Step 3b) and reference it in `images`. See "Image handling" below. |

#### Controlled vocabularies

Unknown values become validator warnings (not errors). The user can extend, but you should map to existing values when reasonable.

- `meal_type`: `breakfast`, `brunch`, `lunch`, `dinner`, `snack`, `dessert`, `side`, `drink`, `sauce`, `base`
- `dietary`: `vegan`, `vegetarian`, `gluten-free`, `dairy-free`, `nut-free`, `low-carb`, `keto`, `paleo`, `pescatarian`, `halal`, `kosher`
- `unit`: `g`, `kg`, `mg`, `oz`, `lb`, `ml`, `l`, `tsp`, `tbsp`, `cup`, `fl_oz`, `pint`, `quart`, `gallon`, `whole`, `slice`, `clove`, `sprig`, `bunch`, `head`, `stalk`, `leaf`, `pinch`, `dash`, `can`, `package`, `jar`

#### Ingredient parsing

Each ingredient must include `name` (canonical short name) and `original` (the exact wording from the recipe). Try to also extract `qty`, `unit`, `prep`, `optional`.

Examples:

- `"3 Tbsp white miso"` → `{name: "white miso", qty: 3, unit: "tbsp", original: "3 Tbsp white miso"}`
- `"1 scallion, thinly sliced (optional)"` → `{name: "scallion", qty: 1, unit: "stalk", prep: "thinly sliced", optional: true, original: "1 scallion, thinly sliced (optional)"}`
- `"Salt and pepper, to taste"` → `{name: "salt and pepper", original: "Salt and pepper, to taste"}` — `qty`/`unit` left unset; don't invent.
- `"½ cup buttermilk"` → `{name: "buttermilk", qty: 0.5, unit: "cup", original: "½ cup buttermilk"}` — convert Unicode fractions to decimals in `qty` while preserving the original glyph in `original`.

When in doubt, leave the numeric/unit fields off and keep only `name` + `original`. The validator's unknown-unit warning is your signal to drop the field, not to invent a new unit.

### Step 3: Build the JSON payload

Write a single JSON object matching the script's payload schema (full reference below). Save it to the project's gitignored scratch dir, e.g. `tmp/recipe-payload.json` (relative to the repo root), and pass it to the script. Use the project `tmp/` rather than the system `/tmp` so reads/writes stay inside the workspace and don't trigger permission prompts. Create `tmp/` if it doesn't exist.

Skip any field you don't have data for — empty/null fields are dropped on output. **Don't fabricate**: if the page doesn't give a cuisine, don't guess one.

### Step 3b: Download the hero image

If the page exposes a hero image (JSON-LD `image`, an `og:image` meta tag, or the main recipe `<img>`), download it so the draft ships with a local copy instead of a fragile remote URL.

Name the file after the slug the draft will get — the normalized title, or the explicit `slug` you're passing for a non-ASCII title (so the filename and the draft stay in lockstep). Pick the extension from the image URL (`.jpg`, `.jpeg`, `.png`, `.webp`); default to `.jpg` if the URL has none. Download with curl and a browser user agent (CDNs hotlink-block bot agents), creating `recipes/images/` if needed:

```bash
curl -sL --compressed \
  -A 'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36' \
  --create-dirs '<hero-image-url>' -o recipes/images/<slug>.<ext>
```

`recipes/` is the bind-mounted volume, so a file written here on the host is visible to the container at `/app/recipes/images/<slug>.<ext>` immediately.

Then add it to the payload (path is **relative to `recipes/`**, so it's `images/<slug>.<ext>` — not `recipes/images/...`):

```json
"images": [{"path": "images/<slug>.<ext>", "alt": "<short description, e.g. the recipe title>"}]
```

Handle the unhappy paths:

- **No hero image on the page** → omit `images` entirely. Don't invent one.
- **Download fails** (403/404, HTML error page, zero bytes) → don't reference a file that isn't there. Omit `images`, and instead record the URL in `body.notes` as `Hero image (download failed): <url>` so the user can grab it manually. Verify the download actually produced a non-empty image (`test -s recipes/images/<slug>.<ext>`) before adding the `images` entry.

### Step 4: Run `scripts/build_draft.py`

Always run the script with the Docker image's Python — never the local `.venv`. The image is rebuilt after local changes, so its interpreter has the current `app.core.*` code and dependencies (`pydantic`, `ruamel.yaml`, `python-ulid`) installed exactly as deployed:

```bash
docker compose exec -T app python /app/.claude/skills/recipe-from-url/scripts/build_draft.py < tmp/recipe-payload.json
```

`-T` disables the TTY so the stdin redirect works. The payload stays on the host; the shell feeds it in. The script writes the draft to `/app/recipes/_drafts/` inside the container, which is the bind-mounted `./recipes/` volume, so the file appears on the host immediately. No `recipes sync` is needed — `_drafts/` is a review staging area, not part of the synced library.

The `app` service must be up (`docker compose up -d app`) before running this. If `docker compose exec` reports the container isn't running, start it and retry.

The script prints a JSON report to stdout. Read it:

- `{"status": "ok", "path": "...", "id": "...", "warnings": [...]}` → success. The `warnings` list contains any non-blocking validation issues (unknown vocab, time-math mismatch, etc.).
- `{"status": "error", "stage": "...", ...}` → failure. Stages are `json` (bad input), `build` (missing required field), `parse` (malformed YAML/body — usually a quoting bug in the payload), `validate` (schema error like an invalid slug or missing ingredient `original`), or `write` (draft already exists at that slug).

### Step 5: Report to the user

Tell them:

- Where the draft landed: `recipes/_drafts/<slug>.md`.
- Any warnings the script returned, in plain language ("flagged the unit 'wedge' as unknown — you may want to change it to 'whole' or leave as-is").
- The hero image: if downloaded, where it landed (`recipes/images/<slug>.<ext>`) and that it's already wired into the frontmatter `images`; if the download failed, that the URL is parked in `## Notes` for them to fetch manually.
- A reminder that the file is a draft — they should look it over and move it into `recipes/` when satisfied.

## JSON payload schema

The script accepts one JSON object. Only `title` and per-ingredient `name`+`original` are required.

```json
{
  "title": "Required string",
  "slug": "optional — auto-derived from title if omitted",
  "summary": "optional one-sentence string",
  "cuisine": "optional",
  "meal_type": ["dinner"],
  "tags": ["weeknight", "one-pot"],
  "dietary": ["vegan"],
  "prep_minutes": 15,
  "cook_minutes": 25,
  "total_minutes": 40,
  "servings": 4,
  "yield_note": "1 loaf",
  "source": {"url": "https://...", "attribution": "Author, Year"},
  "equipment": ["dutch oven", "fine-mesh sieve"],
  "ingredients": [
    {"name": "olive oil", "qty": 2, "unit": "tbsp", "original": "2 Tbsp olive oil"},
    {"name": "garlic", "qty": 3, "unit": "clove", "prep": "minced", "original": "3 garlic cloves, minced"},
    {"name": "fresh thyme", "optional": true, "original": "A few sprigs of fresh thyme (optional)"}
  ],
  "nutrition": {"calories": 320, "protein_g": 18, "carbs_g": 30, "fat_g": 12},
  "images": [{"path": "images/<slug>.jpg", "alt": "Recipe title"}],
  "body": {
    "description": "Optional long-form description (1-2 paragraphs).",
    "instructions": "1. First step.\n2. Second step.\n3. Third step.",
    "notes": "- Any cook's notes here.",
    "substitutions": "- Use tofu instead of chicken.",
    "make_ahead": "Keeps 3 days refrigerated."
  }
}
```

## Image handling

This skill downloads the hero image (Step 3b) so the draft carries a local copy rather than a remote URL that can rot or hotlink-block. The mechanics:

- **Location:** `recipes/images/<slug>.<ext>`, named to match the draft's slug. `recipes/` is the bind-mounted volume, so the host download is visible inside the container.
- **Frontmatter:** referenced via the `images` payload field as `{"path": "images/<slug>.<ext>", "alt": "..."}`. The `path` is relative to `recipes/` (per `docs/recipe-format.md`), so it's `images/<slug>.<ext>` — **not** `recipes/images/...`.
- **Only the hero image.** If the page has a gallery or step-by-step photos, grab just the main/hero image. Don't bulk-download every `<img>`.
- **Fallbacks:** if there's no hero image, omit `images`. If the download fails or yields a non-image (verify with `test -s`), omit `images` and park the URL in `body.notes` as `Hero image (download failed): <url>` so it isn't lost.

The image file is **not** committed (`recipes/` is gitignored dev scratch); it lives alongside the draft for local review.

## Edge cases

- **Multiple recipes on one page** (e.g. "3 variations on miso eggplant"): the schema is one file per recipe. Ask the user which variation to import, or whether to make multiple drafts (one URL → multiple script invocations with distinct slugs).
- **Recipe roundup / list article** (e.g. "25 best chocolate chip cookies"): refuse. Not a single recipe. Suggest the user pick one specific link from the roundup.
- **Recipe video / TikTok-style page** with no ingredient list or instructions in the HTML: refuse. Tell the user the page doesn't expose structured recipe content and they'd need to transcribe manually.
- **Paywall stub**: refuse with a note about the paywall. Don't fabricate the missing steps.
- **Existing draft with same slug**: the script errors with `stage: "write"`. Ask the user: overwrite (they delete the existing draft first), use a different slug (re-run with `"slug": "<custom>"` in the payload), or skip.
- **Ambiguous quantities** ("a handful", "a glug", "to taste"): leave `qty` and `unit` empty — keep only `name` + `original`. The original text is what gets shown in the printed list anyway.
- **Don't invent times**: if the page only gives a total time, populate only `total_minutes`. The validator's time-math warning only triggers when all three of prep/cook/total are set.
- **Don't invent nutrition**: nutrition values often come from the recipe author's calculator. If the page doesn't expose them, leave the `nutrition` field out entirely.
- **`created_at` / `updated_at`**: always now (UTC, set by the script). The source page's publication date belongs in `source.attribution`, not in these timestamps.

## Validation outcomes

The script distinguishes errors (block writes) from warnings (surface but allow). Common signals you'll see:

- `[warning] ingredient.unit.unknown: unknown unit 'X'` — the unit isn't in the controlled vocab. Either remap to a known unit or accept the warning if the user has a recurring custom unit.
- `[warning] dietary.unknown: unknown dietary flag 'X'` — same idea.
- `[warning] time.math: prep+cook (X) ≠ total (Y)` — the source page's own time math doesn't add up. Mention it; don't silently "fix" it.
- `[error] slug.invalid` / `[error] slug.mismatch` — slug derivation failed. Most often happens with non-ASCII titles where the slug becomes empty after ASCII-folding. Pass an explicit `"slug"` in the payload.
- `[error] ingredient.original.empty` or `ingredient.name.empty` — you forgot the required field on an ingredient. Re-check the source extraction.
