"""API permission checks are exercised directly, without website controls."""
from contextlib import contextmanager
from types import SimpleNamespace

import pytest
from sqlalchemy import func, select
from sqlalchemy.orm import sessionmaker

from app.models import Order, StockReceipt, User


REVIEW = {'order_id': 1, 'rating': 5, 'text': 'Good food', 'tags': ['food']}
PROFILE = {'dietary_preferences': ['vegetarian'], 'favourite_tags': ['food']}
ADMIN_CASES = [
    ('PUT', '/api/accounts/5/role', {'role': 'admin'}),
    ('GET', '/api/profiles', None),
    ('GET', '/api/profiles/1', None),
    ('PUT', '/api/profiles/1', PROFILE),
    ('DELETE', '/api/profiles/1', None),
    ('PUT', '/api/reviews/1/replies/0', {'text': 'Changed reply'}),
    ('DELETE', '/api/reviews/1/replies/0', None),
]
STAFF_FORBIDDEN = ADMIN_CASES + [
    ('POST', '/api/reviews', REVIEW), ('PUT', '/api/reviews/1', REVIEW),
    ('DELETE', '/api/reviews/1', None),
    ('GET', '/api/profiles/me', None), ('PUT', '/api/profiles/me', PROFILE),
]
CUSTOMER_FORBIDDEN = ADMIN_CASES + [
    ('POST', '/api/menu', {'name': 'New', 'price': '5.00'}),
    ('PUT', '/api/menu/1', {'name': 'Changed', 'price': '5.00'}),
    ('DELETE', '/api/menu/1', None), ('GET', '/api/recipes', None),
    ('GET', '/api/customers', None),
    ('POST', '/api/customers', {'name': 'New', 'email': 'new@example.test'}),
    ('PUT', '/api/customers/1', {'name': 'Changed', 'email': 'changed@example.test'}),
    ('GET', '/api/stock', None), ('GET', '/api/stock/movements', None),
    ('POST', '/api/stock/receipts', {'branch_id': 1, 'ingredient_id': 1, 'quantity': '3.000'}),
    ('POST', '/api/orders', {'request_key': 'forbidden-order', 'branch_id': 1, 'customer_id': 1,
                             'lines': [{'menu_item_id': 1, 'quantity': 1}]}),
    ('GET', '/api/analytics/sql', None), ('GET', '/api/analytics/mongo', None),
    ('POST', '/api/reviews/1/replies', {'text': 'Business reply'}),
]


def headers(client, email):
    response = client.post('/api/auth/login', json={'email': email, 'password': 'TestPass123!'})
    assert response.status_code == 200
    return {'Authorization': 'Bearer ' + response.json()['access_token']}


@pytest.fixture
def no_mongo(monkeypatch):
    import app.routes as routes
    def unavailable():
        raise AssertionError('A forbidden action reached MongoDB.')
    monkeypatch.setattr(routes, 'mongo_db', unavailable)


@pytest.mark.parametrize('email,role', [('admin@example.test', 'admin'), ('staff@example.test', 'staff'),
                                        ('buyer@example.test', 'customer')])
def test_all_three_roles_sign_in(client, email, role):
    auth = headers(client, email)
    assert client.get('/api/auth/me', headers=auth).json()['role'] == role


@pytest.mark.parametrize('method,path,body', STAFF_FORBIDDEN)
def test_staff_forbidden_actions_are_rejected_before_mongo(client, no_mongo, method, path, body):
    response = client.request(method, path, headers=headers(client, 'staff@example.test'), json=body)
    assert response.status_code == 403, response.text


@pytest.mark.parametrize('method,path,body', CUSTOMER_FORBIDDEN)
def test_customer_cannot_use_operational_or_admin_actions(client, no_mongo, method, path, body):
    response = client.request(method, path, headers=headers(client, 'buyer@example.test'), json=body)
    assert response.status_code == 403, response.text


@pytest.mark.parametrize('method,path,body', STAFF_FORBIDDEN)
def test_protected_actions_require_authentication(client, no_mongo, method, path, body):
    assert client.request(method, path, json=body).status_code == 401


