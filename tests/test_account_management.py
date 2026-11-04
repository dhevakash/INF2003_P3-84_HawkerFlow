"""Account lifecycle, identity preservation, session revocation and deletion guards."""
import hashlib
import json
from types import SimpleNamespace

import pytest
from pymongo.errors import ServerSelectionTimeoutError
from sqlalchemy import event, select
from sqlalchemy.exc import IntegrityError

from app.auth import Principal, verify_password
from app.database import Base
from app.models import Customer, LoyaltyAdjustment, Order, StockAdjustment, StockReceipt, User

PASSWORD = 'ManagedCustomerPass123!'


def auth(client, email='admin@example.test', password='TestPass123!'):
    result = client.post('/api/auth/login', json={'email': email, 'password': password})
    assert result.status_code == 200
    return {'Authorization': 'Bearer ' + result.json()['access_token']}


def fingerprint(factory):
    with factory() as session:
        rows = {table.name: [dict(row) for row in session.execute(select(table).order_by(*table.primary_key)).mappings()]
                for table in Base.metadata.sorted_tables}
    return hashlib.sha256(json.dumps(rows, default=str, sort_keys=True).encode()).hexdigest()


@pytest.fixture
def documents(monkeypatch):
    calls = []
    def find(collection, query, projection):
        calls.append((collection, query))
        return None
    db = SimpleNamespace(**{name: SimpleNamespace(find_one=lambda q, p, name=name: find(name, q, p))
                            for name in ['reviews', 'profiles']})
    monkeypatch.setattr('app.routes.mongo_db', lambda: db)
    return db, calls


def test_admin_customer_creation_uses_new_ids_and_zero_points(client, database):
    before = fingerprint(database)
    response = client.post('/api/accounts', headers=auth(client), json={
        'email': ' NEW-CUSTOMER@example.test ', 'name': ' New Buyer ', 'password': PASSWORD, 'role': 'customer'})
    assert response.status_code == 201
    result = response.json()
    assert result['role'] == 'customer' and result['active'] and result['customer_id'] not in [1, 2]
    assert result['email'] == 'new-customer@example.test' and PASSWORD not in response.text
    with database() as session:
        user = session.get(User, result['id'])
        customer = session.get(Customer, result['customer_id'])
        assert verify_password(PASSWORD, user.password_hash)
        assert customer.name == 'New Buyer' and customer.points == 0 and customer.email == user.email
    assert fingerprint(database) != before
    own = auth(client, result['email'], PASSWORD)
    assert client.get('/api/auth/me', headers=own).json() == {
        'id': result['id'], 'role': 'customer', 'customer_id': result['customer_id']}
    assert client.get('/api/accounts', headers=own).status_code == 403


@pytest.mark.parametrize('changes', [{'name': None}, {'name': '  '}, {'customer_id': 1},
                                   {'points': 900}, {'id': 2}, {'active': False}, {'role': 'manager'}])
def test_customer_creation_is_strict_and_atomic(client, database, changes):
    before = fingerprint(database)
    body = {'email': 'new@example.test', 'name': 'New', 'password': PASSWORD, 'role': 'customer', **changes}
    assert client.post('/api/accounts', headers=auth(client), json=body).status_code == 422
    assert fingerprint(database) == before


def test_failed_customer_account_insert_rolls_back_customer_too(client, database):
    headers = auth(client)
    before = fingerprint(database)
    def fail(mapper, connection, account):
        if account.email == 'new@example.test':
            raise IntegrityError('injected', {}, RuntimeError('failed'))
    event.listen(User, 'before_insert', fail)
    try:
        assert client.post('/api/accounts', headers=headers, json={
            'email': 'new@example.test', 'name': 'New', 'password': PASSWORD, 'role': 'customer'}).status_code == 409
    finally:
        event.remove(User, 'before_insert', fail)
    assert fingerprint(database) == before


def test_account_validation_never_echoes_submitted_password(client):
    admin = auth(client)
    for path, body in [('/api/accounts', {'email': 'new@example.test', 'password': PASSWORD, 'role': 'customer'}),
                       ('/api/accounts/1/password', {'password': PASSWORD, 'role': 'admin'})]:
        result = client.post(path, headers=admin, json=body) if path == '/api/accounts' else client.put(path, headers=admin, json=body)
        assert result.status_code == 422 and PASSWORD not in result.text


