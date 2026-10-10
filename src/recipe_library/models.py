"""Version-one recipe format. Personal state does not belong in these models."""
import re
from typing import Annotated, Literal, Self

from pydantic import BaseModel, ConfigDict, Field, HttpUrl, StringConstraints, model_validator

Text = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)]
Identifier = Annotated[str, StringConstraints(pattern=r"^[a-z0-9]+(?:-[a-z0-9]+)*$")]
Positive = Annotated[float, Field(gt=0, allow_inf_nan=False, strict=True)]
Nonnegative = Annotated[float, Field(ge=0, allow_inf_nan=False, strict=True)]
Unit = Literal["g", "kg", "mg", "ml", "l", "tsp", "tbsp", "cup", "oz", "lb", "count", "fl_oz"]
# How an ingredient line is used; substitution suitability depends on it.
Use = Literal[
    "raw", "finishing", "simmered", "hard-boil-reduce", "seared", "fat-for-cooking", "deglaze",
    "flambe", "marinade", "whipped", "emulsion", "baked-structure", "leavening", "binding", "thickening",
]
Category = Literal["breakfast", "snacks-apps", "lunch-dinner", "dessert"]
CATEGORY_LABELS = {"breakfast": "Breakfast", "snacks-apps": "Snacks & Apps",
                   "lunch-dinner": "Lunch & Dinner", "dessert": "Dessert"}
Served = Literal["hot", "cold", "room-temperature"]
Suitability = Literal["works", "caution", "unsuitable"]
DEFAULT_SEARING_FAT = (1.0, "tbsp")  # Starting amount for a searing-fat line that gives none
PLACEHOLDER = re.compile(r"\{([a-z0-9]+(?:-[a-z0-9]+)*)\}")


class Model(BaseModel):
    model_config = ConfigDict(extra="forbid", validate_default=True)


class RecipeTimes(Model):
    prep_minutes: Nonnegative | None = None
    cook_minutes: Nonnegative | None = None


class Source(Model):
    title: Text
    url: HttpUrl | None = None


class IngredientSubstitutions(Model):
    """Per-line adjustments to the universal substitution library."""
    veto: dict[Identifier, Text] = Field(default_factory=dict)   # rule ID -> why it can't be used here
    notes: dict[Identifier, Text] = Field(default_factory=dict)  # rule ID -> extra note when chosen


def _unique_uses(uses):
    if uses is not None and len(uses) != len(set(uses)):
        raise ValueError("uses must not repeat")
    return uses


class Ingredient(Model):
    id: Identifier
    ingredient: Text
    ref: Identifier | None = None
    uses: list[Use] = Field(default_factory=list)
    group: Text | None = None  # Section heading, e.g. "Chili Spice Mix"; null is the main list.
    quantity: Positive | None = None
    quantity_max: Positive | None = None  # Upper end of a range such as 1–2 peppers.
    unit: Unit | None = None
    preparation: Text | None = None
    liquid: bool = Field(default=False, strict=True)
    optional: bool = Field(default=False, strict=True)
    substitutions: IngredientSubstitutions | None = None
    product: Identifier | None = None  # A specific product listed for the library ingredient

    @model_validator(mode="after")
    def quantity_has_unit(self) -> Self:
        if (self.quantity is None) != (self.unit is None):
            raise ValueError("quantity and unit must both be supplied, or both null")
        if self.quantity_max is not None and (self.quantity is None or self.quantity_max <= self.quantity):
            raise ValueError("quantity_max must be greater than quantity")
        _unique_uses(self.uses)
        return self

    @model_validator(mode="after")
    def default_searing_fat(self) -> Self:
        """Searing fat with no amount starts at 1 tbsp, so it can be edited and counted.
        Frying oil and other cooking fats without an amount stay uncounted."""
        if self.quantity is None and {"fat-for-cooking", "seared"} <= set(self.uses):
            self.quantity, self.unit = DEFAULT_SEARING_FAT
            self.preparation = f"{self.preparation}, adjust as needed" if self.preparation else "adjust as needed"
        return self

    @property
    def typical_quantity(self) -> float | None:
        """Midpoint of a range, used for estimates."""
        if self.quantity is None or self.quantity_max is None:
            return self.quantity
        return (self.quantity + self.quantity_max) / 2


class Nutrition(Model):
    basis: Literal["per_serving", "whole_recipe"]
    status: Literal["unknown", "estimated", "source_provided"] = "unknown"
    calories_kcal: Nonnegative | None = None
    protein_g: Nonnegative | None = None
    carbohydrate_g: Nonnegative | None = None
    fat_g: Nonnegative | None = None
    source: Text | None = None

    @model_validator(mode="after")
    def status_matches_values(self) -> Self:
        values = (self.calories_kcal, self.protein_g, self.carbohydrate_g, self.fat_g)
        if self.status == "unknown" and any(v is not None for v in values):
            raise ValueError("unknown nutrition must have null values")
        if self.status != "unknown" and all(v is None for v in values):
            raise ValueError("known nutrition requires at least one value")
        if self.status == "source_provided" and self.source is None:
            raise ValueError("source_provided nutrition requires a source")
        return self


