import json
from pathlib import Path
import zipfile

import pytest
import yaml
from fastapi.testclient import TestClient

from recipe_library import usda
from recipe_library.api import create_app
from recipe_library.customize import CustomizationError, customize, editable_ratio, options, rate
from recipe_library.loader import CatalogError, load_catalog, load_ingredients, load_substitutions
from recipe_library.models import Ingredient, LibraryIngredient, Recipe, SubstitutionRule
from recipe_library.nutrition import estimate_nutrition
from recipe_library.shopping import ShoppingRequest, generate_list

ROOT = Path(__file__).resolve().parents[1]


def lib(id, cup=None, each=None, kcal=100):
    return LibraryIngredient.model_validate({"id": id, "name": id, "grams_per_cup": cup, "grams_each": each,
                                            "nutrition_per_100g": {"status": "estimated", "calories_kcal": kcal}})


LIBRARY = {i.id: i for i in [lib("beef", kcal=250), lib("turkey", kcal=150), lib("cream", cup=240), lib("yogurt", cup=245),
                              lib("disc", each=90), lib("dark", kcal=600), lib("sugar", cup=200, kcal=400)]}


def rule(**fields):
    data = {"id": "r", "title": "R", "replaces": "beef", "with": [{"ref": "turkey", "ingredient": "turkey", "ratio": 1}],
            "ratio_basis": "weight", "suitability": {"seared": "works"}}
    if "with_" in fields:
        fields["with"] = fields.pop("with_")
    return SubstitutionRule.model_validate({**data, **fields})


RULES = {
    "beef-turkey": rule(id="beef-turkey", title="Ground Turkey", suitability={"seared": "works", "raw": "unsuitable"},
                        reasons={"raw": "Must be cooked."}, instruction_notes={"seared": "Add oil."}, effects="Leaner."),
    "cream-yogurt": rule(id="cream-yogurt", title="Yogurt", replaces="cream", ratio_basis="volume",
                         with_=[{"ref": "yogurt", "ingredient": "yogurt", "ratio": 1}],
                         suitability={"raw": "works", "simmered": "caution"}, reasons={"simmered": "Curdles."}),
    "disc-dark": rule(id="disc-dark", title="Dark and Sugar", replaces="disc",
                      with_=[{"ref": "dark", "ingredient": "dark chocolate", "ratio": 0.5},
                             {"ref": "sugar", "ingredient": "sugar", "ratio": 0.45}], suitability={"simmered": "works"}),
}


def recipe(**changes):
    data = {"schema_version": 1, "id": "chili", "title": "Chili", "category": "lunch-dinner", "servings": 4,
            "ingredients": [
                {"id": "meat", "ingredient": "ground beef", "ref": "beef", "uses": ["seared"], "quantity": 2, "unit": "lb"},
                {"id": "topping", "ingredient": "sour cream", "ref": "cream", "uses": ["raw"], "quantity": 0.5, "unit": "cup"},
                {"id": "choc", "ingredient": "Mexican chocolate", "ref": "disc", "uses": ["simmered"], "quantity": 1, "unit": "count"},
                {"id": "salt", "ingredient": "salt"}],
            "instructions": ["Brown the {meat}.", "Stir in the {choc}.", "Top with {topping}."]}
    data.update(changes)
    return Recipe.model_validate(data)


def test_rating_uses_the_worst_use_and_vetoes():
    line = Ingredient(id="x", ingredient="beef", ref="beef", uses=["seared", "raw"])
    assert rate(RULES["beef-turkey"], line) == {"rating": "unsuitable", "reasons": ["Must be cooked."], "vetoed": False}
    assert rate(RULES["beef-turkey"], line.model_copy(update={"uses": ["seared", "marinade"]}))["rating"] == "caution"
    assert rate(RULES["beef-turkey"], line.model_copy(update={"uses": []}))["rating"] == "caution"
    vetoed = Ingredient(id="x", ingredient="beef", ref="beef", uses=["seared"],
                        substitutions={"veto": {"beef-turkey": "Beef is the point."}})
    assert rate(RULES["beef-turkey"], vetoed) == {
        "rating": "unsuitable", "reasons": ["Beef is the point."], "vetoed": True}
    assert [o["rule"].id for o in options(line, RULES)] == ["beef-turkey"]