def test_details_update_preserves_customer_identity_points_password_and_orders(client, database):
    admin, old_customer = auth(client), auth(client, 'buyer@example.test')
    with database.begin() as session:
        session.add(Order(request_key='historical-account-edit', request_hash='a'*64, branch_id=1,
            customer_id=1, cashier_user_id=1, subtotal=5, discount=0, total=5))
    with database() as session:
        original_hash = session.get(User, 2).password_hash
        orders = [dict(row) for row in session.execute(select(Order.__table__)).mappings()]
    result = client.put('/api/accounts/2', headers=admin,
                        json={'email': ' UPDATED@example.test ', 'name': ' Updated Buyer '})
    assert result.status_code == 200 and result.json()['name'] == 'Updated Buyer'
    with database() as session:
        account, customer = session.get(User, 2), session.get(Customer, 1)
        assert account.customer_id == 1 and customer.points == 100 and account.password_hash == original_hash
        assert customer.email == account.email == 'updated@example.test'
        assert [dict(row) for row in session.execute(select(Order.__table__)).mappings()] == orders
    assert client.get('/api/auth/me', headers=old_customer).status_code == 401
    assert client.post('/api/auth/login', json={'email': 'buyer@example.test', 'password': 'TestPass123!'}).status_code == 401
    assert client.get('/api/auth/me', headers=auth(client, 'updated@example.test')).json()['id'] == 2


@pytest.mark.parametrize('email', ['STAFF@example.test', 'other@example.test', 'orphan@example.test'])
def test_duplicate_details_email_does_not_mutate_either_record(client, database, email):
    with database.begin() as session:
        session.add(Customer(name='Retained customer', email='orphan@example.test', points=0))
    before = fingerprint(database)
    assert client.put('/api/accounts/2', headers=auth(client), json={'email': email, 'name': 'Wrong'}).status_code == 409
    assert fingerprint(database) == before


@pytest.mark.parametrize('extra', [{'role': 'admin'}, {'active': False}, {'customer_id': 2},
                                  {'id': 9}, {'points': 8000}, {'password_hash': 'injected'}, {'password': PASSWORD}])
def test_details_reject_mass_assignment(client, database, extra):
    before = fingerprint(database)
    assert client.put('/api/accounts/2', headers=auth(client),
                      json={'email': 'buyer@example.test', 'name': 'Buyer', **extra}).status_code == 422
    assert fingerprint(database) == before


def test_staff_email_edit_and_customer_name_edit_without_email_change(client, database):
    admin, own = auth(client), auth(client, 'buyer@example.test')
    assert client.put('/api/accounts/1', headers=admin, json={'email': 'staff-new@example.test'}).status_code == 200
    assert client.put('/api/accounts/1', headers=admin, json={'email': 'staff-new@example.test', 'name': 'Invalid'}).status_code == 422
    assert client.put('/api/accounts/2', headers=admin, json={'email': 'buyer@example.test', 'name': 'New Name'}).status_code == 200
    assert client.get('/api/auth/me', headers=own).status_code == 200


@pytest.mark.parametrize('actor', [None, 'staff@example.test', 'buyer@example.test'])
@pytest.mark.parametrize('method,path,body', [
    ('post', '/api/accounts', {'role': 'customer', 'email': 'new@example.test', 'name': 'New', 'password': PASSWORD}),
    ('put', '/api/accounts/3', {'email': 'new@example.test', 'name': 'New'}),
    ('put', '/api/accounts/3/password', {'password': PASSWORD}),
    ('delete', '/api/accounts/3', None)])
def test_all_management_actions_require_admin_without_side_effects(client, database, monkeypatch, actor, method, path, body):
    monkeypatch.setattr('app.routes.mongo_db', lambda: pytest.fail('Forbidden request touched MongoDB'))
    before = fingerprint(database)
    result = getattr(client, method)(path, headers=auth(client, actor) if actor else {},
                                     **({'json': body} if body else {}))
    assert result.status_code == (403 if actor else 401)
    assert fingerprint(database) == before


