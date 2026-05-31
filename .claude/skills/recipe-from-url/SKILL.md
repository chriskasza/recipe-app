---
name: recipe-from-url
description: Given a URL, verify the page contains a single meal recipe, extract its content, and write it to recipes/<slug>.md following the project's canonical schema. Use whenever the user pastes a recipe link, says "import this recipe", "save this from <url>", "add <recipe-page> to my cookbook", "scrape this recipe", or otherwise asks to bring a web recipe into this repo — even if they don't explicitly mention "import".
---

# Recipe from URL

## What this does

Given a URL like `https://example.com/grandmas-cookies`, this skill:

1. Fetches the page and confirms it's a single complete meal recipe (not a roundup, not a blog post, not a paywalled stub).
2. Extracts structured recipe data — preferring schema.org JSON-LD `Recipe` markup when present, falling back to the visible HTML otherwise.
3. Maps that data to the project's canonical recipe schema (`docs/recipe-format.md`).
4. Downloads the hero image to `recipes/images/<slug>.<ext>` and wires it into the frontmatter `images`.
5. Writes the recipe to `recipes/<slug>.md` via the project's canonical pipeline so the file gets a fresh ULID + UTC timestamps, validates clean, and is byte-stable on parse/serialize roundtrip.

The intelligent half of `recipes import-url <url>` (TODO.md Stage 5) — fetching the page and extracting fields — is still done here by the agent; the mechanical write half now ships in the app as `recipes save-recipe`.

## Why a CLI command, not direct file writing

The project's source-of-truth rule (CLAUDE.md) is that all writes flow through the canonical pipeline: `Recipe model → serializer → Markdown`. Hand-rolled Markdown can drift from the parser's expectations and break `parse → serialize` byte-stability.