def test_swaps_convert_amounts_and_rewrite_steps_and_notes():
    custom, changes = customize(recipe(), {"meat": 1.5}, {"meat": "beef-turkey", "choc": "disc-dark", "topping": "cream-yogurt"},
                                LIBRARY, RULES)
    lines = {(i.ingredient, i.unit): i.quantity for i in custom.ingredients if i.quantity}
    assert lines[("turkey", "lb")] == 1.5
    assert lines[("yogurt", "cup")] == 0.5
    assert lines[("dark chocolate", "g")] == pytest.approx(45)
    assert lines[("sugar", "cup")] == pytest.approx(40.5 / 200)
    assert [i.id for i in custom.ingredients][:4] == ["meat", "topping", "choc", "choc-sub-2"]
    assert custom.instructions == ["Brown the turkey.", "Stir in the dark chocolate and sugar.", "Top with yogurt."]
    assert "Swap — Ground Turkey for Ground Beef: Add oil. Leaner." in custom.notes
    assert set(changes) == {"meat", "choc", "topping"}
    assert estimate_nutrition(custom, LIBRARY)["per_serving"]["calories_kcal"] < estimate_nutrition(recipe(), LIBRARY)["per_serving"]["calories_kcal"]


def test_placeholders_fill_without_changes_and_must_name_ingredients():
    assert customize(recipe(), {}, {}, LIBRARY, RULES)[0].instructions[0] == "Brown the ground beef."
    with pytest.raises(ValueError, match="placeholder"):
        recipe(instructions=["Add {nothing}."])


@pytest.mark.parametrize("amounts, swaps, message", [
    ({"nope": 1}, {}, "Unknown ingredient"), ({"salt": 1}, {}, "no amount"),
    ({}, {"meat": "cream-yogurt"}, "not a substitution"), ({}, {"meat": "missing"}, "not a substitution"),
])
def test_invalid_customizations_rejected(amounts, swaps, message):
    with pytest.raises(CustomizationError, match=message):
        customize(recipe(), amounts, swaps, LIBRARY, RULES)


def test_unsuitable_swap_rejected():
    raw = recipe(ingredients=[{"id": "meat", "ingredient": "beef", "ref": "beef", "uses": ["raw"], "quantity": 1, "unit": "lb"}],
                 instructions=["Serve."])
    with pytest.raises(CustomizationError, match="isn't suitable here: Must be cooked."):
        customize(raw, {}, {"meat": "beef-turkey"}, LIBRARY, RULES)


def test_editable_ratio_only_for_one_to_one_same_unit_swaps():
    meat, choc = recipe().ingredients[0], recipe().ingredients[2]
    assert editable_ratio(RULES["beef-turkey"], meat) == 1
    assert editable_ratio(RULES["disc-dark"], choc) is None


def test_rules_need_reasons_and_valid_references(tmp_path):
    with pytest.raises(ValueError, match="needs a reason"):
        rule(suitability={"seared": "caution"})
    (tmp_path / "subs").mkdir()
    (tmp_path / "subs/a.yaml").write_text(yaml.safe_dump({"schema_version": 1, "substitutions": [
        {"id": "x", "title": "X", "replaces": "beef", "with": [{"ref": "ghost", "ingredient": "g", "ratio": 1}],
         "ratio_basis": "weight", "suitability": {"seared": "works"}}]}))
    with pytest.raises(CatalogError, match="unknown library ingredient 'ghost'"):
        load_substitutions(tmp_path / "subs", LIBRARY)