@pytest.mark.parametrize('target', [1, 2, 4])
def test_password_reset_revokes_tokens_and_old_password_for_all_roles(client, database, target):
    email = {1: 'staff@example.test', 2: 'buyer@example.test', 4: 'admin@example.test'}[target]
    admin, old = auth(client), auth(client, email)
    with database() as session:
        user = session.get(User, target)
        identity = user.id, user.role, user.customer_id, user.active
    result = client.put(f'/api/accounts/{target}/password', headers=admin, json={'password': PASSWORD})
    assert result.status_code == 200 and PASSWORD not in result.text and 'hash' not in result.text
    assert client.get('/api/auth/me', headers=old).status_code == 401
    assert client.post('/api/auth/login', json={'email': email, 'password': 'TestPass123!'}).status_code == 401
    assert client.get('/api/auth/me', headers=auth(client, email, PASSWORD)).status_code == 200
    with database() as session:
        user = session.get(User, target)
        assert (user.id, user.role, user.customer_id, user.active) == identity


def test_password_reset_keeps_disabled_account_disabled(client, database):
    admin = auth(client)
    assert client.put('/api/accounts/3/status', headers=admin, json={'active': False}).status_code == 200
    assert client.put('/api/accounts/3/password', headers=admin, json={'password': PASSWORD}).status_code == 200
    assert client.post('/api/auth/login', json={'email': 'other@example.test', 'password': PASSWORD}).status_code == 401
    assert client.put('/api/accounts/3/status', headers=admin, json={'active': True}).status_code == 200
    assert client.get('/api/auth/me', headers=auth(client, 'other@example.test', PASSWORD)).json()['id'] == 3


@pytest.mark.parametrize('body', [{'password': 'short'}, {'password': ' '*12}, {'password': 'x'*129},
                                 {'password': PASSWORD, 'role': 'admin'}, {'password_hash': 'raw'}])
def test_invalid_reset_does_not_change_credentials(client, database, body):
    before = fingerprint(database)
    assert client.put('/api/accounts/1/password', headers=auth(client), json=body).status_code == 422
    assert fingerprint(database) == before


def test_unused_customer_deletion_is_explicit_and_removes_only_unused_identity(client, database, documents):
    admin, old = auth(client), auth(client, 'other@example.test')
    assert client.delete('/api/accounts/3', headers=admin).status_code == 409
    assert client.delete('/api/accounts/4', headers=admin).status_code == 409
    assert client.put('/api/accounts/3/status', headers=admin, json={'active': False}).status_code == 200
    assert client.delete('/api/accounts/3', headers=admin).status_code == 200
    with database() as session:
        assert session.get(User, 3) is None and session.get(Customer, 2) is None
        assert session.get(Customer, 1).points == 100 and session.get(User, 2).customer_id == 1
    assert client.get('/api/auth/me', headers=old).status_code == 401
    assert {name for name, query in documents[1]} == {'reviews', 'profiles'}


@pytest.mark.parametrize('reference', ['purchase', 'receipt', 'stock_correction', 'points_correction', 'customer_purchase', 'balance'])
def test_sql_history_blocks_deletion_and_remains_identical(client, database, documents, reference):
    target = 3 if reference in ['customer_purchase', 'balance'] else 1
    with database.begin() as session:
        if reference in ['purchase', 'customer_purchase']:
            session.add(Order(request_key='historic-'+reference, request_hash='a'*64, branch_id=1,
                customer_id=2 if reference == 'customer_purchase' else 1,
                cashier_user_id=4 if reference == 'customer_purchase' else 1, subtotal=5, discount=0, total=5))
        elif reference == 'receipt':
            session.add(StockReceipt(branch_id=1, ingredient_id=1, quantity=1, actor_user_id=1, note='Historical'))
        elif reference == 'stock_correction':
            session.add(StockAdjustment(branch_id=1, ingredient_id=1, previous_quantity=10, quantity=9, actor_user_id=1, reason='Historical'))
        elif reference == 'points_correction':
            session.add(LoyaltyAdjustment(customer_id=1, action='edit', previous_points=101, points=100, delta=-1, actor_user_id=1, reason='Historical'))
        else:
            session.get(Customer, 2).points = 1
        session.get(User, target).active = False
    before = fingerprint(database)
    result = client.delete(f'/api/accounts/{target}', headers=auth(client))
    assert result.status_code == 409 and 'disabled' in result.text
    assert fingerprint(database) == before


