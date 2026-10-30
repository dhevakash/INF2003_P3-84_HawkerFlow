from datetime import datetime, timezone
from decimal import Decimal
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import delete, select, text
from sqlalchemy.orm import Session
from app import analytics
from app.auth import current_user, issue_token, require_roles, verify_password
from app.database import engine, get_session
from app.models import (Branch, BranchStock, Customer, Ingredient, LoyaltyTransaction,
                        MenuItem, Order, OrderLine, RecipeComponent, StockMovement, User)
from app.nosql import complaint_pipeline, mongo_db, monthly_pipeline
from app.schemas import (CheckoutInput, CustomerInput, Login, MenuInput, ProfileInput,
                         ReplyInput, RestockInput, ReviewInput)
from app.services.checkout import checkout, order_result
from app.services.inventory import restock

router = APIRouter(prefix='/api')
Staff = Depends(require_roles('manager', 'cashier'))
Manager = Depends(require_roles('manager'))
CustomerOnly = Depends(require_roles('customer'))


def fields(obj, *names):
    return {name: getattr(obj, name) for name in names}


def document(obj):
    if obj is None:
        raise HTTPException(404, 'Document not found.')
    obj['id'] = str(obj.pop('_id'))
    return obj


def owned_order(session, order_id, user):
    order = session.get(Order, order_id)
    if order is None or order.customer_id != user.customer_id:
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


@router.post('/auth/login')
def login(payload: Login, session: Session = Depends(get_session)):
    user = session.scalar(select(User).where(User.email == payload.email))
    if not user or not verify_password(payload.password, user.password_hash):
        raise HTTPException(401, 'Invalid email or password.')
    return {'access_token': issue_token(user), 'token_type': 'bearer',
            'role': user.role, 'customer_id': user.customer_id}


@router.get('/auth/me')
def me(user=Depends(current_user)):
    return {'id': user.id, 'role': user.role, 'customer_id': user.customer_id}


@router.get('/branches')
def branches(user=Depends(current_user), session: Session = Depends(get_session)):
    return [fields(b, 'id', 'name', 'address', 'source_label') for b in session.scalars(select(Branch).order_by(Branch.id))]


@router.get('/menu')
def menu(user=Depends(current_user), session: Session = Depends(get_session)):
    return [fields(m, 'id', 'name', 'price', 'active') for m in session.scalars(select(MenuItem).order_by(MenuItem.id))]


@router.post('/menu', status_code=201)
def add_menu(payload: MenuInput, user=Manager, session: Session = Depends(get_session)):
    with session.begin():
        item = MenuItem(**payload.model_dump())
        session.add(item)
        session.flush()
        return fields(item, 'id', 'name', 'price', 'active')


@router.put('/menu/{item_id}')
def update_menu(item_id: int, payload: MenuInput, user=Manager, session: Session = Depends(get_session)):
    with session.begin():
        item = session.scalar(select(MenuItem).where(MenuItem.id == item_id).with_for_update())
        if not item:
            raise HTTPException(404, 'Menu item not found.')
        for key, value in payload.model_dump().items():
            setattr(item, key, value)
        return fields(item, 'id', 'name', 'price', 'active')


@router.delete('/menu/{item_id}')
def delete_menu(item_id: int, user=Manager, session: Session = Depends(get_session)):
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
def recipes(user=Staff, session: Session = Depends(get_session)):
    return [fields(r, 'menu_item_id', 'ingredient_id', 'quantity') for r in session.scalars(select(RecipeComponent))]


@router.get('/customers')
def customers(user=Staff, session: Session = Depends(get_session)):
    return [fields(c, 'id', 'name', 'email', 'points', 'active') for c in session.scalars(select(Customer).order_by(Customer.id))]


@router.post('/customers', status_code=201)
def add_customer(payload: CustomerInput, user=Staff, session: Session = Depends(get_session)):
    with session.begin():
        customer = Customer(**payload.model_dump())
        session.add(customer)
        session.flush()
        return fields(customer, 'id', 'name', 'email', 'points')


@router.put('/customers/{customer_id}')
def update_customer(customer_id: int, payload: CustomerInput, user=Manager, session: Session = Depends(get_session)):
    with session.begin():
        customer = session.get(Customer, customer_id)
        if not customer:
            raise HTTPException(404, 'Customer not found.')
        customer.name, customer.email = payload.name, payload.email
        return fields(customer, 'id', 'name', 'email', 'points')


@router.get('/stock')
def stock(user=Staff, session: Session = Depends(get_session)):
    return analytics.rows(session, '''SELECT s.branch_id, b.name AS branch, s.ingredient_id,
        i.name AS ingredient, i.unit, s.quantity FROM branch_stock s
        JOIN branches b ON b.id=s.branch_id JOIN ingredients i ON i.id=s.ingredient_id
        ORDER BY s.branch_id, s.ingredient_id''')