class IngredientOverride(Model):
    ingredient: Text | None = None
    ref: Identifier | None = None
    uses: list[Use] | None = None
    group: Text | None = None
    quantity: Positive | None = None
    quantity_max: Positive | None = None
    unit: Unit | None = None
    preparation: Text | None = None
    liquid: bool | None = Field(default=None, strict=True)
    optional: bool | None = Field(default=None, strict=True)
    product: Identifier | None = None

    @model_validator(mode="after")
    def nonempty_override(self) -> Self:
        if not self.model_fields_set:
            raise ValueError("an override must change at least one field")
        _unique_uses(self.uses)
        return self


class Variation(Model):
    id: Identifier
    title: Text
    ingredient_overrides: dict[Identifier, IngredientOverride] = Field(default_factory=dict)
    instruction_notes: list[Text] = Field(default_factory=list)
    nutrition: Nutrition | None = None


class Recipe(Model):
    schema_version: Literal[1]
    id: Identifier
    title: Text
    description: Text | None = None
    category: Category
    served: list[Served] = Field(default_factory=list)
    servings: Positive
    tags: list[Text] = Field(default_factory=list)
    times: RecipeTimes = Field(default_factory=RecipeTimes)
    source: Source | None = None
    ingredients: list[Ingredient] = Field(min_length=1)
    instructions: list[Text] = Field(min_length=1)
    nutrition: Nutrition | None = None
    variations: list[Variation] = Field(default_factory=list)
    notes: list[Text] = Field(default_factory=list)

    @model_validator(mode="before")
    @classmethod
    def strict_version(cls, data):
        if isinstance(data, dict) and type(data.get("schema_version")) is not int:
            raise ValueError("schema_version must be an integer")
        return data

    @model_validator(mode="after")
    def check_references(self) -> Self:
        for label, items in (("ingredient", self.ingredients), ("variation", self.variations)):
            ids = [item.id for item in items]
            if len(ids) != len(set(ids)):
                raise ValueError(f"duplicate {label} IDs")
        ingredients = {item.id: item for item in self.ingredients}
        for step in self.instructions:
            for ingredient_id in PLACEHOLDER.findall(step):
                if ingredient_id not in ingredients:
                    raise ValueError(f"instruction placeholder {{{ingredient_id}}} names no ingredient")
        for variation in self.variations:
            for ingredient_id, override in variation.ingredient_overrides.items():
                if ingredient_id not in ingredients:
                    raise ValueError(f"variation {variation.id}: unknown ingredient {ingredient_id}")
                try:
                    Ingredient.model_validate({
                        **ingredients[ingredient_id].model_dump(),
                        **override.model_dump(exclude_unset=True),
                    })
                except ValueError as exc:
                    raise ValueError(f"variation {variation.id}, ingredient {ingredient_id}: {exc}") from exc
        return self


class IngredientNutrition(Model):
    """Macros per 100 g of the ingredient as measured in recipes."""
    status: Literal["estimated", "source_provided"]
    calories_kcal: Nonnegative | None = None
    protein_g: Nonnegative | None = None
    carbohydrate_g: Nonnegative | None = None
    fat_g: Nonnegative | None = None
    source: Text | None = None

    @model_validator(mode="after")
    def has_values(self) -> Self:
        if all(v is None for v in (self.calories_kcal, self.protein_g, self.carbohydrate_g, self.fat_g)):
            raise ValueError("nutrition requires at least one value")
        if self.status == "source_provided" and self.source is None:
            raise ValueError("source_provided nutrition requires a source")
        return self


class UsdaLink(Model):
    """The USDA FoodData Central food the nutrition values were copied from."""
    fdc_id: Annotated[int, Field(gt=0, strict=True)]
    dataset: Literal["SR Legacy", "Foundation"]
    description: Text


class Product(Model):
    """A specific brand or style whose nutrition (and sizes) differ from the generic entry."""
    id: Identifier
    name: Text
    nutrition_per_100g: IngredientNutrition
    grams_per_cup: Positive | None = None   # Falls back to the ingredient's
    grams_each: Positive | None = None      # e.g. one tablet of this brand
    notes: list[Text] = Field(default_factory=list)


