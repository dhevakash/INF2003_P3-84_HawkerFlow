"""Real setup transactions and cross-connection locking in an owned test DB."""
from concurrent.futures import ThreadPoolExecutor
import os
import uuid

import pytest
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import sessionmaker

from app.auth import verify_password
from app.database import Base
from app.models import Customer, User
from app.schemas import InitialAdminInput
from app.services.accounts import AccountEmailConflict, AccountSetupError, bootstrap_admin

pytestmark = pytest.mark.integration
PASSWORD = 'InitialAdminTestPass123!'


@pytest.fixture
def setup_store(password_hash):
    if os.getenv('RUN_INITIAL_ADMIN_INTEGRATION') != '1':
        pytest.skip('Enable RUN_INITIAL_ADMIN_INTEGRATION with an explicit test server URL.')
    server = create_engine(os.environ['INITIAL_ADMIN_TEST_SERVER_URL'], isolation_level='AUTOCOMMIT')
    assert server.dialect.name in {'mysql', 'mariadb'}
    name = 'hawkerflow_admin_setup_' + uuid.uuid4().hex + '_test'
    assert name.startswith('hawkerflow_admin_setup_') and name.endswith('_test')
    quoted = server.dialect.identifier_preparer.quote(name)
    engine = None
    created = False
    try:
        with server.connect() as connection:
            connection.exec_driver_sql('CREATE DATABASE ' + quoted)
            created = True
        engine = create_engine(server.url.set(database=name), pool_pre_ping=True)
        Base.metadata.create_all(engine)
        factory = sessionmaker(bind=engine, expire_on_commit=False)
        with factory.begin() as session:
            session.add(Customer(id=29, name='Old customer', email='old-customer@example.test', points=900))
            session.add(User(id=19, email='old-staff@example.test', role='staff', password_hash=password_hash))
        yield engine, factory
    finally:
        if engine is not None:
            engine.dispose()
        if created:
            # Only this fixture's freshly created UUID database may be dropped.
            assert name.startswith('hawkerflow_admin_setup_') and name.endswith('_test')
            with server.connect() as connection:
                connection.exec_driver_sql('DROP DATABASE ' + quoted)
        server.dispose()


def supplied(email='initial-admin@example.test'):
    return InitialAdminInput(email=email, password=PASSWORD)


def test_real_setup_creates_one_admin_and_repeat_changes_nothing(setup_store):
    engine, factory = setup_store
    with factory() as session:
        staff = session.get(User, 19)
        identity = (staff.id, staff.role, staff.email, staff.password_hash)
    first = bootstrap_admin(engine, supplied)
    repeated = bootstrap_admin(engine, lambda: pytest.fail('Repeat setup must not read new credentials.'))
    assert first.created and not repeated.created and first.account_id == repeated.account_id
    with factory() as session:
        assert session.scalar(select(func.count()).select_from(User).where(User.role == 'admin')) == 1
        admin = session.get(User, first.account_id)
        assert verify_password(PASSWORD, admin.password_hash)
        assert admin.id != 19 and admin.customer_id is None
        staff = session.get(User, 19)
        assert (staff.id, staff.role, staff.email, staff.password_hash) == identity
        assert session.get(Customer, 29).points == 900


def test_real_concurrent_setup_creates_one_admin_across_connections(setup_store):
    engine, factory = setup_store
    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(executor.map(lambda i: bootstrap_admin(engine,
            lambda: supplied(f'initial-{i}@example.test')), range(2)))
    assert sum(result.created for result in results) == 1
    assert results[0].account_id == results[1].account_id
    with factory() as session:
        assert session.scalar(select(func.count()).select_from(User)) == 2
        assert session.scalar(select(func.count()).select_from(User).where(User.role == 'admin')) == 1


@pytest.mark.parametrize('email', [' OLD-STAFF@EXAMPLE.TEST ', 'old-customer@example.test'])
def test_real_setup_never_promotes_or_claims_existing_email(setup_store, email):
    engine, factory = setup_store
    with pytest.raises(AccountEmailConflict):
        bootstrap_admin(engine, lambda: supplied(email))
    with factory() as session:
        assert session.scalar(select(func.count()).select_from(User)) == 1
        assert session.get(User, 19).role == 'staff'
        assert session.get(Customer, 29).points == 900
    # The failed transaction released its named lock and a corrected retry works.
    assert bootstrap_admin(engine, supplied).created


