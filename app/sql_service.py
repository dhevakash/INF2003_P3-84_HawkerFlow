"""Business transactions. FOR UPDATE is enforced by MariaDB/InnoDB, not SQLite.

All loyalty writes lock Customer first. Checkout then locks menu items and stock
in ascending ID order; this prevents overselling and serializes redemptions.
No MongoDB operation occurs inside these SQL transactions.
"""
import hashlib
import json
from collections import defaultdict
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation, ROUND_FLOOR
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError, OperationalError
from app.models import Branch, BranchStock, Customer, Ingredient, LoyaltyTransaction, MenuItem, Order, OrderLine, RecipeComponent, StockMovement, StockReceipt

class BusinessError(Exception):
    def __init__(self, status_code, detail):
        self.status_code = status_code
        self.detail = detail
        super().__init__(detail)

def iso(value):
    return value.replace(tzinfo=timezone.utc).isoformat() if value else None

def positive_id(value, field):
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise BusinessError(422, f"{field} must be a positive integer")
    return value

def request_key(value):
    if not isinstance(value, str) or not value.strip() or len(value.strip()) > 100:
        raise BusinessError(422, "request_key must contain 1 to 100 characters")
    return value.strip()

def normalize_order(payload):
    data = {"branch_id": positive_id(payload.get("branch_id"), "branch_id"),
            "customer_id": positive_id(payload.get("customer_id"), "customer_id"),
            "request_key": request_key(payload.get("request_key")),
            "redeem_points": payload.get("redeem_points", 0), "lines": []}
    points = data["redeem_points"]
    if isinstance(points, bool) or not isinstance(points, int) or points < 0 or points % 100:
        raise BusinessError(422, "redeem_points must be a nonnegative multiple of 100")
    lines = payload.get("lines")
    if not isinstance(lines, list) or not 1 <= len(lines) <= 100:
        raise BusinessError(422, "An order requires 1 to 100 lines")
    for line in lines:
        if not isinstance(line, dict):
            raise BusinessError(422, "Each line must be an object")
        item_id = positive_id(line.get("menu_item_id"), "menu_item_id")
        quantity = positive_id(line.get("quantity"), "quantity")
        if quantity > 1000:
            raise BusinessError(422, "Line quantity cannot exceed 1000")
        notes = line.get("notes", "")
        if not isinstance(notes, str) or len(notes) > 500:
            raise BusinessError(422, "notes must be text of at most 500 characters")
        data["lines"].append({"menu_item_id": item_id, "quantity": quantity, "notes": notes.strip()})
    return data

def payload_hash(data):
    return hashlib.sha256(json.dumps(data, sort_keys=True, separators=(",", ":")).encode()).hexdigest()

def locked_balance(session, customer_id):
    # Current locking read is essential: a normal SUM can see a stale RR snapshot
    # after waiting for a Customer lock acquired by a concurrent checkout.
    rows = session.scalars(select(LoyaltyTransaction).where(LoyaltyTransaction.customer_id == customer_id).order_by(LoyaltyTransaction.id).with_for_update()).all()
    return sum(row.points_delta for row in rows)

def loyalty_summary(session, customer_id):
    if session.get(Customer, customer_id) is None:
        raise BusinessError(404, "Customer not found")
    rows = session.scalars(select(LoyaltyTransaction).where(LoyaltyTransaction.customer_id == customer_id).order_by(LoyaltyTransaction.created_at.desc(), LoyaltyTransaction.id.desc())).all()
    return {"balance": sum(row.points_delta for row in rows), "transactions": [
        {"id": row.id, "order_id": row.order_id, "points_delta": row.points_delta,
         "event_type": row.event_type, "created_at": iso(row.created_at)} for row in rows]}

def order_dict(session, order):
    earned = session.scalar(select(func.coalesce(func.sum(LoyaltyTransaction.points_delta), 0)).where(LoyaltyTransaction.order_id == order.id, LoyaltyTransaction.event_type == "earned"))
    balance = session.scalar(select(func.coalesce(func.sum(LoyaltyTransaction.points_delta), 0)).where(LoyaltyTransaction.customer_id == order.customer_id))
    return {"id": order.id, "branch_id": order.branch_id, "customer_id": order.customer_id,
            "status": order.status, "total": float(order.total), "points_redeemed": order.points_redeemed,
            "request_key": order.request_key, "created_at": iso(order.created_at),
            "points_earned": int(earned), "loyalty_balance": int(balance),
            "lines": [{"id": line.id, "menu_item_id": line.menu_item_id,
                       "quantity": line.quantity, "unit_price": float(line.unit_price),
                       "notes": line.notes} for line in sorted(order.lines, key=lambda x: x.id)]}

def duplicate_order(session, existing, digest):
    if existing.request_payload_hash != digest:
        raise BusinessError(409, "request_key was already used for a different order")
    result = order_dict(session, existing)
    result["idempotent_replay"] = True
    return result

