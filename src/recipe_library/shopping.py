"""Destination-independent serving scaling and conservative aggregation."""
import hashlib
from decimal import Decimal

from pydantic import Field

from .customize import customize
from .models import Identifier, Model, Positive
from .formatting import format_amount, title_case
from .variations import resolve_variation


class Selection(Model):
    recipe_id: Identifier
    servings: Positive
    variation: Identifier | None = None
    amounts: dict[Identifier, Positive] = Field(default_factory=dict)        # original-batch amounts
    substitutions: dict[Identifier, Identifier] = Field(default_factory=dict)  # line ID -> rule ID
    products: dict[Identifier, Identifier] = Field(default_factory=dict)       # line ID -> product ID


class ShoppingRequest(Model):
    selections: list[Selection] = Field(min_length=1, max_length=50)
    include_optional: bool = False


def generate_list(index, request: ShoppingRequest, library=None, rules=None) -> dict:
    grouped = {}
    warnings = []
    for selection in request.selections:
        recipe = index.get(selection.recipe_id)
        if recipe is None:
            raise ValueError(f"Recipe not found: {selection.recipe_id}")
        if selection.variation:
            recipe = resolve_variation(recipe, selection.variation)
        recipe = customize(recipe, selection.amounts, selection.substitutions, library or {}, rules or {},
                           selection.products)[0]
        if 'needs-review' in recipe.tags:
            warnings.append(f"{recipe.title}: incomplete or unconfirmed recipe details; review ingredient notes before shopping.")
        scale = Decimal(str(selection.servings)) / Decimal(str(recipe.servings))
        for ingredient in recipe.ingredients:
            if ingredient.optional and not request.include_optional:
                continue
            # Preparation remains part of identity: dry and cooked rice must not merge.
            entry = (library or {}).get(ingredient.ref) if ingredient.ref else None
            product = entry.product(ingredient.product) if entry and ingredient.product else None
            name = f"{title_case(ingredient.ingredient)} ({product.name})" if product else title_case(ingredient.ingredient)
            key = (name.casefold(), ingredient.unit,
                   (ingredient.preparation or '').strip().casefold(), ingredient.quantity is None, ingredient.liquid)
            if key not in grouped:
                grouped[key] = dict(id=hashlib.sha256(repr(key).encode()).hexdigest()[:20],
                    ingredient=name, unit=ingredient.unit, liquid=ingredient.liquid,
                    quantity=None if ingredient.quantity is None else Decimal(0),
                    preparation=ingredient.preparation, sources=[], from_range=False)
            item = grouped[key]
            if ingredient.quantity is not None:
                # Buy for the top of a range so there is enough either way.
                amount = ingredient.quantity_max if ingredient.quantity_max is not None else ingredient.quantity
                item['quantity'] += Decimal(str(amount)) * scale
                item['from_range'] |= ingredient.quantity_max is not None
            if recipe.title not in item['sources']:
                item['sources'].append(recipe.title)
    items = sorted(grouped.values(), key=lambda item: item['ingredient'].casefold())
    for item in items:
        item['quantity'] = format(item['quantity'].normalize(), 'f') if item['quantity'] is not None else None
        amount = format_amount(item["quantity"], item["unit"], item["liquid"])
        item['text'] = f"{amount} — {item['ingredient']}"
        if item['preparation']:
            item['text'] += f" ({item['preparation']})"
        if item.pop('from_range'):
            item['text'] += " (top of the recipe's range)"
    return dict(items=items, warnings=list(dict.fromkeys(warnings)))
