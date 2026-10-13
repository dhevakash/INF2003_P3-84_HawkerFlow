"""Authenticated HTTP adapters for the operational SQL application."""
from datetime import date, datetime, time
from decimal import Decimal
from typing import Annotated
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, ConfigDict, Field, StrictInt, field_validator
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session
from app.db import get_session
from app.models import Branch, BranchStock, Customer, Ingredient, MenuItem, Order, RecipeComponent, User
from app.security import current_user, require_roles
from app.sql_service import BusinessError, checkout, list_inventory, loyalty_summary, order_dict, receive_stock, sales_analytics, menu_availability, list_batches, waste_analytics, discard_batch

router = APIRouter(prefix="/api", tags=["SQL operations"])
SessionDep = Annotated[Session, Depends(get_session)]
UserDep = Annotated[User, Depends(current_user)]
StaffDep = Annotated[User, Depends(require_roles("manager", "cashier"))]
ManagerDep = Annotated[User, Depends(require_roles("manager"))]

class Input(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

class CustomerInput(Input):
    name: str = Field(min_length=1, max_length=150)
    email: str = Field(min_length=3, max_length=254)
    @field_validator("email")
    @classmethod
    def valid_email(cls, value):
        if value.count("@") != 1 or not all(value.split("@")) or " " in value:
            raise ValueError("A valid email address is required")
        return value.lower()

class MenuInput(Input):
    name: str = Field(min_length=1, max_length=150)
    category: str = Field(min_length=1, max_length=80)
    price: Decimal = Field(ge=0, max_digits=12, decimal_places=2)

class MenuPatch(Input):
    name: str | None = Field(default=None, min_length=1, max_length=150)
    category: str | None = Field(default=None, min_length=1, max_length=80)
    price: Decimal | None = Field(default=None, ge=0, max_digits=12, decimal_places=2)
    is_active: bool | None = None
    @field_validator("name", "category", "price", "is_active", mode="before")
    @classmethod
    def no_explicit_null(cls, value):
        if value is None:
            raise ValueError("Fields cannot be null")
        return value

class IngredientInput(Input):
    name: str = Field(min_length=1, max_length=150)
    unit: str = Field(min_length=1, max_length=20)

class RecipeInput(Input):
    ingredient_id: StrictInt = Field(gt=0)
    quantity: Decimal = Field(gt=0, max_digits=14, decimal_places=4)

class ReceiptInput(Input):
    branch_id: StrictInt = Field(gt=0)
    ingredient_id: StrictInt = Field(gt=0)
    quantity: Decimal = Field(gt=0, max_digits=14, decimal_places=4)
    request_key: str = Field(min_length=1, max_length=100)
    expires_on: date | None = None
    unit_cost: Decimal | None = Field(default=None, ge=0, max_digits=14, decimal_places=4)

class DiscardInput(Input):
    request_key: str = Field(min_length=1, max_length=100)

class ReorderInput(Input):
    reorder_level: Decimal = Field(ge=0, max_digits=14, decimal_places=4)

class LineInput(Input):
    menu_item_id: StrictInt = Field(gt=0)
    quantity: StrictInt = Field(gt=0, le=1000)
    notes: str = Field(default="", max_length=500)

class OrderInput(Input):
    branch_id: StrictInt = Field(gt=0)
    customer_id: StrictInt = Field(gt=0)
    request_key: str = Field(min_length=1, max_length=100)
    redeem_points: StrictInt = Field(default=0, ge=0)
    lines: list[LineInput] = Field(min_length=1, max_length=100)

def invoke(function, *args, **kwargs):
    try:
        return function(*args, **kwargs)
    except BusinessError as error:
        raise HTTPException(error.status_code, error.detail) from error

def commit(session):
    try:
        session.commit()
    except IntegrityError as error:
        session.rollback()
        raise HTTPException(409, "Data conflicts with existing records or constraints") from error

def branch_access(user, branch_id):
    if user.role == "cashier" and (user.branch_id is None or user.branch_id != branch_id):
        raise HTTPException(403, "Cashier access is restricted to the assigned branch")

def order_access(user, order):
    if user.role == "customer" and user.customer_id != order.customer_id:
        raise HTTPException(403, "You can only access your own orders")
    branch_access(user, order.branch_id)

def menu_dict(item):
    return {"id": item.id, "name": item.name, "category": item.category, "price": float(item.price), "is_active": item.is_active}

@router.get("/branches")
def branches(session: SessionDep, user: UserDep):
    return [{"id": b.id, "name": b.name, "address": b.address, "postal_code": b.postal_code} for b in session.scalars(select(Branch).order_by(Branch.id))]

@router.get("/customers")
def customers(session: SessionDep, user: StaffDep):
    return [{"id": c.id, "name": c.name, "email": c.email} for c in session.scalars(select(Customer).order_by(Customer.id))]

@router.post("/customers", status_code=201)
def create_customer(payload: CustomerInput, session: SessionDep, user: StaffDep):
    customer = Customer(**payload.model_dump())
    session.add(customer)
    commit(session)
    return {"id": customer.id, "name": customer.name, "email": customer.email}

@router.get("/menu")
def menu(session: SessionDep, user: UserDep, include_inactive: bool = False):
    if include_inactive and user.role != "manager":
        raise HTTPException(403, "Only managers can include inactive menu items")
    query = select(MenuItem).order_by(MenuItem.id)
    if not include_inactive:
        query = query.where(MenuItem.is_active.is_(True))
    return [menu_dict(item) for item in session.scalars(query)]

@router.post("/menu", status_code=201)
def create_menu(payload: MenuInput, session: SessionDep, user: ManagerDep):
    item = MenuItem(**payload.model_dump(), is_active=True)
    session.add(item)
    commit(session)
    return menu_dict(item)

@router.get("/menu/availability")
def availability(session: SessionDep, user: StaffDep, branch_id: int = Query(gt=0)):
    branch_access(user, branch_id)
    return invoke(menu_availability, session, branch_id)

@router.patch("/menu/{item_id}")
def update_menu(item_id: int, payload: MenuPatch, session: SessionDep, user: ManagerDep):
    item = session.scalar(select(MenuItem).where(MenuItem.id == item_id).with_for_update())
    if item is None:
        raise HTTPException(404, "Menu item not found")
    updates = payload.model_dump(exclude_unset=True)
    if not updates:
        raise HTTPException(422, "At least one field is required")
    for key, value in updates.items():
        setattr(item, key, value)
    commit(session)
    return menu_dict(item)

@router.delete("/menu/{item_id}")
def delete_menu(item_id: int, session: SessionDep, user: ManagerDep):
    item = session.scalar(select(MenuItem).where(MenuItem.id == item_id).with_for_update())
    if item is None:
        raise HTTPException(404, "Menu item not found")
    item.is_active = False
    commit(session)
    return menu_dict(item)

@router.get("/ingredients")
def ingredients(session: SessionDep, user: StaffDep):
    return [{"id": i.id, "name": i.name, "unit": i.unit} for i in session.scalars(select(Ingredient).order_by(Ingredient.id))]

@router.post("/ingredients", status_code=201)
def create_ingredient(payload: IngredientInput, session: SessionDep, user: ManagerDep):
    ingredient = Ingredient(**payload.model_dump())
    session.add(ingredient)
    commit(session)
    return {"id": ingredient.id, "name": ingredient.name, "unit": ingredient.unit}

@router.get("/menu/{item_id}/recipe")
def get_recipe(item_id: int, session: SessionDep, user: StaffDep):
    if session.get(MenuItem, item_id) is None:
        raise HTTPException(404, "Menu item not found")
    return [{"ingredient_id": c.ingredient_id, "quantity": float(c.quantity)} for c in session.scalars(select(RecipeComponent).where(RecipeComponent.menu_item_id == item_id).order_by(RecipeComponent.ingredient_id))]

@router.put("/menu/{item_id}/recipe")
def put_recipe(item_id: int, payload: list[RecipeInput], session: SessionDep, user: ManagerDep):
    item = session.scalar(select(MenuItem).where(MenuItem.id == item_id).with_for_update())
    if item is None:
        raise HTTPException(404, "Menu item not found")
    if not 1 <= len(payload) <= 100 or len({p.ingredient_id for p in payload}) != len(payload):
        raise HTTPException(422, "Recipe requires 1 to 100 distinct ingredients")
    for component in payload:
        if session.get(Ingredient, component.ingredient_id) is None:
            raise HTTPException(404, "Ingredient not found")
    for old in session.scalars(select(RecipeComponent).where(RecipeComponent.menu_item_id == item_id)).all():
        session.delete(old)
    session.flush()
    for component in payload:
        session.add(RecipeComponent(menu_item_id=item_id, **component.model_dump()))
    commit(session)
    return [{"ingredient_id": c.ingredient_id, "quantity": float(c.quantity)} for c in payload]

@router.get("/inventory")
def inventory(session: SessionDep, user: StaffDep, branch_id: int = Query(gt=0)):
    branch_access(user, branch_id)
    return invoke(list_inventory, session, branch_id)

@router.post("/inventory/receive")
def receive(payload: ReceiptInput, session: SessionDep, user: ManagerDep):
    return invoke(receive_stock, session, payload.model_dump())

@router.get("/inventory/batches")
def batches(session: SessionDep, user: StaffDep, branch_id: int = Query(gt=0)):
    branch_access(user, branch_id)
    return invoke(list_batches, session, branch_id)

@router.post("/inventory/batches/{batch_id}/discard")
def discard(batch_id: int, payload: DiscardInput, session: SessionDep, user: ManagerDep):
    return invoke(discard_batch, session, batch_id, payload.request_key, user.id)

@router.patch("/inventory/{branch_id}/{ingredient_id}")
def set_reorder(branch_id: int, ingredient_id: int, payload: ReorderInput, session: SessionDep, user: ManagerDep):
    stock = session.scalar(select(BranchStock).where(BranchStock.branch_id == branch_id, BranchStock.ingredient_id == ingredient_id).with_for_update())
    if stock is None:
        raise HTTPException(404, "Stock row not found; receive stock first")
    stock.reorder_level = payload.reorder_level
    commit(session)
    return {"branch_id": branch_id, "ingredient_id": ingredient_id, "reorder_level": float(stock.reorder_level)}

@router.post("/orders", status_code=201)
def create_order(payload: OrderInput, session: SessionDep, user: StaffDep):
    branch_access(user, payload.branch_id)
    return invoke(checkout, session, payload.model_dump())

@router.get("/orders")
def orders(session: SessionDep, user: UserDep, branch_id: int | None = Query(default=None, gt=0), customer_id: int | None = Query(default=None, gt=0)):
    query = select(Order).order_by(Order.created_at.desc(), Order.id.desc())
    if user.role == "customer":
        if user.customer_id is None or customer_id not in (None, user.customer_id):
            raise HTTPException(403, "You can only access your own orders")
        query = query.where(Order.customer_id == user.customer_id)
    if user.role == "cashier":
        if user.branch_id is None:
            raise HTTPException(403, "Cashier has no assigned branch")
        branch_access(user, branch_id if branch_id is not None else user.branch_id)
        query = query.where(Order.branch_id == user.branch_id)
    if branch_id is not None:
        query = query.where(Order.branch_id == branch_id)
    if customer_id is not None:
        query = query.where(Order.customer_id == customer_id)
    return [order_dict(session, order) for order in session.scalars(query)]

@router.get("/orders/{order_id}")
def get_order(order_id: int, session: SessionDep, user: UserDep):
    order = session.get(Order, order_id)
    if order is None:
        raise HTTPException(404, "Order not found")
    order_access(user, order)
    return order_dict(session, order)

@router.get("/loyalty/{customer_id}")
def loyalty(customer_id: int, session: SessionDep, user: UserDep):
    if user.role == "customer" and user.customer_id != customer_id:
        raise HTTPException(403, "You can only access your own loyalty history")
    return invoke(loyalty_summary, session, customer_id)

@router.get("/analytics/sales")
def sales(session: SessionDep, user: ManagerDep, start: date, end: date):
    return invoke(sales_analytics, session, datetime.combine(start, time.min), datetime.combine(end, time.min))

@router.get("/analytics/low-stock")
def low_stock(session: SessionDep, user: ManagerDep, branch_id: int = Query(gt=0)):
    return invoke(list_inventory, session, branch_id, low_only=True)

@router.get("/analytics/waste")
def waste(session: SessionDep, user: ManagerDep, branch_id: int = Query(gt=0),
          as_of: date | None = None, horizon_days: int = Query(default=7, ge=1, le=90)):
    return invoke(waste_analytics, session, branch_id, as_of, horizon_days)
