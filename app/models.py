"""Normalized operational schema. MariaDB tables explicitly use InnoDB."""
from datetime import date, datetime, timezone
from decimal import Decimal
from sqlalchemy import Boolean, CheckConstraint, Date, DateTime, ForeignKey, Integer, Numeric, String, Index
from sqlalchemy.orm import Mapped, mapped_column, relationship
from app.db import Base

def utcnow():
    return datetime.now(timezone.utc).replace(tzinfo=None)

class Branch(Base):
    __tablename__ = "branches"
    __table_args__ = {"mysql_engine": "InnoDB"}
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(150))
    address: Mapped[str] = mapped_column(String(300))
    postal_code: Mapped[str] = mapped_column(String(6))

class Customer(Base):
    __tablename__ = "customers"
    __table_args__ = {"mysql_engine": "InnoDB"}
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(150))
    email: Mapped[str] = mapped_column(String(254), unique=True)
    orders: Mapped[list["Order"]] = relationship(back_populates="customer")

class User(Base):
    __tablename__ = "users"
    __table_args__ = (CheckConstraint("role IN ('manager','cashier','customer')", name="ck_user_role"), {"mysql_engine": "InnoDB"})
    id: Mapped[int] = mapped_column(primary_key=True)
    email: Mapped[str] = mapped_column(String(254), unique=True)
    name: Mapped[str] = mapped_column(String(150))
    password_hash: Mapped[str] = mapped_column(String(255))
    role: Mapped[str] = mapped_column(String(20))
    customer_id: Mapped[int | None] = mapped_column(ForeignKey("customers.id"))
    branch_id: Mapped[int | None] = mapped_column(ForeignKey("branches.id"))
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)

class MenuItem(Base):
    __tablename__ = "menu_items"
    __table_args__ = (CheckConstraint("price >= 0", name="ck_menu_price"), {"mysql_engine": "InnoDB"})
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(150))
    category: Mapped[str] = mapped_column(String(80))
    price: Mapped[Decimal] = mapped_column(Numeric(12, 2))
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)

class Ingredient(Base):
    __tablename__ = "ingredients"
    __table_args__ = {"mysql_engine": "InnoDB"}
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(150), unique=True)
    unit: Mapped[str] = mapped_column(String(20))

class RecipeComponent(Base):
    __tablename__ = "recipe_components"
    __table_args__ = (CheckConstraint("quantity > 0", name="ck_recipe_quantity"), {"mysql_engine": "InnoDB"})
    menu_item_id: Mapped[int] = mapped_column(ForeignKey("menu_items.id"), primary_key=True)
    ingredient_id: Mapped[int] = mapped_column(ForeignKey("ingredients.id"), primary_key=True)
    quantity: Mapped[Decimal] = mapped_column(Numeric(14, 4))

class BranchStock(Base):
    __tablename__ = "branch_stock"
    __table_args__ = (CheckConstraint("quantity >= 0", name="ck_stock_quantity"), CheckConstraint("reorder_level >= 0", name="ck_stock_reorder"), {"mysql_engine": "InnoDB"})
    branch_id: Mapped[int] = mapped_column(ForeignKey("branches.id"), primary_key=True)
    ingredient_id: Mapped[int] = mapped_column(ForeignKey("ingredients.id"), primary_key=True)
    quantity: Mapped[Decimal] = mapped_column(Numeric(14, 4), default=0)
    reorder_level: Mapped[Decimal] = mapped_column(Numeric(14, 4), default=0)

