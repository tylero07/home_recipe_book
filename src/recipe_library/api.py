"""Recipe API and server-rendered browser. Only personal ratings are written."""
from pathlib import Path
from urllib.parse import parse_qs, urlencode, urlsplit

from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from .loader import load_ingredients
from .models import CATEGORY_LABELS
from .nutrition import estimate_nutrition, per_serving_macros
from .ratings import Rating, RatingsError, load_ratings, matching_ids, save_rating
from .search import SearchIndex, rebuild_index
from .shopping import ShoppingRequest, generate_list
from .formatting import format_amount, format_number, format_quantity, tag_label, title_case
from .variations import resolve_variation


SERVED_LABELS = {"hot": "Hot", "cold": "Cold", "room-temperature": "Room Temperature"}


def _number(params, name, label, integer=False, low=0, high=float("inf")):
    raw = params.get(name, "").strip()
    if not raw:
        return None
    try:
        value = int(raw) if integer else float(raw)
        if not low <= value < high:
            raise ValueError
    except ValueError:
        raise HTTPException(422, f"{label} must be a number from {low}{f' to {high - 1}' if integer else ' up'}")
    return value


def parse_filters(params) -> dict:
    """Shared by the JSON API and the browser. Empty form fields mean 'no filter'."""
    category = params.get("category", "").strip() or None
    if category is not None and category not in CATEGORY_LABELS:
        raise HTTPException(422, "Unknown category")
    served = tuple(dict.fromkeys(v for v in params.getlist("served") if v))
    if any(v not in SERVED_LABELS for v in served):
        raise HTTPException(422, "Served must be hot, cold, or room-temperature")
    return {
        "category": category, "served": served,
        "tags": tuple(dict.fromkeys(v for v in params.getlist("tag") if v)),
        "max_minutes": _number(params, "max_minutes", "Maximum minutes"),
        "max_calories": _number(params, "max_calories", "Maximum calories"),
        "min_protein": _number(params, "min_protein", "Minimum protein"),
        "min_rating": _number(params, "min_rating", "Minimum recipe rating", True, 1, 6),
        "min_leftovers": _number(params, "min_leftovers", "Minimum leftover rating", True, 1, 6),
    }


def create_app(recipes: Path = Path("recipes"), database: Path = Path("data/recipes.sqlite3"),
               ingredients: Path = Path("ingredients"), personal: Path = Path("personal")) -> FastAPI:
    rebuild_index(recipes, database, ingredients)
    ratings_path = personal / "ratings.yaml"
    library = load_ingredients(ingredients)
    index = SearchIndex(database)
    app = FastAPI(title="Recipe Library", version="0.1.0")
    web = Path(__file__).parent / "web"
    templates = Jinja2Templates(directory=web)
    templates.env.filters["quantity"] = format_quantity
    templates.env.filters["amount"] = format_amount
    templates.env.filters["number"] = format_number
    templates.env.filters["titlecase"] = title_case
    templates.env.filters["tag_label"] = tag_label
    templates.env.globals["CATEGORY_LABELS"] = CATEGORY_LABELS
    templates.env.globals["SERVED_LABELS"] = SERVED_LABELS

    def ratings():
        try:
            return load_ratings(ratings_path)
        except RatingsError as exc:
            raise HTTPException(500, str(exc)) from exc

    def filtered_search(filters, limit, offset, q=""):
        ids = matching_ids(ratings(), filters["min_rating"], filters["min_leftovers"])
        search = {k: v for k, v in filters.items() if k not in ("min_rating", "min_leftovers")}
        return index.search(q, None, limit=limit, offset=offset, ids=ids, **search)
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
    def recipes_api(request: Request, q: str = Query("", max_length=200),
                    limit: int = Query(50, ge=1, le=100), offset: int = Query(0, ge=0)):
        """Filters: category, tag (repeatable, all must match), served (repeatable, any may
        match), max_minutes, max_calories, min_protein, min_rating, min_leftovers."""
        return filtered_search(parse_filters(request.query_params), limit, offset, q)

    @app.get("/recipes/{recipe_id}")
    def recipe_api(recipe_id: str, variation: str | None = None):
        return detail(recipe_id, variation)[1]

    @app.get("/tags")
    def tags_api():
        return index.tags()

    @app.get("/", response_class=HTMLResponse)
    def home(request: Request, q: str = Query("", max_length=200), page: int = Query(1, ge=1)):
        filters = parse_filters(request.query_params)
        results = filtered_search(filters, 12, (page - 1) * 12, q)
        query = [(k, v) for k, v in request.query_params.multi_items() if k != "page" and v]
        def page_url(number):
            return "/?" + urlencode(query + [("page", number)])
        active = sum(1 for k, v in filters.items() if k != "category" and v)
        saved = ratings()
        cards = [{"recipe": r, "macros": per_serving_macros(r, library), "rating": saved.get(r.id)} for r in results["items"]]
        return templates.TemplateResponse(request=request, name="index.html", context={
            "results": results, "cards": cards, "tags": index.tags(), "q": q, "filters": filters,
            "active_filters": active, "page": page,
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
                if ingredient.quantity_max is not None:
                    ingredient.quantity_max *= factor
            if recipe.nutrition and recipe.nutrition.basis == 'whole_recipe':
                for field in ('calories_kcal', 'protein_g', 'carbohydrate_g', 'fat_g'):
                    value = getattr(recipe.nutrition, field)
                    if value is not None:
                        setattr(recipe.nutrition, field, value * factor)
            recipe.servings = servings
        return templates.TemplateResponse(request=request, name="recipe.html", context={
            "recipe": recipe, "base": base, "variation": variation, "original_servings": original_servings,
            "estimate": estimate_nutrition(recipe, library), "rating": ratings().get(base.id),
        })

    @app.post("/recipe/{recipe_id}/rating")
    async def rate_recipe(request: Request, recipe_id: str):
        # Writes only personal/ratings.yaml. Reject cross-site form posts to this local server.
        origin = request.headers.get("origin")
        if origin and urlsplit(origin).netloc != request.headers.get("host"):
            raise HTTPException(403, "Ratings can only be changed from this recipe library")
        if index.get(recipe_id) is None:
            raise HTTPException(404, "Recipe not found")
        form = parse_qs((await request.body()).decode("utf-8", "replace"))
        try:
            values = {k: int(form[k][0]) if form.get(k, [""])[0] else None for k in ("recipe", "leftovers")}
            rating = Rating(**values)
        except ValueError:
            raise HTTPException(422, "Ratings must be whole numbers from 1 to 5")
        save_rating(ratings_path, recipe_id, rating)
        back = form.get("return", [""])[0]
        target = back if back.startswith(f"/recipe/{recipe_id}") else f"/recipe/{recipe_id}"
        return RedirectResponse(target + "#ratings", status_code=303)

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
