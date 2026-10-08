from copy import deepcopy
from pathlib import Path

import pytest
import yaml
from pydantic import ValidationError

from recipe_library.cli import main
from recipe_library.loader import CatalogError, load_catalog
from recipe_library.models import Recipe
from recipe_library.personal import DEFAULTS, initialize_personal
from recipe_library.variations import resolve_variation

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def recipe_data():
    return yaml.safe_load((ROOT / "recipes/lemon-chickpea-bowl.yaml").read_text())


def test_sample_catalog_and_variation():
    base = load_catalog(ROOT / "recipes")["lemon-chickpea-bowl"]
    resolved = resolve_variation(base, "extra-chickpeas")
    assert resolved.ingredients[0].quantity == 360
    assert base.ingredients[0].quantity == 240
    assert resolved.nutrition is None
    assert resolved.notes == base.variations[0].instruction_notes


@pytest.mark.parametrize("field,value", [
    ("servings", 0), ("servings", True), ("servings", "2"),
    ("servings", float("inf")), ("title", " "),
    ("schema_version", 2), ("schema_version", True),
    ("schema_version", 1.0), ("instructions", []), ("ingredients", []),
])
def test_invalid_recipe_fields(recipe_data, field, value):
    recipe_data[field] = value
    with pytest.raises(ValidationError):
        Recipe.model_validate(recipe_data)


@pytest.mark.parametrize("field,value", [
    ("quantity", -1), ("quantity", True), ("quantity", None),
    ("unit", "bucket"), ("optional", "false"), ("ingredient", ""),
])
def test_invalid_ingredients(recipe_data, field, value):
    recipe_data["ingredients"][0][field] = value
    with pytest.raises(ValidationError):
        Recipe.model_validate(recipe_data)


def test_unknown_fields_rejected(recipe_data):
    recipe_data["last_cooked"] = "2026-10-08"
    with pytest.raises(ValidationError, match="Extra inputs"):
        Recipe.model_validate(recipe_data)


@pytest.mark.parametrize("collection", ["ingredients", "variations"])
def test_duplicate_local_ids(recipe_data, collection):
    recipe_data[collection].append(deepcopy(recipe_data[collection][0]))
    with pytest.raises(ValidationError, match="duplicate"):
        Recipe.model_validate(recipe_data)


@pytest.mark.parametrize("overrides", [
    {"missing": {"quantity": 10}},
    {"chickpeas": {"quantity": None}},
    {"chickpeas": {"ingredient": None}},
    {"chickpeas": {}},
])
def test_invalid_variation_overrides(recipe_data, overrides):
    recipe_data["variations"][0]["ingredient_overrides"] = overrides
    with pytest.raises(ValidationError):
        Recipe.model_validate(recipe_data)


def test_variation_does_not_inherit_known_nutrition(recipe_data):
    recipe_data["nutrition"] = {"basis": "per_serving", "status": "estimated", "protein_g": 10}
    base = Recipe.model_validate(recipe_data)
    assert resolve_variation(base, "extra-chickpeas").nutrition is None
    assert base.nutrition.protein_g == 10
    with pytest.raises(ValueError, match="has no variation"):
        resolve_variation(base, "missing")


@pytest.mark.parametrize("nutrition", [
    {"basis": "per_serving", "status": "unknown", "protein_g": 10},
    {"basis": "whole_recipe", "status": "estimated"},
    {"basis": "per_serving", "status": "estimated", "fat_g": -1},
    {"basis": "per_serving", "status": "source_provided", "fat_g": 1},
])
def test_inconsistent_nutrition_rejected(recipe_data, nutrition):
    recipe_data["nutrition"] = nutrition
    with pytest.raises(ValidationError):
        Recipe.model_validate(recipe_data)


def test_loader_reports_all_files_and_fields(tmp_path, recipe_data):
    recipe_data["servings"] = 0
    (tmp_path / "bad.yaml").write_text(yaml.safe_dump(recipe_data))
    (tmp_path / "syntax.yml").write_text("title: [broken")
    with pytest.raises(CatalogError) as error:
        load_catalog(tmp_path)
    message = str(error.value)
    assert "bad.yaml: servings:" in message
    assert "syntax.yml" in message


def test_catalog_duplicate_ids(tmp_path, recipe_data):
    for name in ("one.yaml", "two.yml"):
        (tmp_path / name).write_text(yaml.safe_dump(recipe_data))
    with pytest.raises(CatalogError, match="duplicate recipe ID"):
        load_catalog(tmp_path)


@pytest.mark.parametrize("content", [
    "title: one\ntitle: two", "!!python/object:builtins.object {}", "[]", "",
])
def test_bad_yaml_documents(tmp_path, content):
    (tmp_path / "bad.yaml").write_text(content)
    with pytest.raises(CatalogError):
        load_catalog(tmp_path)


def test_empty_and_missing_catalogs(tmp_path):
    with pytest.raises(CatalogError, match="no YAML"):
        load_catalog(tmp_path)
    with pytest.raises(CatalogError, match="does not exist"):
        load_catalog(tmp_path / "missing")


def test_personal_initialization_preserves_existing_data(tmp_path):
    personal = tmp_path / "personal"
    created = initialize_personal(personal)
    assert len(created) == len(DEFAULTS)
    for path in created:
        data = yaml.safe_load(path.read_text())
        assert data["schema_version"] == 1
        assert [] in data.values()
    history = personal / "cooking-history.yaml"
    history.write_text("my existing history\n")
    assert initialize_personal(personal) == []
    assert history.read_text() == "my existing history\n"


def test_cli_success_failure_and_schema(tmp_path, capsys):
    assert main(["validate", str(ROOT / "recipes")]) == 0
    assert "Validated 3" in capsys.readouterr().out
    assert main(["validate", str(tmp_path)]) == 1
    assert "no YAML" in capsys.readouterr().err
    assert main(["schema"]) == 0
    assert '"Recipe"' in capsys.readouterr().out