def test_recipe_vetoes_must_name_matching_rules(tmp_path):
    data = yaml.safe_load((ROOT / "recipes/wheat-beer-chili.yaml").read_text())
    data["ingredients"][0]["substitutions"] = {"veto": {"sour-cream-to-greek-yogurt-nonfat": "no"}, "notes": {"nope": "x"}}
    (tmp_path / "r").mkdir()
    (tmp_path / "r/chili.yaml").write_text(yaml.safe_dump(data, allow_unicode=True))
    library = load_ingredients(ROOT / "ingredients")
    with pytest.raises(CatalogError) as exc:
        load_catalog(tmp_path / "r", library, load_substitutions(ROOT / "substitutions", library))
    assert "replaces sour-cream, not ground-beef-85" in str(exc.value)
    assert "unknown substitution 'nope'" in str(exc.value)


@pytest.fixture
def client(tmp_path):
    app = create_app(ROOT / "recipes", tmp_path / "i.sqlite3", ROOT / "ingredients", tmp_path / "p")
    with TestClient(app) as test_client:
        yield test_client


def test_page_form_round_trips_to_canonical_url(client):
    # Turkey shown as 1 lb at 4 servings is 2 lb for the original 8-serving batch.
    response = client.get("/recipe/wheat-beer-chili", params={"at": "4", "servings": "4", "amount.beef": "1",
                          "s.beef": "ground-beef-85-to-ground-turkey-93", "amount.onion": "0.5", "s.chocolate": ""},
                          follow_redirects=False)
    assert response.status_code == 303
    assert response.headers["location"] == "/recipe/wheat-beer-chili?servings=4&a.beef=2&s.beef=ground-beef-85-to-ground-turkey-93"
    page = client.get(response.headers["location"]).text
    assert "Was 1.25 lb Ground Beef" in page and "1 ingredient changed" in page
    assert "Add the ground turkey (93% lean), break it up" in page
    assert '(was ≈' in page
    assert 'href="/recipe/wheat-beer-chili?servings=4">Reset to Original' in page
    same = client.get("/recipe/wheat-beer-chili", params={"at": "8", "servings": "8", "amount.beef": "2.5"}, follow_redirects=False)
    assert same.headers["location"] == "/recipe/wheat-beer-chili"


def test_page_shows_ratings_and_disabled_unsuitable_swaps(client):
    page = client.get("/recipe/chicken-cheddar-bay-dumplings").text
    assert 'name="s.butter"' in page and ">Olive Oil</option>" in page
    assert "<span class=\"badge\">Works</span>" in page and "1 Swap Available" in page


def test_page_drops_edits_that_do_not_apply_and_rejects_bad_input(client):
    page = client.get("/recipe/wheat-beer-chili", params={"a.salt": "2", "s.beef": "sour-cream-to-greek-yogurt-nonfat", "a.ghost": "1"}).text
    assert "were left out" in page and "ingredient changed" not in page
    assert client.get("/recipe/wheat-beer-chili", params={"at": "8", "amount.beef": "-1"}).status_code == 422
    assert client.get("/recipe/wheat-beer-chili", params={"at": "0"}).status_code == 422


def test_shopping_list_applies_customizations(client):
    selection = {"recipe_id": "wheat-beer-chili", "servings": 4, "amounts": {"beef": 2},
                 "substitutions": {"beef": "ground-beef-85-to-ground-turkey-93", "chocolate": "mexican-chocolate-to-dark-chocolate"}}
    items = [i["text"] for i in client.post("/shopping/generate", json={"selections": [selection]}).json()["items"]]
    assert "1 lb — Ground Turkey (93% Lean)" in items
    assert not any("Ground Beef" in text or "Mexican Chocolate" in text for text in items)
    assert any(text.endswith("— Sugar") for text in items)
    bad = {**selection, "substitutions": {"beef": "sour-cream-to-greek-yogurt-nonfat"}}
    assert client.post("/shopping/generate", json={"selections": [bad]}).status_code == 422