@router.post('/stock/receipts', status_code=201)
def replenish(payload: RestockInput, user=Manager, session: Session = Depends(get_session)):
    return restock(session, payload, user.id)


@router.get('/stock/movements')
def movements(user=Manager, session: Session = Depends(get_session)):
    return [fields(m, 'id', 'branch_id', 'ingredient_id', 'delta', 'order_id', 'receipt_id', 'created_at')
            for m in session.scalars(select(StockMovement).order_by(StockMovement.id.desc()).limit(100))]


@router.post('/orders', status_code=201)
def create_order(payload: CheckoutInput, user=Staff, session: Session = Depends(get_session)):
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
    if user.role == 'customer':
        query = query.where(LoyaltyTransaction.customer_id == user.customer_id)
    return [fields(t, 'id', 'customer_id', 'order_id', 'kind', 'delta')
            for t in session.scalars(query.order_by(LoyaltyTransaction.id.desc()).limit(100))]


@router.get('/analytics/sql')
def sql_analytics(user=Manager, session: Session = Depends(get_session)):
    return {'branches': analytics.rows(session, analytics.RANKED_SALES),
            'items': analytics.rows(session, 'SELECT * FROM v_item_sales ORDER BY gross_sales DESC'),
            'above_average_customers': analytics.rows(session, analytics.ABOVE_AVERAGE_CUSTOMERS)}


@router.get('/reviews')
def reviews(user=Depends(current_user)):
    query = {'customer_id': user.customer_id} if user.role == 'customer' else {}
    return [document(d) for d in mongo_db().reviews.find(query).sort('created_at', -1).limit(100)]


@router.post('/reviews', status_code=201)
def add_review(payload: ReviewInput, user=CustomerOnly, session: Session = Depends(get_session)):
    order = owned_order(session, payload.order_id, user)
    doc = {**payload.model_dump(), 'customer_id': user.customer_id,
           'branch_id': order.branch_id, 'created_at': datetime.now(timezone.utc),
           'source': 'application_purchase', 'replies': []}
    result = mongo_db().reviews.insert_one(doc)
    return {'id': str(result.inserted_id), 'order_id': order.id}


@router.put('/reviews/{order_id}')
def edit_review(order_id: int, payload: ReviewInput, user=CustomerOnly, session: Session = Depends(get_session)):
    owned_order(session, order_id, user)
    if order_id != payload.order_id:
        raise HTTPException(422, 'Body order_id must match the path.')
    changes = payload.model_dump(exclude={'order_id'})
    changes['updated_at'] = datetime.now(timezone.utc)
    result = mongo_db().reviews.update_one({'order_id': order_id, 'customer_id': user.customer_id}, {'$set': changes})
    if not result.matched_count:
        raise HTTPException(404, 'Review not found.')
    return {'updated': order_id}


@router.delete('/reviews/{order_id}')
def remove_review(order_id: int, user=CustomerOnly, session: Session = Depends(get_session)):
    owned_order(session, order_id, user)
    result = mongo_db().reviews.delete_one({'order_id': order_id, 'customer_id': user.customer_id})
    if not result.deleted_count:
        raise HTTPException(404, 'Review not found.')
    return {'deleted': order_id}


@router.post('/reviews/{order_id}/replies')
def reply(order_id: int, payload: ReplyInput, user=Manager):
    # Predicate and update are atomic: two simultaneous replies cannot exceed the bound.
    result = mongo_db().reviews.update_one({'order_id': order_id, 'replies.19': {'$exists': False}},
        {'$push': {'replies': {'manager_user_id': user.id, 'text': payload.text,
                             'created_at': datetime.now(timezone.utc)}}})
    if not result.matched_count:
        raise HTTPException(409, 'Review missing or the 20-reply limit has been reached.')
    return {'replied_to': order_id}


@router.get('/profiles/me')
def read_profile(user=CustomerOnly):
    found = mongo_db().profiles.find_one({'customer_id': user.customer_id})
    if not found:
        return {'customer_id': user.customer_id, 'dietary_preferences': [], 'favourite_tags': []}
    return document(found)


@router.put('/profiles/me')
def save_profile(payload: ProfileInput, user=CustomerOnly):
    mongo_db().profiles.update_one({'customer_id': user.customer_id},
        {'$set': {**payload.model_dump(), 'updated_at': datetime.now(timezone.utc)}}, upsert=True)
    return {'updated': user.customer_id}


@router.get('/analytics/mongo')
def mongo_analytics(user=Manager):
    db = mongo_db()
    return {'negative_tags': list(db.reviews.aggregate(complaint_pipeline())),
            'monthly_ratings': list(db.reviews.aggregate(monthly_pipeline()))}
