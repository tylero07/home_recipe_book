from pathlib import Path

import pytest
import yaml
from fastapi.testclient import TestClient
from pydantic import ValidationError

from recipe_library.api import create_app
from recipe_library.formatting import format_amount, tag_label, title_case
from recipe_library.models import Ingredient, Recipe
from recipe_library.ratings import Rating, load_ratings, matching_ids, save_rating
from recipe_library.shopping import ShoppingRequest, generate_list

ROOT = Path(__file__).resolve().parents[1]


def recipe(id, category, served, tags, calories, protein, minutes=30):
    return {
        "schema_version": 1, "id": id, "title": id.replace("-", " ").title(), "category": category,
        "served": served, "servings": 1, "tags": tags, "times": {"prep_minutes": minutes, "cook_minutes": 0},
        "ingredients": [{"id": "x", "ingredient": "x", "quantity": 1, "unit": "g"}], "instructions": ["Cook."],
        "nutrition": {"basis": "per_serving", "status": "estimated", "calories_kcal": calories, "protein_g": protein},
    }


@pytest.fixture
def client(tmp_path):
    recipes = tmp_path / "recipes"
    recipes.mkdir()
    for data in (
        recipe("oat-bowl", "breakfast", ["hot"], ["quick", "vegetarian"], 350, 12),
        recipe("salsa", "snacks-apps", ["cold"], ["quick", "vegetarian", "spicy"], 80, 2),
        recipe("stew", "lunch-dinner", ["hot"], ["spicy"], 600, 45, minutes=180),
        recipe("tart", "dessert", ["cold", "room-temperature"], [], 420, 5),
    ):
        (recipes / f"{data['id']}.yaml").write_text(yaml.safe_dump(data))
    app = create_app(recipes, tmp_path / "index.sqlite3", tmp_path / "no-library", tmp_path / "personal")
    with TestClient(app) as test_client:
        test_client.personal = tmp_path / "personal"
        yield test_client


def ids(client, **params):
    response = client.get("/recipes", params=params)
    assert response.status_code == 200, response.text
    return sorted(item["id"] for item in response.json()["items"])


def test_filters_combine(client):
    assert ids(client, category="breakfast") == ["oat-bowl"]
    assert ids(client, tag=["quick", "spicy"]) == ["salsa"]
    assert ids(client, served=["cold"]) == ["salsa", "tart"]
    assert ids(client, served=["hot", "room-temperature"]) == ["oat-bowl", "stew", "tart"]
    assert ids(client, max_calories=400) == ["oat-bowl", "salsa"]
    assert ids(client, min_protein=10, max_minutes=60) == ["oat-bowl"]
    assert ids(client, category="", max_calories="") == ["oat-bowl", "salsa", "stew", "tart"]


@pytest.mark.parametrize("params", [
    {"category": "brunch"}, {"served": "warm"}, {"max_calories": "-1"}, {"min_protein": "nan"},
    {"min_rating": "6"}, {"min_rating": "2.5"}, {"max_minutes": "-1"},
])
def test_invalid_filters_rejected(client, params):
    assert client.get("/recipes", params=params).status_code == 422


def test_home_shows_categories_filters_and_counts(client):
    page = client.get("/", params={"category": "snacks-apps"}).text
    assert "Snacks &amp; Apps" in page and "Lunch &amp; Dinner" in page
    assert "Show 1 Recipe<" in page and "1 Recipe</h2>" in page
    assert "Spicy" in page and "Room Temperature" in page
    filtered = client.get("/", params={"tag": "quick", "max_calories": "100"}).text
    assert "Filters (2 active)" in filtered and "Show 1 Recipe<" in filtered


def test_ratings_save_filter_and_clear(client):
    response = client.post("/recipe/stew/rating", data={"recipe": "5", "leftovers": "4", "return": "/recipe/stew?servings=2"},
                           follow_redirects=False)
    assert response.status_code == 303
    assert response.headers["location"] == "/recipe/stew?servings=2#ratings"
    client.post("/recipe/salsa/rating", data={"recipe": "3", "leftovers": ""})
    assert load_ratings(client.personal / "ratings.yaml")["salsa"] == Rating(recipe=3)
    assert ids(client, min_rating=4) == ["stew"]
    assert ids(client, min_leftovers=1) == ["stew"]
    assert ids(client, min_rating=3) == ["salsa", "stew"]
    page = client.get("/recipe/stew").text
    assert "Recipe 5/5" in page and "Leftovers 4/5" in page
    assert "Recipe 5/5" in client.get("/").text
    client.post("/recipe/stew/rating", data={"recipe": "", "leftovers": ""})
    assert "stew" not in load_ratings(client.personal / "ratings.yaml")


