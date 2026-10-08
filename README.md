# Recipe Library

A shareable collection of YAML recipes, with separate personal cooking history,
pantry records, and meal plans.

The first foundation is implemented: strict recipe validation, a sample recipe,
one-level ingredient variations, optional macro nutrition, and non-destructive
personal-data initialization. SQLite FTS5 search, filters, personal ratings, and a web interface are also implemented.
Shopping-list generation remains the next milestone.

## Get started

Requires Python 3.11 or newer. Run from the repository root:

```sh
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -e '.[dev]'
recipe-library validate
recipe-library init-personal
python -m pytest
```

`python -m recipe_library` also works in place of `recipe-library`.
The sample is illustrative, not an independently tested cooking recipe.

## Add a recipe

Copy `recipes/lemon-chickpea-bowl.yaml` to a new `.yaml` or `.yml` file under
`recipes/` and change its ID, title, ingredients, and instructions. Nested
folders are supported. Run `recipe-library validate` before committing.
Errors include the filename and field; any invalid file makes validation fail.

- Use stable lowercase IDs with hyphens. Recipe IDs must be unique across files;
  ingredient and variation IDs must be unique within each recipe.
- Every recipe has a `category`: `breakfast`, `snacks-apps`, `lunch-dinner`, or
  `dessert`. `served` lists `hot`, `cold`, and/or `room-temperature`. Other
  descriptors go in `tags` (slugs such as `comfort-food`, shown as "Comfort Food").
- Supply positive numeric servings and quantities. A quantified ingredient needs
  both a quantity and unit; an unquantified ingredient needs both set to null.
  For a range such as 1–2 peppers, add `quantity_max`. Estimates use the middle
  of a range; shopping lists buy for the top.
- `group` puts an ingredient under a heading such as "Chili Spice Mix" or
  "Garnish"; lines without one form the main list.
- Units currently supported: `g`, `kg`, `mg`, `ml`, `l`, `tsp`, `tbsp`, `cup`,
  `oz`, `lb`, `count`. This vocabulary does not imply automatic conversions.
- Use `preparation` for distinctions such as dry, cooked, drained, or to taste.
- Unknown fields and duplicate YAML keys are rejected to catch mistakes.
- Nutrition is optional. State its basis (`per_serving` or `whole_recipe`) and
  status (`unknown`, `estimated`, or `source_provided`). Missing macros remain
  null; source-provided values require a source. Hand-entered nutrition takes
  precedence over the ingredient-library estimate below.
- Link an ingredient to the shared library with `ref: <library-id>` to get macro
  estimates. `uses` lists how the line is used (e.g. `[simmered]`,
  `[deglaze, simmered]`); it will drive substitution suitability.
- Variations override named ingredients and can add instruction notes. They do
  not add/remove ingredients or inherit nutrition from the base recipe. Supply
  variation-specific nutrition if known. An explicit null clears an override
  field; omitted fields preserve the base value.

The generated editor schemas are in `schemas/`. Regenerate after changing the models:

```sh
recipe-library schema > schemas/recipe.schema.json
recipe-library schema ingredients > schemas/ingredients.schema.json
```

## Ingredient library

`ingredients/*.yaml` holds shared ingredient entries reused by every recipe:
nutrition per 100 g, `grams_per_cup` for volume amounts, and `grams_each` for
counts. `recipe-library validate` checks the library and that every recipe
`ref` exists in it.

Recipe pages without hand-entered nutrition show a per-serving estimate summed
from linked ingredients. Lines that can't be counted are listed with the reason
(amount unknown, optional, not in the library, no nutrition data, or no
weight conversion). Macros a counted ingredient lacks are marked as excluding it.
Library values are approximate typical values marked `estimated` unless they
come from a label (`source_provided`); check labels for your brands.

Catalog-wide uniqueness and variation references are checked by the validation
command, beyond what JSON Schema can express.

## Personal data

