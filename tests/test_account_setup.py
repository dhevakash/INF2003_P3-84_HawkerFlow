"""Initial setup and privileged creation must preserve existing identities."""
from concurrent.futures import ThreadPoolExecutor
import hashlib
import json
import sys

import pytest
from sqlalchemy import event, func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import sessionmaker

from app.auth import verify_password
from app.database import Base, make_engine
from app.models import Branch, Customer, Order, User
from app.schemas import InitialAdminInput
from app.services.accounts import AccountEmailConflict, bootstrap_admin

PASSWORD = 'NewPrivilegedPass123!'


def credentials(email='setup-admin@example.test'):
    return InitialAdminInput(email=email, password=PASSWORD)


def fingerprint(factory):
    with factory() as session:
        rows = {table.name: [dict(row) for row in session.execute(select(table).order_by(*table.primary_key)).mappings()]
                for table in Base.metadata.sorted_tables}
    return hashlib.sha256(json.dumps(rows, default=str, sort_keys=True).encode()).hexdigest()


@pytest.fixture
def setup_engine(tmp_path, password_hash):
    engine = make_engine('sqlite:///' + str(tmp_path / 'setup.sqlite'))
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    with factory.begin() as session:
        session.add_all([Branch(id=7, name='Test branch', address='Fictional'),
            Customer(id=29, name='Existing buyer', email='existing-buyer@example.test', points=90),
            User(id=19, email='existing-staff@example.test', role='staff', password_hash=password_hash)])
        session.flush()
        session.add(User(id=31, email='existing-buyer@example.test', role='customer',
                         customer_id=29, password_hash=password_hash))
        session.add(Order(id=71, request_key='historical-setup-test', request_hash='a' * 64,
            branch_id=7, customer_id=29, cashier_user_id=19, subtotal=5, discount=0, total=5))
    yield engine, factory
    engine.dispose()


def test_bootstrap_creates_separate_admin_and_preserves_history(setup_engine):
    engine, factory = setup_engine
    with factory() as session:
        original_users = [(u.id, u.email, u.role, u.password_hash, u.customer_id)
                          for u in session.scalars(select(User).order_by(User.id))]
    result = bootstrap_admin(engine, credentials)
    assert result.created and result.account_id not in {19, 31}
    with factory() as session:
        assert [(u.id, u.email, u.role, u.password_hash, u.customer_id)
                for u in session.scalars(select(User).where(User.id.in_([19, 31])).order_by(User.id))] == original_users
        admin = session.get(User, result.account_id)
        assert admin.role == 'admin' and admin.customer_id is None
        assert verify_password(PASSWORD, admin.password_hash)
        assert session.get(Order, 71).cashier_user_id == 19
        assert session.scalar(select(func.count()).select_from(Customer)) == 1


def test_repeat_setup_never_reads_new_credentials_or_resets_admin(setup_engine):
    engine, factory = setup_engine
    first = bootstrap_admin(engine, credentials)
    before = fingerprint(factory)
    def forbidden():
        raise AssertionError('Repeat setup unexpectedly requested credentials.')
    repeated = bootstrap_admin(engine, forbidden)
    assert not repeated.created and repeated.account_id == first.account_id
    assert fingerprint(factory) == before


def test_existing_admin_on_another_id_is_never_overwritten(database):
    before = fingerprint(database)
    result = bootstrap_admin(database.kw['bind'], lambda: pytest.fail('Existing Admin must skip credential entry.'))
    assert not result.created and result.account_id == 4
    assert fingerprint(database) == before


@pytest.mark.parametrize('email', ['EXISTING-STAFF@example.test', 'existing-buyer@example.test'])
def test_bootstrap_duplicate_email_never_promotes_or_claims_existing_accounts(setup_engine, email):
    engine, factory = setup_engine
    before = fingerprint(factory)
    with pytest.raises(AccountEmailConflict):
        bootstrap_admin(engine, lambda: credentials(email))
    assert fingerprint(factory) == before


def test_bootstrap_insert_failure_rolls_back_and_allows_retry(setup_engine):
    engine, factory = setup_engine
    before = fingerprint(factory)
    def fail_insert(mapper, connection, account):
        if account.email == 'setup-admin@example.test':
            raise IntegrityError('injected test failure', {}, RuntimeError('failed'))
    event.listen(User, 'before_insert', fail_insert)
    try:
        with pytest.raises(RuntimeError, match='database rejected'):
            bootstrap_admin(engine, credentials)
    finally:
        event.remove(User, 'before_insert', fail_insert)
    assert fingerprint(factory) == before
    assert bootstrap_admin(engine, credentials).created


