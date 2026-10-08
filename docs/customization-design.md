# Recipe customization — design brainstorm

Status: **proposal for review**. Nothing here is implemented yet. Settled
decisions are marked; everything else is a recommendation or an open question.

## Goals

1. **Amount edits.** Change one ingredient (e.g. chicken 2 lb → 1.5 lb). Every
   other ingredient stays put; macros update. A reset button restores the
   original.
2. **Substitutions.** Swap an ingredient (e.g. heavy cream → milk) from a
   dropdown. Amounts, instructions, and macros adjust. Only swaps that work
   *for how the ingredient is used in this recipe* are offered.
3. **Context-aware measurements.** How an amount is displayed (cups, spoons,
   weight, count) depends on the ingredient and the use case, not one global rule.

These layer on top of servings and **Make it your way** variations; they do not
replace them.

### Settled

- Nutrition data lives in a **shared ingredient catalog**, entered once and
  reused by every recipe.
- Substitutions are **universal** (a shared library), with suitability that
  depends on how the ingredient is used.
- Customizations **carry into the recipe cart and shopping list**.
- Unsuitable substitutions are **shown greyed out with a "?"** that explains why.
- A recipe **may veto** a universal substitution and add its own note to one.
- Weights under 1 lb show **both**: `0.67 lb (10.7 oz)`.
- Baking defaults to **volume / weight** together (`½ cup / 113 g`); fats such as
  butter use grams in baking rather than tbsp or sticks.
- Package-size rounding on the shopping list is **deferred to a later phase**.
- Volume / weight is the default **for baking only**; other recipes stay
  volume-first.
- Countable items follow the per-item rules in "Countable items".
- Steps may use optional `{ingredient-id}` placeholders so names update after a swap.
- Switching variation keeps customizations whose ingredient still exists and
  drops the rest with a notice.

## 1. Shared ingredient catalog

One file per ingredient family or a single `catalog/ingredients.yaml`. Each entry
holds what the rest of the system needs to reason about it:

```yaml
- id: heavy-cream
  name: heavy whipping cream
  aliases: [heavy cream, whipping cream]
  category: dairy
  form: liquid                # liquid | fat | powder | granular | chopped | whole | paste
  grams_per_cup: 238          # converts volume ⇄ weight for macros and ratios
  grams_each: null            # weight of one "count" (garlic clove ≈ 3 g)
  properties:                 # functional facts substitution rules can check
    fat_pct: 36
    whips: true
    heat_stable: true         # resists curdling at a boil
  measure: liquid             # display profile, see section 4
  nutrition_per_100g:
    calories_kcal: 340
    protein_g: 2.8
    carbohydrate_g: 2.7
    fat_g: 36
    status: estimated         # estimated | source_provided
    source: typical published values; verify against your brand
```

Recipe ingredients link to it with `ref:`; everything else in the recipe stays
as today. Unlinked ingredients still work, but they have no macros or
substitutions.

```yaml
- id: milk
  ref: whole-milk-ultrafiltered-2pct
  ingredient: ultra-filtered 2% milk
  quantity: 0.75
  unit: cup
  uses: [simmered]      # see section 2
```

Brand-specific label data (e.g. the bone broth's 45 kcal / 9 g protein per
8 fl oz) becomes its own catalog entry with `status: source_provided`.

### Macro calculation

- Per-serving macros = Σ(ingredient grams × nutrition per gram) ÷ servings.
  Volume and count amounts convert to grams via `grams_per_cup` / `grams_each`.
- Lines that can't be counted (no `ref`, unknown amount, "to taste", "enough to
  coat the pot") are **listed as excluded**, e.g. "Excludes olive oil (amount
  unknown)". The app never silently pretends a total is complete.
- If a recipe has hand-entered or label `nutrition` and is fully linked, show
  the recipe value and apply customization *deltas*: original + (new line −
  old line). Otherwise show the computed total, marked *estimated*.
