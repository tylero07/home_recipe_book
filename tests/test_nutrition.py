from pathlib import Path

import pytest
import yaml

from recipe_library.loader import CatalogError, load_catalog, load_ingredients
from recipe_library.models import Ingredient, LibraryIngredient, Recipe
from recipe_library.nutrition import estimate_nutrition, ingredient_grams
from recipe_library.variations import resolve_variation

ROOT = Path(__file__).resolve().parents[1]


def item(**fields):
    return LibraryIngredient.model_validate({"id": "thing", "name": "thing", **fields})


def line(quantity, unit, **fields):
    return Ingredient(id="x", ingredient="thing", ref="thing", quantity=quantity, unit=unit, **fields)


def test_shipped_library_and_recipe_refs_validate():
    library = load_ingredients(ROOT / "ingredients")
    recipes = load_catalog(ROOT / "recipes", library)
    refs = {i.ref for r in recipes.values() for i in r.ingredients if i.ref}
    assert refs <= library.keys()


@pytest.mark.parametrize("quantity, unit, fields, grams", [
    (2, "lb", {}, 907.18474), (8, "oz", {}, 226.796185), (250, "g", {}, 250),
    (0.5, "cup", {"grams_per_cup": 120}, 60), (2, "tbsp", {"grams_per_cup": 240}, 30),
    (3, "count", {"grams_each": 3}, 9),
])
def test_amounts_convert_to_grams(quantity, unit, fields, grams):
    value, reason = ingredient_grams(line(quantity, unit), item(**fields))
    assert reason is None and value == pytest.approx(grams)


def test_missing_conversion_data_explains_why():
    assert ingredient_grams(line(1, "cup"), item())[1] == "no weight per cup in the ingredient library"
    assert ingredient_grams(line(1, "count"), item())[1] == "no weight per count in the ingredient library"


def test_estimate_divides_by_servings_and_lists_exclusions():
    library = {
        "chicken": item(id="chicken", nutrition_per_100g={"status": "estimated", "calories_kcal": 100, "protein_g": 20, "carbohydrate_g": 0, "fat_g": 2}),
        "broth": item(id="broth", grams_per_cup=240, nutrition_per_100g={"status": "source_provided", "calories_kcal": 20, "protein_g": 4, "source": "label"}),
        "mix": item(id="mix"),
    }
    recipe = Recipe.model_validate({
        "schema_version": 1, "id": "r", "title": "R", "category": "lunch-dinner", "servings": 2, "instructions": ["Cook."],
        "ingredients": [
            {"id": "chicken", "ingredient": "chicken", "ref": "chicken", "quantity": 500, "unit": "g"},
            {"id": "broth", "ingredient": "broth", "ref": "broth", "quantity": 1, "unit": "cup"},
            {"id": "mix", "ingredient": "mix", "ref": "mix", "quantity": 1, "unit": "count"},
            {"id": "salt", "ingredient": "salt", "quantity": None, "unit": None},
            {"id": "herb", "ingredient": "herb", "quantity": 1, "unit": "g"},
            {"id": "cheese", "ingredient": "cheese", "ref": "chicken", "quantity": 1, "unit": "g", "optional": True},
        ],
    })
    result = estimate_nutrition(recipe, library)
    assert result["status"] == "estimated"
    assert result["per_serving"]["calories_kcal"] == pytest.approx((500 + 48) / 2)
    assert result["per_serving"]["protein_g"] == pytest.approx((100 + 9.6) / 2)
    assert result["incomplete"] == {"carbohydrate_g": ["broth"], "fat_g": ["broth"]}
    assert [(e["ingredient"], e["reason"]) for e in result["excluded"]] == [
        ("mix", "no nutrition data"), ("salt", "amount unknown"),
        ("herb", "not in the ingredient library"), ("cheese", "optional"),
    ]


def test_variation_quantity_changes_estimate():
    library = load_ingredients(ROOT / "ingredients")
    base = load_catalog(ROOT / "recipes", library)["lemon-chickpea-bowl"]
    more = resolve_variation(base, "extra-chickpeas")
    assert estimate_nutrition(more, library)["per_serving"]["protein_g"] > estimate_nutrition(base, library)["per_serving"]["protein_g"]


def test_nothing_countable_returns_none():
    recipe = Recipe.model_validate({"schema_version": 1, "id": "r", "title": "R", "category": "lunch-dinner", "servings": 1, "instructions": ["x"],
                                    "ingredients": [{"id": "salt", "ingredient": "salt"}]})
    assert estimate_nutrition(recipe, {}) is None


def write(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(yaml.safe_dump(data))


def test_unknown_refs_and_duplicate_library_ids_fail(tmp_path):
    recipe = yaml.safe_load((ROOT / "recipes/lemon-chickpea-bowl.yaml").read_text())
    recipe["variations"][0]["ingredient_overrides"]["chickpeas"]["ref"] = "missing-too"
    recipe["ingredients"][0]["ref"] = "missing"
    write(tmp_path / "recipes/bowl.yaml", recipe)
    with pytest.raises(CatalogError) as exc:
        load_catalog(tmp_path / "recipes", {})
    assert "ingredients.chickpeas.ref: unknown library ingredient 'missing'" in str(exc.value)
    assert "ingredient_overrides.chickpeas.ref: unknown library ingredient 'missing-too'" in str(exc.value)
    entry = {"id": "salt", "name": "salt"}
    write(tmp_path / "lib/a.yaml", {"schema_version": 1, "ingredients": [entry]})
    write(tmp_path / "lib/b.yaml", {"schema_version": 1, "ingredients": [entry]})
    with pytest.raises(CatalogError, match="duplicate ingredient ID 'salt'"):
        load_ingredients(tmp_path / "lib")
    assert load_ingredients(tmp_path / "absent") == {}


@pytest.mark.parametrize("bad", [
    {"uses": ["juggling"]}, {"uses": ["raw", "raw"]}, {"ref": "Not An ID"},
])
def test_invalid_ref_or_uses_rejected(bad):
    with pytest.raises(ValueError):
        Ingredient.model_validate({"id": "x", "ingredient": "x", **bad})


@pytest.mark.parametrize("nutrition", [
    {"status": "estimated"}, {"status": "source_provided", "protein_g": 1}, {"status": "unknown", "protein_g": 1},
])
def test_invalid_library_nutrition_rejected(nutrition):
    with pytest.raises(ValueError):
        item(nutrition_per_100g=nutrition)
