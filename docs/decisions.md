# Implementation decisions

## 2026-10-08 — Foundation

These are implementation choices made while starting the repository, not claims
about what was finalized in the earlier conversation.

- Python 3.11+; Pydantic 2 and PyYAML; standard-library argparse for the CLI.
- Shared YAML files are authoritative. A catalog load either validates all files
  successfully or reports errors without returning a partially valid catalog.
- Schema version 1, stable slug IDs, structured ingredient quantities and units,
  ordered instructions, optional nutrition, and one level of explicit variation
  overrides follow the plan's illustrative format.
- YAML duplicate keys, unsupported units, unknown fields, non-finite quantities,
  and invalid references fail validation. Numeric strings and booleans are not
  accepted as quantities. Unquantified ingredients have null quantity and unit.
- A variation retains the base recipe ID for association with personal records;
  callers must retain the selected variation ID separately. Resolved recipes
  contain no further variations and do not inherit base nutrition.
- Nutrition values are supplied manually; no ingredient database or automatic
  macro calculation is included.
- Personal setup creates only empty files, preserves existing records, and is
  independent of catalog loading. Personal persistence/validation will be built
  with its features rather than pretending the empty files implement them.
- The original plan is preserved in `project-plan.md` as a historical planning
  artifact. README describes the current implementation.

## Deferred choices

Phone checklist destination, offline support, Apple Shortcuts, private sync,
quantitative pantry tracking, API write boundaries, and automatic nutrition
remain open. None blocks validating shared recipes.

## 2026-10-08 — Search and browsing

- SQLite FTS5 stores a disposable validated recipe snapshot. Rebuilds use one
  transaction; invalid YAML is rejected before the database is opened.
- Preserve omitted versus explicitly null variation fields in indexed JSON.
- Plain search words are AND-combined, parameterized, and quoted for FTS. Titles
  rank above ingredients, tags, and descriptions. Tag filters are exact matches;
  time filters use prep plus cook minutes. Variation ingredients are not indexed.
- FastAPI provides GET endpoints and server-rendered Jinja pages with escaped
  recipe content. No JavaScript, external fonts, or frontend build is required.
- Startup refreshes the index; recipe edits require indexing or a restart.
- The server binds to loopback. Phone access, offline caching, editing, shopping,
  and personal-data writes remain separate milestones.

## 2026-10-08 — First cooking-history imports

- Added chicken and Cheddar Bay dumplings and turkey/Shaoxing chili from the
  available chat follow-ups. Chili attribution links to its supplied public source.
- Confirmed modifications and unconfirmed base-recipe defaults are labeled in
  ingredient notes. Both records carry `needs-review`; the dumpling method is
  incomplete because the original generated message was unavailable.
- No personal dates, health information, or chat transcripts enter shared recipes.
- Missing times are null, display as unknown, and are excluded by time filters.
- Provisional macro estimates are not imported as numeric nutrition.

## 2026-10-08 — Ingredient library and macro estimates

Step 1 of [the customization design](customization-design.md).

- Shared `ingredients/*.yaml` entries hold nutrition per 100 g plus
  `grams_per_cup` and `grams_each` conversions. A missing directory is an empty
  library; duplicate IDs fail validation.
- Recipe ingredients gain optional `ref` and `uses`. Unknown refs fail catalog
  validation, including refs in variation overrides. `uses` is a fixed vocabulary
  reserved for substitution suitability.
- Estimates are per serving and never presented as complete when they are not:
  uncountable lines are listed by reason, and macros missing from a counted
  ingredient name it. Hand-entered recipe nutrition still takes precedence.
- Library values are approximate typical values marked `estimated`; the bone
  broth uses the user-reported label as `source_provided`. Biscuit-mix box size
  and nutrition remain unknown, so it is not counted.

## 2026-10-08 — Categories, filters, ratings, and the chili rewrite

- `category` is required and limited to Breakfast, Snacks & Apps, Lunch & Dinner,
  and Dessert. Meal tags (lunch, dinner) were removed; other descriptors stay tags.
  `served` (hot, cold, room temperature) supports the hot/cold filter.
- The index stores category, served, and per-serving calories and protein (hand
  nutrition first, else the ingredient estimate; incomplete macros are left
  unset so filters never rely on an undercount). Tables are recreated on every
  rebuild because the index is disposable.
- Filters combine with AND; tags must all match, served values may match any.
  The browser shows a live count through the JSON API and still works without
  JavaScript.
- Ratings are personal (`personal/ratings.yaml`), whole numbers 1–5 for the
  recipe and its leftovers. This is the first personal write. The form is parsed
  with the standard library to avoid a new dependency, rejects cross-origin
  posts, and saves atomically.
