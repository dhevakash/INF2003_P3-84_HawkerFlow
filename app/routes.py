from datetime import datetime, timezone
from decimal import Decimal
from fastapi import APIRouter, Depends, HTTPException, Path
from sqlalchemy import delete, func, select, text
from sqlalchemy.orm import Session
from app import analytics
from app.auth import current_user, document_writer, hash_password, issue_token, principal_for, require_roles, verify_password
from app.database import engine, get_session
from app.models import (Branch, BranchStock, Customer, Ingredient, LoyaltyTransaction,
                        LoyaltyAdjustment, MenuItem, Order, OrderLine, RecipeComponent, StockAdjustment, StockMovement, StockReceipt, User)
from app.nosql import complaint_pipeline, mongo_db, monthly_pipeline
from app.roles import Role
from app.schemas import (AccountCreateInput, AccountDetailsInput, AccountListResult, AccountPasswordInput,
                         AccountResult, AccountRoleInput, AccountStatusInput, CheckoutInput, CustomerInput, Login,
                         MenuInput, PointsEditInput, PointsRemovalInput, ProfileInput, RecipeInput, ReplyInput, RestockInput,
                         ReviewInput, SignupInput, SignupResult, StockAdjustmentInput)
from app.services.accounts import AccountEmailConflict
from app.services.account_management import create_account, delete_unused_account, edit_details, lock_account
from app.services.checkout import checkout, order_result
from app.services.inventory import adjust_stock, restock
from app.services.loyalty import correct_points
from app.services.recipes import save_recipe

router = APIRouter(prefix='/api')
Operations = Depends(require_roles(Role.ADMIN, Role.STAFF))
AdminOnly = Depends(require_roles(Role.ADMIN))
CustomerOrAdmin = Depends(require_roles(Role.ADMIN, Role.CUSTOMER))


def fields(obj, *names):
    return {name: getattr(obj, name) for name in names}


def document(obj):
    if obj is None:
        raise HTTPException(404, 'Document not found.')
    obj['id'] = str(obj.pop('_id'))
    return obj


def owned_order(session, order_id, user):
    order = session.get(Order, order_id)
    if order is None or (user.role != Role.ADMIN and order.customer_id != user.customer_id):
        raise HTTPException(404, 'Purchase not found for this customer.')
    return order


@router.get('/health')
def health():
    result = {'sql': 'unavailable', 'mongo': 'unavailable', 'sql_dialect': engine.dialect.name}
    try:
        with engine.connect() as connection:
            connection.execute(text('SELECT 1'))
            result['sql'] = 'connected'
    except Exception:
        pass
    try:
        mongo_db().command('ping')
        result['mongo'] = 'connected'
    except Exception:
        pass
    return result


@router.post('/auth/signup', status_code=201, response_model=SignupResult)
def signup(payload: SignupInput, session: Session = Depends(get_session)):
    password_hash = hash_password(payload.password.get_secret_value())
    with session.begin():
        existing_account = session.scalar(select(User.id).where(func.lower(User.email) == payload.email).limit(1))
        existing_customer = session.scalar(select(Customer.id).where(func.lower(Customer.email) == payload.email).limit(1))
        if existing_account is not None or existing_customer is not None:
            raise HTTPException(409, 'This email is already in use. Sign in or contact an administrator.')
        # Never bind caller-supplied account IDs, customer links, roles or points.
        customer = Customer(name=payload.name, email=payload.email, birthday=payload.birthday, points=0, active=True)
        session.add(customer)
        session.flush()
        account = User(email=payload.email, password_hash=password_hash,
                       role=Role.CUSTOMER.value, customer_id=customer.id)
        session.add(account)
        session.flush()
        result = fields(account, 'id', 'email', 'role', 'customer_id')
    return result


@router.post('/auth/login')
def login(payload: Login, session: Session = Depends(get_session)):
    user = session.scalar(select(User).where(func.lower(User.email) == payload.email.strip().lower()))
    if not user or not user.active or not verify_password(payload.password, user.password_hash):
        raise HTTPException(401, 'Invalid email or password.')
    principal_for(user)
    return {'access_token': issue_token(user), 'token_type': 'bearer',
            'role': user.role, 'customer_id': user.customer_id}


