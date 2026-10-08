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
    assert format_amount(3, 'tbsp', True) == '3/16 cups (1½ fl oz)'
    assert format_amount(8, 'oz', True) == '8 oz'
    assert format_amount(.5, 'cup', False) == '½ cup'
    assert format_amount(None, None, True) == 'Quantity needed'
