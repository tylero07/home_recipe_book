# Recipe Library — Project Plan

Prepared October 8, 2026.

## Source and decision status

This plan consolidates the available [Recipe Search System conversation](chatgpt-conversation://6ac7b800-95c4-83e8-8264-a5224c327486) and the topics explicitly requested for this document.

**Source limitation:** The conversation reader returned five recent user turns, two assistant replies, and no continuation cursor. The supplied cached preview additionally contains the assistant’s response recommending simple export and deferring a heavy PWA. Earlier architecture messages were not available. This document covers all requested subjects, but cannot certify their original wording or whether the earlier discussion finalized them. Repository paths, schema fields, API details, and milestone boundaries below are concrete planning proposals, not a recovered transcript or an implemented system.

Status labels used throughout:

- **Confirmed requirement:** Explicitly stated by the user in the available conversation or current request.
- **Recommended direction:** Suggested by the assistant in the available conversation; not necessarily explicitly accepted by the user.
- **Reconstructed proposal:** Included to make a requested architecture topic actionable; earlier agreement cannot be verified.
- **Open:** Requires a choice or validation before implementation.

## 1. Purpose and user workflow

Build a shareable recipe library with a separate personal layer. Find recipes, choose what to cook, generate a shopping list before leaving home, review what is already available, and use a checklist on a phone at the store.

The user wants to avoid screenshots, switching between recipes, and having to log in away from home. Apple ecosystem integration would be welcome, but should not complicate getting version one running.

The assistant proposed three product pillars: recipes, meal planning, and shopping lists, with search and cooking history supporting them. Shopping lists are an explicit user need; the exact depth of meal planning remains a proposal.

## 2. Decision register

| Topic | Status | Direction and rationale |
|---|---|---|
| Shared recipes and separate personal state | Confirmed requirement | Other people cloning the repository should get their own dates and history, not the author’s. Modularity is the primary motivation; the user did not describe cooking dates as highly sensitive. |
| Ignored personal overlay | Recommended direction | Read public recipes alongside an ignored user-data directory. New clones begin with empty personal state. |
| Optional private sync | Recommended direction | A separate private repository or another optional store can back up personal data without mixing it into shared recipes. No provider was selected. |
| Shopping list prepared at home | Confirmed requirement | Collect missing ingredients before leaving and access them conveniently on a phone. |
| Checkbox experience | Confirmed requirement | Items should be checkable while shopping. A plain text export alone does not fully satisfy this experience. |
| Apple Reminders or other built-in Apple tools | Confirmed preference, conditional | Desirable only if setup stays simple; complex integration should not block version one. |
| Plain text export first | Latest recommended direction | Keep the list generator independent of its destination. Start with clean export, then enhance the checklist/mobile experience. |
| Offline-capable PWA | Earlier proposal, deferred in latest recommendation | Initially suggested for store use with poor reception; subsequently deprioritized to keep the first version simple. Offline convenience remains relevant, but a PWA is not a settled implementation. |
| YAML, Pydantic, Python, SQLite FTS5, FastAPI, read-only recipe UI | Requested architecture coverage; reconstructed proposal | These technologies are named in the current request. Their earlier decision status is unavailable. The sections below form a consistent proposed design. |
| Variations, macros, pantry, meal planning | Mixed | Pantry subtraction and serving selection were assistant proposals. Detailed variation, nutrition, and planning schemas remain reconstructed proposals. |

## 3. Proposed architecture

**Status: reconstructed proposal**, except for the separation of shared recipes and personal state described above.

```text
Shared recipe YAML files
        |
        v
Python loader -> Pydantic validation -> validated recipe objects
                                           |
                                           +-> rebuildable SQLite + FTS5 index
                                           |             |
Ignored personal overlay ------------------+-------------+
                                                         |
                                               Python service layer
                                                         |
                                    +--------------------+------------------+
                                    |                    |                  |
                                  CLI                 FastAPI         List generator
                                                         |                  |
                                                Read-only recipe UI    Text export
                                                                            |
                                                               Future checklist / Shortcut
```

YAML is the proposed source of truth for shared recipes. SQLite is a generated search/read model, so it can be rebuilt after recipe edits. Personal records live separately and are joined by stable recipe IDs. Neither a search-index rebuild nor a shared-recipe update should erase personal history.

Keep parsing, validation, search, serving calculations, and list generation in Python modules that can be called from either a command-line tool or FastAPI. This avoids tying domain behavior to a particular interface and lets export evolve independently.

### Read-only UI boundary

“Read-only” means the initial web interface does not edit the shared recipe library. Recipes are edited in YAML and reviewed through Git.

Checking a shopping item or recording a cooking date changes personal state. Those actions need a separate write mechanism if included in the web interface. Proposed options are browser-local storage or narrowly scoped personal-data endpoints. An entirely read-only API would instead require personal updates through a CLI or an external checklist app. This distinction must be resolved before claiming an integrated checklist is complete.

## 4. Proposed repository layout

Exact names are illustrative, not recovered decisions.

```text
recipe-library/
├── README.md
├── pyproject.toml
├── .gitignore
├── recipes/                    # Shared, versioned YAML recipes
│   └── example-recipe.yaml
├── schemas/                    # Optional exported JSON Schema
│   └── recipe.schema.json
├── src/recipe_library/
│   ├── models.py               # Pydantic recipe and personal-data models
│   ├── loader.py               # YAML loading and error reporting
│   ├── catalog.py              # Stable IDs and recipe lookup
│   ├── search.py               # SQLite index building and FTS5 queries
│   ├── variations.py           # Resolve a selected variation
│   ├── nutrition.py            # Macro display and serving calculations
│   ├── personal.py             # Overlay persistence and defaults
│   ├── shopping.py             # Scaling, aggregation, pantry review
│   ├── exports.py              # Text and future destination adapters
│   ├── cli.py
│   ├── api.py                  # FastAPI read endpoints
│   └── web/                    # Templates and static assets
├── examples/
│   └── personal/               # Synthetic examples only
├── data/                       # Ignored, rebuildable index/cache
├── personal/                   # Ignored, user-owned records
│   ├── cooking-history.yaml
│   ├── preferences.yaml
│   ├── pantry.yaml
│   ├── meal-plan.yaml
│   └── shopping-lists/
├── tests/
└── docs/
    └── project-plan.md
```

Proposed ignore rules:

```gitignore
/personal/
/data/
.env
.venv/
__pycache__/
```

Keep generated indexes and personal information out of the shared repository. Ignoring a path does not remove files already tracked by Git; verify tracked contents when setting this up. A fresh clone should create empty personal defaults and remain fully usable without sync credentials.

## 5. YAML recipe schema

**Status: reconstructed proposal.** Start with one self-contained file per recipe, a stable ID, structured ingredients, and ordered instructions. Avoid placing personal dates, ratings, or pantry state in recipe files.

The following is an illustrative data shape, not a tested recipe or verified nutritional analysis:

```yaml
schema_version: 1
id: lemon-chickpea-bowl
title: Lemon Chickpea Bowl
description: A simple grain bowl with chickpeas and lemon.
servings: 2
tags: [vegetarian, lunch, quick]
times:
  prep_minutes: 10
  cook_minutes: 15
source:
  title: Original recipe
  url: null
ingredients:
  - id: chickpeas
    ingredient: chickpeas
    quantity: 240
    unit: g
    preparation: cooked and drained
    optional: false
  - id: rice
    ingredient: rice
    quantity: 150
    unit: g
    preparation: dry
    optional: false
  - id: lemon-juice
    ingredient: lemon juice
    quantity: 30
    unit: ml
    optional: false
  - id: salt
    ingredient: salt
    quantity: null
    unit: null
    preparation: to taste
    optional: false
instructions:
  - Cook the rice.
  - Warm the chickpeas and combine with the rice.
  - Add lemon juice and season to taste.
nutrition:
  basis: per_serving
  status: unknown
  calories_kcal: null
  protein_g: null
  carbohydrate_g: null
  fat_g: null
  source: null
variations:
  - id: extra-chickpeas
    title: Extra chickpeas
    ingredient_overrides:
      chickpeas:
        quantity: 360
    instruction_notes:
      - Use the larger chickpea quantity; otherwise follow the base method.
    nutrition: null
notes: []
```

### Schema conventions to settle

- Keep recipe IDs stable when titles or file paths change, so personal references remain intact.
- Use ingredient IDs within a recipe for variation references. Ingredient normalization across recipes is a separate concern.
- Store numeric quantities separately from units and preparation notes. Explicitly represent unquantified ingredients such as “to taste.”
- Preserve source attribution when available; decide how externally sourced recipes may be shared before public publication.
- Define a small initial unit vocabulary and tag convention. Do not silently treat cooked and dry weights, or drained and undrained quantities, as equivalent.
- Version the schema so future migrations are deliberate.

## 6. Pydantic validation

**Status: reconstructed proposal.** Proposed models include `Recipe`, `Ingredient`, `RecipeTimes`, `Nutrition`, `Variation`, and separate models for history, pantry, and shopping lists.

Load YAML safely, then validate it before indexing or serving it. Report errors with the file path and relevant field. The proposed validation command should check the whole library and fail clearly when recipes are invalid.

Validation rules should cover:

- Required nonempty IDs, titles, ingredients, and instructions; positive servings.
- Positive quantities when specified; nonnegative times and nutrition values.
- Explicit nutrition basis and units; unknown values remain null rather than becoming zero.
- Supported schema versions and unit values.
- Unique recipe IDs across the catalog and ingredient/variation IDs within a recipe.
- Variation references that point to existing ingredients and yield a valid resolved recipe.
- Unknown fields reported as errors to catch spelling mistakes, with explicit extension fields only if needed.

Pydantic handles object-level validation; catalog-wide duplicate checks and reference integrity need a loading/validation step across files. Exported JSON Schema is optional editor assistance, not a substitute for these checks.

## 7. Python and SQLite FTS5 search

**Status: reconstructed proposal.** Use SQLite for a local generated catalog and FTS5 for full-text search. No external search service is proposed for the initial scope.

Index the recipe ID plus searchable text such as title, description, ingredient names, tags, and optionally instructions. Keep structured values such as time and servings in ordinary columns or related tables so filters do not depend on free-text matches.

Proposed search behavior:

- Search text across names and ingredients, with title matches weighted more strongly.
- Combine full-text queries with structured filters such as tags or maximum cooking time.
- Return recipe IDs, titles, and useful preview information; load the canonical recipe for details.
- Parameterize queries, define handling of FTS query syntax, and report unsupported queries clearly.
- Rebuild the index after recipe changes. Initially prefer a reliable full rebuild over incremental complexity.
- Verify FTS5 availability in the selected Python/SQLite runtime and provide a clear setup error if unavailable.

Exact ranking, tokenization, stemming, fuzzy matching, exclusions, and empty-query behavior are open design choices. Personal history can supplement results locally without becoming part of the shared index.

## 8. FastAPI and web interface

**Status: reconstructed proposal.** FastAPI exposes the validated catalog and search service. A small mobile-friendly interface supports search, filtering, and readable recipe pages. No frontend framework was confirmed.

Illustrative endpoints:

| Endpoint | Intended behavior |
|---|---|
| `GET /recipes` | Browse or search with query parameters and filters. |
| `GET /recipes/{recipe_id}` | Read one recipe, including variation options and available macros. |
| `GET /tags` | Read available tags. |

Shopping-list generation could begin as a CLI operation. If the UI calls a generation endpoint later, distinguish a calculation request from a persistent personal-data write. Final endpoint names, authentication, and deployment are open.

Start locally unless a different deployment is chosen. A server running on a home computer does not by itself make a list available away from home. Phone access, offline persistence, and export must be designed and tested as separate user-facing capabilities.

## 9. Personal overlay and optional sync

**Confirmed requirement:** A person cloning the shared library should have independent personal dates and records.

**Recommended direction:** An ignored folder contains cooking history and future preferences/pantry data. The app combines it with shared recipes at runtime. Personal state is optional; its absence must not prevent recipe browsing.

Proposed personal record categories:

- Cooking history: recipe ID, variation ID if used, date, and optional notes or servings.
- Preferences: favorites or ratings, if desired.
- Pantry: ingredient availability, optionally quantities and units later.
- Meal plans: selected recipes, variations, and target servings.
- Shopping lists: generated items, manual adjustments, and checked state.

Derive “last cooked” from cooking events where possible. Handle deleted or renamed recipe references without discarding the original history.

Optional sync could use a separate private repository or another user-selected store. It is not required for the shared application to work. Decide backup frequency, multi-device conflict handling, and recovery before treating sync as reliable. An ignored folder prevents accidental inclusion in normal Git changes; it is not encryption or a backup.

## 10. Recipe variations

**Status: reconstructed proposal.** Keep related alternatives discoverable from a base recipe. Choose a representation before building advanced editing or calculation logic.

The sample schema uses named variations with ingredient overrides and instruction notes. An alternative is separate complete recipe files linked by a parent ID. Overrides reduce duplication but require resolution rules; complete files are simpler to inspect but can drift apart.

Proposed initial scope is one base recipe plus one level of explicit variations. Resolve the variation before scaling ingredients, calculating macros, or creating a shopping list. Avoid recursive inheritance initially. If ingredients change and nutrition has not been recalculated or explicitly supplied, show variation nutrition as unknown rather than inheriting misleading base values.

## 11. Macro nutrition

**Status: reconstructed proposal.** Support calories, protein, carbohydrate, and fat with an explicit per-serving or whole-recipe basis and provenance. Optional values allow useful recipes to exist without nutrition data.

Start with manually supplied or source-provided estimates if nutrition belongs in version one. Automatic ingredient-level calculation requires a selected food data source, ingredient matching, quantity conversions, and treatment of cooking yield; it is a separate enhancement.

For unchanged ingredient proportions, scaling servings scales whole-recipe totals while leaving per-serving values unchanged. Ingredient substitutions or altered proportions require fresh calculation or an unknown/estimated label. Keep missing values distinct from zero, and avoid displaying greater precision than the source supports.

## 12. Pantry and shopping lists

**Confirmed requirement:** Prepare a list before leaving home and check off missing items on a phone.

**Recommended flow from the discussion:** Select one or more recipes, choose servings, combine ingredients, remove what is already in the pantry, and produce a clean list.

Proposed processing order:

1. Select each recipe and variation.
2. Resolve variation ingredients.
3. Scale quantities by requested servings divided by base servings.
4. Normalize ingredient identities and compatible units.
5. Aggregate compatible quantities while retaining source-recipe references.
6. Review pantry availability and manual adjustments.
7. Save or export a shopping-list snapshot.
8. Check off items without losing state when the chosen destination closes and reopens.

### Aggregation and pantry rules

Combine only quantities whose identity and units are compatible. Do not add cups to grams without ingredient-specific conversion data. Preserve distinctions such as fresh versus dried, or raw versus cooked. Keep unquantified amounts visible for review. Optional ingredients need an inclusion choice.

For a first pantry version, simple “already have this” exclusions are easier than inventory accounting. Quantitative subtraction can follow once pantry quantities and units are trustworthy. Do not automatically remove an entire required amount merely because an ingredient exists in the pantry.

Checked means obtained for this shopping trip; pantry availability means already available at home. Keep these concepts separate. Automatic pantry depletion after cooking was not decided.

## 13. Phone access, offline options, and Apple integration

The distinction between the user’s desired experience and the proposed implementation matters here.

| Option | Benefits | Remaining work / status |
|---|---|---|
| Simple text export | Small first step; portable; independent of UI or sync backend. | Latest assistant recommendation. Copyable text is not inherently a persistent interactive checklist. |
| Export to a phone app that already supports checklists | May deliver the desired shopping experience with little custom UI. | The actual transfer and checkbox behavior must be tested on the user’s phone. No particular workflow was verified. |
| Lightweight browser checklist | Direct checkbox interaction with a familiar web interface. | Needs local persistence and a way to reach/load it on the phone; offline reload is not automatic. |
| Offline PWA | Could cache a list and preserve checks away from home. | Earlier proposal, deferred in the latest recommendation. Requires offline lifecycle and device testing. |
| Optional hosted backend | Could enable remote access and multi-device sync. | Future possibility; adds hosting, access control, and sync decisions. |
| Apple Shortcuts → Reminders | Fits the user’s preferred ecosystem without building a dedicated Apple integration into the core. | Future proposal; exact actions, permissions, input format, and user setup have not been verified. |

### Export contract

Keep the generator destination-independent. Proposed output is one item per line with a readable amount, unit, ingredient, and essential preparation note. A human-facing version may add checklist markers; a machine-oriented version should avoid unnecessary decoration.

```text
240 g cooked, drained chickpeas
150 g dry rice
30 ml lemon juice
Salt, to taste
```

A later Shortcut could consume these lines and create individual reminders in a chosen list, subject to device testing. Do not promise that pasting multiline text into Reminders already creates separate checkable items.

### Minimum phone acceptance check

Before describing the shopping workflow as complete: generate at home, transfer/load on the phone, leave the home network, access the list without a fresh login, check an item, close and reopen the destination, and confirm the check persists. If offline operation is claimed, perform this with connectivity disabled.

The latest recommendation defers a heavy PWA; it does not resolve which minimal delivery method fulfills the checkbox requirement. Settle that explicitly during the shopping-list milestone.

## 14. Proposed phased milestones

These phases are planning recommendations, not prior commitments or time estimates.

| Phase | Deliverable | Completion evidence |
|---|---|---|
| 0 — Confirm boundaries | Settle the initial schema, variation representation, nutrition basis, and minimal phone checklist destination. | Short decision record identifies chosen and deferred options. |
| 1 — Recipe foundation | Repository skeleton, a small sample library, YAML loader, Pydantic models, validation command, ignored personal defaults. | Valid files load; malformed fields and duplicate IDs report actionable errors; a clean clone has no personal history. |
| 2 — Search and browsing | Rebuildable SQLite FTS5 index, Python search service, FastAPI read endpoints, read-only recipe pages. | Search and filters find expected sample recipes; index rebuilds preserve personal records; recipe editing remains file-based. |
| 3 — Personal workflow and shopping MVP | Minimal recipe/serving selection, basic cooking history if retained in scope, pantry review, ingredient aggregation, text export, and a chosen usable phone checklist path. | Quantities scale correctly; incompatible units stay separate; pantry decisions are reviewable; the phone acceptance check passes. |
| 4 — Refinements | Richer variations, macro display or calculation improvements, more useful meal planning, optional local checklist/PWA. | Chosen features have explicit behavior and appropriate focused checks; offline claims are demonstrated on the phone. |
| 5 — Optional integrations | Apple Shortcut/Reminders workflow, private backup/sync, and hosted access if needed. | Setup is documented; user data stays separate; applicable sync conflicts and restore paths are exercised. |

Nutrition fields and variation placeholders can be included in the foundation without committing to automated nutrition calculation or sophisticated inheritance. Shopping remains part of the proposed first useful release; optional integrations should not delay it.

The last assistant recommendation was to create the repository skeleton and Pydantic models next. Before implementation, settle only the choices that materially affect those models; avoid turning every future enhancement into a prerequisite.

## 15. Open questions

1. **Architecture confirmation:** Were YAML, Pydantic, SQLite FTS5, FastAPI, and a read-only recipe UI finalized in the unavailable earlier discussion? This document treats them as the requested design direction pending confirmation.
2. **Minimum useful release:** Does it require cooking history and dated meal planning, or is selecting recipes for a shopping trip sufficient initially?
3. **Phone destination:** Which simple approach actually provides persistent checkboxes without login at the store? Is a small Shortcut acceptable if it is easy to set up?
4. **Offline requirement:** Must the whole recipe library work offline, or only the current shopping list?
5. **Runtime:** Where will the local service run, and how will the phone access it before departure?
6. **Personal writes:** Will history/pantry edits happen through a CLI, local files, browser storage, or personal-data API endpoints?
7. **Variations:** Use explicit overrides or complete linked recipes? Which variation features are needed first?
8. **Nutrition:** Manual estimates first, or automatic calculation? Which source and serving basis should be used?
9. **Ingredients and units:** Which unit system and normalization vocabulary should the initial catalog support?
10. **Pantry:** Simple availability flags or quantitative inventory? Should any consumption ever be automatic?
11. **Sync:** Is one-device storage sufficient initially? If not, what store, conflict rules, and backup/restore behavior are acceptable?
12. **Shared content:** What attribution and publication rules should apply to imported recipes?
13. **Printable:** For freezer style recipes and day of can we print date prepped, macros, and name of
meal via formatted sticker/zebra printer style labels

## 16. Scope guardrails

- Preserve shareable recipe content separately from each person’s history and preferences.
- Keep the search index disposable and personal data durable.
- Keep list generation separate from web, text, and Apple destinations.
- Treat the read-only recipe UI and writable personal checklist as distinct capabilities.
- Do not equate text export with a complete checkbox experience or a mobile page with verified offline support.
- Record later decisions here as they are made; do not promote recommendations into historical agreements.

This is a planning artifact. No application, schema implementation, search index, phone integration, or sync system has been built or tested as part of this document.