@router.get('/auth/me')
def me(user=Depends(current_user)):
    return {'id': user.id, 'role': user.role, 'customer_id': user.customer_id}


@router.put('/accounts/{account_id}/role')
def change_account_role(account_id: int, payload: AccountRoleInput, user=AdminOnly,
                        session: Session = Depends(get_session)):
    with session.begin():
        admins = list(session.scalars(select(User).where(User.role == Role.ADMIN)
                                      .order_by(User.id).with_for_update()))
        if not any(admin.id == user.id and admin.active and admin.session_version == user.session_version for admin in admins):
            raise HTTPException(403, 'Your account no longer has Admin access.')
        account = session.scalar(select(User).where(User.id == account_id).with_for_update())
        if account is None:
            raise HTTPException(404, 'Account not found.')
        if account.role == Role.ADMIN and account.active and payload.role != Role.ADMIN and sum(admin.active for admin in admins) == 1:
            raise HTTPException(409, 'The last Admin account must retain active Admin access.')
        if payload.role == Role.CUSTOMER and account.customer_id is None:
            raise HTTPException(409, 'Link this account to a customer record before assigning the Customer role.')
        account.role = payload.role.value
        return fields(account, 'id', 'email', 'role', 'customer_id', 'active')


@router.post('/accounts', status_code=201, response_model=AccountResult)
def create_privileged_account(payload: AccountCreateInput, user=AdminOnly,
                               session: Session = Depends(get_session)):
    password_hash = hash_password(payload.password.get_secret_value())
    with session.begin():
        # Same lock order as role changes; recheck authorization under the lock.
        admins = list(session.scalars(select(User).where(User.role == Role.ADMIN)
                                      .order_by(User.id).with_for_update()))
        if not any(admin.id == user.id and admin.active and admin.session_version == user.session_version for admin in admins):
            raise HTTPException(403, 'Your account no longer has Admin access.')
        try:
            account = create_account(session, payload, password_hash)
        except AccountEmailConflict as exc:
            raise HTTPException(409, str(exc)) from None
        result = fields(account, 'id', 'email', 'role', 'customer_id', 'active')
    return result


@router.get('/accounts', response_model=list[AccountListResult])
def accounts(user=AdminOnly, session: Session = Depends(get_session)):
    return [{**fields(account, 'id', 'email', 'role', 'customer_id', 'active'), 'name': name}
            for account, name in session.execute(select(User, Customer.name)
                .outerjoin(Customer, Customer.id == User.customer_id).order_by(User.id))]


@router.put('/accounts/{account_id}', response_model=AccountListResult)
def update_account_details(account_id: int, payload: AccountDetailsInput, user=AdminOnly,
                           session: Session = Depends(get_session)):
    with session.begin():
        account = lock_account(session, user, account_id)
        try:
            customer = edit_details(session, account, payload)
        except AccountEmailConflict as exc:
            raise HTTPException(409, str(exc)) from None
        return {**fields(account, 'id', 'email', 'role', 'customer_id', 'active'),
                'name': customer.name if customer else None}


@router.put('/accounts/{account_id}/password')
def reset_account_password(account_id: int, payload: AccountPasswordInput, user=AdminOnly,
                            session: Session = Depends(get_session)):
    password_hash = hash_password(payload.password.get_secret_value())
    with session.begin():
        account = lock_account(session, user, account_id)
        account.password_hash = password_hash
        account.session_version += 1
    return {'id': account_id, 'password_reset': True}


@router.delete('/accounts/{account_id}')
def remove_unused_account(account_id: int, user=AdminOnly, session: Session = Depends(get_session)):
    with session.begin():
        account = lock_account(session, user, account_id)
        delete_unused_account(session, account, mongo_db)
    return {'deleted': account_id}


@router.put('/accounts/{account_id}/status', response_model=AccountResult)
def change_account_status(account_id: int, payload: AccountStatusInput, user=AdminOnly,
                          session: Session = Depends(get_session)):
    with session.begin():
        admins = list(session.scalars(select(User).where(User.role == Role.ADMIN)
                                      .order_by(User.id).with_for_update()))
        if not any(admin.id == user.id and admin.active and admin.session_version == user.session_version for admin in admins):
            raise HTTPException(403, 'Your account no longer has active Admin access.')
        account = session.scalar(select(User).where(User.id == account_id).with_for_update())
        if account is None:
            raise HTTPException(404, 'Account not found.')
        if not payload.active and account.active and account.role == Role.ADMIN and sum(admin.active for admin in admins) == 1:
            raise HTTPException(409, 'The last active Admin cannot be deactivated.')
        if account.active != payload.active:
            account.active = payload.active
            account.session_version += 1
        return fields(account, 'id', 'email', 'role', 'customer_id', 'active')