class Order(Base):
    __tablename__ = "orders"
    __table_args__ = (CheckConstraint("total >= 0", name="ck_order_total"), CheckConstraint("points_redeemed >= 0 AND points_redeemed % 100 = 0", name="ck_order_redemption"), CheckConstraint("status = 'completed'", name="ck_order_status"), Index("ix_orders_branch_date", "branch_id", "created_at"), {"mysql_engine": "InnoDB"})
    id: Mapped[int] = mapped_column(primary_key=True)
    branch_id: Mapped[int] = mapped_column(ForeignKey("branches.id"))
    customer_id: Mapped[int] = mapped_column(ForeignKey("customers.id"), index=True)
    status: Mapped[str] = mapped_column(String(20), default="completed")
    total: Mapped[Decimal] = mapped_column(Numeric(12, 2))
    points_redeemed: Mapped[int] = mapped_column(Integer, default=0)
    request_key: Mapped[str] = mapped_column(String(100), unique=True)
    request_payload_hash: Mapped[str] = mapped_column(String(64), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    lines: Mapped[list["OrderLine"]] = relationship(back_populates="order", cascade="all, delete-orphan")
    customer: Mapped["Customer"] = relationship(back_populates="orders")

class OrderLine(Base):
    __tablename__ = "order_lines"
    __table_args__ = (CheckConstraint("quantity > 0", name="ck_line_quantity"), CheckConstraint("unit_price >= 0", name="ck_line_price"), {"mysql_engine": "InnoDB"})
    id: Mapped[int] = mapped_column(primary_key=True)
    order_id: Mapped[int] = mapped_column(ForeignKey("orders.id"), index=True)
    menu_item_id: Mapped[int] = mapped_column(ForeignKey("menu_items.id"))
    quantity: Mapped[int] = mapped_column(Integer)
    unit_price: Mapped[Decimal] = mapped_column(Numeric(12, 2))
    notes: Mapped[str] = mapped_column(String(500), default="")
    order: Mapped["Order"] = relationship(back_populates="lines")

class StockMovement(Base):
    __tablename__ = "stock_movements"
    __table_args__ = (CheckConstraint("quantity_delta <> 0", name="ck_movement_nonzero"), Index("ix_movements_branch_date", "branch_id", "created_at"), {"mysql_engine": "InnoDB"})
    id: Mapped[int] = mapped_column(primary_key=True)
    branch_id: Mapped[int] = mapped_column(ForeignKey("branches.id"))
    ingredient_id: Mapped[int] = mapped_column(ForeignKey("ingredients.id"))
    quantity_delta: Mapped[Decimal] = mapped_column(Numeric(14, 4))
    reason: Mapped[str] = mapped_column(String(40))
    order_id: Mapped[int | None] = mapped_column(ForeignKey("orders.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)

class StockReceipt(Base):
    __tablename__ = "stock_receipts"
    __table_args__ = (CheckConstraint("quantity > 0", name="ck_receipt_quantity"), {"mysql_engine": "InnoDB"})
    id: Mapped[int] = mapped_column(primary_key=True)
    request_key: Mapped[str] = mapped_column(String(100), unique=True)
    branch_id: Mapped[int] = mapped_column(ForeignKey("branches.id"))
    ingredient_id: Mapped[int] = mapped_column(ForeignKey("ingredients.id"))
    quantity: Mapped[Decimal] = mapped_column(Numeric(14, 4))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)

class LoyaltyTransaction(Base):
    __tablename__ = "loyalty_transactions"
    __table_args__ = (CheckConstraint("points_delta <> 0", name="ck_points_nonzero"), Index("ix_loyalty_customer_date", "customer_id", "created_at"), {"mysql_engine": "InnoDB"})
    id: Mapped[int] = mapped_column(primary_key=True)
    customer_id: Mapped[int] = mapped_column(ForeignKey("customers.id"))
    order_id: Mapped[int | None] = mapped_column(ForeignKey("orders.id"))
    points_delta: Mapped[int] = mapped_column(Integer)
    event_type: Mapped[str] = mapped_column(String(40))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)

class StockBatch(Base):
    """Expiry is unknown for legacy inventory; no historical dates are invented."""
    __tablename__ = "stock_batches"
    __table_args__ = (CheckConstraint("initial_quantity > 0", name="ck_batch_initial"),
                     CheckConstraint("remaining_quantity >= 0 AND remaining_quantity <= initial_quantity", name="ck_batch_remaining"),
                     CheckConstraint("unit_cost IS NULL OR unit_cost >= 0", name="ck_batch_cost"),
                     Index("ix_batches_branch_ingredient_expiry", "branch_id", "ingredient_id", "expires_on"), {"mysql_engine": "InnoDB"})
    id: Mapped[int] = mapped_column(primary_key=True)
    branch_id: Mapped[int] = mapped_column(ForeignKey("branches.id"))
    ingredient_id: Mapped[int] = mapped_column(ForeignKey("ingredients.id"))
    receipt_id: Mapped[int | None] = mapped_column(ForeignKey("stock_receipts.id"), unique=True)
    initial_quantity: Mapped[Decimal] = mapped_column(Numeric(14, 4))
    remaining_quantity: Mapped[Decimal] = mapped_column(Numeric(14, 4))
    expires_on: Mapped[date | None] = mapped_column(Date)
    unit_cost: Mapped[Decimal | None] = mapped_column(Numeric(14, 4))
    source: Mapped[str] = mapped_column(String(40), default="receipt")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)

class StockBatchAllocation(Base):
    __tablename__ = "stock_batch_allocations"
    __table_args__ = (CheckConstraint("quantity > 0", name="ck_allocation_quantity"), {"mysql_engine": "InnoDB"})
    id: Mapped[int] = mapped_column(primary_key=True)
    batch_id: Mapped[int] = mapped_column(ForeignKey("stock_batches.id"), index=True)
    order_id: Mapped[int] = mapped_column(ForeignKey("orders.id"), index=True)
    quantity: Mapped[Decimal] = mapped_column(Numeric(14, 4))

class StockBatchDiscard(Base):
    __tablename__ = "stock_batch_discards"
    __table_args__ = (CheckConstraint("quantity > 0", name="ck_discard_quantity"), {"mysql_engine": "InnoDB"})
    id: Mapped[int] = mapped_column(primary_key=True)
    batch_id: Mapped[int] = mapped_column(ForeignKey("stock_batches.id"), unique=True)
    request_key: Mapped[str] = mapped_column(String(100), unique=True)
    quantity: Mapped[Decimal] = mapped_column(Numeric(14, 4))
    actor_user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
    movement_id: Mapped[int] = mapped_column(ForeignKey("stock_movements.id"), unique=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
