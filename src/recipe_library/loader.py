"""Load an entire catalog or report all invalid files without partial success."""
from pathlib import Path

import yaml
from pydantic import ValidationError

from .models import IngredientFile, LibraryIngredient, Recipe, SubstitutionFile, SubstitutionRule


class CatalogError(ValueError):
    pass


class UniqueKeyLoader(yaml.SafeLoader):
    """Reject duplicate YAML keys instead of silently replacing values."""


def _mapping(loader, node, deep=False):
    mapping = {}
    for key_node, value_node in node.value:
        key = loader.construct_object(key_node, deep=deep)
        try:
            duplicate = key in mapping
        except TypeError as exc:
            raise yaml.constructor.ConstructorError(
                None, None, "mapping keys must be scalar", key_node.start_mark
            ) from exc
        if duplicate:
            raise yaml.constructor.ConstructorError(
                None, None, f"duplicate key: {key}", key_node.start_mark
            )
        mapping[key] = loader.construct_object(value_node, deep=deep)
    return mapping


UniqueKeyLoader.add_constructor(yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG, _mapping)


def _yaml_files(directory: Path) -> list[Path]:
    return sorted(p for p in directory.rglob("*") if p.suffix.lower() in {".yaml", ".yml"} and p.is_file())


def _read(path: Path, model, errors: list[str]):
    try:
        return model.model_validate(yaml.load(path.read_text(encoding="utf-8"), Loader=UniqueKeyLoader))
    except ValidationError as exc:
        for error in exc.errors():
            field = ".".join(str(part) for part in error["loc"]) or "file"
            errors.append(f"{path}: {field}: {error['msg']}")
    except (OSError, UnicodeError, yaml.YAMLError) as exc:
        errors.append(f"{path}: {exc}")
    return None


def load_ingredients(directory: Path) -> dict[str, LibraryIngredient]:
    """Load the shared ingredient library; a missing directory is an empty library."""
    if not directory.exists():
        return {}
    if not directory.is_dir():
        raise CatalogError(f"{directory}: ingredient library is not a directory")
    library, origins, errors = {}, {}, []
    for path in _yaml_files(directory):
        data = _read(path, IngredientFile, errors)
        for item in data.ingredients if data else []:
            if item.id in library:
                errors.append(f"{path}: duplicate ingredient ID '{item.id}' (also in {origins[item.id]})")
            else:
                library[item.id] = item
                origins[item.id] = path
    if errors:
        raise CatalogError("\n".join(errors))
    return library


def load_substitutions(directory: Path, ingredients: dict[str, LibraryIngredient]) -> dict[str, SubstitutionRule]:
    """Load universal substitution rules; every ingredient they mention must be in the library."""
    if not directory.exists():
        return {}
    if not directory.is_dir():
        raise CatalogError(f"{directory}: substitution library is not a directory")
    rules, origins, errors = {}, {}, []
    for path in _yaml_files(directory):
        data = _read(path, SubstitutionFile, errors)
        expanded = (data.substitutions + [r for family in data.families for r in family.rules()]) if data else []
        for rule in expanded:
            if rule.id in rules:
                errors.append(f"{path}: duplicate substitution ID '{rule.id}' (also in {origins[rule.id]})")
                continue
            rules[rule.id] = rule
            origins[rule.id] = path
            for ref in [rule.replaces] + [item.ref for item in rule.with_]:
                if ref not in ingredients:
                    errors.append(f"{path}: substitution {rule.id}: unknown library ingredient '{ref}'")
    if errors:
        raise CatalogError("\n".join(errors))
    return rules


def load_catalog(directory: Path, ingredients: dict[str, LibraryIngredient] | None = None,
                 substitutions: dict[str, SubstitutionRule] | None = None) -> dict[str, Recipe]:
    """Load every recipe; when libraries are given, every ingredient ref and every
    substitution a recipe vetoes or annotates must exist in them."""
    if not directory.is_dir():
        raise CatalogError(f"{directory}: recipe directory does not exist")
    files = _yaml_files(directory)
    if not files:
        raise CatalogError(f"{directory}: no YAML recipes found")
    recipes = {}
    origins = {}
    errors = []
    for path in files:
        recipe = _read(path, Recipe, errors)
        if recipe is None:
            continue
        if recipe.id in recipes:
            errors.append(f"{path}: duplicate recipe ID '{recipe.id}' (also in {origins[recipe.id]})")
            continue
        recipes[recipe.id] = recipe
        origins[recipe.id] = path
        if ingredients is not None:
            refs = [(f"ingredients.{i.id}", i.ref) for i in recipe.ingredients]
            refs += [(f"variations.{v.id}.ingredient_overrides.{key}", o.ref)
                     for v in recipe.variations for key, o in v.ingredient_overrides.items()]
            errors += [f"{path}: {field}.ref: unknown library ingredient '{ref}'"
                       for field, ref in refs if ref is not None and ref not in ingredients]
        if ingredients is not None:
            for item in recipe.ingredients:
                entry = ingredients.get(item.ref) if item.ref else None
                if item.product and (entry is None or entry.product(item.product) is None):
                    errors.append(f"{path}: ingredients.{item.id}.product: '{item.product}' is not a product of {item.ref}")
        if substitutions is not None:
            for item in recipe.ingredients:
                for kind in ("veto", "notes"):
                    for rule_id in getattr(item.substitutions, kind, {}) if item.substitutions else {}:
                        rule = substitutions.get(rule_id)
                        if rule is None:
                            errors.append(f"{path}: ingredients.{item.id}.substitutions.{kind}: unknown substitution '{rule_id}'")
                        elif rule.replaces != item.ref:
                            errors.append(f"{path}: ingredients.{item.id}.substitutions.{kind}: '{rule_id}' replaces {rule.replaces}, not {item.ref}")
    if errors:
        raise CatalogError("\n".join(errors))
    return recipes
