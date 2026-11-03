"""Account management must expose safe fields to Admin only."""
import pytest
from app.models import User
from app.auth import hash_password


def headers(client, email):
    result = client.post('/api/auth/login', json={'email': email, 'password': 'TestPass123!'})
    assert result.status_code == 200
    return {'Authorization': 'Bearer ' + result.json()['access_token']}


@pytest.mark.parametrize('actor', [None, 'staff@example.test', 'buyer@example.test'])
def test_account_list_is_admin_only(client, actor):
    response = client.get('/api/accounts', headers=headers(client, actor) if actor else {})
    assert response.status_code == (403 if actor else 401)


def test_admin_list_contains_only_safe_account_fields(client):
    response = client.get('/api/accounts', headers=headers(client, 'admin@example.test'))
    assert response.status_code == 200
    accounts = response.json()
    assert [account['id'] for account in accounts] == [1, 2, 3, 4, 5]
    assert all(set(account) == {'id', 'email', 'role', 'customer_id', 'active'} for account in accounts)
    assert {account['role'] for account in accounts} == {'staff', 'customer', 'admin'}
    assert 'password' not in response.text


def test_demoted_admin_cannot_list_accounts_with_old_token(client, database):
    auth = headers(client, 'admin@example.test')
    with database.begin() as session:
        session.add(User(email='backup-admin@example.test', role='admin', password_hash=hash_password('BackupAdminPass123!')))
        session.get(User, 4).role = 'staff'
    assert client.get('/api/accounts', headers=auth).status_code == 403
