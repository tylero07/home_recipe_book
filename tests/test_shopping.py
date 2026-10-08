from pathlib import Path
import pytest
from fastapi.testclient import TestClient
from recipe_library.api import create_app
from recipe_library.models import Recipe
from recipe_library.shopping import ShoppingRequest, generate_list

class Index:
    def get(self, id):
        if id == 'missing': return None
        return Recipe.model_validate(dict(schema_version=1,id=id,title=id,category='lunch-dinner',servings=2,
            ingredients=[dict(id='rice',ingredient='rice',quantity=100,unit='g'),
                         dict(id='salt',ingredient='salt'),
                         dict(id='herbs',ingredient='herbs',optional=True)],instructions=['Cook.']))

def test_scaling_combining_and_unknowns():
    result=generate_list(Index(), ShoppingRequest(selections=[dict(recipe_id='a',servings=4),dict(recipe_id='b',servings=2)]))
    assert len(result['items']) == 2
    assert result['items'][0]['quantity'] == '300'
    assert result['items'][1]['quantity'] is None
    assert 'Quantity needed' in result['items'][1]['text']
    assert result['items'][0]['sources'] == ['a','b']

def test_optional_and_missing():
    assert len(generate_list(Index(),ShoppingRequest(selections=[dict(recipe_id='a',servings=2)],include_optional=True))['items']) == 3
    with pytest.raises(ValueError):
        generate_list(Index(),ShoppingRequest(selections=[dict(recipe_id='missing',servings=2)]))

def test_api_and_variation(tmp_path):
    root=Path(__file__).resolve().parents[1]
    with TestClient(create_app(root/'recipes',tmp_path/'index.sqlite3')) as client:
        response=client.post('/shopping/generate',json={'selections':[{'recipe_id':'lemon-chickpea-bowl','servings':4,'variation':'extra-chickpeas'}]})
        assert response.status_code == 200
        chickpeas=next(i for i in response.json()['items'] if i['ingredient']=='Chickpeas')
        assert chickpeas['quantity']=='720'
        for selections in ([],[{'recipe_id':'missing','servings':2}],[{'recipe_id':'lemon-chickpea-bowl','servings':0}]):
            assert client.post('/shopping/generate',json={'selections':selections}).status_code==422
        assert client.get('/shopping').status_code==200
        assert client.get('/static/shopping.js').status_code==200


def test_serving_update_scales_from_original_without_changing_catalog(tmp_path):
    root = Path(__file__).resolve().parents[1]
    with TestClient(create_app(root/'recipes', tmp_path/'index.sqlite3')) as client:
        page = client.get('/recipe/chicken-cheddar-bay-dumplings?servings=3')
        assert page.status_code == 200
        assert '2½ cups (20 fl oz)' in page.text
        assert '⅜ cup (3 fl oz)' in page.text
        assert 'Update Amounts' in page.text
        assert client.get('/recipes/chicken-cheddar-bay-dumplings').json()['servings'] == 6
        for value in ('0', '-1', 'nan'):
            assert client.get('/recipe/chicken-cheddar-bay-dumplings', params={'servings':value}).status_code == 422
        result = client.post('/shopping/generate', json={'selections':[{'recipe_id':'chicken-cheddar-bay-dumplings','servings':3}]}).json()
        assert any('2½ cups (20 fl oz)' in item['text'] for item in result['items'])