@pytest.mark.parametrize('collection,key', [('reviews', 'created_by_user_id'), ('reviews', 'updated_by_user_id'),
    ('reviews', 'replies.manager_user_id'), ('reviews', 'replies.updated_by_user_id'),
    ('reviews', 'customer_id'), ('profiles', 'customer_id'), ('profiles', 'updated_by_user_id')])
def test_mongo_history_blocks_deletion(client, database, documents, collection, key):
    with database.begin() as session:
        session.get(User, 3).active = False
    before = fingerprint(database)
    value = 2 if key == 'customer_id' else 3
    getattr(documents[0], collection).find_one = lambda query, projection: {'_id': 'retained'} if {key: value} in query['$or'] else None
    assert client.delete('/api/accounts/3', headers=auth(client)).status_code == 409
    assert fingerprint(database) == before


def test_document_outage_fails_closed_and_unused_user_id_is_not_recycled(client, database, documents, monkeypatch):
    admin = auth(client)
    old = auth(client, 'staff2@example.test')
    with database.begin() as session:
        session.get(User, 5).active = False
    before = fingerprint(database)
    def unavailable():
        raise ServerSelectionTimeoutError('unavailable')
    monkeypatch.setattr('app.routes.mongo_db', unavailable)
    assert client.delete('/api/accounts/5', headers=admin).status_code == 503
    assert fingerprint(database) == before
    monkeypatch.setattr('app.routes.mongo_db', lambda: documents[0])
    assert client.delete('/api/accounts/5', headers=admin).status_code == 200
    created = client.post('/api/accounts', headers=admin, json={'email': 'replacement@example.test', 'password': PASSWORD, 'role': 'staff'})
    assert created.status_code == 201 and created.json()['id'] > 5
    assert client.get('/api/auth/me', headers=old).status_code == 401


@pytest.mark.parametrize('method,path,body', [('put', '/api/accounts/3', {'email': 'other@example.test'}),
    ('put', '/api/accounts/3/password', {'password': PASSWORD}), ('delete', '/api/accounts/3', None)])
def test_management_rechecks_actor_under_lock(client, database, method, path, body):
    from app.main import app
    from app.routes import AdminOnly
    app.dependency_overrides[AdminOnly.dependency] = lambda: Principal(1, 'admin', None)
    before = fingerprint(database)
    try:
        assert getattr(client, method)(path, **({'json': body} if body else {})).status_code == 403
    finally:
        del app.dependency_overrides[AdminOnly.dependency]
    assert fingerprint(database) == before


def test_missing_accounts_are_404_and_failed_edits_are_atomic(client, database, documents):
    admin = auth(client)
    before = fingerprint(database)
    for path, body in [('/api/accounts/999', {'email': 'missing@example.test'}),
                       ('/api/accounts/999/password', {'password': PASSWORD})]:
        assert client.put(path, headers=admin, json=body).status_code == 404
    assert client.delete('/api/accounts/999', headers=admin).status_code == 404
    assert fingerprint(database) == before


@pytest.mark.parametrize('state', ['disabled', 'password_reset', 'role_changed'])
def test_mongo_write_guard_rechecks_account_after_authentication(client, database, state):
    from fastapi import HTTPException
    from app.auth import document_writer
    with database.begin() as session:
        account = session.get(User, 1)
        if state == 'disabled':
            account.active = False
        elif state == 'password_reset':
            account.session_version += 1
        else:
            account.role = 'admin'
    guard = document_writer(Principal(1, 'staff', None, 0))
    with pytest.raises(HTTPException) as error:
        next(guard)
    assert error.value.status_code == (403 if state == 'role_changed' else 401)
