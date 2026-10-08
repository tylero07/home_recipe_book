"""Offline lookup of USDA FoodData Central data for the ingredient library.

The public-domain SR Legacy (CSV) and Foundation Foods (JSON) downloads are read
straight from their zip files into a disposable SQLite database. ``link`` copies
one food's macros and portion weights into a library entry, citing its FDC ID.
"""
from contextlib import closing
import csv
import io
import json
from pathlib import Path
import re
import sqlite3
import zipfile

import yaml

from .loader import CatalogError, UniqueKeyLoader
from .models import IngredientFile

SR_ZIP = "FoodData_Central_sr_legacy_food_csv_2018-04.zip"
FOUNDATION_ZIP = "FoodData_Central_foundation_food_json_2025-04-24.zip"
DATASETS = {"sr_legacy_food": "SR Legacy", "Foundation": "Foundation"}
# Nutrient IDs in preference order: energy falls back to Atwater factors; carbohydrate
# falls back to "by summation" where "by difference" was not reported.
MACRO_IDS = {
    "calories_kcal": (1008, 2047, 2048),
    "protein_g": (1003,),
    "carbohydrate_g": (1005, 1050),
    "fat_g": (1004, 1085),
}


class UsdaError(ValueError):
    pass


def _macros(amounts: dict[int, float]) -> dict[str, float | None]:
    return {macro: next((amounts[i] for i in ids if i in amounts), None) for macro, ids in MACRO_IDS.items()}


def _portion_label(amount, unit, description, modifier):
    words = [w for w in (unit if unit != "undetermined" else "", description, modifier) if w]
    return f"{amount:g} " + ", ".join(words) if amount else ", ".join(words)


def _sr_legacy(path: Path):
    wanted = {i for ids in MACRO_IDS.values() for i in ids}
    with zipfile.ZipFile(path) as archive:
        prefix = next(n for n in archive.namelist() if n.endswith("food.csv")).rsplit("/", 1)[0] + "/"

        def rows(name):
            with archive.open(prefix + name) as stream:
                yield from csv.DictReader(io.TextIOWrapper(stream, "utf-8"))

        categories = {r["id"]: r["description"] for r in rows("food_category.csv")}
        units = {r["id"]: r["name"] for r in rows("measure_unit.csv")}
        foods = {r["fdc_id"]: (r["description"], categories.get(r["food_category_id"], "")) for r in rows("food.csv")}
        amounts: dict[str, dict[int, float]] = {}
        for r in rows("food_nutrient.csv"):
            nutrient = int(r["nutrient_id"])
            if nutrient in wanted and r["fdc_id"] in foods and r["amount"]:
                amounts.setdefault(r["fdc_id"], {})[nutrient] = float(r["amount"])
        portions: dict[str, list] = {}
        for r in rows("food_portion.csv"):
            if r["fdc_id"] in foods and r["gram_weight"]:
                amount = float(r["amount"] or 0)
                label = _portion_label(amount, units.get(r["measure_unit_id"], ""), r["portion_description"], r["modifier"])
                portions.setdefault(r["fdc_id"], []).append((label, float(r["gram_weight"])))
    for fdc_id, (description, category) in foods.items():
        yield int(fdc_id), "SR Legacy", description, category, _macros(amounts.get(fdc_id, {})), portions.get(fdc_id, [])


def _foundation(path: Path):
    with zipfile.ZipFile(path) as archive:
        data = json.load(archive.open(archive.namelist()[0]))
    for food in data["FoundationFoods"]:
        amounts = {n["nutrient"]["id"]: n["amount"] for n in food.get("foodNutrients", []) if "amount" in n}
        portions = [(_portion_label(p.get("value") or p.get("amount") or 0, p.get("measureUnit", {}).get("name", ""),
                                    p.get("portionDescription", ""), p.get("modifier", "")), p["gramWeight"])
                    for p in food.get("foodPortions", []) if p.get("gramWeight")]
        yield (food["fdcId"], "Foundation", food["description"], food.get("foodCategory", {}).get("description", ""),
               _macros(amounts), portions)


