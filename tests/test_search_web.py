from pathlib import Path

import pytest
import yaml
from fastapi.testclient import TestClient

from recipe_library.api import create_app
from recipe_library.loader import CatalogError
from recipe_library.search import SearchError, SearchIndex, rebuild_index

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def library(tmp_path):
    recipes = tmp_path / "recipes"
    recipes.mkdir()
    base = yaml.safe_load((ROOT / "recipes/lemon-chickpea-bowl.yaml").read_text())
    (recipes / "bowl.yaml").write_text(yaml.safe_dump(base))
    second = dict(base, id="rice-supper", title="Rice supper", tags=["dinner"],
                  times={"prep_minutes": 20, "cook_minutes": 30})
    (recipes / "supper.yml").write_text(yaml.safe_dump(second))
    return recipes, tmp_path / "data" / "recipes.sqlite3"


def test_search_filters_literal_input_and_pagination(library):
    recipes, database = library
    assert rebuild_index(recipes, database) == 2
    index = SearchIndex(database)
    assert index.search("chickpeas")["total"] == 2
    assert index.search("lemon", tag="quick", max_minutes=25)["total"] == 1
    assert index.search(max_minutes=24)["total"] == 0
    assert index.search(tag="dinner")["items"][0].id == "rice-supper"
    assert index.search("nonexistent")["total"] == 0
    assert index.search('" OR * : -')["total"] == 0
    assert index.search("' ; DROP TABLE recipes --")["total"] == 0
    assert index.search()["total"] == 2
    first = index.search(limit=1)
    second = index.search(limit=1, offset=1)
    assert first["items"][0].id != second["items"][0].id
    assert first["total"] == second["total"] == 2
    assert "quick" in index.tags()
    assert index.get("missing") is None


def test_rebuild_preserves_personal_and_rejects_invalid_catalog(library):
    recipes, database = library
    history = recipes.parent / "personal" / "history.yaml"
    history.parent.mkdir()
    history.write_text("my records")
    rebuild_index(recipes, database)
    (recipes / "supper.yml").write_text("invalid: recipe")
    with pytest.raises(CatalogError):
        rebuild_index(recipes, database)
    assert SearchIndex(database).search()["total"] == 2
    (recipes / "supper.yml").unlink()
    rebuild_index(recipes, database)
    assert SearchIndex(database).search()["total"] == 1
    assert history.read_text() == "my records"


def test_missing_index_has_actionable_error(tmp_path):
    with pytest.raises(SearchError, match="index first"):
        SearchIndex(tmp_path / "missing.sqlite3").search()


def test_read_only_api_and_html(library):
    with TestClient(create_app(*library)) as client:
        assert client.get("/recipes", params={"q": "lemon", "tag": "quick"}).json()["total"] == 1
        assert "quick" in client.get("/tags").json()
        assert client.get("/recipes/missing").status_code == 404
        assert client.get("/recipes/lemon-chickpea-bowl?variation=bad").status_code == 404
        changed = client.get("/recipes/lemon-chickpea-bowl?variation=extra-chickpeas").json()
        assert changed["ingredients"][0]["quantity"] == 360
        assert changed["nutrition"] is None
        assert client.post("/recipes").status_code == 405
        for params in ({"limit": 0}, {"offset": -1}, {"max_minutes": -1}, {"max_minutes": "nan"}, {"q": "x" * 201}):
            assert client.get("/recipes", params=params).status_code == 422
        home = client.get("/")
        assert home.status_code == 200
        assert "Lemon Chickpea Bowl" in home.text
        assert client.get("/?q=missing").text.count("No recipes found") == 1
        assert client.get("/?max_minutes=&tag=").status_code == 200
        assert client.get("/?max_minutes=nan").status_code == 422
        page = client.get("/recipe/lemon-chickpea-bowl?variation=extra-chickpeas")
        assert page.status_code == 200
        assert "360 g" in page.text
        assert "Nutrition hasn’t been supplied" in page.text
        assert client.get("/static/style.css").status_code == 200


def test_html_escapes_recipe_content(library):
    recipes, database = library
    path = recipes / "bowl.yaml"
    recipe = yaml.safe_load(path.read_text())
    recipe["title"] = '<script>alert("bad")</script>'
    path.write_text(yaml.safe_dump(recipe))
    with TestClient(create_app(recipes, database)) as client:
        assert "<script>" not in client.get("/").text
        assert "&lt;script&gt;" in client.get("/recipe/lemon-chickpea-bowl").text


def test_unknown_times_are_not_quick_recipes(library):
    recipes, database = library
    path = recipes / "bowl.yaml"
    recipe = yaml.safe_load(path.read_text())
    recipe["times"] = {"prep_minutes": None, "cook_minutes": None}
    path.write_text(yaml.safe_dump(recipe))
    with TestClient(create_app(recipes, database)) as client:
        assert client.get('/recipes?max_minutes=100').json()['total'] == 1
        assert 'Time not recorded' in client.get('/').text
        assert 'Prep unknown' in client.get('/recipe/lemon-chickpea-bowl').text