- Changed lines show their effect: "Protein 47 g → 41 g (chicken 2 → 1.5 lb)".

## 2. Usage contexts: how an ingredient is used

The same ingredient behaves differently depending on its job. Each recipe
ingredient carries one or more `uses` from a fixed vocabulary:

| Use | Examples | What matters |
|---|---|---|
| `raw` / `cold` | dressings, garnish, cold sauces | flavor, texture; no heat chemistry |
| `simmered` | soups, pan sauces, braises, boiled grains | curdling, thickening, reduction |
| `seared` | browning meat or aromatics | Maillard browning, fat content, moisture |
| `hard-boil-reduce` | reductions, caramel | sugar/protein scorching, splitting |
| `whipped` | whipped cream, meringue | fat %, protein foam stability |
| `emulsion` | mayo, hollandaise, beurre blanc | fat/water balance, emulsifiers |
| `baked-structure` | cakes, breads, biscuits | gluten, leavening, moisture, sugar ratios |
| `leavening` | baking soda/powder, yeast | acid/base balance, timing |
| `binding` | eggs in meatballs, flax eggs | protein set, gel formation |
| `thickening` | roux flour, cornstarch | starch type, heat/acid tolerance, freezing |
| `fat-for-cooking` | sauté, frying | smoke point, flavor |
| `deglaze` | wine, stock into the pan | acidity, sugar, alcohol |
| `flambe` | brandy, rum | needs about 35%+ alcohol |
| `marinade` | acid/enzyme tenderizing | acid strength, contact time |
| `finishing` | added off heat | fresh flavor; heat not involved |

Recipes in the library today would be tagged like this: dumpling milk →
`simmered`, roux flour → `thickening`, chili Shaoxing wine → `deglaze`,
`simmered`.

## 3. Universal substitution library

A rule replaces one catalog ingredient with one or more others, at a ratio,
and rates how well it works **for each use**:

```yaml
- id: heavy-cream-to-milk-butter
  replaces: heavy-cream
  with:
    - {ref: whole-milk, ratio: 0.75}
    - {ref: butter, ratio: 0.25, preparation: melted}
  ratio_basis: volume          # volume | weight; converted via catalog density
  suitability:
    simmered: works
    baked-structure: works
    hard-boil-reduce: caution
    whipped: unsuitable
  reasons:
    whipped: Milk fat is too low to hold a whipped foam.
    hard-boil-reduce: Milk proteins curdle at a hard boil; keep it to a gentle simmer.
  instruction_notes:           # added to the recipe when this rule is applied
    simmered: Stir in off the boil and keep at a gentle simmer.
  effects: Thinner and less rich than cream.
  confidence: common-practice  # common-practice | tested | user-verified
```

**First rules to implement** (requested for the Wheat Beer Chili):

- **Ground beef → ground turkey:** works for `seared` and `simmered`; leaner, so
  it browns less and leaves less fond. Add a little oil and allow more time for
  browning.
- **Sour cream → nonfat Greek yogurt:** works for `raw` and `finishing`;
  caution for `simmered` (curdles if boiled). Tangier, much higher protein.
- **Mexican chocolate → dark chocolate (+ cinnamon and sugar):** works for
  `simmered`. Mexican chocolate is sweetened and spiced, so add cinnamon and
  sugar to match.

More examples, showing why one ratio doesn't fit every case:

- **Heavy cream → whole milk alone:** works for `simmered` with a thickener
  (caution: thinner), unsuitable for `whipped`, caution for `baked-structure`
  (less fat, so a drier crumb).
- **Heavy cream → coconut cream (chilled):** works for `whipped`, works for
  `simmered` (flavor change noted). Its suitability differs from milk's.
- **Shaoxing wine → dry sherry:** works 1:1 for `deglaze`, `simmered`,
  and `marinade`.
- **Shaoxing wine → stock + rice vinegar (non-alcoholic):** works for
  `simmered` and `deglaze`; caution for `marinade` (different tenderizing).
