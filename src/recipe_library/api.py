"""Recipe API and server-rendered browser. Only personal ratings are written."""
from pathlib import Path
from urllib.parse import parse_qs, urlencode, urlsplit

from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from .customize import CustomizationError, customize, editable_ratio, options, rate
from .loader import load_ingredients, load_substitutions
from .models import CATEGORY_LABELS
from .nutrition import effective_item, estimate_nutrition, ingredient_grams, per_serving_macros
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


def _scale(recipe, servings):
    """Scale every amount (and whole-recipe nutrition) to a new number of servings."""
    if servings is None:
        return recipe
    recipe = recipe.model_copy(deep=True)
    factor = servings / recipe.servings
    for ingredient in recipe.ingredients:
        if ingredient.quantity is not None:
            ingredient.quantity *= factor
        if ingredient.quantity_max is not None:
            ingredient.quantity_max *= factor
    if recipe.nutrition and recipe.nutrition.basis == "whole_recipe":
        for field in ("calories_kcal", "protein_g", "carbohydrate_g", "fat_g"):
            value = getattr(recipe.nutrition, field)
            if value is not None:
                setattr(recipe.nutrition, field, value * factor)
    recipe.servings = servings
    return recipe


def _positive(raw):
    try:
        return 0 < float(raw) < float("inf")
    except ValueError:
        return False


def _input_value(value):
    """Prefill for an amount box: exact enough to round-trip, without float noise."""
    return f"{round(value, 4):g}"