def checkout(session, payload):
    data = normalize_order(payload)
    digest = payload_hash(data)
    try:
        existing = session.scalar(select(Order).where(Order.request_key == data["request_key"]))
        if existing:
            return duplicate_order(session, existing, digest)
        customer = session.scalar(select(Customer).where(Customer.id == data["customer_id"]).with_for_update())
        if customer is None:
            raise BusinessError(404, "Customer not found")
        if session.get(Branch, data["branch_id"]) is None:
            raise BusinessError(404, "Branch not found")
        # Recheck using a current read after the customer lock; another request
        # may have committed this key while we waited.
        existing = session.scalar(select(Order).where(Order.request_key == data["request_key"]).with_for_update())
        if existing:
            result = duplicate_order(session, existing, digest)
            result["loyalty_balance"] = locked_balance(session, customer.id)
            session.commit()
            return result
        balance = locked_balance(session, customer.id)
        points = data["redeem_points"]
        if points > balance:
            raise BusinessError(409, "Not enough loyalty points")
        requirements = defaultdict(Decimal)
        prices = {}
        for item_id in sorted({line["menu_item_id"] for line in data["lines"]}):
            item = session.scalar(select(MenuItem).where(MenuItem.id == item_id).with_for_update())
            if item is None or not item.is_active:
                raise BusinessError(409, f"Menu item {item_id} is unavailable")
            prices[item_id] = item.price
            recipe = session.scalars(select(RecipeComponent).where(RecipeComponent.menu_item_id == item_id).order_by(RecipeComponent.ingredient_id).with_for_update()).all()
            if not recipe:
                raise BusinessError(409, f"Menu item {item_id} has no configured recipe")
            item_qty = sum(line["quantity"] for line in data["lines"] if line["menu_item_id"] == item_id)
            for component in recipe:
                requirements[component.ingredient_id] += component.quantity * item_qty
        subtotal = sum((prices[line["menu_item_id"]] * line["quantity"] for line in data["lines"]), Decimal(0))
        discount = Decimal(points) / Decimal(100)
        if discount > subtotal:
            raise BusinessError(409, "Points discount cannot exceed the bill")
        total = (subtotal - discount).quantize(Decimal("0.01"))
        if total > Decimal("9999999999.99"):
            raise BusinessError(422, "Order amount exceeds the supported limit")
        stock_rows = {}
        for ingredient_id in sorted(requirements):
            stock = session.scalar(select(BranchStock).where(BranchStock.branch_id == data["branch_id"], BranchStock.ingredient_id == ingredient_id).with_for_update())
            if stock is None or stock.quantity < requirements[ingredient_id]:
                ingredient = session.get(Ingredient, ingredient_id)
                name = ingredient.name if ingredient else str(ingredient_id)
                raise BusinessError(409, f"Insufficient stock: {name}")
            stock_rows[ingredient_id] = stock
        order = Order(branch_id=data["branch_id"], customer_id=customer.id, status="completed", total=total,
                      points_redeemed=points, request_key=data["request_key"], request_payload_hash=digest)
        session.add(order)
        session.flush()
        for line in data["lines"]:
            session.add(OrderLine(order_id=order.id, menu_item_id=line["menu_item_id"], quantity=line["quantity"],
                                  unit_price=prices[line["menu_item_id"]], notes=line["notes"]))
        for ingredient_id, stock in stock_rows.items():
            needed = requirements[ingredient_id]
            stock.quantity -= needed
            session.add(StockMovement(branch_id=order.branch_id, ingredient_id=ingredient_id,
                                      quantity_delta=-needed, reason="sale", order_id=order.id))
        if points:
            session.add(LoyaltyTransaction(customer_id=customer.id, order_id=order.id, points_delta=-points, event_type="redeemed"))
        earned = int(total.to_integral_value(rounding=ROUND_FLOOR))
        if earned:
            session.add(LoyaltyTransaction(customer_id=customer.id, order_id=order.id, points_delta=earned, event_type="earned"))
        session.flush()
        # Capture the result under the lock, before releasing the transaction.
        result = order_dict(session, order)
        result["loyalty_balance"] = balance - points + earned
        result["idempotent_replay"] = False
        session.commit()
        return result
    except BusinessError:
        session.rollback()
        raise
    except IntegrityError:
        session.rollback()
        existing = session.scalar(select(Order).where(Order.request_key == data["request_key"]))
        if existing:
            return duplicate_order(session, existing, digest)
        raise BusinessError(409, "Order conflicts with database constraints")
    except OperationalError as error:
        session.rollback()
        code = error.orig.args[0] if getattr(error.orig, "args", ()) else None
        if code in (1205, 1213):
            raise BusinessError(409, "Checkout could not acquire database locks; retry with the same request_key") from error
        raise BusinessError(503, "The SQL store is unavailable") from error