def test_concurrent_sqlite_setup_creates_one_initial_admin(setup_engine):
    engine, factory = setup_engine
    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(executor.map(lambda i: bootstrap_admin(engine,
            lambda: credentials(f'initial-{i}@example.test')), range(2)))
    assert sum(result.created for result in results) == 1
    assert results[0].account_id == results[1].account_id
    with factory() as session:
        assert session.scalar(select(func.count()).select_from(User).where(User.role == 'admin')) == 1


def headers(client, email='admin@example.test'):
    result = client.post('/api/auth/login', json={'email': email, 'password': 'TestPass123!'})
    assert result.status_code == 200
    return {'Authorization': 'Bearer ' + result.json()['access_token']}


def account_payload(role='staff', **changes):
    return {'email': 'new-privileged@example.test', 'password': PASSWORD, 'role': role, **changes}


@pytest.mark.parametrize('role', ['staff', 'admin'])
def test_admin_can_create_and_sign_in_privileged_accounts(client, database, role):
    before = fingerprint(database)
    response = client.post('/api/accounts', headers=headers(client), json=account_payload(role))
    assert response.status_code == 201
    result = response.json()
    assert set(result) == {'id', 'email', 'role', 'customer_id', 'active'}
    assert result['role'] == role and result['customer_id'] is None
    with database() as session:
        account = session.get(User, result['id'])
        assert verify_password(PASSWORD, account.password_hash)
        assert session.scalar(select(func.count()).select_from(Customer)) == 2
        assert session.get(User, 1).role == 'staff' and session.get(User, 4).role == 'admin'
    login = client.post('/api/auth/login', json={'email': result['email'].upper(), 'password': PASSWORD})
    assert login.status_code == 200 and login.json()['role'] == role
    auth = {'Authorization': 'Bearer ' + login.json()['access_token']}
    assert client.get('/api/stock', headers=auth).status_code == 200
    assert client.put('/api/accounts/5/role', headers=auth, json={'role': 'admin'}).status_code == (200 if role == 'admin' else 403)
    assert fingerprint(database) != before


@pytest.mark.parametrize('actor', [None, 'staff@example.test', 'buyer@example.test'])
@pytest.mark.parametrize('role', ['admin', 'staff'])
def test_privileged_creation_rejects_unauthorized_callers_without_writes(client, database, actor, role):
    auth = headers(client, actor) if actor else {}
    before = fingerprint(database)
    assert client.post('/api/accounts', headers=auth, json=account_payload(role)).status_code == (403 if actor else 401)
    assert fingerprint(database) == before


@pytest.mark.parametrize('extra', [{'id': 1}, {'customer_id': 1}, {'password_hash': 'injected'},
                                  {'active': False}, {'permissions': ['*']}, {'is_admin': True}])
def test_privileged_creation_rejects_mass_assignment(client, database, extra):
    before = fingerprint(database)
    assert client.post('/api/accounts', headers=headers(client), json=account_payload(**extra)).status_code == 422
    assert fingerprint(database) == before


@pytest.mark.parametrize('role', ['customer', 'manager', 'cashier', 'owner', 'ADMIN', None])
def test_privileged_creation_accepts_only_explicit_admin_or_staff(client, database, role):
    before = fingerprint(database)
    assert client.post('/api/accounts', headers=headers(client), json=account_payload(role)).status_code == 422
    assert fingerprint(database) == before


def test_privileged_creation_requires_role_and_valid_credentials(client, database):
    before = fingerprint(database)
    for change in ({'email': 'invalid'}, {'password': 'short'}, {'password': ' ' * 12}):
        assert client.post('/api/accounts', headers=headers(client), json=account_payload(**change)).status_code == 422
    body = account_payload()
    body.pop('role')
    assert client.post('/api/accounts?role=admin', headers=headers(client), json=body).status_code == 422
    assert fingerprint(database) == before


@pytest.mark.parametrize('email', [' ADMIN@EXAMPLE.TEST ', 'staff@example.test', 'buyer@example.test'])
def test_privileged_duplicate_email_preserves_existing_accounts(client, database, email):
    before = fingerprint(database)
    assert client.post('/api/accounts', headers=headers(client), json=account_payload(email=email)).status_code == 409
    assert fingerprint(database) == before


def test_privileged_creation_cannot_claim_customer_without_login(client, database):
    with database.begin() as session:
        session.add(Customer(name='Old customer', email='unclaimed@example.test', points=900))
    before = fingerprint(database)
    assert client.post('/api/accounts', headers=headers(client),
                       json=account_payload(email='UNCLAIMED@example.test')).status_code == 409
    assert fingerprint(database) == before


