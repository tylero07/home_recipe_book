"""Estimate recipe macros from the shared ingredient library."""
from .models import Ingredient, LibraryIngredient, Recipe

MACROS = ("calories_kcal", "protein_g", "carbohydrate_g", "fat_g")
GRAMS_PER_UNIT = {"g": 1, "kg": 1000, "mg": 0.001, "oz": 28.349523125, "lb": 453.59237}
CUPS_PER_UNIT = {"cup": 1, "fl_oz": 1 / 8, "tbsp": 1 / 16, "tsp": 1 / 48,
                 "ml": 1 / 236.5882365, "l": 1000 / 236.5882365}


def ingredient_grams(ingredient: Ingredient, item: LibraryIngredient) -> tuple[float | None, str | None]:
    """Weight of a recipe line (the middle of a range), or None and the reason it cannot be converted."""
    quantity = ingredient.typical_quantity
    if ingredient.unit in GRAMS_PER_UNIT:
        return quantity * GRAMS_PER_UNIT[ingredient.unit], None
    if ingredient.unit in CUPS_PER_UNIT:
        if item.grams_per_cup is None:
            return None, "no weight per cup in the ingredient library"
        return quantity * CUPS_PER_UNIT[ingredient.unit] * item.grams_per_cup, None
    if item.grams_each is None:
        return None, "no weight per count in the ingredient library"
    return quantity * item.grams_each, None


def estimate_nutrition(recipe: Recipe, library: dict[str, LibraryIngredient]) -> dict | None:
    """Per-serving macros with every line that could not be counted listed by reason.

    Returns None when no line could be counted. A macro is listed in ``incomplete``
    with the counted ingredients that lack a value for it.
    """
    totals = dict.fromkeys(MACROS, 0.0)
    incomplete = {macro: [] for macro in MACROS}
    excluded, counted, statuses = [], [], set()
    for ingredient in recipe.ingredients:
        item = library.get(ingredient.ref) if ingredient.ref else None
        if ingredient.optional:
            reason = "optional"
        elif ingredient.quantity is None:
            reason = "amount unknown"
        elif item is None:
            reason = "not in the ingredient library"
        elif item.nutrition_per_100g is None:
            reason = "no nutrition data"
        else:
            grams, reason = ingredient_grams(ingredient, item)
        if reason:
            excluded.append({"ingredient": ingredient.ingredient, "reason": reason})
            continue
        nutrition = item.nutrition_per_100g
        statuses.add(nutrition.status)
        counted.append(ingredient.ingredient)
        for macro in MACROS:
            value = getattr(nutrition, macro)
            if value is None:
                incomplete[macro].append(ingredient.ingredient)
            else:
                totals[macro] += value * grams / 100
    if not counted:
        return None
    return {
        "basis": "per_serving",
        "status": "estimated" if "estimated" in statuses else "source_provided",
        "per_serving": {macro: totals[macro] / recipe.servings for macro in MACROS},
        "counted": counted,
        "excluded": excluded,
        "incomplete": {macro: names for macro, names in incomplete.items() if names},
    }


def per_serving_macros(recipe: Recipe, library: dict[str, LibraryIngredient]) -> dict[str, float]:
    """Known per-serving macro values: hand-entered nutrition first, else the estimate.
    Macros an estimate marks incomplete are omitted rather than understated."""
    nutrition = recipe.nutrition
    if nutrition and nutrition.status != "unknown":
        divisor = recipe.servings if nutrition.basis == "whole_recipe" else 1
        return {m: getattr(nutrition, m) / divisor for m in MACROS if getattr(nutrition, m) is not None}
    estimate = estimate_nutrition(recipe, library)
    if estimate is None:
        return {}
    return {m: v for m, v in estimate["per_serving"].items() if m not in estimate["incomplete"]}
