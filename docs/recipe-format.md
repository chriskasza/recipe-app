# Canonical recipe format

A recipe is a single UTF-8 Markdown file named `<slug>.md` with LF line endings. It may live directly
under `recipes/` or in any subdirectory (folders are organization-only; the slug, not the path, is the
recipe's identity). The filename stem must equal the `slug` and be unique across the whole tree.

```
---
<YAML frontmatter>
---

## Description
…

## Instructions
1. …

## Notes
…

## Substitutions
…

## Make-ahead
…
```

The body section headings are matched **case-insensitively**. Unknown headings are preserved verbatim and surface under `RecipeBody.extras`, so the parser never silently discards content.

## Frontmatter fields

| field | type | required | notes |
|---|---|---|---|
| `id` | string (ULID) | yes | Immutable. Generated once; never edited by tools or humans after creation. |
| `slug` | string | yes | `^[a-z0-9][a-z0-9-]{0,79}$`. Must equal the filename stem. |
| `title` | string | yes | |
| `summary` | string | no | One sentence. |
| `cuisine` | string | no | Free-form. |
| `meal_type` | list of string | no | Controlled vocab (`breakfast`, `lunch`, `dinner`, `snack`, …). Unknown values → warning. |
| `tags` | list of string | no | Free-form. |
| `dietary` | list of string | no | Controlled vocab (`vegan`, `vegetarian`, `gluten-free`, …). Unknown values → warning. |
| `prep_minutes` | integer ≥ 0 | no | |
| `cook_minutes` | integer ≥ 0 | no | |
| `total_minutes` | integer ≥ 0 | no | If all three time fields are present, `prep + cook == total` (warning if not). |
| `servings` | integer ≥ 0 | no | |
| `yield_note` | string | no | Free-form, e.g. `"1 loaf"` or `"about 24 cookies"`. |
| `source` | mapping | no | `{ url, attribution }`. |
| `equipment` | list of string | no | |
| `ingredients` | list of mapping | no | See below. |
| `nutrition` | mapping | no | Open mapping; common keys are `calories`, `protein_g`, `carbs_g`, `fat_g`, `fiber_g`, `sodium_mg`. |
| `images` | list of mapping | no | `[{ path, alt }]`. Paths are relative to `recipes/`. |
| `created_at` | datetime (ISO 8601) | yes | UTC, ends with `Z`. |
| `updated_at` | datetime (ISO 8601) | yes | UTC, ends with `Z`. |
| `archived` | boolean | yes | Defaults `false`. Archived recipes drop out of the library listing but keep their `/r/{slug}` URL. |
| `favorite` | boolean | yes | Defaults `false`. Surfaces the recipe in the "My recipes" view. |

### Ingredient entries

```yaml
ingredients:
  - name: white miso
    qty: 3
    unit: tbsp
    original: "3 Tbsp white miso"
  - name: scallion
    qty: 1
    unit: stalk
    prep: thinly sliced
    optional: true
    original: "1 scallion, thinly sliced (optional)"
```

| field | type | required | notes |
|---|---|---|---|
| `name` | string | yes | Canonical name. Lowercased for the SQLite ingredient index but preserved as authored in the file. |
| `qty` | number | no | Decimal allowed (e.g. `0.5`). |
| `unit` | string | no | Controlled vocab (`g`, `kg`, `oz`, `lb`, `tsp`, `tbsp`, `cup`, `ml`, `l`, `whole`, `slice`, `clove`, `pinch`, …). Unknown values → warning. |
| `prep` | string | no | "minced", "halved lengthwise", etc. |
| `optional` | boolean | no | Defaults `false`. |
| `original` | string | yes | The exact wording you'd want in a printed ingredient list. Preserves authorship. |

## Style conventions

These conventions exist so `parse → serialize` is byte-stable. The parser doesn't *require* them, but if you stray ruamel will normalize your file on next save:

- **Block style for `ingredients`** (multi-line entries with `name:`, `qty:`, etc. one per line). Flow style mappings (`{name: x, qty: 1}`) work but ruamel strips inner spaces on roundtrip — author them without inner spaces to keep diffs clean.
- **Flow style is fine for short, primitive lists** (`tags: [vegan, weeknight]`, `meal_type: [dinner, side]`).
- **Quote strings that contain `:`** to avoid YAML interpreting them as nested mappings. `summary: "Marcella-style sauce: butter, onion, tomatoes."` not `summary: Marcella-style sauce: butter, ...`.
- **UTC ISO timestamps ending with `Z`**: `2026-05-28T10:00:00Z`. The parser also accepts other offsets and naive timestamps (treated as UTC) but the serializer emits the Z form.

## Validation levels

- **Errors** block sync — the file is parsed but not written to SQLite, and `recipes validate` exits non-zero.
- **Warnings** are surfaced by `validate` but don't block. They include unknown vocabulary terms, time-math mismatches, suspicious quantities, and source URLs without an `http(s)` scheme.

## Roundtrip guarantee

For any file in the canonical style, `serialize(parse(file)) == file` byte-for-byte. This is enforced by `tests/test_parser_roundtrip.py` across the entire seed corpus and any file added to `recipes/`. If a future change to the serializer drifts, that test fails first.
