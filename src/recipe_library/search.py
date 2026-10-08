"""Disposable, transactional SQLite index of a validated catalog."""
from contextlib import closing
from pathlib import Path
import json
import re
import sqlite3

from .loader import load_catalog, load_ingredients, load_substitutions
from .models import Recipe
from .nutrition import per_serving_macros


class SearchError(ValueError):
    pass


def rebuild_index(recipes: Path, database: Path, ingredients: Path = Path("ingredients"),
                  substitutions: Path | None = None) -> int:
    # Never touch the current index on invalid input.
    library = load_ingredients(ingredients)
    rules = load_substitutions(substitutions or ingredients.parent / "substitutions", library)
    catalog = load_catalog(recipes, library, rules)
    database.parent.mkdir(parents=True, exist_ok=True)
    try:
        with closing(sqlite3.connect(database)) as db, db:
            db.execute("BEGIN IMMEDIATE")
            # The index is disposable: recreate tables so new columns never need migrating.
            for table in ("recipe_fts", "tags", "recipes"):
                db.execute(f"DROP TABLE IF EXISTS {table}")
            db.execute("CREATE TABLE recipes (id TEXT PRIMARY KEY, title TEXT, minutes REAL, category TEXT,"
                       " served TEXT, calories REAL, protein REAL, payload TEXT)")
            db.execute("CREATE VIRTUAL TABLE recipe_fts USING fts5(id UNINDEXED, title, ingredients, tags, description)")
            db.execute("CREATE TABLE tags (recipe_id TEXT, tag TEXT, PRIMARY KEY(recipe_id, tag))")
            for recipe in catalog.values():
                macros = per_serving_macros(recipe, library)
                db.execute("INSERT INTO recipes VALUES (?, ?, ?, ?, ?, ?, ?, ?)", (
                    recipe.id, recipe.title, (recipe.times.prep_minutes + recipe.times.cook_minutes)
                    if recipe.times.prep_minutes is not None and recipe.times.cook_minutes is not None else None,
                    recipe.category, "".join(f",{value}," for value in recipe.served),
                    macros.get("calories_kcal"), macros.get("protein_g"),
                    recipe.model_dump_json(exclude_unset=True),
                ))
                db.execute("INSERT INTO recipe_fts VALUES (?, ?, ?, ?, ?)", (
                    recipe.id, recipe.title, " ".join(i.ingredient for i in recipe.ingredients),
                    " ".join(recipe.tags), recipe.description or "",
                ))
                db.executemany("INSERT INTO tags VALUES (?, ?)", [(recipe.id, tag) for tag in set(recipe.tags)])
        return len(catalog)
    except sqlite3.Error as exc:
        raise SearchError(f"Cannot build search index (SQLite FTS5 is required): {exc}") from exc


class SearchIndex:
    def __init__(self, database: Path):
        self.database = database.resolve()

    def _connect(self):
        try:
            return sqlite3.connect(self.database.as_uri() + "?mode=ro", uri=True)
        except sqlite3.Error as exc:
            raise SearchError("Search index unavailable; run recipe-library index first.") from exc

    def search(self, query: str = "", tag: str | None = None,
               max_minutes: float | None = None, limit: int = 50, offset: int = 0, *,
               category: str | None = None, tags: tuple[str, ...] = (), served: tuple[str, ...] = (),
               max_calories: float | None = None, min_protein: float | None = None,
               ids: set[str] | None = None) -> dict:
        """Filters combine with AND; every listed tag must match, any listed served value may.
        Recipes without a time or macro value are excluded when that filter is used."""
        if len(query) > 200 or not 1 <= limit <= 100 or offset < 0:
            raise SearchError("Use a query up to 200 characters, limit 1–100, and nonnegative offset.")
        for label, value in (("Maximum minutes", max_minutes), ("Maximum calories", max_calories), ("Minimum protein", min_protein)):
            if value is not None and (not 0 <= value < float("inf")):
                raise SearchError(f"{label} must be finite and nonnegative.")
        tokens = re.findall(r"[^\W_]+", query, flags=re.UNICODE)
        clauses, params = [], []
        join = ""
        order = "r.title COLLATE NOCASE, r.id"
        if tokens:
            # Treat every input word literally; do not expose the FTS query language.
            clauses.append("recipe_fts MATCH ?")
            params.append(" AND ".join('"' + token + '"' for token in tokens))
            join = " JOIN recipe_fts ON recipe_fts.id = r.id"
            order = "bm25(recipe_fts, 0, 5, 2, 1, 1), " + order
        elif query.strip():
            return {"items": [], "total": 0, "limit": limit, "offset": offset}
        for item in dict.fromkeys(([tag] if tag else []) + list(tags)):
            clauses.append("EXISTS (SELECT 1 FROM tags t WHERE t.recipe_id=r.id AND t.tag=?)")
            params.append(item)
        if served:
            clauses.append("(" + " OR ".join("instr(r.served, ?) > 0" for _ in served) + ")")
            params += [f",{value}," for value in served]
        for column, operator, value in (("minutes", "<=", max_minutes), ("calories", "<=", max_calories),
                                        ("protein", ">=", min_protein), ("category", "=", category)):
            if value is not None:
                clauses.append(f"r.{column} {operator} ?")
                params.append(value)
        if ids is not None:
            clauses.append("r.id IN (SELECT value FROM json_each(?))")
            params.append(json.dumps(sorted(ids)))
        where = " WHERE " + " AND ".join(clauses) if clauses else ""
        with closing(self._connect()) as db:
            total = db.execute("SELECT count(*) FROM recipes r" + join + where, params).fetchone()[0]
            rows = db.execute("SELECT r.payload FROM recipes r" + join + where + " ORDER BY " + order + " LIMIT ? OFFSET ?", [*params, limit, offset]).fetchall()
        return {"items": [Recipe.model_validate_json(row[0]) for row in rows], "total": total, "limit": limit, "offset": offset}

    def get(self, recipe_id: str) -> Recipe | None:
        with closing(self._connect()) as db:
            row = db.execute("SELECT payload FROM recipes WHERE id=?", (recipe_id,)).fetchone()
        return Recipe.model_validate_json(row[0]) if row else None

    def tags(self) -> list[str]:
        with closing(self._connect()) as db:
            return [row[0] for row in db.execute("SELECT DISTINCT tag FROM tags ORDER BY tag COLLATE NOCASE")]
