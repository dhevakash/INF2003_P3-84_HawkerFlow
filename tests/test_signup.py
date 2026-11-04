"""Public signup must never accept privileged roles or existing identities."""
import hashlib
import json
from datetime import date, datetime, timedelta, timezone

import pytest
from sqlalchemy import event, select
from sqlalchemy.exc import IntegrityError

from app.auth import verify_password
from app.models import Customer, User

PASSWORD = 'NewCustomerPass123!'


def payload(**changes):
    return {'name': 'New Customer', 'email': 'new-customer@example.test', 'password': PASSWORD, **changes}


def database_state(factory):
    with factory() as session:
        users = [dict(row) for row in session.execute(select(User.__table__).order_by(User.id)).mappings()]
        customers = [dict(row) for row in session.execute(select(Customer.__table__).order_by(Customer.id)).mappings()]
    # Compare all fields without exposing password hashes in assertion output.
    fingerprint = hashlib.sha256(json.dumps([users, customers], default=str, sort_keys=True).encode()).hexdigest()
    return len(users), len(customers), fingerprint


def auth_headers(client, email='admin@example.test'):
    result = client.post('/api/auth/login', json={'email': email, 'password': 'TestPass123!'})
    assert result.status_code == 200
    return {'Authorization': 'Bearer ' + result.json()['access_token']}


def test_public_signup_creates_linked_customer_with_hashed_password(client, database):
    result = client.post('/api/auth/signup', json=payload())
    assert result.status_code == 201, result.text
    account = result.json()
    assert set(account) == {'id', 'email', 'role', 'customer_id'}
    assert account['role'] == 'customer'
    with database() as session:
        user = session.get(User, account['id'])
        customer = session.get(Customer, account['customer_id'])
        assert user.role == 'customer' and user.customer_id == customer.id
        assert customer.name == 'New Customer' and customer.email == user.email
        assert customer.points == 0 and customer.active is True
        assert user.password_hash != PASSWORD and verify_password(PASSWORD, user.password_hash)
    login = client.post('/api/auth/login', json={'email': account['email'], 'password': PASSWORD})
    assert login.status_code == 200 and login.json()['role'] == 'customer'
    auth = {'Authorization': 'Bearer ' + login.json()['access_token']}
    assert client.get('/api/orders', headers=auth).json() == []
    assert client.get('/api/loyalty', headers=auth).json() == []
    own = client.get('/api/customers/me', headers=auth).json()
    assert own == {'id': account['customer_id'], 'name': 'New Customer', 'email': account['email'], 'birthday': None, 'points': 0}
    assert client.put('/api/accounts/4/role', headers=auth, json={'role': 'admin'}).status_code == 403
    assert client.post('/api/menu', headers=auth, json={'name': 'Forbidden', 'price': '5.00'}).status_code == 403


@pytest.mark.parametrize('extra', [
    {'role': 'admin'}, {'role': 'staff'}, {'role': 'customer'}, {'role': None},
    {'roles': ['admin']}, {'is_admin': True}, {'id': 1}, {'user_id': 1},
    {'customer_id': 1}, {'points': 10000}, {'active': False}, {'password_hash': 'injected'},
    {'account': {'role': 'admin'}}, {'permissions': ['*']}, {'Role': 'Admin'},
])
def test_signup_rejects_privileges_and_identity_mass_assignment(client, database, extra):
    before = database_state(database)
    result = client.post('/api/auth/signup', json=payload(**extra))
    assert result.status_code == 422
    assert database_state(database) == before


@pytest.mark.parametrize('changes', [
    {'name': '   '}, {'name': 'x' * 121}, {'email': 'not-an-email'},
    {'email': 'a@@example.test'}, {'email': 'a b@example.test'}, {'email': None},
    {'password': 'short'}, {'password': ' ' * 12}, {'password': 'x' * 129},
    {'password': 123456789012},
])
def test_signup_rejects_invalid_details_without_writes(client, database, changes):
    before = database_state(database)
    assert client.post('/api/auth/signup', json=payload(**changes)).status_code == 422
    assert database_state(database) == before


@pytest.mark.parametrize('missing', ['name', 'email', 'password'])
def test_signup_requires_all_public_fields(client, database, missing):
    body = payload()
    body.pop(missing)
    before = database_state(database)
    assert client.post('/api/auth/signup', json=body).status_code == 422
    assert database_state(database) == before


@pytest.mark.parametrize('email', ['admin@example.test', 'staff@example.test', ' BUYER@EXAMPLE.TEST '])
def test_duplicate_account_emails_do_not_change_existing_accounts(client, database, email):
    before = database_state(database)
    assert client.post('/api/auth/signup', json=payload(email=email)).status_code == 409
    assert database_state(database) == before


def test_existing_customer_without_login_cannot_be_claimed_by_signup(client, database):
    with database.begin() as session:
        session.add(Customer(id=33, name='Existing customer', email='Unclaimed@Example.Test', points=900))
    before = database_state(database)
    assert client.post('/api/auth/signup', json=payload(email='unclaimed@example.test')).status_code == 409
    assert database_state(database) == before


def test_email_and_name_normalization_and_case_insensitive_login(client, database):
    result = client.post('/api/auth/signup', json=payload(name='  New Customer  ', email=' NEW-CUSTOMER@EXAMPLE.TEST '))
    assert result.status_code == 201 and result.json()['email'] == 'new-customer@example.test'
    with database() as session:
        assert session.get(Customer, result.json()['customer_id']).name == 'New Customer'
    assert client.post('/api/auth/login', json={'email': ' NEW-CUSTOMER@EXAMPLE.TEST ', 'password': PASSWORD}).status_code == 200
    before = database_state(database)
    assert client.post('/api/auth/signup', json=payload(email='NEW-CUSTOMER@example.test')).status_code == 409
    assert database_state(database) == before


