from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from recipe_library.api import create_app
from recipe_library.customize import CustomizationError, customize, difference, options
from recipe_library.loader import load_ingredients, load_substitutions
from recipe_library.models import LibraryIngredient, Recipe, SubstitutionFamily
from recipe_library.nutrition import estimate_nutrition, per_serving_macros

ROOT = Path(__file__).resolve().parents[1]


def entry(id, kcal=100, protein=10, fat=5, **fields):
    return LibraryIngredient.model_validate({"id": id, "name": id, **fields, "nutrition_per_100g": {
        "status": "estimated", "calories_kcal": kcal, "protein_g": protein, "fat_g": fat}})


def product(id, kcal, protein=None, each=None):
    data = {"id": id, "name": id.title(), "nutrition_per_100g": {"status": "estimated", "calories_kcal": kcal}}
    if protein is not None:
        data["nutrition_per_100g"]["protein_g"] = protein
    if each:
        data["grams_each"] = each
    return data


LIBRARY = {
    "beer": entry("beer", grams_per_cup=240, requires_product=True,
                  products=[product("light", 30, 0.2), product("strong", 60, 0.8), product("unknown", 50)]),
    "disc": entry("disc", grams_each=90, requires_product=True, products=[product("big", 400, 3, each=90), product("small", 500, 4, each=60)]),
    "pepper": entry("pepper", kcal=250, grams_per_cup=110, negligible=True),
    "beef": entry("beef", kcal=215, protein=18.6, fat=15),
    "oil": entry("oil", kcal=884, protein=0, fat=100, grams_per_cup=216),
}


def recipe(**changes):
    data = {"schema_version": 1, "id": "r", "title": "R", "category": "lunch-dinner", "servings": 2, "instructions": ["Cook."],
            "ingredients": [
                {"id": "beef", "ingredient": "beef", "ref": "beef", "uses": ["seared"], "quantity": 500, "unit": "g"},
                {"id": "beer", "ingredient": "beer", "ref": "beer", "quantity": 1, "unit": "cup"},
                {"id": "disc", "ingredient": "chocolate", "ref": "disc", "quantity": 1, "unit": "count"},
                {"id": "pepper", "ingredient": "pepper", "ref": "pepper"},
                {"id": "oil", "ingredient": "oil", "ref": "oil"},
            ]}
    data.update(changes)
    return Recipe.model_validate(data)


def test_unchosen_products_are_reported_separately_from_negligible_and_unknown_amounts():
    estimate = estimate_nutrition(recipe(), LIBRARY)
    kinds = {kind: [e["ingredient"] for e in items] for kind, items in estimate["excluded_by_kind"].items()}
    assert kinds == {"choice": ["beer", "chocolate"], "amount": ["oil"], "negligible": ["pepper"]}
    assert estimate["per_serving"]["calories_kcal"] == pytest.approx(215 * 5 / 2)


def test_products_supply_nutrition_and_sizes():
    chosen, _ = customize(recipe(), {}, {}, LIBRARY, {}, {"beer": "strong", "disc": "small"})
    estimate = estimate_nutrition(chosen, LIBRARY)
    assert "choice" not in estimate["excluded_by_kind"]
    assert estimate["per_serving"]["calories_kcal"] == pytest.approx((1075 + 240 * 0.6 + 60 * 5) / 2)
    with pytest.raises(CustomizationError, match="not a product"):
        customize(recipe(), {}, {}, LIBRARY, {}, {"beer": "small"})


def test_filters_bound_unchosen_products():
    macros = per_serving_macros(recipe(), LIBRARY)
    # Highest-calorie products for calories; lowest known protein for protein.
    assert macros["calories_kcal"] == pytest.approx((1075 + 240 * 0.6 + 90 * 4) / 2)
    assert macros["protein_g"] == pytest.approx((93 + 240 * 0.002 + 60 * 0.04) / 2)


def test_library_product_rules():
    with pytest.raises(ValueError, match="requires_product"):
        entry("x", requires_product=True)
    with pytest.raises(ValueError, match="duplicate product"):
        entry("x", products=[product("a", 1), product("a", 2)])


