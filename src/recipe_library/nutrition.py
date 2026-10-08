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


def effective_item(ingredient: Ingredient, library: dict[str, LibraryIngredient]) -> LibraryIngredient | None:
    """The library entry for a line, with its chosen product's nutrition and sizes applied."""
    item = library.get(ingredient.ref) if ingredient.ref else None
    product = item.product(ingredient.product) if item else None
    if product is None:
        return item
    return item.model_copy(update={
        "nutrition_per_100g": product.nutrition_per_100g, "requires_product": False,
        "grams_per_cup": product.grams_per_cup or item.grams_per_cup,
        "grams_each": product.grams_each or item.grams_each,
    })


# Why a line isn't counted, in the order the page lists them.
EXCLUSION_KINDS = ("choice", "amount", "optional", "data", "negligible")


def estimate_nutrition(recipe: Recipe, library: dict[str, LibraryIngredient]) -> dict | None:
    """Per-serving macros with every line that could not be counted listed by reason.

    Returns None when no line could be counted. A macro is listed in ``incomplete``
    with the counted ingredients that lack a value for it; ``estimated`` names counted
    ingredients whose library values are estimates rather than USDA or label data.
    """
    totals = dict.fromkeys(MACROS, 0.0)
    incomplete = {macro: [] for macro in MACROS}
    excluded, counted, estimated = [], [], []
    for ingredient in recipe.ingredients:
        item = effective_item(ingredient, library)
        kind = None
        if ingredient.optional:
            reason, kind = "optional", "optional"
        elif item is not None and item.requires_product:
            reason, kind = "choose a product to count it", "choice"
        elif ingredient.quantity is None:
            reason, kind = "amount unknown", "amount"
        elif item is None:
            reason = "not in the ingredient library"
        elif item.nutrition_per_100g is None:
            reason = "no nutrition data"
        else:
            grams, reason = ingredient_grams(ingredient, item)
        if reason:
            if item is not None and item.negligible:
                kind = "negligible"  # Spices and seasonings: not worth counting either way.
            excluded.append({"id": ingredient.id, "ingredient": ingredient.ingredient, "reason": reason,
                             "kind": kind or "data"})
            continue
        nutrition = item.nutrition_per_100g
        counted.append(ingredient.ingredient)
        if nutrition.status == "estimated":
            estimated.append(ingredient.ingredient)
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
        "status": "estimated" if estimated else "source_provided",
        "estimated": estimated,
        "per_serving": {macro: totals[macro] / recipe.servings for macro in MACROS},
        "counted": counted,
        "excluded": excluded,
        "excluded_by_kind": {kind: [e for e in excluded if e["kind"] == kind]
                             for kind in EXCLUSION_KINDS if any(e["kind"] == kind for e in excluded)},
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
    if "choice" in estimate["excluded_by_kind"]:
        # Unchosen products: bound the filters safely. Calories assume the highest-calorie
        # product and protein the lowest-protein one, so filters never rely on an undercount.
        def pick(key, choose):
            lines = []
            for line in recipe.ingredients:
                item = library.get(line.ref) if line.ref else None
                if item is not None and item.requires_product and not line.product:
                    def amount(product, line=line):
                        # What this product adds at the line's amount: sizes differ by brand.
                        chosen = line.model_copy(update={"product": product.id})
                        grams = ingredient_grams(chosen, effective_item(chosen, library))[0] if line.quantity else None
                        return (grams or 0) * (getattr(product.nutrition_per_100g, key) or 0)
                    known = [p for p in item.products if getattr(p.nutrition_per_100g, key) is not None]
                    line = line.model_copy(update={"product": choose(known or item.products, key=amount).id})
                lines.append(line)
            bounded = estimate_nutrition(recipe.model_copy(update={"ingredients": lines}), library)
            return None if key in bounded["incomplete"] else bounded["per_serving"][key]
        values = {"calories_kcal": pick("calories_kcal", max), "protein_g": pick("protein_g", min)}
        return {m: v for m, v in values.items() if v is not None}
    return {m: v for m, v in estimate["per_serving"].items() if m not in estimate["incomplete"]}
