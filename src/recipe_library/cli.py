"""Small command-line entry point for maintaining the recipe library."""
import argparse
import json
from pathlib import Path
import sys

from .loader import CatalogError, load_catalog, load_ingredients, load_substitutions
from .models import IngredientFile, Recipe, SubstitutionFile
from .personal import initialize_personal
from .search import SearchError, SearchIndex, rebuild_index


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(prog="recipe-library")
    commands = parser.add_subparsers(dest="command", required=True)
    validate = commands.add_parser("validate", help="Validate all recipes, reporting file and field errors")
    validate.add_argument("directory", nargs="?", type=Path, default=Path("recipes"))
    validate.add_argument("--ingredients", type=Path, default=Path("ingredients"))
    validate.add_argument("--substitutions", type=Path, default=Path("substitutions"))
    schema = commands.add_parser("schema", help="Print the recipe or ingredient-library JSON Schema")
    schema.add_argument("kind", nargs="?", choices=["recipe", "ingredients", "substitutions"], default="recipe")
    personal = commands.add_parser("init-personal", help="Create empty personal files; preserve existing files")
    personal.add_argument("directory", nargs="?", type=Path, default=Path("personal"))
    index = commands.add_parser("index", help="Rebuild the disposable search index")
    index.add_argument("--recipes", type=Path, default=Path("recipes"))
    index.add_argument("--database", type=Path, default=Path("data/recipes.sqlite3"))
    index.add_argument("--ingredients", type=Path, default=Path("ingredients"))
    search = commands.add_parser("search", help="Search the current index")
    search.add_argument("query", nargs="?", default="")
    search.add_argument("--tag")
    search.add_argument("--max-minutes", type=float)
    search.add_argument("--database", type=Path, default=Path("data/recipes.sqlite3"))
    serve = commands.add_parser("serve", help="Rebuild the index and start the local recipe browser")
    serve.add_argument("--recipes", type=Path, default=Path("recipes"))
    serve.add_argument("--database", type=Path, default=Path("data/recipes.sqlite3"))
    serve.add_argument("--ingredients", type=Path, default=Path("ingredients"))
    serve.add_argument("--personal", type=Path, default=Path("personal"))
    serve.add_argument("--port", type=int, default=8000)
    usda = commands.add_parser("usda", help="Look up USDA FoodData Central nutrition for the ingredient library")
    usda.add_argument("--directory", type=Path, default=Path("data/usda"), help="Folder holding the USDA downloads")
    usda_commands = usda.add_subparsers(dest="usda_command", required=True)
    usda_commands.add_parser("build", help="Build the lookup database from the downloaded zips")
    usda_search = usda_commands.add_parser("search", help="Find foods whose description contains every word")
    usda_search.add_argument("query")
    usda_show = usda_commands.add_parser("show", help="Show a food's macros per 100 g and numbered portions")
    usda_show.add_argument("fdc_id", type=int)
    usda_link = usda_commands.add_parser("link", help="Copy a food's macros (and portion weights) into a library entry")
    usda_link.add_argument("ingredient")
    usda_link.add_argument("fdc_id", type=int)
    usda_link.add_argument("--cup", type=int, help="Portion number giving the weight of a cup")
    usda_link.add_argument("--per-cup", type=float, default=1, help="Cups in that portion (default 1)")
    usda_link.add_argument("--each", type=int, help="Portion number giving the weight of one item")
    usda_link.add_argument("--per-each", type=float, default=1, help="Items in that portion (default 1)")
    usda_link.add_argument("--proxy", action="store_true", help="The food stands in for one USDA doesn't list")
    usda_link.add_argument("--ingredients", type=Path, default=Path("ingredients"))
    args = parser.parse_args(argv)
    try:
        if args.command == "validate":
            library = load_ingredients(args.ingredients)
            rules = load_substitutions(args.substitutions, library)
            catalog = load_catalog(args.directory, library, rules)
            print(f"Validated {len(catalog)} recipe(s) in {args.directory}, {len(library)} library ingredient(s), "
                  f"and {len(rules)} substitution(s).")
        elif args.command == "schema":
            model = {"recipe": Recipe, "ingredients": IngredientFile, "substitutions": SubstitutionFile}[args.kind]
            print(json.dumps(model.model_json_schema(by_alias=True), indent=2))
        elif args.command == "init-personal":
            created = initialize_personal(args.directory)
            print(f"Created {len(created)} personal file(s) in {args.directory}; existing files preserved.")
        elif args.command == "index":
            print(f"Indexed {rebuild_index(args.recipes, args.database, args.ingredients)} recipe(s).")
        elif args.command == "search":
            results = SearchIndex(args.database).search(args.query, args.tag, args.max_minutes)
            for recipe in results["items"]:
                print(f"{recipe.id}: {recipe.title}")
            print(f"{results['total']} recipe(s) found.")
        elif args.command == "usda":
            from . import usda as fdc
            database = args.directory / "usda.sqlite3"
            if args.usda_command == "build":
                print(f"Indexed {fdc.build(args.directory, database)} USDA foods into {database}.")
            elif args.usda_command == "search":
                for food in fdc.search(database, args.query):
                    print(f"{food['fdc_id']}  [{food['dataset']}] {food['description']}")
            elif args.usda_command == "show":
                food = fdc.show(database, args.fdc_id)
                print(f"{food['fdc_id']}  [{food['dataset']}] {food['description']} — {food['category']}")
                print("Per 100 g: " + ", ".join(f"{k} {food[k]:g}" for k in fdc.MACRO_IDS if food[k] is not None))
                for portion in food["portions"]:
                    print(f"  portion {portion['number']}: {portion['label']} = {portion['grams']:g} g")
            else:
                food = fdc.show(database, args.fdc_id)
                path = fdc.link(args.ingredients, args.ingredient, food, args.cup, args.each, args.per_cup,
                                args.per_each, args.proxy)
                load_ingredients(args.ingredients)
                print(f"Linked {args.ingredient} to FDC ID {args.fdc_id} in {path}.")
        elif args.command == "serve":
            import uvicorn
            from .api import create_app
            uvicorn.run(create_app(args.recipes, args.database, args.ingredients, args.personal), host="127.0.0.1", port=args.port)
    except (CatalogError, SearchError, OSError, ValueError) as exc:
        print(str(exc), file=sys.stderr)
        return 1
    return 0
