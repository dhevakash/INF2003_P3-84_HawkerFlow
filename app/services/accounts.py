"""Explicit privileged account setup; never run by signup, imports or startup."""
from collections.abc import Callable
from dataclasses import dataclass
import hashlib

from sqlalchemy import func, select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.auth import hash_password
from app.models import Customer, User
from app.roles import Role, VALID_ROLES
from app.schemas import InitialAdminInput


class AccountSetupError(RuntimeError):
    pass


class AccountEmailConflict(AccountSetupError):
    pass


def ensure_unused_email(session, email):
    if (session.scalar(select(User.id).where(func.lower(User.email) == email).limit(1)) is not None
            or session.scalar(select(Customer.id).where(func.lower(Customer.email) == email).limit(1)) is not None):
        raise AccountEmailConflict('This email is already in use. Existing accounts and customer links were not changed.')


def insert_privileged_account(session, *, email, password_hash, role):
    if role not in {Role.ADMIN, Role.STAFF}:
        raise ValueError('Privileged creation requires Admin or Staff.')
    ensure_unused_email(session, email)
    # No caller-selected ID or customer association; preserve historical identities.
    account = User(email=email, password_hash=password_hash, role=str(role), customer_id=None)
    session.add(account)
    session.flush()
    return account


@dataclass(frozen=True)
class BootstrapResult:
    created: bool
    account_id: int


def _bootstrap_in_transaction(session, credentials):
    if set(session.scalars(select(User.role).distinct())) - VALID_ROLES:
        raise AccountSetupError('Complete the Admin/Staff/Customer role migration before creating the initial Admin.')
    existing_id = session.scalar(select(User.id).where(User.role == Role.ADMIN).order_by(User.id).limit(1))
    if existing_id is not None:
        return BootstrapResult(False, existing_id)
    # Read secrets only when setup is necessary, after obtaining the setup lock.
    supplied = credentials()
    if not isinstance(supplied, InitialAdminInput):
        raise TypeError('Initial Admin credentials must be validated.')
    account = insert_privileged_account(session, email=supplied.email,
        password_hash=hash_password(supplied.password.get_secret_value()), role=Role.ADMIN)
    return BootstrapResult(True, account.id)


def bootstrap_admin(engine, credentials: Callable[[], InitialAdminInput]):
    """Create at most one initial Admin, without changing any existing account.

    MariaDB serializes setup across processes on one pinned connection. SQLite
    preview uses an immediate write transaction before reading the Admin count.
    """
    dialect = engine.dialect.name
    try:
        if dialect == 'sqlite':
            with Session(engine) as session, session.begin():
                session.connection().exec_driver_sql('BEGIN IMMEDIATE')
                return _bootstrap_in_transaction(session, credentials)
        if dialect not in {'mysql', 'mariadb'}:
            raise AccountSetupError('Admin setup supports MariaDB and the SQLite preview.')
        lock_name = 'hf_initial_admin_' + hashlib.sha256(engine.url.database.encode()).hexdigest()[:32]
        with engine.connect() as connection:
            acquired = connection.execute(text('SELECT GET_LOCK(:name, 10)'), {'name': lock_name}).scalar_one()
            connection.commit()
            if acquired != 1:
                raise AccountSetupError('Another Admin setup is running. Try again after it finishes.')
            try:
                with Session(bind=connection) as session, session.begin():
                    return _bootstrap_in_transaction(session, credentials)
            finally:
                connection.rollback()
                try:
                    released = connection.execute(text('SELECT RELEASE_LOCK(:name)'), {'name': lock_name}).scalar_one()
                    connection.commit()
                    if released != 1:
                        raise AccountSetupError('The Admin setup lock could not be released.')
                except Exception:
                    # Never return a pooled connection with an unreleased named lock.
                    connection.invalidate()
                    raise
    except IntegrityError:
        raise AccountSetupError('The database rejected Admin setup. Check the role migration and use an unused email.') from None
