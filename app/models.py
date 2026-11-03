"""SQL source of truth. Run `python -m app.cli export-schema` to inspect DDL."""
from datetime import datetime, timezone
from decimal import Decimal
from sqlalchemy import (Boolean, CheckConstraint, DateTime, ForeignKey, Index,
                        Integer, Numeric, String, UniqueConstraint, true, text)
from sqlalchemy.orm import Mapped, mapped_column
from app.database import Base
from app.roles import ROLE_CHECK_SQL


def utcnow():
    # Persist naive UTC consistently in SQL; serialize as UTC at the API boundary.
    return datetime.now(timezone.utc).replace(tzinfo=None)


class Branch(Base):
    __tablename__ = 'branches'
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(120), unique=True)
    address: Mapped[str] = mapped_column(String(255))
    source_label: Mapped[str] = mapped_column(String(120), default='fictional demonstration branch')


class Customer(Base):
    __tablename__ = 'customers'
    __table_args__ = (CheckConstraint('points >= 0', name='ck_customer_points'),)
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(120))
    email: Mapped[str] = mapped_column(String(180), unique=True)
    points: Mapped[int] = mapped_column(Integer, default=0)
    active: Mapped[bool] = mapped_column(Boolean, default=True)


class User(Base):
    __tablename__ = 'users'
    __table_args__ = (CheckConstraint(ROLE_CHECK_SQL, name='ck_user_role'),
                      CheckConstraint('active IN (0,1)', name='ck_user_active'),
                      CheckConstraint('session_version >= 0', name='ck_user_session_version'))
    id: Mapped[int] = mapped_column(primary_key=True)
    email: Mapped[str] = mapped_column(String(180), unique=True)
    password_hash: Mapped[str] = mapped_column(String(255))
    role: Mapped[str] = mapped_column(String(20))
    customer_id: Mapped[int | None] = mapped_column(ForeignKey('customers.id'), unique=True)
    active: Mapped[bool] = mapped_column(Boolean, default=True, server_default=true())
    session_version: Mapped[int] = mapped_column(Integer, default=0, server_default=text('0'))


class MenuItem(Base):
    __tablename__ = 'menu_items'
    __table_args__ = (CheckConstraint('price > 0', name='ck_menu_price'),)
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(120), unique=True)
    price: Mapped[Decimal] = mapped_column(Numeric(10, 2))
    active: Mapped[bool] = mapped_column(Boolean, default=True)


class Ingredient(Base):
    __tablename__ = 'ingredients'
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(100), unique=True)
    unit: Mapped[str] = mapped_column(String(12), default='g')


class RecipeComponent(Base):
    __tablename__ = 'recipe_components'
    __table_args__ = (CheckConstraint('quantity > 0', name='ck_recipe_quantity'),)
    menu_item_id: Mapped[int] = mapped_column(ForeignKey('menu_items.id'), primary_key=True)
    ingredient_id: Mapped[int] = mapped_column(ForeignKey('ingredients.id'), primary_key=True)
    quantity: Mapped[Decimal] = mapped_column(Numeric(14, 3))


class BranchStock(Base):
    __tablename__ = 'branch_stock'
    __table_args__ = (CheckConstraint('quantity >= 0', name='ck_stock_quantity'),)
    branch_id: Mapped[int] = mapped_column(ForeignKey('branches.id'), primary_key=True)
    ingredient_id: Mapped[int] = mapped_column(ForeignKey('ingredients.id'), primary_key=True)
    quantity: Mapped[Decimal] = mapped_column(Numeric(14, 3), default=0)


class Order(Base):
    __tablename__ = 'orders'
    __table_args__ = (
        CheckConstraint('subtotal >= 0 AND discount >= 0 AND total >= 0', name='ck_order_money'),
        CheckConstraint('total = subtotal - discount', name='ck_order_total'),
        Index('ix_orders_branch_created', 'branch_id', 'created_at'),
    )
    id: Mapped[int] = mapped_column(primary_key=True)
    request_key: Mapped[str] = mapped_column(String(80), unique=True)
    request_hash: Mapped[str] = mapped_column(String(64))
    branch_id: Mapped[int] = mapped_column(ForeignKey('branches.id'))
    customer_id: Mapped[int] = mapped_column(ForeignKey('customers.id'))
    cashier_user_id: Mapped[int] = mapped_column(ForeignKey('users.id'))
    subtotal: Mapped[Decimal] = mapped_column(Numeric(12, 2))
    discount: Mapped[Decimal] = mapped_column(Numeric(12, 2))
    total: Mapped[Decimal] = mapped_column(Numeric(12, 2))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class OrderLine(Base):
    __tablename__ = 'order_lines'
    __table_args__ = (
        UniqueConstraint('order_id', 'menu_item_id', name='uq_order_menu'),
        CheckConstraint('quantity > 0 AND unit_price > 0', name='ck_line_values'),
    )
    id: Mapped[int] = mapped_column(primary_key=True)
    order_id: Mapped[int] = mapped_column(ForeignKey('orders.id'))
    menu_item_id: Mapped[int] = mapped_column(ForeignKey('menu_items.id'))
    quantity: Mapped[int] = mapped_column(Integer)
    unit_price: Mapped[Decimal] = mapped_column(Numeric(10, 2))