`recipe-library init-personal` creates empty records under `personal/` and never
overwrites existing files. Both `personal/` and generated `data/` are ignored by
Git. Reading and validating shared recipes does not require personal files.
Ratings are the first personal records the app writes: the recipe page saves
recipe and leftover ratings (1–5) to `personal/ratings.yaml`, and only from pages
served by this library. Other personal records are still empty files; editing,
validation, and sync will follow with their features.

The CLI accepts an optional directory for `validate` and `init-personal`.
Paths are relative to your current directory. Custom personal-data locations
inside the repository must also be ignored before adding records.

## Architecture and next steps

The original discussion and proposal statuses are preserved in
[the project plan](docs/project-plan.md). Current implementation choices are
recorded in [the decision log](docs/decisions.md).

Next: shopping-list generation and a usable phone checklist.
Text export comes before a heavier offline app or Apple integration.

## Browse and search

```sh
source .venv/bin/activate
recipe-library serve
```

Open http://127.0.0.1:8000. Pick a category (Breakfast, Snacks & Apps, Lunch &
Dinner, Dessert) and search by title, ingredient, tag, or description. The
Filters panel narrows by total prep + cooking minutes, maximum calories and
minimum protein per serving, served hot/cold/room temperature, tags (all
selected must match), and minimum recipe or leftover rating. The results button
shows the updated count as filters change. Recipe pages include grouped
ingredients, steps, variations, source attribution, nutrition, and ratings.
Names and headings display in Title Case; recipe data is not changed.
The interface adapts to narrow screens, but phone/offline access is not implemented.

The server validates recipes and rebuilds `data/recipes.sqlite3` at startup.
After editing recipes, run `recipe-library index` or restart the server.
Invalid recipes leave the previous index intact. Search and browsing read
personal ratings only for the rating filters and display. The server listens on this computer only.

```sh
recipe-library index
recipe-library search chickpeas --tag quick --max-minutes 30
```

Search matches all entered words literally, with title matches weighted most
strongly. It does not implement fuzzy matching or advanced search operators.
Empty queries browse alphabetically; punctuation-only queries return no results.
Search indexes base recipes; select a variation on the recipe page.
The CLI displays up to 50 results; the browser pages through 12 at a time.

JSON endpoints: `/recipes` (q, category, tag and served (repeatable),
max_minutes, max_calories, min_protein, min_rating, min_leftovers, limit, offset),
`/recipes/{id}` (optional variation), and `/tags`. API documentation is at `/docs`.
The only write is the rating form, `POST /recipe/{id}/rating`.

If an editable installation is not found on macOS/Python 3.14 because its `.pth`
file is marked hidden, use `PYTHONPATH=src .venv/bin/python -m recipe_library serve`
from the repository root. The same prefix works for validation and tests.

## Shopping lists

Open `/shopping`, select recipes and versions, enter target servings, and generate
 a checklist. Exact ingredient names, units, and preparation notes must match to
combine; no mass/volume conversions are guessed. Unknown quantities remain
flagged, and incomplete recipes carry review warnings. Optional ingredients are
excluded unless selected.

“Already have” excludes an item from text export; “Got it” records a purchased
item. The snapshot and checks persist in this browser's local storage. Generating
another list replaces it and resets checks. Download the `.txt` checklist before
leaving home: offline app access, device sync, and Reminders are still future work.
`POST /shopping/generate` calculates a list without writing server-side personal
records or modifying shared recipes.

### Recipe cart

Use **Add to shopping list** on a recipe page to stage the displayed version and
servings without leaving the recipe. The expandable recipe cart appears on every
page and allows serving changes and removal. It persists in this browser and
updates across tabs. Adding the same recipe/version again updates its servings;
different versions are separate entries.

Generate the checklist from the cart on the shopping page. Changes to the cart or
optional-ingredient setting require regeneration before download, so an outdated
checklist cannot be exported accidentally. Text exports include the staged recipe
names and servings as well as the ingredient checklist.
