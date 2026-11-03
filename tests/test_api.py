from decimal import Decimal

from app.nosql import complaint_pipeline, monthly_pipeline


def headers(client, email):
    response = client.post('/api/auth/login', json={'email': email, 'password': 'TestPass123!'})
    assert response.status_code == 200
    return {'Authorization': 'Bearer ' + response.json()['access_token']}


def test_api_requires_sign_in(client):
    assert client.get('/api/orders').status_code == 401


def test_customer_cannot_modify_menu(client):
    auth = headers(client, 'buyer@example.test')
    assert client.post('/api/menu', headers=auth, json={'name': 'New', 'price': '4.00'}).status_code == 403


def test_staff_menu_crud(client):
    auth = headers(client, 'staff@example.test')
    result = client.post('/api/menu', headers=auth, json={'name': 'New', 'price': '4.00'})
    assert result.status_code == 201
    item_id = result.json()['id']
    assert client.put(f'/api/menu/{item_id}', headers=auth,
                      json={'name': 'Rice meal', 'price': '4.00'}).status_code == 409
    assert client.put(f'/api/menu/{item_id}', headers=auth, json={'name': 'Renamed', 'price': '6.00'}).status_code == 200
    assert client.delete(f'/api/menu/{item_id}', headers=auth).status_code == 200

def test_staff_can_manage_ingredients(client):
    staff = headers(client, 'staff@example.test')
    assert client.post('/api/ingredients', headers=staff,
                       json={'name': '  ', 'unit': 'g'}).status_code == 422
    created = client.post('/api/ingredients', headers=staff,
                          json={'name': 'Sugar', 'unit': 'g'})
    assert created.status_code == 201
    ingredient_id = created.json()['id']
    assert client.post('/api/ingredients', headers=staff,
                       json={'name': 'Sugar', 'unit': 'kg'}).status_code == 409
    assert client.put(f'/api/ingredients/{ingredient_id}', headers=staff,
                      json={'name': 'Brown sugar', 'unit': 'g'}).json()['name'] == 'Brown sugar'
    assert client.delete(f'/api/ingredients/{ingredient_id}', headers=staff).status_code == 200
    assert client.delete('/api/ingredients/1', headers=staff).status_code == 409


def test_staff_can_replace_recipe_and_invalid_recipes_are_rejected(client):
    staff = headers(client, 'staff@example.test')
    created = client.post('/api/ingredients', headers=staff,
                          json={'name': 'Sauce', 'unit': 'ml'})
    ingredient_id = created.json()['id']
    recipe_path = '/api/menu/1/recipe'

    replaced = client.put(recipe_path, headers=staff,
                          json={'ingredients': [{'ingredient_id': ingredient_id, 'quantity': '12.500'}]})
    assert replaced.status_code == 200
    saved = replaced.json()[0]
    assert saved['menu_item_id'] == 1 and saved['ingredient_id'] == ingredient_id
    assert Decimal(str(saved['quantity'])) == Decimal('12.500')

    invalid_recipes = [
        {'ingredients': []},
        {'ingredients': [{'ingredient_id': ingredient_id, 'quantity': '1'},
                         {'ingredient_id': ingredient_id, 'quantity': '2'}]},
        {'ingredients': [{'ingredient_id': ingredient_id, 'quantity': '0'}]},
        {'ingredients': [{'ingredient_id': ingredient_id, 'quantity': '0.0001'}]},
        {'ingredients': [{'ingredient_id': 999, 'quantity': '1'}]},
    ]
    for payload in invalid_recipes:
        assert client.put(recipe_path, headers=staff, json=payload).status_code == 422

    current = client.get('/api/recipes', headers=staff).json()
    assert len(current) == 1 and current[0]['ingredient_id'] == ingredient_id
    assert Decimal(str(current[0]['quantity'])) == Decimal('12.500')

def test_menu_and_ingredient_management_is_staff_only(client):
    customer = headers(client, 'buyer@example.test')
    assert client.get('/api/ingredients', headers=customer).status_code == 403
    assert client.get('/api/recipes', headers=customer).status_code == 403
    assert client.post('/api/ingredients', headers=customer,
                       json={'name': 'Forbidden', 'unit': 'g'}).status_code == 403