So this skill **always** writes through `recipes save-recipe` (the app's operator CLI, implemented in `app/importer/save.py`). That command generates the ULID, normalizes the slug, stamps timestamps, builds the Markdown text in canonical field order, parses + validates it, roundtrips through the serializer to confirm stability, and only then writes the file. Do not use the `Write` tool to produce recipe files in this skill.

## Workflow

### Python execution rule

**Always run Python through the container — never the host `python3`.** The host has no `.venv`. All Python work (HTML parsing, extraction scripts, save-recipe) runs via the container.

**Available libraries (this is the whole list — don't reach for anything else):** `curl_cffi`, `pydantic`, `ruamel.yaml`, `ulid`, plus the full Python standard library. The container has **no** `bs4`/BeautifulSoup, `lxml`, `requests`, `html5lib`, or `selectolax`. Do not write a script that imports them — it will `ImportError` and stall the run. Parse with the stdlib instead:

- **JSON-LD (the primary extraction path) needs no HTML parser at all** — pull the `<script type="application/ld+json">` blocks and `json.loads` them.
- **HTML fallback:** use stdlib `html.parser` (`HTMLParser`) or targeted `re`. That's enough for grabbing an `<h1>`, an `og:image`, or a recipe container's text.

**Run scripts as files, never as inline `python -c`.** Write the script to `tmp/` on the host (visible in the container at `/app/tmp/`, and `Write(tmp/*)` is pre-allowed) and invoke it as:

```bash
docker compose exec -T app python /app/tmp/script.py
```

Why files, not `-c`: a multi-line `python -c '...'` that contains a comment trips a Bash safety heuristic ("newline followed by `#` inside a quoted argument"), which forces a manual permission prompt **even though the command matches the allowlist** — defeating autonomous operation. Writing the script to a `tmp/*.py` file avoids the heuristic entirely and runs unprompted (`docker compose *` is allowlisted). Reserve inline `-c` for trivial single-line, comment-free probes (e.g. `python -c "import json,sys; print(len(sys.argv))"`); anything with a newline or a `#` goes in a file.

The HTML fetched in Step 1 is at `tmp/recipe-page.html` on the host = `/app/tmp/recipe-page.html` in the container.

### Step 1: Fetch the page

Fetch in **tiers**, escalating only when a tier fails. Each tier writes raw HTML to the project `tmp/` dir; after each, `Read` `tmp/recipe-page.html` (or `grep` for the `application/ld+json` block) to judge whether it's usable. "Usable" means real recipe HTML — not an HTTP error, not an empty/near-empty body, not a bot-challenge/CAPTCHA/"enable JavaScript" interstitial.

Why not `WebFetch` anywhere in this ladder: it sends a fixed bot user agent you can't override (so bot-protected sites reject it), and it converts the page to markdown with a small model that routinely drops or mangles `<script type="application/ld+json">` blocks — exactly the structured data this skill wants. The tiers below all preserve raw HTML and present a browser identity.

**Tier 1 — `curl`.** Cheapest. Presents a browser user agent over plain HTTP:

```bash
curl -sL --compressed \
  -A 'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36' \
  -w '\nHTTP %{http_code}, %{size_download} bytes\n' \
  '<url>' -o tmp/recipe-page.html
```

This clears UA-sniffing blocks. It does **not** clear bot walls that fingerprint the TLS/JA3 handshake (Cloudflare, PerimeterX, DataDome — e.g. food52.com), because curl's TLS signature doesn't look like a real browser's. For those you'll get a challenge/CAPTCHA page or a 403 → escalate.

**Tier 2 — `curl_cffi` (TLS impersonation).** `curl_cffi` replays a real Chrome TLS/JA3 fingerprint, so it sails past the fingerprint-based walls that block plain curl. It's bundled in the app image, so run it through the container's Python. Per the Python execution rule, write the fetch script to a file rather than inline `-c`. `Write` `tmp/fetch.py` with:

```python
import sys
from curl_cffi import requests
r = requests.get(sys.argv[1], impersonate="chrome", timeout=30)
sys.stderr.write(f"HTTP {r.status_code}\n")
open("/app/tmp/recipe-page.html", "w").write(r.text)
```

Then run it (`tmp/` is mounted at `/app/tmp/` in the container, so the script and its output both land there):

```bash
docker compose exec -T app python /app/tmp/fetch.py '<url>'
```

This assumes the `app` service is already up. If `docker compose exec` reports the container isn't running, **stop and tell the user** to start it (`docker compose up -d app`) — don't start it yourself. If this returns a challenge page or 403, the wall is checking something curl_cffi can't fake (a real session cookie, a solved JS challenge) → escalate to the human.

**Tier 3 — ask the human to grab it from a real browser.** When both automated tiers are blocked, the user's own browser is already past the wall (it solved the JS challenge / holds the session cookie). Ask them to open the URL, open DevTools (F12) → Console, and run this snippet, which copies every JSON-LD block to their clipboard:

```js
copy([...document.querySelectorAll('script[type="application/ld+json"]')].map(s => s.textContent).join('\n---\n'))
```

Ask them to paste the result back into the chat. That JSON-LD is the same structured data Tier 1/2 would have yielded — proceed to Step 2 with it.

If the clipboard comes back empty (some sites render the recipe only in HTML, no JSON-LD), ask them to run this fallback instead and paste the output — then extract fields from the visible text:

```js
copy(document.querySelector('main, article, [itemtype*="Recipe"]')?.innerText ?? document.body.innerText)
```

If all three tiers fail (the human reports a paywall stub, no recipe content, or declines), **stop and tell the user** — name what happened (blocked, JS-only, paywalled) and link them back to the URL. Don't fabricate a recipe from an inadequate source.

### Step 1b: Verify the URL points at a single complete recipe

Whichever fetch path succeeded, treat the page as a recipe only if:

- It clearly describes **one dish** (not "25 best chocolate chip cookies", not a navigation page).
- It has both an ingredient list AND numbered/step-by-step instructions visible (or in the JSON-LD).
- It's not behind a paywall stub (only the first paragraph available).

If any of those fails, **stop and tell the user why** — name the specific reason and link them back to the URL. Don't fabricate a recipe from an inadequate source.

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

Write a single JSON object matching the command's payload schema (full reference below). Save it to `tmp/recipe-payload.json` (repo-root `tmp/`, which is mounted at `/app/tmp/` in the container).

Use the `Write` tool — but **always `Read` `tmp/recipe-payload.json` first** (even if the file doesn't exist; an error is fine). The `Write` tool requires a prior `Read` of any pre-existing file and will fail without it.

Then pass it to the command via stdin.

Skip any field you don't have data for — empty/null fields are dropped on output. **Don't fabricate**: if the page doesn't give a cuisine, don't guess one.

### Step 3b: Download the hero image

If the page exposes a hero image (JSON-LD `image`, an `og:image` meta tag, or the main recipe `<img>`), download it so the recipe ships with a local copy instead of a fragile remote URL.

Name the file after the slug the recipe will get — the normalized title, or the explicit `slug` you're passing for a non-ASCII title (so the filename and the recipe stay in lockstep). Pick the extension from the image URL (`.jpg`, `.jpeg`, `.png`, `.webp`); default to `.jpg` if the URL has none. Download with curl and a browser user agent (CDNs hotlink-block bot agents). `recipes/images/` already exists — don't `mkdir` it; the `--create-dirs` flag below is a harmless no-op safety net, not a cue to run a separate directory-creation command:

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

### Step 4: Run `recipes save-recipe`

Always run inside the Docker container — never the local `.venv`. The image is rebuilt after local changes, so its `recipes` CLI has the current `app.*` code and dependencies (`pydantic`, `ruamel.yaml`, `python-ulid`) installed exactly as deployed. Pass `--json` so the command emits the machine-readable report (without it, you get a human-friendly summary instead):

```bash
docker compose exec -T app recipes save-recipe --json < tmp/recipe-payload.json
```

`-T` disables the TTY so the stdin redirect works. The payload stays on the host; the shell feeds it in over stdin. The command writes straight into the corpus at `/app/recipes/<slug>.md` (bind-mounted `recipes/` on the host) — no draft staging, no `mv`. Then sync so the library picks it up:

```bash
docker compose exec app recipes sync
```

(If the `recipes` entry point isn't on PATH in the image, fall back to `docker compose exec -T app python -m app.cli save-recipe --json`.)

This assumes the `app` service is already up. If `docker compose exec` reports the container isn't running, **stop and tell the user** to start it (`docker compose up -d app`) — don't start it yourself.

With `--json` the command prints a JSON report to stdout. Read it:

- `{"status": "ok", "path": "...", "id": "...", "warnings": [...]}` → success. The `warnings` list contains any non-blocking validation issues (unknown vocab, time-math mismatch, etc.).
- `{"status": "error", "stage": "...", ...}` → failure. Stages are `json` (bad input), `build` (missing required field), `parse` (malformed YAML/body — usually a quoting bug in the payload), `validate` (schema error like an invalid slug or missing ingredient `original`), or `write` (a recipe already exists at that slug).

### Step 5: Report to the user

Tell them:

- Where the recipe landed: `recipes/<slug>.md`.
- Any warnings the command returned, in plain language ("flagged the unit 'wedge' as unknown — you may want to change it to 'whole' or leave as-is").
- The hero image: if downloaded, where it landed (`recipes/images/<slug>.<ext>`) and that it's already wired into the frontmatter `images`; if the download failed, that the URL is parked in `## Notes` for them to fetch manually.

## JSON payload schema

The command accepts one JSON object. Only `title` and per-ingredient `name`+`original` are required.

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

This skill downloads the hero image (Step 3b) so the recipe carries a local copy rather than a remote URL that can rot or hotlink-block. The mechanics:

- **Location:** `recipes/images/<slug>.<ext>`, named to match the recipe's slug. `recipes/` is the bind-mounted volume, so the host download is visible inside the container.
- **Frontmatter:** referenced via the `images` payload field as `{"path": "images/<slug>.<ext>", "alt": "..."}`. The `path` is relative to `recipes/` (per `docs/recipe-format.md`), so it's `images/<slug>.<ext>` — **not** `recipes/images/...`.
- **Only the hero image.** If the page has a gallery or step-by-step photos, grab just the main/hero image. Don't bulk-download every `<img>`.
- **Fallbacks:** if there's no hero image, omit `images`. If the download fails or yields a non-image (verify with `test -s`), omit `images` and park the URL in `body.notes` as `Hero image (download failed): <url>` so it isn't lost.

The image file is **not** committed (`recipes/` is gitignored dev scratch); it lives alongside the recipe file for local review.

## Edge cases

- **Multiple recipes on one page** (e.g. "3 variations on miso eggplant"): the schema is one file per recipe. Ask the user which variation to import, or whether to save multiple recipes (one URL → multiple `save-recipe` runs with distinct slugs).
- **Recipe roundup / list article** (e.g. "25 best chocolate chip cookies"): refuse. Not a single recipe. Suggest the user pick one specific link from the roundup.
- **Recipe video / TikTok-style page** with no ingredient list or instructions in the HTML: refuse. Tell the user the page doesn't expose structured recipe content and they'd need to transcribe manually.
- **Paywall stub**: refuse with a note about the paywall. Don't fabricate the missing steps.
- **Existing recipe with same slug**: the command errors with `stage: "write"`. Ask the user: overwrite (they delete the existing file first), use a different slug (re-run with `"slug": "<custom>"` in the payload), or skip.
- **Ambiguous quantities** ("a handful", "a glug", "to taste"): leave `qty` and `unit` empty — keep only `name` + `original`. The original text is what gets shown in the printed list anyway.
- **Don't invent times**: if the page only gives a total time, populate only `total_minutes`. The validator's time-math warning only triggers when all three of prep/cook/total are set.
- **Don't invent nutrition**: nutrition values often come from the recipe author's calculator. If the page doesn't expose them, leave the `nutrition` field out entirely.
- **`created_at` / `updated_at`**: always now (UTC, set by the command). The source page's publication date belongs in `source.attribution`, not in these timestamps.

## Validation outcomes

The command distinguishes errors (block writes) from warnings (surface but allow). Common signals you'll see:

- `[warning] ingredient.unit.unknown: unknown unit 'X'` — the unit isn't in the controlled vocab. Either remap to a known unit or accept the warning if the user has a recurring custom unit.
- `[warning] dietary.unknown: unknown dietary flag 'X'` — same idea.
- `[warning] time.math: prep+cook (X) ≠ total (Y)` — the source page's own time math doesn't add up. Mention it; don't silently "fix" it.
- `[error] slug.invalid` / `[error] slug.mismatch` — slug derivation failed. Most often happens with non-ASCII titles where the slug becomes empty after ASCII-folding. Pass an explicit `"slug"` in the payload.
- `[error] ingredient.original.empty` or `ingredient.name.empty` — you forgot the required field on an ingredient. Re-check the source extraction.
