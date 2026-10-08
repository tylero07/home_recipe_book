"""Resolve a single variation without mutating the shared recipe."""
from .models import Recipe


def resolve_variation(recipe: Recipe, variation_id: str) -> Recipe:
    variation = next((v for v in recipe.variations if v.id == variation_id), None)
    if variation is None:
        raise ValueError(f"recipe {recipe.id} has no variation {variation_id}")
    data = recipe.model_dump()
    for ingredient in data["ingredients"]:
        override = variation.ingredient_overrides.get(ingredient["id"])
        if override is not None:
            ingredient.update(override.model_dump(exclude_unset=True))
    data["title"] = f"{recipe.title} — {variation.title}"
    data["notes"] += variation.instruction_notes
    data["nutrition"] = variation.nutrition.model_dump() if variation.nutrition else None
    data["variations"] = []
    return Recipe.model_validate(data)