def build(directory: Path, database: Path) -> int:
    """Rebuild the lookup database from whichever downloaded zips are present."""
    sources = [(directory / SR_ZIP, _sr_legacy), (directory / FOUNDATION_ZIP, _foundation)]
    if not any(path.exists() for path, _ in sources):
        raise UsdaError(f"{directory}: no USDA downloads found ({SR_ZIP} or {FOUNDATION_ZIP})")
    database.parent.mkdir(parents=True, exist_ok=True)
    count = 0
    with closing(sqlite3.connect(database)) as db, db:
        for table in ("foods", "portions", "food_fts"):
            db.execute(f"DROP TABLE IF EXISTS {table}")
        db.execute("CREATE TABLE foods (fdc_id INTEGER PRIMARY KEY, dataset TEXT, description TEXT, category TEXT,"
                   " calories_kcal REAL, protein_g REAL, carbohydrate_g REAL, fat_g REAL)")
        db.execute("CREATE TABLE portions (fdc_id INTEGER, number INTEGER, label TEXT, grams REAL)")
        db.execute("CREATE VIRTUAL TABLE food_fts USING fts5(fdc_id UNINDEXED, description, category)")
        for path, reader in sources:
            if not path.exists():
                continue
            for fdc_id, dataset, description, category, macros, portions in reader(path):
                db.execute("INSERT INTO foods VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                           (fdc_id, dataset, description, category, *macros.values()))
                db.execute("INSERT INTO food_fts VALUES (?, ?, ?)", (fdc_id, description, category))
                db.executemany("INSERT INTO portions VALUES (?, ?, ?, ?)",
                               [(fdc_id, n, label, grams) for n, (label, grams) in enumerate(portions, 1)])
                count += 1
    return count


def _connect(database: Path):
    if not database.exists():
        raise UsdaError(f"{database}: lookup database missing; run `recipe-library usda build` first")
    connection = sqlite3.connect(database)
    connection.row_factory = sqlite3.Row
    return connection


def search(database: Path, query: str, limit: int = 15) -> list[dict]:
    """Every word must appear; Foundation entries (newer analyses) sort first among equals."""
    tokens = re.findall(r"[^\W_]+", query)
    if not tokens:
        return []
    with closing(_connect(database)) as db:
        rows = db.execute(
            "SELECT f.* FROM food_fts JOIN foods f ON f.fdc_id = food_fts.fdc_id WHERE food_fts MATCH ?"
            " ORDER BY bm25(food_fts, 0, 4, 1), f.dataset = 'SR Legacy', length(f.description) LIMIT ?",
            (" AND ".join(f'"{t}"' for t in tokens), limit)).fetchall()
    return [dict(row) for row in rows]


def show(database: Path, fdc_id: int) -> dict:
    with closing(_connect(database)) as db:
        food = db.execute("SELECT * FROM foods WHERE fdc_id = ?", (fdc_id,)).fetchone()
        if food is None:
            raise UsdaError(f"FDC ID {fdc_id} is not in the downloaded datasets")
        portions = db.execute("SELECT number, label, grams FROM portions WHERE fdc_id = ? ORDER BY number", (fdc_id,)).fetchall()
    return {**dict(food), "portions": [dict(p) for p in portions]}


def link(library: Path, ingredient_id: str, food: dict, cup: int | None = None, each: int | None = None,
         per_cup: float = 1, per_each: float = 1, proxy: bool = False) -> Path:
    """Write USDA macros (and chosen portion weights) into one library entry.

    ``cup``/``each`` are portion numbers from ``show``; ``per_cup``/``per_each`` say how
    many cups or items that portion holds (e.g. a "1 tbsp" portion has per_cup=1/16).
    ``proxy`` marks a similar food standing in for one USDA doesn't list; its values
    are then labeled estimated rather than source-provided.
    """
    portions = {p["number"]: p for p in food["portions"]}
    for number in (cup, each):
        if number is not None and number not in portions:
            raise UsdaError(f"FDC ID {food['fdc_id']} has no portion {number}")
    for path in sorted(p for p in library.rglob("*") if p.suffix.lower() in {".yaml", ".yml"}):
        data = yaml.load(path.read_text(encoding="utf-8"), Loader=UniqueKeyLoader)
        entry = next((e for e in data.get("ingredients", []) if e.get("id") == ingredient_id), None)
        if entry is None:
            continue
        values = {m: food[m] for m in MACRO_IDS if food[m] is not None}
        if not values:
            raise UsdaError(f"FDC ID {food['fdc_id']} has no macro values")
        citation = f"USDA FoodData Central ({food['dataset']}), FDC ID {food['fdc_id']}: {food['description']}"
        if proxy:
            citation = f"Proxy from a similar food: {citation}"
        entry["usda"] = {"fdc_id": food["fdc_id"], "dataset": food["dataset"], "description": food["description"]}
        entry["nutrition_per_100g"] = {"status": "estimated" if proxy else "source_provided", **values, "source": citation}
        notes = [n for n in entry.get("notes", []) if not n.startswith(("Cup weight from USDA", "Each weight from USDA"))]
        if cup is not None:
            entry["grams_per_cup"] = round(portions[cup]["grams"] / per_cup, 1)
            notes.append(f"Cup weight from USDA portion '{portions[cup]['label']}' ({portions[cup]['grams']:g} g).")
        if each is not None:
            entry["grams_each"] = round(portions[each]["grams"] / per_each, 1)
            notes.append(f"Each weight from USDA portion '{portions[each]['label']}' ({portions[each]['grams']:g} g).")
        if notes:
            entry["notes"] = notes
        IngredientFile.model_validate(data)
        path.write_text(yaml.safe_dump(data, sort_keys=False, allow_unicode=True, width=100), encoding="utf-8")
        return path
    raise CatalogError(f"{library}: no library ingredient '{ingredient_id}'")
