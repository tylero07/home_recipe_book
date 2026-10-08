"""Load an entire catalog or report all invalid files without partial success."""
from pathlib import Path

import yaml
from pydantic import ValidationError

from .models import Recipe


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


def load_catalog(directory: Path) -> dict[str, Recipe]:
    if not directory.is_dir():
        raise CatalogError(f"{directory}: recipe directory does not exist")
    files = sorted(p for p in directory.rglob("*") if p.suffix.lower() in {".yaml", ".yml"} and p.is_file())
    if not files:
        raise CatalogError(f"{directory}: no YAML recipes found")
    recipes = {}
    origins = {}
    errors = []
    for path in files:
        try:
            recipe = Recipe.model_validate(yaml.load(path.read_text(encoding="utf-8"), Loader=UniqueKeyLoader))
            if recipe.id in recipes:
                errors.append(f"{path}: duplicate recipe ID '{recipe.id}' (also in {origins[recipe.id]})")
            else:
                recipes[recipe.id] = recipe
                origins[recipe.id] = path
        except ValidationError as exc:
            for error in exc.errors():
                field = ".".join(str(part) for part in error["loc"]) or "recipe"
                errors.append(f"{path}: {field}: {error['msg']}")
        except (OSError, UnicodeError, yaml.YAMLError) as exc:
            errors.append(f"{path}: {exc}")
    if errors:
        raise CatalogError("\n".join(errors))
    return recipes