@router.get('/branches')
def branches(user=Depends(current_user), session: Session = Depends(get_session)):
    return [fields(b, 'id', 'name', 'address', 'source_label') for b in session.scalars(select(Branch).order_by(Branch.id))]


@router.get('/menu')
def menu(user=Depends(current_user), session: Session = Depends(get_session)):
    return [fields(m, 'id', 'name', 'price', 'active') for m in session.scalars(select(MenuItem).order_by(MenuItem.id))]


@router.post('/menu', status_code=201)
def add_menu(payload: MenuInput, user=Operations, session: Session = Depends(get_session)):
    with session.begin():
        item = MenuItem(**payload.model_dump())
        session.add(item)
        session.flush()
        return fields(item, 'id', 'name', 'price', 'active')


@router.put('/menu/{item_id}')
def update_menu(item_id: int, payload: MenuInput, user=Operations, session: Session = Depends(get_session)):
    with session.begin():
        item = session.scalar(select(MenuItem).where(MenuItem.id == item_id).with_for_update())
        if not item:
            raise HTTPException(404, 'Menu item not found.')
        for key, value in payload.model_dump().items():
            setattr(item, key, value)
        return fields(item, 'id', 'name', 'price', 'active')


@router.delete('/menu/{item_id}')
def delete_menu(item_id: int, user=Operations, session: Session = Depends(get_session)):
    with session.begin():
        item = session.scalar(select(MenuItem).where(MenuItem.id == item_id).with_for_update())
        if not item:
            raise HTTPException(404, 'Menu item not found.')
        if session.scalar(select(OrderLine.id).where(OrderLine.menu_item_id == item_id).limit(1)):
            raise HTTPException(409, 'Historical sales reference this item. Set active=false instead.')
        session.execute(delete(RecipeComponent).where(RecipeComponent.menu_item_id == item_id))
        session.delete(item)
    return {'deleted': item_id}


@router.get('/recipes')
def recipes(user=Operations, session: Session = Depends(get_session)):
    query = (select(RecipeComponent, MenuItem.name, Ingredient.name, Ingredient.unit)
        .join(MenuItem, RecipeComponent.menu_item_id == MenuItem.id)
        .join(Ingredient, RecipeComponent.ingredient_id == Ingredient.id)
        .order_by(RecipeComponent.menu_item_id, RecipeComponent.ingredient_id))
    return [{'menu_item_id': row.menu_item_id, 'menu_item': item, 'ingredient_id': row.ingredient_id,
             'ingredient': ingredient, 'quantity': format(row.quantity, '.3f'), 'unit': unit}
            for row, item, ingredient, unit in session.execute(query)]


@router.get('/ingredients')
def ingredients(user=Operations, session: Session = Depends(get_session)):
    return [fields(ingredient, 'id', 'name', 'unit')
            for ingredient in session.scalars(select(Ingredient).order_by(Ingredient.name, Ingredient.id))]


@router.put('/recipes/{item_id}')
def update_recipe(payload: RecipeInput, item_id: int = Path(gt=0), user=AdminOnly,
                  session: Session = Depends(get_session)):
    return save_recipe(session, item_id, payload)


@router.get('/customers')
def customers(user=Operations, session: Session = Depends(get_session)):
    return [fields(c, 'id', 'name', 'email', 'points', 'active') for c in session.scalars(select(Customer).order_by(Customer.id))]


@router.get('/customers/me')
def own_customer(user=Depends(require_roles(Role.CUSTOMER)), session: Session = Depends(get_session)):
    customer = session.get(Customer, user.customer_id)
    if customer is None:
        raise HTTPException(404, 'Your linked customer record was not found.')
    return fields(customer, 'id', 'name', 'email', 'birthday', 'points')


