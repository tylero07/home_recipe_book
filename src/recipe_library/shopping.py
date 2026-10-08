"""Destination-independent serving scaling and conservative aggregation."""
import hashlib
from decimal import Decimal

from pydantic import Field

from .models import Identifier, Model, Positive
from .formatting import format_amount
from .variations import resolve_variation


class Selection(Model):
    recipe_id: Identifier
    servings: Positive
    variation: Identifier | None = None


class ShoppingRequest(Model):
    selections: list[Selection] = Field(min_length=1, max_length=50)
    include_optional: bool = False


def generate_list(index, request: ShoppingRequest) -> dict:
    grouped = {}
    warnings = []
    for selection in request.selections:
        recipe = index.get(selection.recipe_id)
        if recipe is None:
            raise ValueError(f"Recipe not found: {selection.recipe_id}")
        if selection.variation:
            recipe = resolve_variation(recipe, selection.variation)
        if 'needs-review' in recipe.tags:
            warnings.append(f"{recipe.title}: incomplete or unconfirmed recipe details; review ingredient notes before shopping.")
        scale = Decimal(str(selection.servings)) / Decimal(str(recipe.servings))
        for ingredient in recipe.ingredients:
            if ingredient.optional and not request.include_optional:
                continue
            # Preparation remains part of identity: dry and cooked rice must not merge.
            key = (ingredient.ingredient.strip().casefold(), ingredient.unit,
                   (ingredient.preparation or '').strip().casefold(), ingredient.quantity is None, ingredient.liquid)
            if key not in grouped:
                grouped[key] = dict(id=hashlib.sha256(repr(key).encode()).hexdigest()[:20],
                    ingredient=ingredient.ingredient, unit=ingredient.unit, liquid=ingredient.liquid,
                    quantity=None if ingredient.quantity is None else Decimal(0),
                    preparation=ingredient.preparation, sources=[])
            item = grouped[key]
            if ingredient.quantity is not None:
                item['quantity'] += Decimal(str(ingredient.quantity)) * scale
            if recipe.title not in item['sources']:
                item['sources'].append(recipe.title)
    items = sorted(grouped.values(), key=lambda item: item['ingredient'].casefold())
    for item in items:
        item['quantity'] = format(item['quantity'].normalize(), 'f') if item['quantity'] is not None else None
        amount = format_amount(item["quantity"], item["unit"], item["liquid"])
        item['text'] = f"{amount} — {item['ingredient']}"
        if item['preparation']:
            item['text'] += f" ({item['preparation']})"
    return dict(items=items, warnings=list(dict.fromkeys(warnings)))