def test_family_expands_to_every_pair_with_the_replacement_s_own_notes():
    family = SubstitutionFamily.model_validate({
        "id": "meat", "title": "Ground Meat", "ratio_basis": "weight", "suitability": {"seared": "works", "raw": "unsuitable"},
        "reasons": {"raw": "Cook it."},
        "members": [{"ref": "beef", "title": "Beef", "ingredient": "beef"},
                    {"ref": "turkey", "title": "Turkey", "ingredient": "turkey", "effects": "Leaner.",
                     "instruction_notes": {"seared": "Add oil."}},
                    {"ref": "lamb", "title": "Lamb", "ingredient": "lamb", "suitability": {"seared": "caution"},
                     "reasons": {"seared": "Gamy."}}]})
    rules = {r.id: r for r in family.rules()}
    assert len(rules) == 6
    turkey = rules["beef-to-turkey"]
    assert (turkey.family, turkey.effects, turkey.instruction_notes) == ("Ground Meat", "Leaner.", {"seared": "Add oil."})
    assert rules["beef-to-lamb"].suitability == {"seared": "caution", "raw": "unsuitable"}
    with pytest.raises(ValueError, match="duplicate family"):
        SubstitutionFamily.model_validate({**family.model_dump(), "members": [family.members[0].model_dump()] * 2})


def test_swap_differences_compare_per_100g():
    library = load_ingredients(ROOT / "ingredients")
    rules = load_substitutions(ROOT / "substitutions", library)
    beef = recipe().ingredients[0].model_copy(update={"ref": "ground-beef-85"})
    found = {o["rule"].id: o for o in options(beef, rules, library)}
    assert found["ground-beef-85-to-ground-beef-70"]["difference"] == "+117 kcal, −4 g protein, +15 g fat per 100 g"
    assert found["ground-beef-85-to-ground-turkey-93"]["rule"].family == "Ground Meat"
    assert len([o for o in found.values() if o["rule"].family == "Ground Meat"]) == 17
    oil = recipe().ingredients[4].model_copy(update={"ref": "olive-oil", "uses": ["fat-for-cooking"]})
    assert difference(rules["olive-oil-to-avocado-oil"], oil, library) is None  # volume swaps aren't compared


@pytest.fixture
def client(tmp_path):
    with TestClient(create_app(ROOT / "recipes", tmp_path / "i.sqlite3", ROOT / "ingredients", tmp_path / "p")) as test_client:
        yield test_client


def test_page_product_picker_and_not_counted_sections(client):
    page = client.get("/recipe/wheat-beer-chili").text
    assert "Choose a Product to Count Nutrition" in page
    assert 'href="#product-beer">Wheat Beer</a>' in page and "Mexican Chocolate" in page
    assert "Not counted because the recipe gives no amount:</strong> Olive Oil, Corn Tortillas, Oil for Frying." in page
    assert "Salt, Black Pepper, Sumac, Cinnamon, Fresh Cilantro" in page  # each name once
    assert "17 Swaps Available" in page
    chosen = client.get("/recipe/wheat-beer-chili", params={"p.beer": "blue-moon-belgian-white"}).text
    assert "Product: Blue Moon Belgian White" in chosen and "#product-beer" not in chosen
    assert "were left out" in client.get("/recipe/wheat-beer-chili", params={"p.beer": "abuelita"}).text
    redirected = client.get("/recipe/wheat-beer-chili", params={"at": "8", "p.beer": "hoegaarden", "s.beef": ""},
                            follow_redirects=False)
    assert redirected.headers["location"] == "/recipe/wheat-beer-chili?p.beer=hoegaarden"


def test_shopping_list_names_chosen_products(client):
    selection = {"recipe_id": "wheat-beer-chili", "servings": 8, "products": {"beer": "bells-oberon", "chocolate": "abuelita"}}
    items = [i["text"] for i in client.post("/shopping/generate", json={"selections": [selection]}).json()["items"]]
    assert "1½ cups (12 fl oz) — Wheat Beer (Bell's Oberon) (one bottle; 12 fl oz assumed)" in items
    assert any("Mexican Chocolate (Nestlé Abuelita)" in text for text in items)
    bad = {**selection, "products": {"beer": "abuelita"}}
    assert client.post("/shopping/generate", json={"selections": [bad]}).status_code == 422