def test_rating_rejects_bad_values_unknown_recipes_and_cross_site_posts(client):
    assert client.post("/recipe/stew/rating", data={"recipe": "9"}).status_code == 422
    assert client.post("/recipe/stew/rating", data={"recipe": "two"}).status_code == 422
    assert client.post("/recipe/missing/rating", data={"recipe": "3"}).status_code == 404
    assert client.post("/recipe/stew/rating", data={"recipe": "3"}, headers={"origin": "https://evil.example"}).status_code == 403
    response = client.post("/recipe/stew/rating", data={"recipe": "3", "return": "https://evil.example"}, follow_redirects=False)
    assert response.headers["location"] == "/recipe/stew#ratings"


def test_rating_storage_round_trip(tmp_path):
    path = tmp_path / "ratings.yaml"
    assert load_ratings(path) == {}
    save_rating(path, "a", Rating(recipe=4, leftovers=2))
    save_rating(path, "b", Rating(leftovers=5))
    assert matching_ids(load_ratings(path), 3, None) == {"a"}
    assert matching_ids(load_ratings(path), None, 3) == {"b"}
    assert matching_ids(load_ratings(path), None, None) is None
    with pytest.raises(ValidationError):
        Rating(recipe=0)


def test_ranges_validate_display_and_shop_high():
    with pytest.raises(ValidationError):
        Ingredient(id="x", ingredient="x", quantity=2, quantity_max=1, unit="count")
    with pytest.raises(ValidationError):
        Ingredient(id="x", ingredient="x", quantity_max=1)
    assert Ingredient(id="x", ingredient="x", quantity=1, quantity_max=2, unit="count").typical_quantity == 1.5
    assert format_amount(1, "count", False, 2) == "1–2"
    assert format_amount(.25, "cup", True, .5) == "¼–½ cup (2–4 fl oz)"
    assert format_amount(1, "cup", False, 2) == "1–2 cups"

    class Index:
        def get(self, id):
            return Recipe.model_validate({**recipe("r", "lunch-dinner", [], [], 1, 1), "servings": 2, "ingredients": [
                {"id": "chile", "ingredient": "poblano pepper", "quantity": 1, "quantity_max": 2, "unit": "count"}]})
    item = generate_list(Index(), ShoppingRequest(selections=[{"recipe_id": "r", "servings": 4}]))["items"][0]
    assert item["quantity"] == "4"
    assert item["text"] == "4 — Poblano Pepper (top of the recipe's range)"


@pytest.mark.parametrize("text, expected", [
    ("ultra-filtered 2% milk", "Ultra-Filtered 2% Milk"), ("salt and pepper", "Salt and Pepper"),
    ("jalapeño or Fresno chili", "Jalapeño or Fresno Chili"), ("Cholula® hot sauce", "Cholula® Hot Sauce"),
    ("the end of it", "The End of It"), ("IPA", "IPA"),
])
def test_title_case(text, expected):
    assert title_case(text) == expected


def test_tag_labels():
    assert tag_label("comfort-food") == "Comfort Food"


def test_category_required_and_known():
    data = recipe("r", "lunch-dinner", [], [], 1, 1)
    for bad in ({"category": "brunch"}, {"served": ["warm"]}):
        with pytest.raises(ValidationError):
            Recipe.model_validate({**data, **bad})
    del data["category"]
    with pytest.raises(ValidationError):
        Recipe.model_validate(data)


def test_shipped_chili_renders_groups_ranges_and_estimate(tmp_path):
    with TestClient(create_app(ROOT / "recipes", tmp_path / "i.sqlite3", ROOT / "ingredients", tmp_path / "p")) as client:
        page = client.get("/recipe/wheat-beer-chili").text
    assert '<h3 class="group-heading">Chili Spice Mix</h3>' in page
    assert "1–2</strong>" in page and "Poblano Pepper" in page
    assert "¼–½ cup (2–4 fl oz)" in page
    assert "ranges use their middle amount" in page
