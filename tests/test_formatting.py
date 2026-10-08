import pytest
from recipe_library.formatting import format_quantity

@pytest.mark.parametrize('amount, expected', [(1/3,'⅓'),(.75,'¾'),(1.5,'1½'),(2+2/3,'2⅔'),(5,'5'),(.125,'⅛'),(1.2,'1 1/5')])
def test_cup_fractions(amount, expected):
    assert format_quantity(amount, 'cup') == expected


def test_other_units_remain_numeric():
    assert format_quantity(240, 'g') == '240'


def test_liquid_units_do_not_convert_weights_or_dry_cups():
    from recipe_library.formatting import format_amount
    assert format_amount(1.5, 'cup', True) == '1½ cups (12 fl oz)'
    assert format_amount(3, 'tbsp', True) == '3 tbsp (1½ fl oz)'
    assert format_amount(8, 'oz', True) == '8 oz'
    assert format_amount(.5, 'cup', False) == '½ cup'
    assert format_amount(None, None, True) == 'Quantity needed'


@pytest.mark.parametrize('value, unit, expected', [
    (.375, 'cup', '⅜ cup (3 fl oz)'), (1, 'cup', '1 cup (8 fl oz)'), (4 / 3, 'cup', '1⅓ cups (10⅔ fl oz)'),
    (6, 'fl_oz', '¾ cup (6 fl oz)'), (1.125, 'tbsp', '1⅛ tbsp (≈ ½ fl oz)'), (.5, 'tsp', '½ tsp (≈ ⅛ fl oz)'),
    (45, 'ml', '45 ml (≈ 3 tbsp · ≈ 1½ fl oz)'), (240, 'ml', '240 ml (≈ 1 cup · 8⅛ fl oz)'),
])
def test_liquids_show_kitchen_measures_and_fluid_ounces(value, unit, expected):
    from recipe_library.formatting import format_amount
    assert format_amount(value, unit, True) == expected


@pytest.mark.parametrize('value, expected', [
    (1 / 16, '1 tbsp'), (3 / 64, '2¼ tsp'), (1 / 48, '1 tsp'), (.1, '≈ 1⅝ tbsp'), (1 / 8, '⅛ cup'), (.75, '¾ cup'),
])
def test_dry_cups_below_an_eighth_use_spoons(value, expected):
    from recipe_library.formatting import format_amount
    assert format_amount(value, 'cup') == expected


@pytest.mark.parametrize('value, unit, expected', [
    (2 / 3, 'lb', '0.67'), (1.005, 'kg', '1'), (12.5, 'g', '12.5'), (2.25, 'count', '2.25'), (3, 'oz', '3'), (.001, 'g', '< 0.01'),
])
def test_decimal_quantities_round_to_hundredths(value, unit, expected):
    assert format_quantity(value, unit) == expected


@pytest.mark.parametrize('value, unit, expected', [
    (.5, 'tsp', '½ tsp'), (.25, 'tsp', '¼ tsp'), (10 / 3, 'tbsp', '3⅓ tbsp'), (1.6, 'tbsp', '≈ 1⅝ tbsp'), (2, 'tbsp', '2 tbsp'),
])
def test_dry_spoons_use_fractions(value, unit, expected):
    from recipe_library.formatting import format_amount
    assert format_amount(value, unit) == expected