- Display uses Title Case for names, tags, and headings; stored data keeps its
  original case. Measuring-spoon amounts always show fractions.
- Ingredients gain `group` (section headings) and `quantity_max` (ranges).
- The turkey/Shaoxing chili was replaced by the user-supplied Wheat Beer Chili.
  Steps are paraphrased with a source link rather than copied. Servings, times,
  beef lean percentage, beer bottle size, and chocolate disc weight are
  provisional. Turkey-for-beef, nonfat Greek yogurt-for-sour cream, and dark
  chocolate-for-Mexican chocolate are queued as the first substitution rules.

## 2026-10-08 — USDA nutrition, amount edits, and substitutions

Steps 2 and 3 of [the customization design](customization-design.md).

- Nutrition comes from USDA FoodData Central's public-domain SR Legacy and
  Foundation downloads, read straight from their zips into a disposable lookup
  database under ignored `data/usda/`. Library entries record the FDC ID they
  were copied from. Energy falls back to Atwater values and carbohydrate to
  "by summation" where Foundation foods lack the usual nutrient.
- 43 of 50 library entries now use USDA values. Proxies (poblano, cubanelle,
  chili flakes, wheat beer, biscuit mix) are labeled estimated; ultra-filtered
  milk stays on its label estimate because generic 2% milk has half the protein;
  the bone broth keeps the user's label; sumac has no USDA entry.
- Customizations live in the URL (`a.<line>` original-batch amounts, `s.<line>`
  rule IDs), so pages stay bookmarkable and nothing is written to `personal/`.
  The page form submits amounts as shown plus the servings they were shown at;
  the server converts them and redirects to the canonical URL.
- Order: variation, then amount edits, then swaps, then servings scaling.
  Edits that don't fit a version are dropped with a notice on the page; the
  shopping API rejects them instead.
- A line's rating for a rule is its worst across its `uses`; unrated uses count
  as caution; recipe vetoes make a rule unsuitable for that line.
- Swapped lines are editable only for one-for-one swaps in the same unit; other
  swaps scale from the original line's amount.
- Cart entries carry amounts and swaps; the same recipe with different
  customizations is a separate entry. Older saved carts load with none.

## 2026-10-08 — Substitution families, products, and not-counted reporting

- Substitution families expand to every ordered pair at load time
  (`<from>-to-<to>` IDs). The replacement's suitability overrides, reasons,
  cooking notes, and effects apply, since what changes is what goes into the pot.
  Ground meat (18 members), sour cream and yogurt (7), and cooking oils (3) yield
  348 rules alongside 3 one-off rules. All new meats and dairy are USDA-linked.
- Swap explanations include the per-100 g change in calories, protein, and fat
  for weight-based swaps, computed from the library rather than written by hand.
- Products: library entries can list brand/style products with their own
  nutrition and sizes. `requires_product` keeps an ingredient out of totals
  until one is chosen (wheat beer, Mexican chocolate) rather than guessing.
  Choices live in the URL (`p.<line>`), carry into the cart, and name the
  product on the shopping list.
- Product data came from label panels found on 2026-10-08: Blue Moon (retailer
  label), Bell's Oberon (brewery), Nestlé Abuelita (retailer label); Shock Top,
  Hoegaarden, Allagash, and Ibarra's serving weight are third-party or derived
  and marked estimated. The fairlife 2% and Cheddar Bay Biscuit Mix entries now
  use their labels (box confirmed at 11.36 oz).
- Filters bound unchosen products by what each adds at the recipe's amount, so a
  heavier tablet with fewer calories per gram still counts as the larger one.
- Not-counted lines are grouped by why; seasonings flagged `negligible` are
  listed as negligible rather than missing.

## 2026-10-08 — Chicken and dumplings rewrite

- The dumpling recipe was rebuilt from the full cooking conversation, replacing
  the partial reconstruction and its recovery notes. It records the cooked
  version: 2 lb chicken breast, bone broth, ultra-filtered 2% milk, the boxed
  Cheddar Bay mix with added cheddar, and no finishing butter.
- Vegetables use the source counts (1 onion, 3 carrots, 3 celery stalks) instead
  of the earlier estimated cup amounts. Thyme, rosemary, and bay leaves have no
  library entry and stay out of macro totals.
- The 4 tbsp of roux butter was never confirmed and is assumed used.
- No hand-entered nutrition. The conversation's rough 511 kcal / 47 g protein
  per serving guessed at the biscuit mix; the library estimate uses its label
  and comes out near 626 kcal / 50 g protein per serving.
- The `needs-review` tag was dropped since the method is now complete.