def test_staff_can_manage_ingredients(client):
    staff = headers(client, 'staff@example.test')
    assert client.post('/api/ingredients', headers=staff,
                       json={'name': '  ', 'unit': 'g'}).status_code == 422
    created = client.post('/api/ingredients', headers=staff,
                          json={'name': 'Sugar', 'unit': 'g'})
    assert created.status_code == 201
    ingredient_id = created.json()['id']
    assert client.post('/api/ingredients', headers=staff,
                       json={'name': 'Sugar', 'unit': 'kg'}).status_code == 409
    assert client.put(f'/api/ingredients/{ingredient_id}', headers=staff,
                      json={'name': 'Brown sugar', 'unit': 'g'}).json()['name'] == 'Brown sugar'
    assert client.delete(f'/api/ingredients/{ingredient_id}', headers=staff).status_code == 200
    assert client.delete('/api/ingredients/1', headers=staff).status_code == 409


def test_staff_can_replace_recipe_and_invalid_recipes_are_rejected(client):
    staff = headers(client, 'staff@example.test')
    created = client.post('/api/ingredients', headers=staff,
                          json={'name': 'Sauce', 'unit': 'ml'})
    ingredient_id = created.json()['id']
    recipe_path = '/api/menu/1/recipe'

    replaced = client.put(recipe_path, headers=staff,
                          json={'ingredients': [{'ingredient_id': ingredient_id, 'quantity': '12.500'}]})
    assert replaced.status_code == 200
    saved = replaced.json()[0]
    assert saved['menu_item_id'] == 1 and saved['ingredient_id'] == ingredient_id
    assert Decimal(str(saved['quantity'])) == Decimal('12.500')

    invalid_recipes = [
        {'ingredients': []},
        {'ingredients': [{'ingredient_id': ingredient_id, 'quantity': '1'},
                         {'ingredient_id': ingredient_id, 'quantity': '2'}]},
        {'ingredients': [{'ingredient_id': ingredient_id, 'quantity': '0'}]},
        {'ingredients': [{'ingredient_id': ingredient_id, 'quantity': '0.0001'}]},
        {'ingredients': [{'ingredient_id': 999, 'quantity': '1'}]},
    ]
    for payload in invalid_recipes:
        assert client.put(recipe_path, headers=staff, json=payload).status_code == 422

    current = client.get('/api/recipes', headers=staff).json()
    assert len(current) == 1 and current[0]['ingredient_id'] == ingredient_id
    assert Decimal(str(current[0]['quantity'])) == Decimal('12.500')


def test_menu_and_ingredient_management_is_staff_only(client):
    customer = headers(client, 'buyer@example.test')
    assert client.get('/api/ingredients', headers=customer).status_code == 403
    assert client.get('/api/recipes', headers=customer).status_code == 403
    assert client.post('/api/ingredients', headers=customer,
                       json={'name': 'Forbidden', 'unit': 'g'}).status_code == 403


def test_customer_only_sees_own_orders(client):
    staff = headers(client, 'staff@example.test')
    payload = {'request_key': 'api-ownership-order', 'branch_id': 1, 'customer_id': 1,
               'lines': [{'menu_item_id': 1, 'quantity': 1}]}
    assert client.post('/api/orders', headers=staff, json=payload).status_code == 201
    buyer = headers(client, 'buyer@example.test')
    other = headers(client, 'other@example.test')
    assert len(client.get('/api/orders', headers=buyer).json()) == 1
    assert client.get('/api/orders', headers=other).json() == []


def test_customers_cannot_place_orders_or_list_customers(client):
    # Staff and admins operate ordering and customer records on a customer's behalf.
    buyer = headers(client, 'buyer@example.test')
    payload = {'request_key': 'customer-own-order', 'branch_id': 1, 'customer_id': 1,
               'lines': [{'menu_item_id': 1, 'quantity': 1}]}
    assert client.post('/api/orders', headers=buyer, json=payload).status_code == 403
    assert client.get('/api/customers', headers=buyer).status_code == 403


def test_historical_menu_delete_is_blocked(client):
    auth = headers(client, 'staff@example.test')
    client.post('/api/orders', headers=auth, json={'request_key': 'historical-delete', 'branch_id': 1,
        'customer_id': 1, 'lines': [{'menu_item_id': 1, 'quantity': 1}]})
    assert client.delete('/api/menu/1', headers=auth).status_code == 409


def test_pipeline_uses_rating_filter_before_unwind():
    pipeline = complaint_pipeline(3)
    assert pipeline[0] == {'$match': {'rating': {'$lte': 2}, 'branch_id': 3}}
    assert pipeline[1] == {'$unwind': '$tags'}
    assert monthly_pipeline()[0]['$group']['reviews'] == {'$sum': 1}