def create_app(recipes: Path = Path("recipes"), database: Path = Path("data/recipes.sqlite3"),
               ingredients: Path = Path("ingredients"), personal: Path = Path("personal"),
               substitutions: Path | None = None) -> FastAPI:
    substitutions = substitutions or ingredients.parent / "substitutions"  # Libraries live side by side.
    rebuild_index(recipes, database, ingredients, substitutions)
    ratings_path = personal / "ratings.yaml"
    library = load_ingredients(ingredients)
    rules = load_substitutions(substitutions, library)
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
        return customize(detail(recipe_id, variation)[1], {}, {}, library, rules)[0]

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

    def canonical_url(recipe_id, variation, servings, amounts, swaps, original=None, products=None):
        if servings is not None and servings == original:
            servings = None
        query = ([("servings", f"{servings:g}")] if servings is not None else []) + \
                ([("variation", variation)] if variation else []) + \
                [(f"a.{k}", f"{round(v, 6):g}") for k, v in sorted(amounts.items())] + \
                [(f"s.{k}", v) for k, v in sorted(swaps.items())] + \
                [(f"p.{k}", v) for k, v in sorted((products or {}).items())]
        return f"/recipe/{recipe_id}" + ("?" + urlencode(query) if query else "")

    def submitted_customization(params, recipe):
        """Turn the page's form (amounts as shown at the `at` servings) into original-batch edits."""
        at = _number(params, "at", "Servings shown")
        if not at:
            raise HTTPException(422, "Servings shown must be positive")
        lines = {line.id: line for line in recipe.ingredients}
        swaps = {key[2:]: value for key, value in params.items() if key.startswith("s.") and value}
        products = {key[2:]: value for key, value in params.items() if key.startswith("p.") and value}
        amounts = {key[2:]: float(value) for key, value in params.items()
                   if key.startswith("a.") and key[2:] in lines and _positive(value)}
        for key, raw in params.items():
            if not key.startswith("amount.") or not raw.strip():
                continue
            line = lines.get(key[7:])
            if line is None or line.quantity is None:
                continue
            try:
                shown = float(raw)
                if not 0 < shown < float("inf"):
                    raise ValueError
            except ValueError:
                raise HTTPException(422, f"Enter a positive amount for {line.ingredient}")
            rule = rules.get(swaps.get(line.id, ""))
            ratio = editable_ratio(rule, line) if rule else 1
            value = shown * recipe.servings / at / (ratio or 1)
            if abs(value - line.quantity) > line.quantity * 0.001:
                amounts[line.id] = value
            else:
                amounts.pop(line.id, None)
        return amounts, swaps, products

    def requested_customization(params, recipe):
        """Edits from the URL; any that don't fit this version are dropped and reported."""
        lines = {line.id: line for line in recipe.ingredients}
        amounts, swaps, products, dropped = {}, {}, {}, []
        for key, raw in params.items():
            if key.startswith("a."):
                line = lines.get(key[2:])
                try:
                    value = float(raw)
                except ValueError:
                    value = 0
                if line is not None and line.quantity is not None and 0 < value < float("inf"):
                    amounts[line.id] = value
                else:
                    dropped.append(key[2:])
            elif key.startswith("s.") and raw:
                line, rule = lines.get(key[2:]), rules.get(raw)
                if line is not None and rule is not None and rule.replaces == line.ref and rate(rule, line)["rating"] != "unsuitable":
                    swaps[line.id] = raw
                else:
                    dropped.append(key[2:])
            elif key.startswith("p.") and raw:
                line = lines.get(key[2:])
                item = library.get(line.ref) if line is not None and line.ref else None
                if item is not None and item.product(raw) is not None:
                    products[line.id] = raw
                else:
                    dropped.append(key[2:])
        return amounts, swaps, products, dropped

    def product_choices(line, item, servings):
        """Each product with what it adds per serving at this line's amount, sorted by name."""
        choices = []
        for product in sorted(item.products, key=lambda p: p.name.casefold()):
            chosen = effective_item(line.model_copy(update={"product": product.id}), library)
            grams = ingredient_grams(line, chosen)[0] if line.quantity is not None else None
            kcal = product.nutrition_per_100g.calories_kcal
            per_serving = grams * kcal / 100 / servings if grams is not None and kcal is not None else None
            choices.append({"product": product, "per_serving": per_serving})
        return choices

    @app.get("/recipe/{recipe_id}", response_class=HTMLResponse)
    def recipe_page(request: Request, recipe_id: str, variation: str | None = None,
                    servings: str | None = Query(None)):
        base, recipe = detail(recipe_id, variation or None)
        params = request.query_params
        servings_value = _number(params, "servings", "Servings")
        if servings_value == 0:
            raise HTTPException(422, "Servings must be positive")
        if "at" in params:
            amounts, swaps, products = submitted_customization(params, recipe)
            return RedirectResponse(canonical_url(base.id, variation, servings_value, amounts, swaps, recipe.servings, products),
                                    status_code=303)
        amounts, swaps, products, dropped = requested_customization(params, recipe)
        custom, changes = customize(recipe, amounts, swaps, library, rules, products)
        url = lambda a, s, p: canonical_url(base.id, variation, servings_value, a, s, recipe.servings, p)
        shown = _scale(custom, servings_value)
        factor = shown.servings / recipe.servings
        originals = {line.id: line for line in recipe.ingredients}
        rows, previous = [], None
        for line in shown.ingredients:
            origin = originals.get(line.id)
            change = changes.get(line.id, {})
            rule = change.get("rule")
            item = library.get(line.ref) if line.ref else None
            row = {"line": line, "controls": origin is not None, "id": line.id, "swap": rule.id if rule else "",
                   "options": options(origin, rules, library) if origin is not None else [], "was": None, "input": None,
                   "products": product_choices(line, item, shown.servings) if item and item.products else [],
                   "product": item.product(line.product) if item and line.product else None,
                   "needs_product": bool(item and item.requires_product and not line.product and not line.optional),
                   "reset": None, "continued": origin is None and previous is not None and previous["was"] is not None}
            if origin is not None and origin.quantity is not None and (rule is None or editable_ratio(rule, origin)):
                row["input"] = _input_value(line.quantity)
            if change:
                was = _scale(recipe.model_copy(update={"ingredients": [origin]}), servings_value).ingredients[0]
                row["was"] = was
                row["reset"] = url({k: v for k, v in amounts.items() if k != line.id},
                                   {k: v for k, v in swaps.items() if k != line.id}, products)
            rows.append(row)
            previous = row if origin is not None else previous
        default_estimate = estimate_nutrition(recipe, library) if changes else None
        return templates.TemplateResponse(request=request, name="recipe.html", context={
            "recipe": shown, "base": base, "variation": variation, "original_servings": recipe.servings,
            "rows": rows, "changes": changes, "dropped": dropped, "amounts": amounts, "swaps": swaps, "products": products,
            "estimate": estimate_nutrition(custom, library), "default_estimate": default_estimate,
            "rating": ratings().get(base.id), "factor": factor,
            "reset_all": url({}, {}, products),
            "current_url": url(amounts, swaps, products),
            "custom_title": shown.title + (" — Customized" if changes else ""),
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
            return generate_list(index, request, library, rules)
        except ValueError as exc:
            raise HTTPException(422, str(exc)) from exc

    return app
