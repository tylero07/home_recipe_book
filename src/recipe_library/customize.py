"""Per-ingredient amount edits and universal substitutions, applied without
changing the shared recipe. Amounts are for the recipe's original batch, so a
later servings change scales them like everything else."""
from .formatting import title_case
from .models import PLACEHOLDER, Ingredient, LibraryIngredient, Recipe, SubstitutionRule
from .nutrition import CUPS_PER_UNIT, GRAMS_PER_UNIT, effective_item, ingredient_grams

ORDER = {"works": 0, "caution": 1, "unsuitable": 2}


class CustomizationError(ValueError):
    pass


def rate(rule: SubstitutionRule, ingredient: Ingredient) -> dict:
    """The rule's rating for this line: its worst rating across the line's uses.

    A recipe veto makes it unsuitable. Uses the rule doesn't rate count as caution."""
    veto = ingredient.substitutions.veto.get(rule.id) if ingredient.substitutions else None
    if veto:
        return {"rating": "unsuitable", "reasons": [veto], "vetoed": True}
    uses = ingredient.uses or [None]
    ratings = []
    for use in uses:
        if use is None:
            ratings.append(("caution", "This ingredient's use in the recipe isn't recorded."))
        elif use not in rule.suitability:
            ratings.append(("caution", f"Not rated for {use.replace('-', ' ')}."))
        else:
            ratings.append((rule.suitability[use], rule.reasons.get(use)))
    worst = max(ORDER[r] for r, _ in ratings)
    rating = next(r for r in ORDER if ORDER[r] == worst)
    return {"rating": rating, "reasons": [why for r, why in ratings if r == rating and why], "vetoed": False}


def difference(rule: SubstitutionRule, ingredient: Ingredient, library: dict[str, LibraryIngredient]) -> str | None:
    """How calories, protein, and fat change per 100 g of the replaced ingredient (weight swaps)."""
    original = effective_item(ingredient, library)
    if rule.ratio_basis != "weight" or original is None or original.nutrition_per_100g is None:
        return None
    parts = []
    for field, label, unit in (("calories_kcal", "kcal", ""), ("protein_g", "protein", " g"), ("fat_g", "fat", " g")):
        before = getattr(original.nutrition_per_100g, field)
        after = [getattr(library[i.ref].nutrition_per_100g, field) if library[i.ref].nutrition_per_100g else None
                 for i in rule.with_]
        if before is None or None in after:
            continue
        change = sum(v * i.ratio for v, i in zip(after, rule.with_)) - before
        if abs(change) >= (5 if field == "calories_kcal" else 1):
            parts.append(f"{change:+.0f}{unit} {label}".replace("-", "−"))
    return ", ".join(parts) + " per 100 g" if parts else "About the same calories, protein, and fat"


def options(ingredient: Ingredient, rules: dict[str, SubstitutionRule],
            library: dict[str, LibraryIngredient] | None = None) -> list[dict]:
    """Every rule that replaces this line's library ingredient: best rating first, then by family."""
    found = [{"rule": rule, **rate(rule, ingredient),
              "difference": difference(rule, ingredient, library) if library else None}
             for rule in rules.values() if ingredient.ref and rule.replaces == ingredient.ref]
    return sorted(found, key=lambda o: (ORDER[o["rating"]], o["rule"].family or "~", o["rule"].title))


def _convert(line: Ingredient, value: float, item, rule: SubstitutionRule,
             library: dict[str, LibraryIngredient]) -> tuple[float, str]:
    """Substitute amount for one end of the original amount, in the most natural unit."""
    unit = line.unit
    same_kind = (rule.ratio_basis == "volume" and unit in CUPS_PER_UNIT) or \
                (rule.ratio_basis == "weight" and unit in GRAMS_PER_UNIT)
    if same_kind:
        return value * item.ratio, unit
    original = effective_item(line, library)
    grams, reason = ingredient_grams(line.model_copy(update={"quantity": value, "quantity_max": None}), original) \
        if original else (None, "not in the ingredient library")
    if grams is None:
        raise CustomizationError(f"Can't convert {line.ingredient} for this substitution: {reason}")
    substitute = library[item.ref]
    if rule.ratio_basis == "volume":
        if original.grams_per_cup is None:
            raise CustomizationError(f"Can't convert {line.ingredient} to a volume: no weight per cup")
        cups = grams / original.grams_per_cup * item.ratio
        return (cups / CUPS_PER_UNIT[unit], unit) if unit in CUPS_PER_UNIT else (cups, "cup")
    grams *= item.ratio
    if substitute.grams_per_cup:
        # Measure by volume when the substitute can be: cups here become spoons when small.
        cups = grams / substitute.grams_per_cup
        return (cups / CUPS_PER_UNIT[unit], unit) if unit in CUPS_PER_UNIT else (cups, "cup")
    return grams, "g"


