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


def test_recipe_and_ingredient_reads_are_staff_or_admin_only(client):
    customer = headers(client, 'buyer@example.test')
    assert client.get('/api/ingredients', headers=customer).status_code == 403
    assert client.get('/api/recipes', headers=customer).status_code == 403


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


def _place_order(client, request_key='receipt-order', redeem_points=0):
    staff = headers(client, 'staff@example.test')
    body = {'request_key': request_key, 'branch_id': 1, 'customer_id': 1,
            'redeem_points': redeem_points, 'lines': [{'menu_item_id': 1, 'quantity': 1}]}
    response = client.post('/api/orders', headers=staff, json=body)
    assert response.status_code == 201, response.text
    return response.json()['order_id']


def test_receipt_shows_readable_detail_with_points(client):
    # Buyer has 100 points; redeem 100 (=$1) on a $5 meal -> total $4, earns int(4)=4.
    order_id = _place_order(client, 'receipt-readable', redeem_points=100)
    buyer = headers(client, 'buyer@example.test')
    receipt = client.get(f'/api/orders/{order_id}', headers=buyer)
    assert receipt.status_code == 200, receipt.text
    data = receipt.json()
    assert data['order_id'] == order_id
    assert data['branch'] == {'id': 1, 'name': 'Test Branch'}
    assert data['lines'] == [{'menu_item_id': 1, 'name': 'Rice meal', 'quantity': 1,
                              'unit_price': '5.00', 'line_total': '5.00'}]
    assert data['subtotal'] == '5.00' and data['discount'] == '1.00' and data['total'] == '4.00'
    assert data['points_earned'] == 4 and data['points_redeemed'] == 100
    assert 'created_at' in data


def test_receipt_is_scoped_to_the_owning_customer(client):
    order_id = _place_order(client, 'receipt-scoped')
    # A different customer cannot read someone else's receipt (404, not 403, hides existence).
    other = headers(client, 'other@example.test')
    assert client.get(f'/api/orders/{order_id}', headers=other).status_code == 404
    # Staff and admin may read any receipt.
    assert client.get(f'/api/orders/{order_id}', headers=headers(client, 'staff@example.test')).status_code == 200
    assert client.get(f'/api/orders/{order_id}', headers=headers(client, 'admin@example.test')).status_code == 200


def test_receipt_requires_sign_in(client):
    assert client.get('/api/orders/1').status_code == 401


def test_profile_me_includes_points_balance(client, monkeypatch):
    # No stored Mongo profile: endpoint returns the empty profile plus the SQL points balance.
    import app.routes as routes
    monkeypatch.setattr(routes, 'mongo_db', lambda: type('Db', (), {
        'profiles': type('C', (), {'find_one': staticmethod(lambda query: None)})()})())
    buyer = headers(client, 'buyer@example.test')
    data = client.get('/api/profiles/me', headers=buyer).json()
    assert data['points'] == 100  # matches Customer(id=1).points seeded in conftest
    assert data['dietary_preferences'] == [] and data['favourite_tags'] == []


def test_public_review_projection_strips_private_fields():
    from app.routes import public_review
    stored = {'_id': 'abc', 'order_id': 7, 'customer_id': 1, 'branch_id': 2, 'rating': 5,
              'text': 'Great', 'tags': ['food'], 'category_ratings': {'food': 5},
              'created_at': 'when', 'source': 'application_purchase',
              'created_by_user_id': 9, 'updated_by_user_id': 9,
              'replies': [{'manager_user_id': 3, 'text': 'Thanks', 'created_at': 'later',
                           'updated_at': 'latest', 'updated_by_user_id': 4}]}
    public = public_review(stored)
    # Nothing identifying survives.
    for leaked in ('_id', 'order_id', 'customer_id', 'created_by_user_id', 'updated_by_user_id', 'source'):
        assert leaked not in public
    assert public == {'rating': 5, 'text': 'Great', 'tags': ['food'],
                      'category_ratings': {'food': 5}, 'branch_id': 2, 'created_at': 'when',
                      'replies': [{'text': 'Thanks', 'created_at': 'later', 'updated_at': 'latest'}]}
    # Reply keeps only text and timestamps; no author id.
    assert 'manager_user_id' not in public['replies'][0]
    assert 'updated_by_user_id' not in public['replies'][0]


def test_shared_reviews_use_projection_for_all_roles(client, monkeypatch):
    import app.routes as routes

    class FakeCursor:
        def __init__(self, docs): self._docs = docs
        def sort(self, *a, **k): return self
        def limit(self, *a, **k): return self
        def __iter__(self): return iter(self._docs)

    stored = [{'_id': 'x', 'order_id': 7, 'customer_id': 2, 'branch_id': 1, 'rating': 4,
               'text': 'Nice', 'tags': [], 'category_ratings': {}, 'created_at': 'when',
               'created_by_user_id': 3, 'replies': []}]

    class FakeReviews:
        def find(self, query): FakeReviews.last_query = query; return FakeCursor(stored)

    monkeypatch.setattr(routes, 'mongo_db', lambda: type('Db', (), {'reviews': FakeReviews()})())
    for email in ('buyer@example.test', 'staff@example.test', 'admin@example.test'):
        response = client.get('/api/reviews/shared?branch_id=1', headers=headers(client, email))
        assert response.status_code == 200, response.text
        rows = response.json()
        assert rows and all('customer_id' not in row and 'order_id' not in row for row in rows)
    assert FakeReviews.last_query == {'branch_id': 1}