@router.post('/customers', status_code=201)
def add_customer(payload: CustomerInput, user=Operations, session: Session = Depends(get_session)):
    with session.begin():
        customer = Customer(**payload.model_dump())
        session.add(customer)
        session.flush()
        return fields(customer, 'id', 'name', 'email', 'points')


@router.put('/customers/{customer_id}')
def update_customer(customer_id: int, payload: CustomerInput, user=Operations, session: Session = Depends(get_session)):
    with session.begin():
        customer = session.get(Customer, customer_id)
        if not customer:
            raise HTTPException(404, 'Customer not found.')
        customer.name, customer.email = payload.name, payload.email
        return fields(customer, 'id', 'name', 'email', 'points')


@router.get('/stock')
def stock(user=Operations, session: Session = Depends(get_session)):
    return analytics.rows(session, '''SELECT s.branch_id, b.name AS branch, s.ingredient_id,
        i.name AS ingredient, i.unit, s.quantity FROM branch_stock s
        JOIN branches b ON b.id=s.branch_id JOIN ingredients i ON i.id=s.ingredient_id
        ORDER BY s.branch_id, s.ingredient_id''')


@router.post('/stock/receipts', status_code=201)
def replenish(payload: RestockInput, user=Operations, session: Session = Depends(get_session)):
    return restock(session, payload, user.id)


@router.get('/stock/movements')
def movements(user=Operations, session: Session = Depends(get_session)):
    query = (select(StockMovement, StockAdjustment, StockReceipt)
        .outerjoin(StockAdjustment, StockMovement.adjustment_id == StockAdjustment.id)
        .outerjoin(StockReceipt, StockMovement.receipt_id == StockReceipt.id)
        .order_by(StockMovement.id.desc()).limit(100))
    return [{**fields(m, 'id', 'branch_id', 'ingredient_id', 'delta', 'order_id', 'receipt_id', 'adjustment_id', 'created_at'),
             'kind': 'adjustment' if a else 'receipt' if receipt else 'sale',
             'actor_user_id': a.actor_user_id if a else receipt.actor_user_id if receipt else None,
             'reason': a.reason if a else receipt.note if receipt else None,
             'previous_quantity': a.previous_quantity if a else None,
             'quantity': a.quantity if a else None}
            for m, a, receipt in session.execute(query)]


@router.put('/stock/{branch_id}/{ingredient_id}')
def correct_stock(payload: StockAdjustmentInput, branch_id: int = Path(gt=0), ingredient_id: int = Path(gt=0),
                  user=AdminOnly, session: Session = Depends(get_session)):
    return adjust_stock(session, branch_id, ingredient_id, payload, user.id)


@router.post('/orders', status_code=201)
def create_order(payload: CheckoutInput, user=Operations, session: Session = Depends(get_session)):
    return checkout(session, payload, user.id)


@router.get('/orders')
def orders(user=Depends(current_user), session: Session = Depends(get_session)):
    query = select(Order)
    if user.role == 'customer':
        query = query.where(Order.customer_id == user.customer_id)
    return [{**order_result(o), 'created_at': o.created_at.isoformat() + 'Z'}
            for o in session.scalars(query.order_by(Order.id.desc()).limit(100))]


@router.get('/loyalty')
def loyalty(user=Depends(current_user), session: Session = Depends(get_session)):
    query = select(LoyaltyTransaction)
    corrections = select(LoyaltyAdjustment)
    if user.role == 'customer':
        query = query.where(LoyaltyTransaction.customer_id == user.customer_id)
        corrections = corrections.where(LoyaltyAdjustment.customer_id == user.customer_id)
    entries = [{**fields(t, 'id', 'customer_id', 'order_id', 'kind', 'delta'),
                'created_at': t.created_at.isoformat(timespec='microseconds') + 'Z', 'adjustment_id': None}
        for t in session.scalars(query.order_by(LoyaltyTransaction.created_at.desc(), LoyaltyTransaction.id.desc()).limit(100))]
    for adjustment in session.scalars(corrections.order_by(LoyaltyAdjustment.created_at.desc(), LoyaltyAdjustment.id.desc()).limit(100)):
        entry = {'id': None, 'adjustment_id': adjustment.id, 'customer_id': adjustment.customer_id,
                 'order_id': None, 'kind': 'adjustment', 'delta': adjustment.delta,
                 'created_at': adjustment.created_at.isoformat(timespec='microseconds') + 'Z'}
        if user.role == Role.ADMIN:
            entry.update(fields(adjustment, 'actor_user_id', 'action', 'previous_points', 'points', 'reason'))
        entries.append(entry)
    entries.sort(key=lambda entry: (entry['created_at'], entry['adjustment_id'] is not None,
                                   entry['adjustment_id'] or entry['id']), reverse=True)
    return entries[:100]