def test_real_setup_refuses_unmigrated_roles_without_changes(setup_store):
    engine, factory = setup_store
    with engine.begin() as connection:
        connection.exec_driver_sql('ALTER TABLE users DROP CONSTRAINT ck_user_role')
        connection.exec_driver_sql("UPDATE users SET role = 'manager' WHERE id = 19")
        connection.exec_driver_sql("ALTER TABLE users ADD CONSTRAINT ck_user_role "
            "CHECK (role IN ('manager','cashier','customer'))")
    with pytest.raises(AccountSetupError, match='role migration'):
        bootstrap_admin(engine, supplied)
    with factory() as session:
        assert session.scalar(select(func.count()).select_from(User)) == 1
        assert session.get(User, 19).role == 'manager'


def test_real_coordinated_migration_preserves_existing_accounts_and_orders(setup_store):
    import importlib.util
    from pathlib import Path
    from app.models import Branch, Order
    engine, factory = setup_store
    with factory.begin() as session:
        user = session.get(User, 19)
        identity = (user.id, user.email, user.password_hash, user.customer_id)
        session.add(Branch(id=7, name='Historical branch', address='Fictional'))
        session.flush()
        session.add(Order(id=71, request_key='migration-history', request_hash='a' * 64,
            branch_id=7, customer_id=29, cashier_user_id=19, subtotal=5, discount=0, total=5))
    with engine.begin() as connection:
        connection.exec_driver_sql('ALTER TABLE users DROP CONSTRAINT ck_user_active, '
            'DROP CONSTRAINT ck_user_session_version, DROP COLUMN active, DROP COLUMN session_version, '
            'DROP CONSTRAINT ck_user_role')
        connection.exec_driver_sql("UPDATE users SET role='manager' WHERE id=19")
        connection.exec_driver_sql("ALTER TABLE users ADD CONSTRAINT ck_user_role CHECK (role IN ('manager','cashier','customer'))")
    path = Path(__file__).resolve().parents[2] / 'database/migrations/002_account_activation.py'
    spec = importlib.util.spec_from_file_location('upgrade_002_test', path)
    migration = importlib.util.module_from_spec(spec); spec.loader.exec_module(migration)
    result = migration.upgrade(engine, engine.url.database)
    assert result['accounts_preserved'] == 1 and result['role_changes'] == [19]
    assert migration.upgrade(engine, engine.url.database)['status'] == 'already_applied'
    with factory() as session:
        user = session.get(User, 19)
        assert (user.id, user.email, user.password_hash, user.customer_id) == identity
        assert user.role == 'staff' and user.active and user.session_version == 0
        assert session.get(Order, 71).cashier_user_id == 19
        assert session.get(Customer, 29).points == 900


def test_real_concurrent_admin_deactivations_preserve_one_active_admin(setup_store):
    from threading import Barrier
    from fastapi import HTTPException
    from app.auth import Principal
    from app.routes import change_account_status
    from app.schemas import AccountStatusInput
    engine, factory = setup_store
    with factory.begin() as session:
        admins = [User(email=f'concurrent-admin-{i}@example.test', role='admin', password_hash='unused-test-hash')
                  for i in range(2)]
        session.add_all(admins); session.flush()
        ids = [admin.id for admin in admins]
    barrier = Barrier(2)
    def deactivate(account_id):
        barrier.wait(timeout=10)
        try:
            with factory() as session:
                change_account_status(account_id, AccountStatusInput(active=False),
                    user=Principal(account_id, 'admin', None), session=session)
            return 200
        except HTTPException as error:
            return error.status_code
    with ThreadPoolExecutor(max_workers=2) as executor:
        statuses = list(executor.map(deactivate, ids))
    assert sorted(statuses) == [200, 409]
    with factory() as session:
        assert session.scalar(select(func.count()).select_from(User).where(User.role == 'admin', User.active.is_(True))) == 1
