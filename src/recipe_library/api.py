"""Read-only API and server-rendered recipe browser."""
from pathlib import Path
from urllib.parse import urlencode

from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from .search import SearchIndex, rebuild_index
from .shopping import ShoppingRequest, generate_list
from .formatting import format_quantity, format_amount
from .variations import resolve_variation


def create_app(recipes: Path = Path("recipes"), database: Path = Path("data/recipes.sqlite3")) -> FastAPI:
    rebuild_index(recipes, database)
    index = SearchIndex(database)
    app = FastAPI(title="Recipe Library", version="0.1.0")
    web = Path(__file__).parent / "web"
    templates = Jinja2Templates(directory=web)
    templates.env.filters["quantity"] = format_quantity
    templates.env.filters["amount"] = format_amount
    app.mount("/static", StaticFiles(directory=web / "static"), name="static")

    def detail(recipe_id: str, variation: str | None):
        base = index.get(recipe_id)
        if base is None:
            raise HTTPException(404, "Recipe not found")
        try:
            return base, resolve_variation(base, variation) if variation else base
        except ValueError as exc:
            raise HTTPException(404, "Variation not found") from exc

    @app.get("/recipes")
    def recipes_api(q: str = Query("", max_length=200), tag: str | None = None,
                    max_minutes: float | None = Query(None, ge=0, allow_inf_nan=False),
                    limit: int = Query(50, ge=1, le=100), offset: int = Query(0, ge=0)):
        return index.search(q, tag, max_minutes, limit, offset)

    @app.get("/recipes/{recipe_id}")
    def recipe_api(recipe_id: str, variation: str | None = None):
        return detail(recipe_id, variation)[1]

    @app.get("/tags")
    def tags_api():
        return index.tags()

    @app.get("/", response_class=HTMLResponse)
    def home(request: Request, q: str = Query("", max_length=200), tag: str = "",
             max_minutes: str = "", page: int = Query(1, ge=1)):
        # HTML forms submit an empty string for an unselected number field.
        try:
            minutes = float(max_minutes) if max_minutes.strip() else None
            if minutes is not None and not 0 <= minutes < float("inf"):
                raise ValueError
        except ValueError:
            raise HTTPException(422, "Maximum minutes must be a finite nonnegative number")
        results = index.search(q, tag, minutes, 12, (page - 1) * 12)
        def page_url(number):
            return "/?" + urlencode({"q": q, "tag": tag, "max_minutes": max_minutes, "page": number})
        return templates.TemplateResponse(request=request, name="index.html", context={
            "results": results, "tags": index.tags(), "q": q, "tag": tag,
            "max_minutes": max_minutes, "page": page,
            "previous": page_url(page - 1) if page > 1 else None,
            "next": page_url(page + 1) if results["total"] > page * 12 else None,
        })

    @app.get("/recipe/{recipe_id}", response_class=HTMLResponse)
    def recipe_page(request: Request, recipe_id: str, variation: str | None = None,
                    servings: float | None = Query(None, gt=0, allow_inf_nan=False)):
        base, recipe = detail(recipe_id, variation)
        original_servings = recipe.servings
        if servings is not None:
            recipe = recipe.model_copy(deep=True)
            factor = servings / original_servings
            for ingredient in recipe.ingredients:
                if ingredient.quantity is not None:
                    ingredient.quantity *= factor
            if recipe.nutrition and recipe.nutrition.basis == 'whole_recipe':
                for field in ('calories_kcal', 'protein_g', 'carbohydrate_g', 'fat_g'):
                    value = getattr(recipe.nutrition, field)
                    if value is not None:
                        setattr(recipe.nutrition, field, value * factor)
            recipe.servings = servings
        return templates.TemplateResponse(request=request, name="recipe.html", context={
            "recipe": recipe, "base": base, "variation": variation, "original_servings": original_servings,
        })

    @app.get("/shopping", response_class=HTMLResponse)
    def shopping_page(request: Request):
        catalog = []
        offset = 0
        while True:
            page = index.search(limit=100, offset=offset)
            catalog.extend(page["items"])
            offset += 100
            if offset >= page["total"]:
                break
        return templates.TemplateResponse(request=request, name="shopping.html", context={"catalog": catalog})

    @app.post("/shopping/generate")
    def shopping_generate(request: ShoppingRequest):
        try:
            return generate_list(index, request)
        except ValueError as exc:
            raise HTTPException(422, str(exc)) from exc

    return app