@router.put('/loyalty/customers/{customer_id}/points')
def edit_customer_points(payload: PointsEditInput, customer_id: int = Path(gt=0), user=AdminOnly,
                         session: Session = Depends(get_session)):
    return correct_points(session, customer_id, payload, user.id)


@router.post('/loyalty/customers/{customer_id}/points/removals')
def remove_customer_points(payload: PointsRemovalInput, customer_id: int = Path(gt=0), user=AdminOnly,
                           session: Session = Depends(get_session)):
    return correct_points(session, customer_id, payload, user.id, remove=True)


@router.get('/analytics/sql')
def sql_analytics(user=Operations, session: Session = Depends(get_session)):
    return {'branches': analytics.rows(session, analytics.RANKED_SALES),
            'items': analytics.rows(session, 'SELECT * FROM v_item_sales ORDER BY gross_sales DESC'),
            'above_average_customers': analytics.rows(session, analytics.ABOVE_AVERAGE_CUSTOMERS)}


@router.get('/reviews')
def reviews(user=Depends(current_user)):
    query = {'customer_id': user.customer_id} if user.role == 'customer' else {}
    return [document(d) for d in mongo_db().reviews.find(query).sort('created_at', -1).limit(100)]


@router.post('/reviews', status_code=201)
def add_review(payload: ReviewInput, user=CustomerOrAdmin, session: Session = Depends(get_session), write_guard=Depends(document_writer)):
    order = owned_order(session, payload.order_id, user)
    doc = {**payload.model_dump(), 'customer_id': order.customer_id,
           'branch_id': order.branch_id, 'created_at': datetime.now(timezone.utc),
           'source': 'application_purchase', 'replies': [], 'created_by_user_id': user.id}
    result = mongo_db().reviews.insert_one(doc)
    return {'id': str(result.inserted_id), 'order_id': order.id}


@router.put('/reviews/{order_id}')
def edit_review(order_id: int, payload: ReviewInput, user=CustomerOrAdmin, session: Session = Depends(get_session), write_guard=Depends(document_writer)):
    order = owned_order(session, order_id, user)
    if order_id != payload.order_id:
        raise HTTPException(422, 'Body order_id must match the path.')
    changes = payload.model_dump(exclude={'order_id'})
    changes['updated_at'] = datetime.now(timezone.utc)
    changes['updated_by_user_id'] = user.id
    result = mongo_db().reviews.update_one({'order_id': order_id, 'customer_id': order.customer_id}, {'$set': changes})
    if not result.matched_count:
        raise HTTPException(404, 'Review not found.')
    return {'updated': order_id}


@router.delete('/reviews/{order_id}')
def remove_review(order_id: int, user=CustomerOrAdmin, session: Session = Depends(get_session), write_guard=Depends(document_writer)):
    order = owned_order(session, order_id, user)
    result = mongo_db().reviews.delete_one({'order_id': order_id, 'customer_id': order.customer_id})
    if not result.deleted_count:
        raise HTTPException(404, 'Review not found.')
    return {'deleted': order_id}


@router.post('/reviews/{order_id}/replies')
def reply(order_id: int, payload: ReplyInput, user=Operations, write_guard=Depends(document_writer)):
    # Predicate and update are atomic: two simultaneous replies cannot exceed the bound.
    result = mongo_db().reviews.update_one({'order_id': order_id, 'replies.19': {'$exists': False}},
        {'$push': {'replies': {'manager_user_id': user.id, 'text': payload.text,
                             'created_at': datetime.now(timezone.utc)}}})
    if not result.matched_count:
        raise HTTPException(409, 'Review missing or the 20-reply limit has been reached.')
    return {'replied_to': order_id}


def existing_reply(db, order_id, reply_index):
    review = db.reviews.find_one({'order_id': order_id})
    if review is None or reply_index >= len(review.get('replies', [])):
        raise HTTPException(404, 'Review reply not found.')
    return review


