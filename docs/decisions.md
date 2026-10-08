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