@pytest.mark.parametrize('email', ['admin@example.test', 'staff@example.test'])
def test_both_operational_roles_can_use_previous_manager_actions(client, email):
    auth = headers(client, email)
    for path in ('recipes', 'customers', 'stock', 'stock/movements', 'analytics/sql'):
        assert client.get('/api/' + path, headers=auth).status_code == 200
    assert client.post('/api/menu', headers=auth, json={'name': 'New meal', 'price': '6.50'}).status_code == 201
    assert client.put('/api/customers/1', headers=auth,
                      json={'name': 'Updated buyer', 'email': 'updated@example.test'}).status_code == 200
    assert client.post('/api/stock/receipts', headers=auth,
                       json={'branch_id': 1, 'ingredient_id': 1, 'quantity': '10.000'}).status_code == 201


def test_admin_role_changes_take_effect_for_existing_tokens(client, database):
    admin = headers(client, 'admin@example.test')
    original_staff_token = headers(client, 'staff2@example.test')
    assert client.put('/api/accounts/5/role', headers=admin, json={'role': 'admin'}).status_code == 200
    assert client.get('/api/auth/me', headers=original_staff_token).json()['role'] == 'admin'
    assert client.put('/api/accounts/5/role', headers=admin, json={'role': 'staff'}).status_code == 200
    assert client.put('/api/accounts/2/role', headers=original_staff_token, json={'role': 'admin'}).status_code == 403
    with database() as session:
        assert session.get(User, 5).role == 'staff'
        assert session.get(User, 2).role == 'customer'


def test_last_admin_is_preserved(client):
    auth = headers(client, 'admin@example.test')
    assert client.put('/api/accounts/4/role', headers=auth, json={'role': 'staff'}).status_code == 409
    assert client.get('/api/auth/me', headers=auth).json()['role'] == 'admin'


def test_customer_assignment_requires_customer_link(client):
    assert client.put('/api/accounts/5/role', headers=headers(client, 'admin@example.test'),
                      json={'role': 'customer'}).status_code == 409


def test_invalid_role_and_mass_assignment_are_rejected(client, database):
    admin = headers(client, 'admin@example.test')
    assert client.put('/api/accounts/5/role', headers=admin, json={'role': 'owner'}).status_code == 422
    staff = headers(client, 'staff@example.test')
    assert client.put('/api/customers/1', headers=staff,
                      json={'name': 'Buyer', 'email': 'buyer@example.test', 'role': 'admin'}).status_code == 422
    assert client.post('/api/auth/login', json={'email': 'staff@example.test', 'password': 'TestPass123!',
                                               'role': 'admin'}).status_code == 422
    with database() as session:
        assert session.get(User, 1).role == 'staff'


@pytest.mark.parametrize('stored_role', ['manager', 'cashier', 'owner', '', 'ADMIN'])
def test_unsupported_stored_roles_cannot_read_shared_routes(client, monkeypatch, stored_role):
    import app.auth as auth
    @contextmanager
    def unsupported_account():
        yield SimpleNamespace(scalar=lambda query: SimpleNamespace(id=77, role=stored_role, customer_id=None, active=True, session_version=0))
    monkeypatch.setattr(auth, 'SessionLocal', unsupported_account)
    token = auth.issue_token(SimpleNamespace(id=77))
    assert client.get('/api/orders', headers={'Authorization': 'Bearer ' + token}).status_code == 403


def test_seed_uses_new_roles_and_actual_actor_id(tmp_path, monkeypatch, password_hash):
    import app.cli as cli
    from app.analytics import initialize_views
    from app.database import Base, make_engine
    engine = make_engine('sqlite:///' + str(tmp_path / 'seed.sqlite'))
    Base.metadata.create_all(engine)
    initialize_views(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    with factory.begin() as session:
        session.add(User(id=17, email='setup-admin@example.test', role='admin', password_hash=password_hash))
    monkeypatch.setattr(cli, 'SessionLocal', factory)
    cli.seed_sql()
    cli.seed_sql()
    with factory() as session:
        actor_id = session.scalar(select(User.id).where(User.email == 'manager@hawkerflow.local'))
        assert actor_id != 1
        assert session.get(User, 17).role == 'admin'
        assert session.scalar(select(func.count()).select_from(User)) == 53
        assert set(session.scalars(select(User.role))) == {'admin', 'staff', 'customer'}
        assert set(session.scalars(select(Order.cashier_user_id))) == {actor_id}
        assert set(session.scalars(select(StockReceipt.actor_user_id))) == {actor_id}
    engine.dispose()
