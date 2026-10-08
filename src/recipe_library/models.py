"""Version-one recipe format. Personal state does not belong in these models."""
from typing import Annotated, Literal, Self

from pydantic import BaseModel, ConfigDict, Field, HttpUrl, StringConstraints, model_validator

Text = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)]
Identifier = Annotated[str, StringConstraints(pattern=r"^[a-z0-9]+(?:-[a-z0-9]+)*$")]
Positive = Annotated[float, Field(gt=0, allow_inf_nan=False, strict=True)]
Nonnegative = Annotated[float, Field(ge=0, allow_inf_nan=False, strict=True)]
Unit = Literal["g", "kg", "mg", "ml", "l", "tsp", "tbsp", "cup", "oz", "lb", "count", "fl_oz"]


class Model(BaseModel):
    model_config = ConfigDict(extra="forbid", validate_default=True)


class RecipeTimes(Model):
    prep_minutes: Nonnegative | None = None
    cook_minutes: Nonnegative | None = None


class Source(Model):
    title: Text
    url: HttpUrl | None = None


class Ingredient(Model):
    id: Identifier
    ingredient: Text
    quantity: Positive | None = None
    unit: Unit | None = None
    preparation: Text | None = None
    liquid: bool = Field(default=False, strict=True)
    optional: bool = Field(default=False, strict=True)

    @model_validator(mode="after")
    def quantity_has_unit(self) -> Self:
        if (self.quantity is None) != (self.unit is None):
            raise ValueError("quantity and unit must both be supplied, or both null")
        return self


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
    quantity: Positive | None = None
    unit: Unit | None = None
    preparation: Text | None = None
    liquid: bool | None = Field(default=None, strict=True)
    optional: bool | None = Field(default=None, strict=True)

    @model_validator(mode="after")
    def nonempty_override(self) -> Self:
        if not self.model_fields_set:
            raise ValueError("an override must change at least one field")
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