- **Brandy → anything under 35% alcohol:** unsuitable for `flambe` (it won't
  ignite). The rule checks the catalog's `alcohol_pct` property.
- **Butter → oil:** works for `fat-for-cooking` at about 0.75 of the volume;
  caution for `baked-structure` (no creaming, different texture); unsuitable
  where the butter must be solid (laminated dough, pie crust).
- **All-purpose flour → cornstarch** for `thickening`: ratio 0.5, add as a
  slurry. Cornstarch thins again if boiled long or frozen (noted as an effect).

### How the app chooses

1. For each linked ingredient, find rules whose `replaces` matches its `ref`.
2. Rate each rule by the ingredient's **worst** listed use (a line used for both
   `deglaze` and `simmered` takes the stricter rating).
3. Dropdown shows **works** options plainly and **caution** options with a
   warning. **Unsuitable** options appear greyed out and can't be selected; a
   "?" beside each one shows the reason (e.g. "Milk fat is too low to hold a
   whipped foam").
4. Applying a rule: replaces the line(s) with the substitute amounts (converted
   to sensible units), adds the instruction note to that ingredient and a
   "Substitutions" callout, and recalculates macros.
5. Instruction text: free-text steps can't safely be rewritten. Recommended:
   allow optional placeholders in steps (`Stir in the {milk}.`) so names update.
   Unmarked steps stay as written and the callout explains the swap.

One substitution per ingredient line; no chaining (substituting a substitute).

### Recipe vetoes and notes

A recipe can veto a universal rule for one ingredient line, or attach a note
that appears when the rule is chosen. Vetoed rules appear greyed out like
unsuitable ones, and the "?" shows the recipe's reason.

```yaml
- id: cream
  ref: heavy-cream
  uses: [whipped]
  substitutions:
    veto:
      coconut-cream-chilled: The topping must taste neutral for this dessert.
    notes:
      heavy-cream-to-milk-butter: Expect a looser filling.
```

Recipes can't define their own rules; any rule they reference must exist in
the shared library.

## 4. Measurement display profiles

The earlier "dry cups" question was really this: the right display depends on
the ingredient and use. Each catalog entry gets a `measure` profile:

| Profile | Examples | Cooking display | Notes |
|---|---|---|---|
| `liquid` | milk, broth, wine | cups + fl oz; spoons below ¼ cup | current behavior |
| `spice` | salt, spices, extracts | tsp/tbsp to ⅛ tsp; below that "pinch" | never cups |
| `leavening` | baking soda/powder | exact tsp fractions; no "≈" rounding | precision matters |
| `fat` | butter | tbsp; ½ cup and up also as sticks (`½ cup (1 stick)`) | baking: grams (`113 g / ½ cup`) |
| `chopped` | diced onion, carrot | cups to ¼ precision; optionally "≈ 1 medium onion" | forgiving, so coarse rounding |
| `shredded` | cheese | cups + oz | |
| `flour-sugar` | flour, sugar | cups/spoons to ⅛ | baking: volume / weight |
| `weight` | meat, blocks | lb with 2 decimals at 1 lb and up; below 1 lb show both: `0.67 lb (10.7 oz)` | |
| `whole` | eggs, cloves, cans, boxes | see "Countable items" below | |

Recipe context also matters. A recipe tagged `baking` shows **volume / weight**
by default (`2¼ cups / 281 g flour`), and fats there use grams. Forgiving
ingredients (veg, broth) get coarse rounding.

### Countable items

Scaling turns whole items into fractions, and the best display depends on the
item:

| Situation | Scaled amount | Recommended display | Why |
|---|---|---|---|
| Garlic, 3 cloves for 8 servings, cooking for 6 | 2.25 cloves | `≈ 2 cloves` | Forgiving; nobody measures ¼ clove. Round to the nearest whole. |
| Onion, 1 medium for 4 servings, cooking for 6 | 1.5 onions | `1½ medium onions (≈ 1½ cups diced)` | Halves are practical; the volume helps when onion sizes vary. |
| Eggs in baking, 2 eggs for 12 muffins, making 10 | 1.67 eggs | `≈ 1⅔ large eggs (83 g, beaten)` | Baking needs precision: beat 2 eggs and weigh out 83 g. |
| Eggs in a savory dish, 2 eggs for a 4-serving meatloaf, making 3 | 1.5 eggs | `1½ eggs` | Binding is forgiving; halves are enough. |
| Canned chickpeas, 1 can (15 oz) for 4 servings, making 3 | 0.75 can | `¾ can (≈ 11 oz drained wt)` | Partial cans are common; the weight tells you how much. |
| Biscuit mix, 1 box for 6 servings, making 5 | 0.83 box | `⅚ box (≈ 6.6 oz of a 7.95 oz box)` | Mix is dry and divisible; the weight makes the fraction measurable. Needs the box size. |

Each catalog entry chooses its counting rule: `round-whole` (garlic),
`halves` (onions, savory eggs), `weight-precise` (baking eggs; needs `grams_each`),
or `package-fraction` (cans, boxes; needs a package size). Without the data a
rule needs, the display falls back to a fraction with "≈".

## 5. Amount edits, reset, and state

- Each quantified line gets an editable amount. Edits are stored relative to
  the **original batch**, so changing servings afterwards scales them too.
- State lives in the URL, the same way servings does today:
  `?servings=4&amount.chicken=1.5&sub.milk=heavy-cream-to-milk-butter`.
  Pages are shareable and bookmarkable, and nothing is written to `personal/`.
- Modified lines are marked ("was 2 lb"). **Reset to original** clears amount
  edits and substitutions but keeps servings and the chosen variation; a
  per-line reset is also available.
- Variations: customizations apply on top of the selected variation.
  Recommended: switching variation keeps edits whose ingredient still exists
  and drops the rest, with a notice.
- Cart: an entry stores recipe + variation + servings + customizations. The
  same recipe with *different* customizations becomes a separate entry; the
  same customizations update servings (today's rule). Shopping generation
  applies them server-side using the same code path as the recipe page.

## 6. Data quality and trust

- Catalog nutrition I enter will be typical published values marked
  `estimated`; label data you supply is `source_provided`.
- Substitution rules I write are common culinary practice, marked
  `confidence: common-practice`. You can promote rules to `user-verified` after
  you've cooked them.
- Validation: every `ref` must exist; rules must reference catalog entries;
  every `uses` value must be in the vocabulary; ratios positive; suitability
  keys valid.

## 7. Proposed build order

1. Catalog schema, recipe `ref`/`uses`, validation, macro calculation with
   exclusions. Link the 3 existing recipes.
2. Amount edits + reset + macro deltas + cart/shopping carry-through.
3. Substitution library, dropdown, instruction notes, and an initial rule set
   covering the current recipes (dairy, wine/alcohol, fats, thickeners, broth).
4. Measurement profiles, including baking volume / weight and countable items.
5. **Later phase — purchasable units on the shopping list.** The recipe page
   shows what to measure; the shopping list would show what to *buy*: round up
   to packages (1 box, 1 lb pack, 1 bunch celery) with the amount needed in
   parentheses, e.g. `1 box (uses ⅚)`. Requires `package` data in the catalog
   (`package: {quantity: 32, unit: fl_oz}`) and a policy for leftovers from
   other recipes in the same list. Until then the shopping list shows the
   measured amounts.

## Open questions

None outstanding. Steps 1–3 are implemented: the ingredient library (now
USDA-backed), amount edits with reset and cart carry-through, and the
substitution library with ratings, vetoes, notes, and step placeholders.
Rules use `uses` ratings rather than ingredient `properties`; the flambé
alcohol check and measurement profiles (step 4) remain.
