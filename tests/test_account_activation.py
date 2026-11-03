import importlib.util
from pathlib import Path

import jwt
import pytest
from sqlalchemy import create_engine, select

from app.auth import issue_token
from app.config import JWT_SECRET
from app.models import User


def login(client, email='admin@example.test'):
    response = client.post('/api/auth/login', json={'email': email, 'password': 'TestPass123!'})
    assert response.status_code == 200
    return {'Authorization': 'Bearer ' + response.json()['access_token']}


@pytest.mark.parametrize('actor', [None, 'staff@example.test', 'buyer@example.test'])
def test_only_admin_can_change_status(client, database, actor):
    before = None
    with database() as session:
        user = session.get(User, 1)
        before = (user.active, user.session_version)
    response = client.put('/api/accounts/1/status', headers=login(client, actor) if actor else {}, json={'active': False})
    assert response.status_code == (403 if actor else 401)
    with database() as session:
        user = session.get(User, 1)
        assert (user.active, user.session_version) == before


def test_deactivate_preserves_identity_and_revokes_old_tokens_even_after_reactivation(client, database):
    admin, original = login(client), login(client, 'staff@example.test')
    with database() as session:
        user = session.get(User, 1)
        identity = (user.id, user.email, user.role, user.password_hash, user.customer_id)
    assert client.put('/api/accounts/1/status', headers=admin, json={'active': False}).status_code == 200
    assert client.get('/api/auth/me', headers=original).status_code == 401
    assert client.post('/api/auth/login', json={'email': 'staff@example.test', 'password': 'TestPass123!'}).status_code == 401
    assert client.put('/api/accounts/1/status', headers=admin, json={'active': True}).status_code == 200
    assert client.get('/api/auth/me', headers=original).status_code == 401
    assert client.get('/api/stock', headers=login(client, 'staff@example.test')).status_code == 200
    with database() as session:
        user = session.get(User, 1)
        assert (user.id, user.email, user.role, user.password_hash, user.customer_id) == identity
        assert user.active and user.session_version == 2


def test_last_active_admin_is_preserved_even_when_an_inactive_admin_exists(client, database, password_hash):
    with database.begin() as session:
        session.add(User(email='inactive-admin@example.test', password_hash=password_hash, role='admin', active=False))
    admin = login(client)
    assert client.put('/api/accounts/4/status', headers=admin, json={'active': False}).status_code == 409
    assert client.put('/api/accounts/4/role', headers=admin, json={'role': 'staff'}).status_code == 409


def test_admin_can_deactivate_another_admin_and_self_when_another_active_admin_exists(client, database, password_hash):
    with database.begin() as session:
        session.add(User(email='second-admin@example.test', password_hash=password_hash, role='admin'))
    auth = login(client)
    assert client.put('/api/accounts/4/status', headers=auth, json={'active': False}).status_code == 200
    assert client.get('/api/accounts', headers=auth).status_code == 401
    other = login(client, 'second-admin@example.test')
    assert client.put('/api/accounts/4/status', headers=other, json={'active': True}).status_code == 200
    assert client.get('/api/accounts', headers=auth).status_code == 401


@pytest.mark.parametrize('body', [{'active': 'false'}, {'active': 0}, {'active': None},
                                  {'active': False, 'role': 'admin'}, {'active': False, 'id': 4}])
def test_status_input_is_strict_and_rejects_mass_assignment(client, body):
    assert client.put('/api/accounts/1/status', headers=login(client), json=body).status_code == 422


def test_status_idempotence_and_unknown_account(client, database):
    auth = login(client)
    assert client.put('/api/accounts/1/status', headers=auth, json={'active': False}).status_code == 200
    assert client.put('/api/accounts/1/status', headers=auth, json={'active': False}).status_code == 200
    with database() as session:
        assert session.get(User, 1).session_version == 1
    assert client.put('/api/accounts/999/status', headers=auth, json={'active': False}).status_code == 404


def test_legacy_and_invalid_session_version_tokens_are_rejected(client, database):
    with database() as session:
        claims = jwt.decode(issue_token(session.get(User, 1)), JWT_SECRET, algorithms=['HS256'])
    for change in (None, '0', True, -1, 1):
        forged = {**claims}
        if change is None:
            del forged['ver']
        else:
            forged['ver'] = change
        token = jwt.encode(forged, JWT_SECRET, algorithm='HS256')
        assert client.get('/api/stock', headers={'Authorization': 'Bearer ' + token}).status_code == 401


def test_migration_requires_an_exact_target_and_live_opt_in():
    path = Path(__file__).resolve().parents[1] / 'database/migrations/002_account_activation.py'
    spec = importlib.util.spec_from_file_location('activation_migration', path)
    module = importlib.util.module_from_spec(spec); spec.loader.exec_module(module)
    engine = create_engine('mysql+pymysql://unused:unused@localhost/hawkerflow')
    try:
        with pytest.raises(ValueError, match='live databases are refused'):
            module.upgrade(engine, 'hawkerflow')
        with pytest.raises(ValueError, match='does not match'):
            module.upgrade(engine, 'another', allow_live=True)
    finally:
        engine.dispose()
