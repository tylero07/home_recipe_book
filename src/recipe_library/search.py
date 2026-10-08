"""Disposable, transactional SQLite index of a validated catalog."""
from contextlib import closing
from pathlib import Path
import re
import sqlite3

from .loader import load_catalog
from .models import Recipe


class SearchError(ValueError):
    pass


def rebuild_index(recipes: Path, database: Path) -> int:
    catalog = load_catalog(recipes)  # Never touch the current index on invalid input.
    database.parent.mkdir(parents=True, exist_ok=True)
    try:
        with closing(sqlite3.connect(database)) as db, db:
            db.execute("BEGIN IMMEDIATE")
            db.execute("CREATE TABLE IF NOT EXISTS recipes (id TEXT PRIMARY KEY, title TEXT, minutes REAL, payload TEXT)")
            db.execute("CREATE VIRTUAL TABLE IF NOT EXISTS recipe_fts USING fts5(id UNINDEXED, title, ingredients, tags, description)")
            db.execute("CREATE TABLE IF NOT EXISTS tags (recipe_id TEXT, tag TEXT, PRIMARY KEY(recipe_id, tag))")
            for table in ("recipe_fts", "tags", "recipes"):
                db.execute(f"DELETE FROM {table}")
            for recipe in catalog.values():
                db.execute("INSERT INTO recipes VALUES (?, ?, ?, ?)", (
                    recipe.id, recipe.title, (recipe.times.prep_minutes + recipe.times.cook_minutes)
                    if recipe.times.prep_minutes is not None and recipe.times.cook_minutes is not None else None,
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
               max_minutes: float | None = None, limit: int = 50, offset: int = 0) -> dict:
        if len(query) > 200 or not 1 <= limit <= 100 or offset < 0:
            raise SearchError("Use a query up to 200 characters, limit 1–100, and nonnegative offset.")
        if max_minutes is not None and (not 0 <= max_minutes < float("inf")):
            raise SearchError("Maximum minutes must be finite and nonnegative.")
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
        if tag:
            clauses.append("EXISTS (SELECT 1 FROM tags t WHERE t.recipe_id=r.id AND t.tag=?)")
            params.append(tag)
        if max_minutes is not None:
            clauses.append("r.minutes <= ?")
            params.append(max_minutes)
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