def test_password_whitespace_is_preserved(client):
    password = '  NewCustomerPass123!  '
    assert client.post('/api/auth/signup', json=payload(password=password)).status_code == 201
    assert client.post('/api/auth/login', json={'email': payload()['email'], 'password': password}).status_code == 200
    assert client.post('/api/auth/login', json={'email': payload()['email'], 'password': password.strip()}).status_code == 401


def test_role_query_parameters_and_admin_session_cannot_create_privileged_signup(client, database):
    admin = auth_headers(client)
    result = client.post('/api/auth/signup?role=admin&customer_id=1&points=9999', headers=admin, json=payload())
    assert result.status_code == 201 and result.json()['role'] == 'customer'
    assert result.json()['customer_id'] != 1
    with database() as session:
        assert session.get(User, 4).role == 'admin'
        assert session.get(Customer, result.json()['customer_id']).points == 0


def test_signup_does_not_require_or_write_to_mongo(client, monkeypatch):
    import app.routes as routes
    def unavailable():
        raise AssertionError('Signup unexpectedly accessed MongoDB.')
    monkeypatch.setattr(routes, 'mongo_db', unavailable)
    assert client.post('/api/auth/signup', json=payload()).status_code == 201


def test_failure_in_account_insert_rolls_back_customer_and_allows_retry(client, database):
    before = database_state(database)
    def fail_account_insert(mapper, connection, account):
        if account.email == payload()['email']:
            raise IntegrityError('simulated account insert failure', {}, RuntimeError('injected test failure'))
    event.listen(User, 'before_insert', fail_account_insert)
    try:
        assert client.post('/api/auth/signup', json=payload(birthday='2000-02-29', confirm_password=PASSWORD)).status_code == 409
    finally:
        event.remove(User, 'before_insert', fail_account_insert)
    assert database_state(database) == before
    assert client.post('/api/auth/signup', json=payload()).status_code == 201


@pytest.mark.parametrize('birthday', [None, '2000-02-29', '1999-12-31',
                                    datetime.now(timezone(timedelta(hours=8))).date().isoformat()])
def test_optional_birthday_persists_and_signup_can_sign_in_immediately(client, database, birthday):
    result = client.post('/api/auth/signup', json=payload(birthday=birthday, confirm_password=PASSWORD))
    assert result.status_code == 201 and PASSWORD not in result.text
    account = result.json()
    with database() as session:
        customer = session.get(Customer, account['customer_id'])
        assert customer.birthday == (date.fromisoformat(birthday) if birthday else None)
        assert customer.points == 0
    login = client.post('/api/auth/login', json={'email': account['email'], 'password': PASSWORD})
    auth = {'Authorization': 'Bearer ' + login.json()['access_token']}
    assert client.get('/api/customers/me', headers=auth).json()['birthday'] == birthday
    assert client.get('/api/orders', headers=auth).json() == []
    assert client.get('/api/loyalty', headers=auth).json() == []


@pytest.mark.parametrize('birthday', ['2001-02-29', '2000-02-30', '01/02/2000', '2000-1-1',
    '2000-01-01T00:00:00Z', '', 946684800, True, [], {}, '0999-12-31',
    (date.today()+timedelta(days=2)).isoformat()])
def test_invalid_or_future_birthday_does_not_create_either_record(client, database, birthday):
    before = database_state(database)
    response = client.post('/api/auth/signup', json=payload(birthday=birthday, confirm_password=PASSWORD))
    assert response.status_code == 422 and PASSWORD not in response.text
    assert database_state(database) == before


def test_server_checks_password_confirmation_without_leaking_password(client, database):
    before = database_state(database)
    response = client.post('/api/auth/signup', json=payload(confirm_password='DifferentPassword123!'))
    assert response.status_code == 422 and 'Passwords do not match' in response.text
    assert PASSWORD not in response.text and 'DifferentPassword123!' not in response.text
    assert database_state(database) == before


@pytest.mark.parametrize('actor', [None, 'staff@example.test', 'admin@example.test'])
def test_own_customer_summary_requires_customer_login(client, actor):
    response = client.get('/api/customers/me', headers=auth_headers(client, actor) if actor else {})
    assert response.status_code == (403 if actor else 401)


def test_customer_summary_uses_session_identity_and_keeps_birthdays_private(client, database):
    with database.begin() as session:
        session.get(Customer, 1).birthday = date(2000, 2, 29)
        session.get(Customer, 2).birthday = date(1991, 1, 1)
    login = client.post('/api/auth/login', json={'email': 'buyer@example.test', 'password': 'TestPass123!'})
    own = {'Authorization': 'Bearer '+login.json()['access_token']}
    response = client.get('/api/customers/me?customer_id=2&id=3', headers=own)
    assert response.status_code == 200
    assert response.json() == {'id': 1, 'name': 'Buyer', 'email': 'buyer@example.test', 'points': 100, 'birthday': '2000-02-29'}
    assert client.get('/api/customers', headers=own).status_code == 403
    staff_customers = client.get('/api/customers', headers=auth_headers(client, 'staff@example.test')).json()
    assert all('birthday' not in row for row in staff_customers)