def test_shipped_substitutions_validate():
    library = load_ingredients(ROOT / "ingredients")
    rules = load_substitutions(ROOT / "substitutions", library)
    assert {"ground-beef-85-to-ground-turkey-93", "sour-cream-to-greek-yogurt-nonfat", "mexican-chocolate-to-dark-chocolate"} <= rules.keys()


def make_usda_downloads(directory):
    base = "FoodData_Central_sr_legacy_food_csv_2018-04/"
    files = {
        "food.csv": "fdc_id,data_type,description,food_category_id,publication_date\n1,sr_legacy_food,\"Cheese, cheddar\",1,2019\n",
        "food_category.csv": "id,code,description\n1,0100,Dairy and Egg Products\n",
        "measure_unit.csv": "id,name\n1000,cup\n9999,undetermined\n",
        "food_nutrient.csv": "id,fdc_id,nutrient_id,amount\n1,1,1008,403\n2,1,1003,22.9\n3,1,1005,3.4\n4,1,1004,33.3\n5,1,1093,620\n",
        "food_portion.csv": "id,fdc_id,seq_num,amount,measure_unit_id,portion_description,modifier,gram_weight\n"
                            "1,1,1,1,1000,,shredded,113\n2,1,2,1,9999,,slice (1 oz),28\n",
    }
    with zipfile.ZipFile(directory / usda.SR_ZIP, "w") as archive:
        for name, text in files.items():
            archive.writestr(base + name, text)
    foods = {"FoundationFoods": [{"fdcId": 2, "description": "Yogurt, Greek, plain, nonfat", "dataType": "Foundation",
                                  "foodCategory": {"description": "Dairy"},
                                  "foodNutrients": [{"nutrient": {"id": 2047}, "amount": 61}, {"nutrient": {"id": 1003}, "amount": 10.3}],
                                  "foodPortions": [{"value": 1, "measureUnit": {"name": "cup"}, "gramWeight": 245}]}]}
    with zipfile.ZipFile(directory / usda.FOUNDATION_ZIP, "w") as archive:
        archive.writestr("foundation.json", json.dumps(foods))


def test_usda_build_search_show_and_link(tmp_path):
    make_usda_downloads(tmp_path)
    database = tmp_path / "usda.sqlite3"
    assert usda.build(tmp_path, database) == 2
    assert [f["fdc_id"] for f in usda.search(database, "cheddar")] == [1]
    cheddar = usda.show(database, 1)
    assert (cheddar["calories_kcal"], cheddar["fat_g"]) == (403, 33.3)
    assert [p["label"] for p in cheddar["portions"]] == ["1 cup, shredded", "1 slice (1 oz)"]
    yogurt = usda.show(database, 2)
    assert yogurt["calories_kcal"] == 61 and yogurt["carbohydrate_g"] is None  # Atwater energy fallback
    library = tmp_path / "ingredients"
    library.mkdir()
    (library / "a.yaml").write_text(yaml.safe_dump({"schema_version": 1, "ingredients": [{"id": "cheddar", "name": "cheddar"}]}))
    usda.link(library, "cheddar", cheddar, cup=1, each=2)
    entry = load_ingredients(library)["cheddar"]
    assert entry.usda.fdc_id == 1 and entry.grams_per_cup == 113 and entry.grams_each == 28
    assert entry.nutrition_per_100g.status == "source_provided"
    assert "FDC ID 1: Cheese, cheddar" in entry.nutrition_per_100g.source
    usda.link(library, "cheddar", cheddar, proxy=True)
    assert load_ingredients(library)["cheddar"].nutrition_per_100g.status == "estimated"
    with pytest.raises(CatalogError):
        usda.link(library, "missing", cheddar)
    with pytest.raises(usda.UsdaError):
        usda.link(library, "cheddar", cheddar, cup=9)
    with pytest.raises(usda.UsdaError):
        usda.show(database, 999)
    with pytest.raises(usda.UsdaError):
        usda.build(tmp_path / "empty", database)