def _substitute(line: Ingredient, rule: SubstitutionRule, library) -> list[Ingredient]:
    lines = []
    for number, item in enumerate(rule.with_, 1):
        quantity = unit = quantity_max = None
        if line.quantity is not None:
            quantity, unit = _convert(line, line.quantity, item, rule, library)
            if line.quantity_max is not None:
                quantity_max = _convert(line, line.quantity_max, item, rule, library)[0]
        lines.append(line.model_copy(update={
            "id": line.id if number == 1 else f"{line.id}-sub-{number}",
            "ingredient": item.ingredient, "ref": item.ref,
            "quantity": quantity, "quantity_max": quantity_max, "unit": unit,
            "preparation": item.preparation, "liquid": line.liquid and unit in CUPS_PER_UNIT,
            "substitutions": None, "product": None,
        }))
    return lines


def editable_ratio(rule: SubstitutionRule, line: Ingredient) -> float | None:
    """For a one-for-one swap in the same unit, how the shown amount maps back to the
    original line's amount. None when the swap changes units or splits into parts."""
    if len(rule.with_) != 1 or line.quantity is None:
        return None
    same_kind = (rule.ratio_basis == "volume" and line.unit in CUPS_PER_UNIT) or \
                (rule.ratio_basis == "weight" and line.unit in GRAMS_PER_UNIT)
    return rule.with_[0].ratio if same_kind else None


def customize(recipe: Recipe, amounts: dict[str, float], substitutions: dict[str, str],
              library: dict[str, LibraryIngredient], rules: dict[str, SubstitutionRule],
              products: dict[str, str] | None = None) -> tuple[Recipe, dict]:
    """Apply product choices, amount edits (original-batch units of the original line), then swaps.

    Returns the customized recipe and, per changed line ID, what changed. Choosing a
    product isn't a change: it only says which brand the recipe's ingredient is."""
    products = products or {}
    for line_id, product_id in products.items():
        line = next((l for l in recipe.ingredients if l.id == line_id), None)
        item = library.get(line.ref) if line and line.ref else None
        if line is None:
            raise CustomizationError(f"Unknown ingredient '{line_id}'")
        if item is None or item.product(product_id) is None:
            raise CustomizationError(f"'{product_id}' is not a product for {line.ingredient}")
    if products:
        recipe = recipe.model_copy(update={"ingredients": [
            line.model_copy(update={"product": products[line.id]}) if line.id in products else line
            for line in recipe.ingredients]})
    lines = {line.id: line for line in recipe.ingredients}
    changes: dict[str, dict] = {}
    for line_id, value in amounts.items():
        line = lines.get(line_id)
        if line is None:
            raise CustomizationError(f"Unknown ingredient '{line_id}'")
        if line.quantity is None:
            raise CustomizationError(f"{line.ingredient} has no amount to change")
        if not 0 < value < float("inf"):
            raise CustomizationError("Amounts must be positive numbers")
        changes[line_id] = {"original": line}
    for line_id, rule_id in substitutions.items():
        line, rule = lines.get(line_id), rules.get(rule_id)
        if line is None:
            raise CustomizationError(f"Unknown ingredient '{line_id}'")
        if rule is None or rule.replaces != line.ref:
            raise CustomizationError(f"'{rule_id}' is not a substitution for {line.ingredient}")
        rating = rate(rule, line)
        if rating["rating"] == "unsuitable":
            raise CustomizationError(f"{rule.title} isn't suitable here: {' '.join(rating['reasons'])}")
        changes.setdefault(line_id, {"original": line})["rule"] = rule
    if not changes:
        return _fill_placeholders(recipe, {}), {}

    ingredients, notes, names = [], list(recipe.notes), {}
    for line in recipe.ingredients:
        if line.id in amounts:
            line = line.model_copy(update={"quantity": amounts[line.id], "quantity_max": None})
        rule = changes.get(line.id, {}).get("rule")
        if rule is None:
            ingredients.append(line)
            continue
        replaced = _substitute(line, rule, library)
        ingredients += replaced
        names[line.id] = [item.ingredient for item in replaced]
        extra = [rule.instruction_notes[use] for use in dict.fromkeys(line.uses) if use in rule.instruction_notes]
        if line.substitutions and rule.id in line.substitutions.notes:
            extra.append(line.substitutions.notes[rule.id])
        if rule.effects:
            extra.append(rule.effects)
        notes.append(f"Swap — {rule.title} for {title_case(line.ingredient)}" + (": " + " ".join(extra) if extra else "."))
    # model_copy keeps the already-validated parts; substitute lines are built from validated lines.
    customized = recipe.model_copy(update={"ingredients": ingredients, "notes": notes})
    return _fill_placeholders(customized, names), changes


def _fill_placeholders(recipe: Recipe, swapped: dict[str, list[str]]) -> Recipe:
    """Replace {ingredient-id} in steps with that line's current name (both names for a split swap)."""
    names = {line.id: [line.ingredient] for line in recipe.ingredients}
    names.update(swapped)
    steps = [PLACEHOLDER.sub(lambda m: " and ".join(names.get(m[1], [m[0]])), step) for step in recipe.instructions]
    return recipe.model_copy(update={"instructions": steps})
