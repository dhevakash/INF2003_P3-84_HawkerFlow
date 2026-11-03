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
    assert client.put(f'/api/menu/{item_id}', headers=auth, json={'name': 'Renamed', 'price': '6.00'}).status_code == 200
    assert client.delete(f'/api/menu/{item_id}', headers=auth).status_code == 200


def test_customer_only_sees_own_orders(client):
    staff = headers(client, 'staff@example.test')
    payload = {'request_key': 'api-ownership-order', 'branch_id': 1, 'customer_id': 1,
               'lines': [{'menu_item_id': 1, 'quantity': 1}]}
    assert client.post('/api/orders', headers=staff, json=payload).status_code == 201
    buyer = headers(client, 'buyer@example.test')
    other = headers(client, 'other@example.test')
    assert len(client.get('/api/orders', headers=buyer).json()) == 1
    assert client.get('/api/orders', headers=other).json() == []


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
