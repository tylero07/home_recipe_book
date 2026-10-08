"""Human-readable amounts; numeric recipe data stays unchanged."""
from fractions import Fraction

GLYPHS = {
    (1, 2): '½', (1, 3): '⅓', (2, 3): '⅔', (1, 4): '¼', (3, 4): '¾',
    (1, 8): '⅛', (3, 8): '⅜', (5, 8): '⅝', (7, 8): '⅞',
}


def format_quantity(value, unit):
    if unit != 'cup':
        return f'{float(value):g}'
    # Recover ordinary fractions from floating-point serving calculations.
    amount = Fraction(str(value)).limit_denominator(1000)
    whole, remainder = divmod(amount.numerator, amount.denominator)
    if not remainder:
        return str(whole)
    fraction = GLYPHS.get((remainder, amount.denominator))
    if fraction:
        return (str(whole) if whole else '') + fraction
    fraction = f'{remainder}/{amount.denominator}'
    return f'{whole} {fraction}' if whole else fraction


def format_amount(value, unit, liquid=False):
    if value is None:
        return 'Quantity needed'
    # US customary volumes; oz remains a weight, never a fluid ounce.
    cups_per_unit = {'cup': 1, 'fl_oz': 1 / 8, 'tbsp': 1 / 16,
                     'tsp': 1 / 48, 'ml': 1 / 236.5882365, 'l': 1000 / 236.5882365}
    if liquid and unit in cups_per_unit:
        cups = float(value) * cups_per_unit[unit]
        if unit in ('ml', 'l'):
            return f"{format_quantity(value, unit)} {unit} (≈ {cups:.3g} cups / {cups * 8:.3g} fl oz)"
        return f"{format_quantity(cups, 'cup')} {'cup' if cups == 1 else 'cups'} ({format_quantity(cups * 8, 'cup')} fl oz)"
    return f"{format_quantity(value, unit)} {unit}"
