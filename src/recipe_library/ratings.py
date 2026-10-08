"""Personal recipe ratings, stored in the ignored personal directory."""
import os
from pathlib import Path
import tempfile
from typing import Annotated, Literal

from pydantic import Field, ValidationError
import yaml

from .loader import UniqueKeyLoader
from .models import Identifier, Model

Stars = Annotated[int, Field(ge=1, le=5, strict=True)]


class Rating(Model):
    recipe: Stars | None = None
    leftovers: Stars | None = None


class RatingsFile(Model):
    schema_version: Literal[1]
    ratings: dict[Identifier, Rating] = Field(default_factory=dict)


class RatingsError(ValueError):
    pass


def load_ratings(path: Path) -> dict[str, Rating]:
    """A missing file means nothing has been rated yet."""
    if not path.exists():
        return {}
    try:
        data = yaml.load(path.read_text(encoding="utf-8"), Loader=UniqueKeyLoader)
        return RatingsFile.model_validate(data).ratings
    except (OSError, UnicodeError, yaml.YAMLError, ValidationError) as exc:
        raise RatingsError(f"{path}: cannot read ratings: {exc}") from exc


def save_rating(path: Path, recipe_id: str, rating: Rating) -> None:
    """Replace one recipe's rating atomically; clearing both values removes the entry."""
    ratings = load_ratings(path)
    if rating.recipe is None and rating.leftovers is None:
        ratings.pop(recipe_id, None)
    else:
        ratings[recipe_id] = rating
    payload = {"schema_version": 1, "ratings": {key: value.model_dump(exclude_none=True) for key, value in sorted(ratings.items())}}
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=path.parent, delete=False, suffix=".tmp") as stream:
        yaml.safe_dump(payload, stream, sort_keys=False)
    os.replace(stream.name, path)


def matching_ids(ratings: dict[str, Rating], min_recipe: int | None, min_leftovers: int | None) -> set[str] | None:
    """Recipe IDs meeting both minimums, or None when no rating filter applies."""
    if min_recipe is None and min_leftovers is None:
        return None
    return {key for key, value in ratings.items()
            if (min_recipe is None or (value.recipe or 0) >= min_recipe)
            and (min_leftovers is None or (value.leftovers or 0) >= min_leftovers)}