def receive_stock(session, payload):
    branch_id = positive_id(payload.get("branch_id"), "branch_id")
    ingredient_id = positive_id(payload.get("ingredient_id"), "ingredient_id")
    key = request_key(payload.get("request_key"))
    try:
        quantity = Decimal(str(payload.get("quantity")))
    except (InvalidOperation, ValueError):
        raise BusinessError(422, "quantity must be a positive decimal")
    if not quantity.is_finite() or quantity <= 0 or quantity > Decimal("9999999999.9999") or quantity != quantity.quantize(Decimal("0.0001")):
        raise BusinessError(422, "quantity must be positive, with at most four decimal places")
    try:
        # Branch lock serializes creating missing stock rows during receipts.
        branch = session.scalar(select(Branch).where(Branch.id == branch_id).with_for_update())
        if branch is None or session.get(Ingredient, ingredient_id) is None:
            raise BusinessError(404, "Branch or ingredient not found")
        previous = session.scalar(select(StockReceipt).where(StockReceipt.request_key == key).with_for_update())
        if previous:
            if (previous.branch_id, previous.ingredient_id, previous.quantity) != (branch_id, ingredient_id, quantity):
                raise BusinessError(409, "request_key was already used for a different receipt")
            stock = session.scalar(select(BranchStock).where(BranchStock.branch_id == branch_id, BranchStock.ingredient_id == ingredient_id).with_for_update())
            result = {"id": previous.id, "branch_id": branch_id, "ingredient_id": ingredient_id, "quantity": float(stock.quantity), "received": float(quantity), "idempotent_replay": True}
            session.commit()
            return result
        stock = session.scalar(select(BranchStock).where(BranchStock.branch_id == branch_id, BranchStock.ingredient_id == ingredient_id).with_for_update())
        if stock is None:
            stock = BranchStock(branch_id=branch_id, ingredient_id=ingredient_id, quantity=0, reorder_level=0)
            session.add(stock)
        if stock.quantity + quantity > Decimal("9999999999.9999"):
            raise BusinessError(422, "Stock quantity exceeds the supported limit")
        stock.quantity += quantity
        receipt = StockReceipt(request_key=key, branch_id=branch_id, ingredient_id=ingredient_id, quantity=quantity)
        session.add(receipt)
        session.add(StockMovement(branch_id=branch_id, ingredient_id=ingredient_id, quantity_delta=quantity, reason="receipt"))
        session.flush()
        result = {"id": receipt.id, "branch_id": branch_id, "ingredient_id": ingredient_id, "quantity": float(stock.quantity), "received": float(quantity), "idempotent_replay": False}
        session.commit()
        return result
    except BusinessError:
        session.rollback()
        raise
    except IntegrityError:
        session.rollback()
        previous = session.scalar(select(StockReceipt).where(StockReceipt.request_key == key))
        if previous:
            return receive_stock(session, payload)
        raise BusinessError(409, "Receipt conflicts with database constraints")
    except OperationalError as error:
        session.rollback()
        code = error.orig.args[0] if getattr(error.orig, "args", ()) else None
        if code in (1205, 1213):
            raise BusinessError(409, "Restock lock conflict; retry with the same request_key") from error
        raise BusinessError(503, "The SQL store is unavailable") from error

def list_inventory(session, branch_id, low_only=False):
    if session.get(Branch, branch_id) is None:
        raise BusinessError(404, "Branch not found")
    query = select(BranchStock, Ingredient).join(Ingredient, Ingredient.id == BranchStock.ingredient_id).where(BranchStock.branch_id == branch_id)
    if low_only:
        query = query.where(BranchStock.quantity <= BranchStock.reorder_level)
    return [{"branch_id": branch_id, "ingredient_id": ingredient.id, "name": ingredient.name, "unit": ingredient.unit,
             "quantity": float(stock.quantity), "reorder_level": float(stock.reorder_level)}
            for stock, ingredient in session.execute(query.order_by(Ingredient.name))]

def sales_analytics(session, start, end):
    if start >= end:
        raise BusinessError(422, "end must be after start (end is exclusive)")
    filters = (Order.status == "completed", Order.created_at >= start, Order.created_at < end)
    branches = session.execute(select(Branch.id, Branch.name, func.count(Order.id), func.sum(Order.total)).join(Order, Order.branch_id == Branch.id).where(*filters).group_by(Branch.id, Branch.name).order_by(func.sum(Order.total).desc())).all()
    # Lines represent gross sales; completed Order totals represent net revenue
    # after points discounts. Never join lines into branch revenue aggregation.
    menu = session.execute(select(MenuItem.id, MenuItem.name, func.sum(OrderLine.quantity), func.sum(OrderLine.quantity * OrderLine.unit_price)).join(OrderLine, OrderLine.menu_item_id == MenuItem.id).join(Order, Order.id == OrderLine.order_id).where(*filters).group_by(MenuItem.id, MenuItem.name).order_by(func.sum(OrderLine.quantity * OrderLine.unit_price).desc())).all()
    return {"start": start.isoformat(), "end": end.isoformat(), "branches": [
        {"branch_id": row[0], "name": row[1], "orders": row[2], "revenue": float(row[3])} for row in branches],
        "menu": [{"menu_item_id": row[0], "name": row[1], "quantity": int(row[2]), "gross_sales": float(row[3])} for row in menu]}