class StockReceipt(Base):
    __tablename__ = 'stock_receipts'
    __table_args__ = (CheckConstraint('quantity > 0', name='ck_receipt_quantity'),)
    id: Mapped[int] = mapped_column(primary_key=True)
    branch_id: Mapped[int] = mapped_column(ForeignKey('branches.id'))
    ingredient_id: Mapped[int] = mapped_column(ForeignKey('ingredients.id'))
    quantity: Mapped[Decimal] = mapped_column(Numeric(14, 3))
    actor_user_id: Mapped[int] = mapped_column(ForeignKey('users.id'))
    note: Mapped[str] = mapped_column(String(255), default='')
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class StockAdjustment(Base):
    __tablename__ = 'stock_adjustments'
    __table_args__ = (
        CheckConstraint('previous_quantity >= 0 AND quantity >= 0 AND quantity <> previous_quantity',
                        name='ck_adjustment_quantity'),
    )
    id: Mapped[int] = mapped_column(primary_key=True)
    branch_id: Mapped[int] = mapped_column(ForeignKey('branches.id'))
    ingredient_id: Mapped[int] = mapped_column(ForeignKey('ingredients.id'))
    previous_quantity: Mapped[Decimal] = mapped_column(Numeric(14, 3))
    quantity: Mapped[Decimal] = mapped_column(Numeric(14, 3))
    actor_user_id: Mapped[int] = mapped_column(ForeignKey('users.id'))
    reason: Mapped[str] = mapped_column(String(255))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


STOCK_MOVEMENT_ORIGIN_SQL = (
    '(order_id IS NOT NULL AND receipt_id IS NULL AND adjustment_id IS NULL AND delta < 0) OR '
    '(order_id IS NULL AND receipt_id IS NOT NULL AND adjustment_id IS NULL AND delta > 0) OR '
    '(order_id IS NULL AND receipt_id IS NULL AND adjustment_id IS NOT NULL)'
)


class StockMovement(Base):
    __tablename__ = 'stock_movements'
    __table_args__ = (
        CheckConstraint('delta <> 0', name='ck_movement_nonzero'),
        CheckConstraint(STOCK_MOVEMENT_ORIGIN_SQL, name='ck_movement_origin'),
    )
    id: Mapped[int] = mapped_column(primary_key=True)
    branch_id: Mapped[int] = mapped_column(ForeignKey('branches.id'))
    ingredient_id: Mapped[int] = mapped_column(ForeignKey('ingredients.id'))
    delta: Mapped[Decimal] = mapped_column(Numeric(14, 3))
    order_id: Mapped[int | None] = mapped_column(ForeignKey('orders.id'))
    receipt_id: Mapped[int | None] = mapped_column(ForeignKey('stock_receipts.id'))
    adjustment_id: Mapped[int | None] = mapped_column(ForeignKey('stock_adjustments.id'))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class LoyaltyTransaction(Base):
    __tablename__ = 'loyalty_transactions'
    __table_args__ = (
        UniqueConstraint('order_id', 'kind', name='uq_loyalty_order_kind'),
        CheckConstraint("kind IN ('earn','redeem')", name='ck_loyalty_kind'),
        CheckConstraint("(kind = 'earn' AND delta > 0) OR (kind = 'redeem' AND delta < 0)", name='ck_loyalty_sign'),
    )
    id: Mapped[int] = mapped_column(primary_key=True)
    customer_id: Mapped[int] = mapped_column(ForeignKey('customers.id'))
    order_id: Mapped[int] = mapped_column(ForeignKey('orders.id'))
    kind: Mapped[str] = mapped_column(String(12))
    delta: Mapped[int] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


# InnoDB is required for the foreign keys and transactional row locks.
for _table in Base.metadata.tables.values():
    _table.dialect_options['mysql']['engine'] = 'InnoDB'