def test_privileged_insert_failure_does_not_leave_account(client, database):
    before = fingerprint(database)
    auth = headers(client)
    def fail_insert(mapper, connection, account):
        if account.email == account_payload()['email']:
            raise IntegrityError('injected test failure', {}, RuntimeError('failed'))
    event.listen(User, 'before_insert', fail_insert)
    try:
        assert client.post('/api/accounts', headers=auth, json=account_payload()).status_code == 409
    finally:
        event.remove(User, 'before_insert', fail_insert)
    assert fingerprint(database) == before
    assert client.post('/api/accounts', headers=auth, json=account_payload()).status_code == 201


def test_creation_rechecks_admin_role_inside_transaction(client, database, monkeypatch):
    from app.auth import Principal, require_roles
    from app.main import app
    import app.routes as routes
    # Simulate a valid Admin principal whose stored role changed after authentication.
    app.dependency_overrides[routes.AdminOnly.dependency] = lambda: Principal(1, 'admin', None)
    before = fingerprint(database)
    try:
        assert client.post('/api/accounts', json=account_payload()).status_code == 403
    finally:
        del app.dependency_overrides[routes.AdminOnly.dependency]
    assert fingerprint(database) == before


def test_cli_hides_password_and_confirms_before_setup(setup_engine, monkeypatch, capsys):
    import app.cli as cli
    engine, factory = setup_engine
    monkeypatch.setattr(cli, 'engine', engine)
    monkeypatch.delenv('HAWKERFLOW_INITIAL_ADMIN_PASSWORD', raising=False)
    values = iter([PASSWORD, PASSWORD])
    monkeypatch.setattr(cli, 'getpass', lambda prompt: next(values))
    monkeypatch.setattr(sys, 'argv', ['cli', 'init-admin', '--email', ' Setup-Admin@Example.Test '])
    cli.main()
    output = capsys.readouterr()
    assert 'Initial Admin created' in output.out and PASSWORD not in output.out + output.err
    monkeypatch.setattr(cli, 'getpass', lambda prompt: pytest.fail('Repeat must not prompt for a password.'))
    before = fingerprint(factory)
    cli.main()
    assert 'already exists' in capsys.readouterr().out
    assert fingerprint(factory) == before


@pytest.mark.parametrize('failure', ['confirmation', 'invalid_password', 'no_terminal', 'blank_env'])
def test_cli_failed_credential_entry_never_creates_admin(setup_engine, monkeypatch, capsys, failure):
    import app.cli as cli
    engine, factory = setup_engine
    monkeypatch.setattr(cli, 'engine', engine)
    monkeypatch.delenv('HAWKERFLOW_INITIAL_ADMIN_PASSWORD', raising=False)
    monkeypatch.setattr(sys, 'argv', ['cli', 'init-admin', '--email', 'setup-admin@example.test'])
    if failure == 'no_terminal':
        def prompt(_):
            raise cli.GetPassWarning('Cannot hide input.')
    else:
        values = iter([PASSWORD, 'different'] if failure == 'confirmation' else ['short', 'short'])
        prompt = lambda _: next(values)
    if failure == 'blank_env':
        monkeypatch.setenv('HAWKERFLOW_INITIAL_ADMIN_PASSWORD', '')
    monkeypatch.setattr(cli, 'getpass', prompt)
    before = fingerprint(factory)
    with pytest.raises(SystemExit) as error:
        cli.main()
    assert error.value.code == 1
    assert fingerprint(factory) == before
    output = capsys.readouterr()
    assert PASSWORD not in output.out + output.err and 'short' not in output.err


def test_cli_environment_provisioning_does_not_echo_secret(setup_engine, monkeypatch, capsys):
    import app.cli as cli
    engine, factory = setup_engine
    monkeypatch.setattr(cli, 'engine', engine)
    monkeypatch.setenv('HAWKERFLOW_INITIAL_ADMIN_PASSWORD', PASSWORD)
    monkeypatch.setattr(cli, 'getpass', lambda _: pytest.fail('Unattended setup must not prompt.'))
    monkeypatch.setattr(sys, 'argv', ['cli', 'init-admin', '--email', 'setup-admin@example.test'])
    cli.main()
    assert PASSWORD not in str(capsys.readouterr())
    with factory() as session:
        assert session.scalar(select(User.role).where(User.email == 'setup-admin@example.test')) == 'admin'
