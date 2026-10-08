"""Human-readable amounts and names; numeric recipe data stays unchanged."""
import re
from fractions import Fraction

GLYPHS = {
    (1, 2): '½', (1, 3): '⅓', (2, 3): '⅔', (1, 4): '¼', (3, 4): '¾',
    (1, 8): '⅛', (3, 8): '⅜', (5, 8): '⅝', (7, 8): '⅞',
}
# US customary volumes in fluid ounces; oz remains a weight, never a fluid ounce.
FL_OZ_PER_UNIT = {'fl_oz': 1, 'cup': 8, 'tbsp': 1 / 2, 'tsp': 1 / 6,
                  'ml': 1 / 29.5735295625, 'l': 1000 / 29.5735295625}


def _fraction_text(amount):
    whole, remainder = divmod(amount.numerator, amount.denominator)
    if not remainder:
        return str(whole)
    fraction = GLYPHS.get((remainder, amount.denominator))
    if fraction:
        return (str(whole) if whole else '') + fraction
    fraction = f'{remainder}/{amount.denominator}'
    return f'{whole} {fraction}' if whole else fraction


def format_number(value):
    """Decimal amounts rounded to hundredths; trailing zeros dropped."""
    value = float(value)
    rounded = round(value, 2)
    if value > 0 and rounded == 0:
        return '< 0.01'
    return f'{rounded:g}'


def format_quantity(value, unit):
    if unit != 'cup':
        return format_number(value)
    # Recover ordinary fractions from floating-point serving calculations.
    return _fraction_text(Fraction(str(value)).limit_denominator(1000))


def kitchen_fraction(value):
    """Nearest measuring fraction (halves, thirds, quarters, eighths), prefixed ≈ if rounded."""
    nearest = min((Fraction(round(value * d), d) for d in (1, 2, 3, 4, 8)),
                  key=lambda f: (abs(f - Fraction(value)), f.denominator)) or Fraction(1, 8)
    approximate = abs(float(nearest) - value) > value * 0.01
    return ('≈ ' if approximate else '') + _fraction_text(nearest), nearest


def spoon_measure(tsp):
    """Tablespoons from one tablespoon up, teaspoons below."""
    unit, size = ('tbsp', 3) if tsp >= 3 else ('tsp', 1)
    return f'{kitchen_fraction(tsp / size)[0]} {unit}'


def liquid_measures(fl_oz):
    """A cup or spoon measure (spoons below a quarter cup) and fluid ounces."""
    if fl_oz >= 2:
        text, shown = kitchen_fraction(fl_oz / 8)
        measure = f"{text} {'cups' if shown > 1 else 'cup'}"
    else:
        measure = spoon_measure(fl_oz * 6)
    return measure, f'{kitchen_fraction(fl_oz)[0]} fl oz'


def _single_amount(value, unit, liquid):
    if liquid and unit in FL_OZ_PER_UNIT:
        measure, ounces = liquid_measures(float(value) * FL_OZ_PER_UNIT[unit])
        if unit in ('ml', 'l'):
            return f"{format_quantity(value, unit)} {unit} ({measure} · {ounces})"
        return f"{measure} ({ounces})"
    if unit == 'cup' and float(value) < 1 / 8:
        # Smaller than the smallest common measuring cup; 1 cup = 48 tsp.
        return spoon_measure(float(value) * 48)
    if unit == 'count':
        return format_quantity(value, unit)
    if unit in ('tsp', 'tbsp'):
        # Measuring spoons come in fractions, never decimals.
        return f"{kitchen_fraction(float(value))[0]} {unit}"
    if unit == 'cup' and float(value) > 1:
        return f"{format_quantity(value, unit)} cups"
    return f"{format_quantity(value, unit)} {unit}"


def _join_range(low, high):
    """'¼ cup' + '½ cup' -> '¼–½ cup'; different units stay spelled out."""
    a = re.fullmatch(r'(≈ )?(\S+)(?: (.+))?', low)
    b = re.fullmatch(r'(≈ )?(\S+)(?: (.+))?', high)
    if a and b and (a[3] == b[3] or (a[3] or '') + 's' == b[3]):
        return f"{a[1] or b[1] or ''}{a[2]}–{b[2]}" + (f" {b[3]}" if b[3] else '')
    return f"{low} – {high}"


def format_amount(value, unit, liquid=False, value_max=None):
    if value is None:
        return 'Quantity needed'
    if value_max is None:
        return _single_amount(value, unit, liquid)
    if liquid and unit in FL_OZ_PER_UNIT and unit not in ('ml', 'l'):
        low = liquid_measures(float(value) * FL_OZ_PER_UNIT[unit])
        high = liquid_measures(float(value_max) * FL_OZ_PER_UNIT[unit])
        return f"{_join_range(low[0], high[0])} ({_join_range(low[1], high[1])})"
    return _join_range(_single_amount(value, unit, liquid), _single_amount(value_max, unit, liquid))


SMALL_WORDS = {'a', 'an', 'and', 'as', 'at', 'but', 'by', 'for', 'from', 'in', 'into', 'of', 'on', 'or', 'the', 'to', 'with'}


def title_case(text):
    """Title Case for names: capitalizes each word (and hyphenated part) without
    lowercasing the rest, so 'IPA' and 'Cholula®' keep their own capitals."""
    if not text:
        return text
    words = str(text).replace('-', ' - ').split(' ')
    result = []
    for position, word in enumerate(words):
        if position and word.lower() in SMALL_WORDS and words[position - 1] != '-':
            result.append(word.lower())
        else:
            result.append(word[:1].upper() + word[1:])
    return ' '.join(result).replace(' - ', '-')


def tag_label(tag):
    """Display form of a tag slug: 'comfort-food' -> 'Comfort Food'."""
    return title_case(str(tag).replace('-', ' '))