class LibraryIngredient(Model):
    """A shared ingredient entry, reused by every recipe that references it."""
    id: Identifier
    name: Text
    aliases: list[Text] = Field(default_factory=list)
    category: Text | None = None
    usda: UsdaLink | None = None
    grams_per_cup: Positive | None = None
    grams_each: Positive | None = None
    nutrition_per_100g: IngredientNutrition | None = None
    # Too little is used to matter (salt, spices); listed as negligible when not counted.
    negligible: bool = Field(default=False, strict=True)
    products: list[Product] = Field(default_factory=list)
    # Products vary too much for a generic value: not counted until one is chosen.
    requires_product: bool = Field(default=False, strict=True)
    notes: list[Text] = Field(default_factory=list)

    @model_validator(mode="after")
    def products_valid(self) -> Self:
        ids = [p.id for p in self.products]
        if len(ids) != len(set(ids)):
            raise ValueError("duplicate product IDs")
        if self.requires_product and not self.products:
            raise ValueError("requires_product needs at least one product")
        return self

    def product(self, product_id: str | None) -> "Product | None":
        return next((p for p in self.products if p.id == product_id), None)


class IngredientFile(Model):
    schema_version: Literal[1]
    ingredients: list[LibraryIngredient] = Field(min_length=1)

    @model_validator(mode="before")
    @classmethod
    def strict_version(cls, data):
        if isinstance(data, dict) and type(data.get("schema_version")) is not int:
            raise ValueError("schema_version must be an integer")
        return data


class SubstituteItem(Model):
    ref: Identifier
    ingredient: Text  # Name shown in the recipe, e.g. "ground turkey"
    ratio: Positive   # Amount relative to the replaced ingredient, by the rule's ratio_basis
    preparation: Text | None = None


class SubstitutionRule(Model):
    """A universal swap, rated per use: what works in a sauce may fail when whipped."""
    model_config = ConfigDict(extra="forbid", validate_default=True, populate_by_name=True)

    id: Identifier
    title: Text
    family: Text | None = None  # Set on rules generated from a family, for grouping
    replaces: Identifier
    with_: list[SubstituteItem] = Field(alias="with", min_length=1)
    ratio_basis: Literal["volume", "weight"]
    suitability: dict[Use, Suitability] = Field(min_length=1)
    reasons: dict[Use, Text] = Field(default_factory=dict)
    instruction_notes: dict[Use, Text] = Field(default_factory=dict)
    effects: Text | None = None
    confidence: Literal["common-practice", "tested", "user-verified"] = "common-practice"

    @model_validator(mode="after")
    def explain_limits(self) -> Self:
        for use, rating in self.suitability.items():
            if rating != "works" and use not in self.reasons:
                raise ValueError(f"{use} is rated {rating} and needs a reason")
        return self


class FamilyMember(Model):
    ref: Identifier
    title: Text        # Menu label, e.g. "Ground Beef (90% Lean)"
    ingredient: Text   # Name shown in the recipe once chosen
    suitability: dict[Use, Suitability] = Field(default_factory=dict)  # Overrides the family's
    reasons: dict[Use, Text] = Field(default_factory=dict)
    instruction_notes: dict[Use, Text] = Field(default_factory=dict)
    effects: Text | None = None


class SubstitutionFamily(Model):
    """Interchangeable ingredients: any member replaces any other one-for-one.
    The replacement's own suitability, notes, and effects apply."""
    id: Identifier
    title: Text
    ratio_basis: Literal["volume", "weight"]
    suitability: dict[Use, Suitability] = Field(min_length=1)
    reasons: dict[Use, Text] = Field(default_factory=dict)
    instruction_notes: dict[Use, Text] = Field(default_factory=dict)
    confidence: Literal["common-practice", "tested", "user-verified"] = "common-practice"
    members: list[FamilyMember] = Field(min_length=2)

    @model_validator(mode="after")
    def unique_members(self) -> Self:
        refs = [m.ref for m in self.members]
        if len(refs) != len(set(refs)):
            raise ValueError("duplicate family members")
        return self

    def rules(self) -> list[SubstitutionRule]:
        return [SubstitutionRule.model_validate({
            "id": f"{a.ref}-to-{b.ref}", "title": b.title, "family": self.title, "replaces": a.ref,
            "with": [{"ref": b.ref, "ingredient": b.ingredient, "ratio": 1}], "ratio_basis": self.ratio_basis,
            "suitability": {**self.suitability, **b.suitability}, "reasons": {**self.reasons, **b.reasons},
            "instruction_notes": {**self.instruction_notes, **b.instruction_notes}, "effects": b.effects,
            "confidence": self.confidence,
        }) for a in self.members for b in self.members if a is not b]


class SubstitutionFile(Model):
    schema_version: Literal[1]
    substitutions: list[SubstitutionRule] = Field(default_factory=list)
    families: list[SubstitutionFamily] = Field(default_factory=list)

    @model_validator(mode="after")
    def not_empty(self) -> Self:
        if not self.substitutions and not self.families:
            raise ValueError("a substitution file needs substitutions or families")
        return self