@router.put('/reviews/{order_id}/replies/{reply_index}')
def edit_reply(order_id: int, payload: ReplyInput, reply_index: int = Path(ge=0, le=19), user=AdminOnly, write_guard=Depends(document_writer)):
    db = mongo_db()
    review = existing_reply(db, order_id, reply_index)
    updated = [dict(item) for item in review['replies']]
    updated[reply_index].update(text=payload.text, updated_at=datetime.now(timezone.utc), updated_by_user_id=user.id)
    result = db.reviews.update_one({'_id': review['_id'], 'replies': review['replies']}, {'$set': {'replies': updated}})
    if not result.matched_count:
        raise HTTPException(409, 'Review replies changed. Reload the review and try again.')
    return {'updated_reply': reply_index, 'order_id': order_id}


@router.delete('/reviews/{order_id}/replies/{reply_index}')
def delete_reply(order_id: int, reply_index: int = Path(ge=0, le=19), user=AdminOnly, write_guard=Depends(document_writer)):
    db = mongo_db()
    review = existing_reply(db, order_id, reply_index)
    updated = review['replies'][:reply_index] + review['replies'][reply_index + 1:]
    result = db.reviews.update_one({'_id': review['_id'], 'replies': review['replies']}, {'$set': {'replies': updated}})
    if not result.matched_count:
        raise HTTPException(409, 'Review replies changed. Reload the review and try again.')
    return {'deleted_reply': reply_index, 'order_id': order_id}


def own_profile_id(user):
    if user.customer_id is None:
        raise HTTPException(404, 'This account has no customer profile. Admins can use the customer-specific profile endpoints.')
    return user.customer_id


@router.get('/profiles/me')
def read_profile(user=CustomerOrAdmin):
    customer_id = own_profile_id(user)
    found = mongo_db().profiles.find_one({'customer_id': customer_id})
    if not found:
        return {'customer_id': customer_id, 'dietary_preferences': [], 'favourite_tags': []}
    return document(found)


@router.put('/profiles/me')
def save_profile(payload: ProfileInput, user=CustomerOrAdmin, write_guard=Depends(document_writer)):
    customer_id = own_profile_id(user)
    mongo_db().profiles.update_one({'customer_id': customer_id},
        {'$set': {**payload.model_dump(), 'updated_at': datetime.now(timezone.utc), 'updated_by_user_id': user.id}}, upsert=True)
    return {'updated': customer_id}


@router.get('/profiles')
def all_profiles(user=AdminOnly):
    return [document(profile) for profile in mongo_db().profiles.find().sort('customer_id', 1).limit(100)]


def existing_customer(session, customer_id):
    if session.get(Customer, customer_id) is None:
        raise HTTPException(404, 'Customer not found.')


@router.get('/profiles/{customer_id}')
def customer_profile(customer_id: int, user=AdminOnly, session: Session = Depends(get_session)):
    existing_customer(session, customer_id)
    return document(mongo_db().profiles.find_one({'customer_id': customer_id}))


@router.put('/profiles/{customer_id}')
def update_customer_profile(customer_id: int, payload: ProfileInput, user=AdminOnly,
                             session: Session = Depends(get_session), write_guard=Depends(document_writer)):
    existing_customer(session, customer_id)
    mongo_db().profiles.update_one({'customer_id': customer_id}, {'$set': {
        **payload.model_dump(), 'updated_at': datetime.now(timezone.utc), 'updated_by_user_id': user.id}}, upsert=True)
    return {'updated': customer_id}


@router.delete('/profiles/{customer_id}')
def delete_customer_profile(customer_id: int, user=AdminOnly, session: Session = Depends(get_session), write_guard=Depends(document_writer)):
    existing_customer(session, customer_id)
    if not mongo_db().profiles.delete_one({'customer_id': customer_id}).deleted_count:
        raise HTTPException(404, 'Profile not found.')
    return {'deleted': customer_id}


@router.get('/analytics/mongo')
def mongo_analytics(user=Operations):
    db = mongo_db()
    return {'negative_tags': list(db.reviews.aggregate(complaint_pipeline())),
            'monthly_ratings': list(db.reviews.aggregate(monthly_pipeline()))}
