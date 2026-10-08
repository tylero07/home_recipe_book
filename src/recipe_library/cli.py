"""Small command-line entry point for maintaining the recipe library."""
import argparse
import json
from pathlib import Path
import sys

from .loader import CatalogError, load_catalog
from .models import Recipe
from .personal import initialize_personal
from .search import SearchError, SearchIndex, rebuild_index


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(prog="recipe-library")
    commands = parser.add_subparsers(dest="command", required=True)
    validate = commands.add_parser("validate", help="Validate all recipes, reporting file and field errors")
    validate.add_argument("directory", nargs="?", type=Path, default=Path("recipes"))
    commands.add_parser("schema", help="Print the recipe JSON Schema to standard output")
    personal = commands.add_parser("init-personal", help="Create empty personal files; preserve existing files")
    personal.add_argument("directory", nargs="?", type=Path, default=Path("personal"))
    index = commands.add_parser("index", help="Rebuild the disposable search index")
    index.add_argument("--recipes", type=Path, default=Path("recipes"))
    index.add_argument("--database", type=Path, default=Path("data/recipes.sqlite3"))
    search = commands.add_parser("search", help="Search the current index")
    search.add_argument("query", nargs="?", default="")
    search.add_argument("--tag")
    search.add_argument("--max-minutes", type=float)
    search.add_argument("--database", type=Path, default=Path("data/recipes.sqlite3"))
    serve = commands.add_parser("serve", help="Rebuild the index and start the local recipe browser")
    serve.add_argument("--recipes", type=Path, default=Path("recipes"))
    serve.add_argument("--database", type=Path, default=Path("data/recipes.sqlite3"))
    serve.add_argument("--port", type=int, default=8000)
    args = parser.parse_args(argv)
    try:
        if args.command == "validate":
            catalog = load_catalog(args.directory)
            print(f"Validated {len(catalog)} recipe(s) in {args.directory}.")
        elif args.command == "schema":
            print(json.dumps(Recipe.model_json_schema(), indent=2))
        elif args.command == "init-personal":
            created = initialize_personal(args.directory)
            print(f"Created {len(created)} personal file(s) in {args.directory}; existing files preserved.")
        elif args.command == "index":
            print(f"Indexed {rebuild_index(args.recipes, args.database)} recipe(s).")
        elif args.command == "search":
            results = SearchIndex(args.database).search(args.query, args.tag, args.max_minutes)
            for recipe in results["items"]:
                print(f"{recipe.id}: {recipe.title}")
            print(f"{results['total']} recipe(s) found.")
        elif args.command == "serve":
            import uvicorn
            from .api import create_app
            uvicorn.run(create_app(args.recipes, args.database), host="127.0.0.1", port=args.port)
    except (CatalogError, SearchError, OSError) as exc:
        print(str(exc), file=sys.stderr)
        return 1
    return 0
