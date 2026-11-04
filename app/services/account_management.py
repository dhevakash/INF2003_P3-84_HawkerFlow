"""Admin account changes preserve identities and reject deletion of linked records."""
from fastapi import HTTPException
from pymongo.errors import PyMongoError
from sqlalchemy import func, select

from app.models import Customer, User
from app.roles import Role
from app.services.accounts import AccountEmailConflict, ensure_unused_email, insert_privileged_account


def lock_account(session, actor, account_id):
    # Share the role/status lock order, including the authorization recheck.
    admins = list(session.scalars(select(User).where(User.role == Role.ADMIN)
                                  .order_by(User.id).with_for_update()))
    if not any(admin.id == actor.id and admin.active and admin.session_version == actor.session_version for admin in admins):
        raise HTTPException(403, 'Your account no longer has active Admin access.')
    account = session.scalar(select(User).where(User.id == account_id).with_for_update())
    if account is None:
        raise HTTPException(404, 'Account not found.')
    return account


def create_account(session, payload, password_hash):
    if payload.role != Role.CUSTOMER:
        return insert_privileged_account(session, email=payload.email, password_hash=password_hash, role=payload.role)
    ensure_unused_email(session, payload.email)
    customer = Customer(name=payload.name, email=payload.email, points=0, active=True)
    session.add(customer)
    session.flush()
    account = User(email=payload.email, password_hash=password_hash, role=Role.CUSTOMER.value, customer_id=customer.id)
    session.add(account)
    session.flush()
    return account


def edit_details(session, account, payload):
    other_user = session.scalar(select(User.id).where(User.id != account.id,
        func.lower(User.email) == payload.email).limit(1))
    customers = select(Customer.id).where(func.lower(Customer.email) == payload.email)
    if account.customer_id is not None:
        customers = customers.where(Customer.id != account.customer_id)
    if other_user is not None or session.scalar(customers.limit(1)) is not None:
        raise AccountEmailConflict('This email is already in use. Existing accounts and customer links were not changed.')
    customer = None
    if account.customer_id is not None:
        customer = session.scalar(select(Customer).where(Customer.id == account.customer_id).with_for_update())
        if customer is None:
            raise HTTPException(409, 'The linked customer record is missing.')
        customer.email = payload.email
        if payload.name is not None:
            customer.name = payload.name
    elif payload.name is not None:
        raise HTTPException(422, 'This account has no linked customer name to edit.')
    if account.email != payload.email:
        # Changed login identity invalidates existing sessions, just like a password reset.
        account.session_version += 1
    account.email = payload.email
    return customer


def delete_unused_account(session, account, mongo):
    if account.active:
        raise HTTPException(409, 'Disable the account before deleting it. Accounts with history must remain disabled.')
    customer = None
    if account.customer_id is not None:
        customer = session.scalar(select(Customer).where(Customer.id == account.customer_id).with_for_update())
        if customer is None or customer.points != 0:
            raise HTTPException(409, 'This account has a customer balance or a missing customer link. Keep it disabled.')
    # Inspect every declared FK so new SQL audit/history tables are protected too.
    for table in User.metadata.sorted_tables:
        for fk in table.foreign_keys:
            identity = account.id if fk.column.table.name == 'users' else (
                account.customer_id if fk.column.table.name == 'customers' else None)
            if identity is None:
                continue
            query = select(fk.parent).where(fk.parent == identity)
            if table.name == 'users':
                query = query.where(table.c.id != account.id)
            if session.execute(query.limit(1)).first() is not None:
                raise HTTPException(409, 'This account has linked ' + table.name.replace('_', ' ') + '. Keep it disabled to preserve history.')
    author_queries = [{'created_by_user_id': account.id}, {'updated_by_user_id': account.id},
                      {'replies.manager_user_id': account.id}, {'replies.updated_by_user_id': account.id}]
    profile_queries = [{'updated_by_user_id': account.id}]
    if account.customer_id is not None:
        author_queries.append({'customer_id': account.customer_id})
        profile_queries.append({'customer_id': account.customer_id})
    try:
        db = mongo()
        linked = (db.reviews.find_one({'$or': author_queries}, {'_id': 1}) is not None
                  or db.profiles.find_one({'$or': profile_queries}, {'_id': 1}) is not None)
    except PyMongoError:
        raise HTTPException(503, 'Could not verify linked documents. No account was deleted. Try again when MongoDB is available.') from None
    if linked:
        raise HTTPException(409, 'This account has linked reviews or preferences. Keep it disabled to preserve history.')
    session.delete(account)
    session.flush()
    if customer is not None:
        session.delete(customer)
        session.flush()
