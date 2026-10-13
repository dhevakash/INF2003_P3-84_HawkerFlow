"""Business transactions. FOR UPDATE is enforced by MariaDB/InnoDB, not SQLite.

All loyalty writes lock Customer first. Checkout then locks menu items and stock
in ascending ID order; this prevents overselling and serializes redemptions.
No MongoDB operation occurs inside these SQL transactions.
"""
import hashlib
import json
from collections import defaultdict
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation, ROUND_FLOOR
from sqlalchemy import case, func, select
from sqlalchemy.exc import IntegrityError, OperationalError
from app.models import Branch, BranchStock, Customer, Ingredient, LoyaltyTransaction, MenuItem, Order, OrderLine, RecipeComponent, StockMovement, StockReceipt, StockBatch, StockBatchAllocation, StockBatchDiscard

def business_today():
    # Singapore has a fixed UTC+08 offset, so no OS timezone database is needed.
    return datetime.now(timezone(timedelta(hours=8))).date()

def ensure_stock_batches(session, stock):
    """Caller holds the aggregate stock lock. Reconcile legacy quantity once.

    Unknown expiry remains explicit and sellable; dated expired batches never
    become legacy stock. Any aggregate/batch corruption fails closed.
    """
    batches = session.scalars(select(StockBatch).where(
        StockBatch.branch_id == stock.branch_id, StockBatch.ingredient_id == stock.ingredient_id
    ).order_by(StockBatch.id).with_for_update()).all()
    tracked = sum((b.remaining_quantity for b in batches), Decimal(0))
    if tracked > stock.quantity:
        raise BusinessError(409, "Inventory batch totals exceed aggregate stock; reconcile inventory")
    missing = stock.quantity - tracked
    if missing:
        batch = StockBatch(branch_id=stock.branch_id, ingredient_id=stock.ingredient_id,
                           initial_quantity=missing, remaining_quantity=missing, source="legacy_unknown")
        session.add(batch)
        session.flush()
        batches.append(batch)
    return sorted(batches, key=lambda b: (b.expires_on is None, b.expires_on or date.max, b.id))

def backfill_stock_batches(session):
    for stock in session.scalars(select(BranchStock).order_by(BranchStock.branch_id, BranchStock.ingredient_id).with_for_update()):
        ensure_stock_batches(session, stock)
    session.commit()

def sellable_stock_quantities(session, branch_id, as_of=None):
    """Read only; safely accounts for legacy untracked quantity and expired lots."""
    as_of = as_of or business_today()
    totals = defaultdict(Decimal)
    expired = defaultdict(Decimal)
    for batch in session.scalars(select(StockBatch).where(StockBatch.branch_id == branch_id)):
        totals[batch.ingredient_id] += batch.remaining_quantity
        if batch.expires_on is not None and batch.expires_on < as_of:
            expired[batch.ingredient_id] += batch.remaining_quantity
    return {stock.ingredient_id: max(Decimal(0), stock.quantity - expired[stock.ingredient_id])
            if totals[stock.ingredient_id] <= stock.quantity else Decimal(0)
            for stock in session.scalars(select(BranchStock).where(BranchStock.branch_id == branch_id))}

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
        batch_rows = {}
        today = business_today()
        for ingredient_id in sorted(requirements):
            stock = session.scalar(select(BranchStock).where(BranchStock.branch_id == data["branch_id"], BranchStock.ingredient_id == ingredient_id).with_for_update())
            if stock is None or stock.quantity < requirements[ingredient_id]:
                ingredient = session.get(Ingredient, ingredient_id)
                name = ingredient.name if ingredient else str(ingredient_id)
                raise BusinessError(409, f"Insufficient stock: {name}")
            stock_rows[ingredient_id] = stock
            batches = ensure_stock_batches(session, stock)
            sellable = [b for b in batches if b.expires_on is None or b.expires_on >= today]
            if sum((b.remaining_quantity for b in sellable), Decimal(0)) < requirements[ingredient_id]:
                ingredient = session.get(Ingredient, ingredient_id)
                raise BusinessError(409, f"Insufficient stock: {ingredient.name}; expired batches cannot be sold")
            batch_rows[ingredient_id] = sellable
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
            remaining = needed
            for batch in batch_rows[ingredient_id]:
                consumed = min(batch.remaining_quantity, remaining)
                if consumed:
                    batch.remaining_quantity -= consumed
                    session.add(StockBatchAllocation(batch_id=batch.id, order_id=order.id, quantity=consumed))
                    remaining -= consumed
                if not remaining:
                    break
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
    expires_on = payload.get("expires_on")
    if isinstance(expires_on, str):
        try:
            expires_on = date.fromisoformat(expires_on)
        except ValueError:
            raise BusinessError(422, "expires_on must be a YYYY-MM-DD date")
    if expires_on is not None and (not isinstance(expires_on, date) or isinstance(expires_on, datetime)):
        raise BusinessError(422, "expires_on must be a date")
    unit_cost = payload.get("unit_cost")
    if unit_cost is not None:
        try:
            unit_cost = Decimal(str(unit_cost))
        except (InvalidOperation, ValueError):
            raise BusinessError(422, "unit_cost must be a nonnegative decimal per ingredient unit")
        if not unit_cost.is_finite() or unit_cost < 0 or unit_cost > Decimal("9999999999.9999") or unit_cost != unit_cost.quantize(Decimal("0.0001")):
            raise BusinessError(422, "unit_cost must be nonnegative with at most four decimal places")
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
            previous_batch = session.scalar(select(StockBatch).where(StockBatch.receipt_id == previous.id).with_for_update())
            metadata = (previous_batch.expires_on, previous_batch.unit_cost) if previous_batch else (None, None)
            if (previous.branch_id, previous.ingredient_id, previous.quantity, *metadata) != (branch_id, ingredient_id, quantity, expires_on, unit_cost):
                raise BusinessError(409, "request_key was already used for a different receipt")
            stock = session.scalar(select(BranchStock).where(BranchStock.branch_id == branch_id, BranchStock.ingredient_id == ingredient_id).with_for_update())
            result = {"id": previous.id, "batch_id": previous_batch.id if previous_batch else None, "branch_id": branch_id, "ingredient_id": ingredient_id, "quantity": float(stock.quantity), "received": float(quantity), "idempotent_replay": True}
            session.commit()
            return result
        stock = session.scalar(select(BranchStock).where(BranchStock.branch_id == branch_id, BranchStock.ingredient_id == ingredient_id).with_for_update())
        if stock is None:
            stock = BranchStock(branch_id=branch_id, ingredient_id=ingredient_id, quantity=0, reorder_level=0)
            session.add(stock)
            session.flush()
        ensure_stock_batches(session, stock)
        if stock.quantity + quantity > Decimal("9999999999.9999"):
            raise BusinessError(422, "Stock quantity exceeds the supported limit")
        stock.quantity += quantity
        receipt = StockReceipt(request_key=key, branch_id=branch_id, ingredient_id=ingredient_id, quantity=quantity)
        session.add(receipt)
        session.flush()
        batch = StockBatch(branch_id=branch_id, ingredient_id=ingredient_id, receipt_id=receipt.id,
                           initial_quantity=quantity, remaining_quantity=quantity, expires_on=expires_on, unit_cost=unit_cost)
        session.add(batch)
        session.add(StockMovement(branch_id=branch_id, ingredient_id=ingredient_id, quantity_delta=quantity, reason="receipt"))
        session.flush()
        result = {"id": receipt.id, "batch_id": batch.id, "branch_id": branch_id, "ingredient_id": ingredient_id, "quantity": float(stock.quantity), "received": float(quantity), "idempotent_replay": False}
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
    sellable = sellable_stock_quantities(session, branch_id)
    expired = dict(session.execute(select(StockBatch.ingredient_id, func.sum(StockBatch.remaining_quantity))
        .where(StockBatch.branch_id == branch_id, StockBatch.expires_on < business_today())
        .group_by(StockBatch.ingredient_id)).all())
    return [{"branch_id": branch_id, "ingredient_id": ingredient.id, "name": ingredient.name, "unit": ingredient.unit,
             "quantity": float(stock.quantity), "sellable_quantity": float(sellable.get(ingredient.id, 0)),
             "expired_quantity": float(expired.get(ingredient.id, 0)),
             "reorder_level": float(stock.reorder_level)}
            for stock, ingredient in session.execute(query.order_by(Ingredient.name))
            if not low_only or sellable.get(ingredient.id, 0) <= stock.reorder_level]

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

def menu_availability(session, branch_id, as_of=None):
    if session.get(Branch, branch_id) is None:
        raise BusinessError(404, "Branch not found")
    available = sellable_stock_quantities(session, branch_id, as_of)
    recipes = defaultdict(list)
    for component, ingredient in session.execute(select(RecipeComponent, Ingredient).join(
            Ingredient, Ingredient.id == RecipeComponent.ingredient_id).order_by(RecipeComponent.ingredient_id)):
        quantity = available.get(ingredient.id, Decimal(0))
        recipes[component.menu_item_id].append({"ingredient_id": ingredient.id, "name": ingredient.name,
            "unit": ingredient.unit, "available_quantity": float(quantity), "required_per_portion": float(component.quantity),
            "portions": int(quantity // component.quantity)})
    result = []
    for item in session.scalars(select(MenuItem).order_by(MenuItem.id)):
        ingredients = recipes[item.id]
        portions = min((i["portions"] for i in ingredients), default=0) if item.is_active else 0
        result.append({"menu_item_id": item.id, "name": item.name, "available_portions": portions,
                       "sellable": bool(item.is_active and ingredients and portions > 0),
                       "limiting_ingredients": [i for i in ingredients if i["portions"] == portions],
                       "recipe_ingredients": ingredients,
                       "reason": "inactive" if not item.is_active else "recipe_missing" if not ingredients else
                                 "insufficient_sellable_stock" if not portions else "available"})
    return result

def list_batches(session, branch_id, as_of=None, horizon_days=7):
    if session.get(Branch, branch_id) is None:
        raise BusinessError(404, "Branch not found")
    as_of = as_of or business_today()
    result = []
    tracked = defaultdict(Decimal)
    rows = session.execute(select(StockBatch, Ingredient).join(Ingredient, Ingredient.id == StockBatch.ingredient_id)
                           .where(StockBatch.branch_id == branch_id, StockBatch.remaining_quantity > 0)
                           .order_by(case((StockBatch.expires_on.is_(None), 1), else_=0), StockBatch.expires_on, StockBatch.id))
    for batch, ingredient in rows:
        tracked[ingredient.id] += batch.remaining_quantity
        days = (batch.expires_on - as_of).days if batch.expires_on else None
        status = "unknown" if days is None else "expired" if days < 0 else "expiring" if days <= horizon_days else "fresh"
        result.append({"id": batch.id, "branch_id": branch_id, "ingredient_id": ingredient.id,
                       "ingredient_name": ingredient.name, "unit": ingredient.unit,
                       "initial_quantity": float(batch.initial_quantity), "remaining_quantity": float(batch.remaining_quantity),
                       "expires_on": batch.expires_on.isoformat() if batch.expires_on else None,
                       "days_to_expiry": days, "unit_cost": float(batch.unit_cost) if batch.unit_cost is not None else None,
                       "value_at_risk": float(batch.remaining_quantity * batch.unit_cost) if batch.unit_cost is not None and status in ("expiring", "expired") else None,
                       "status": status, "source": batch.source})
    # Fixtures and installations started before batches existed retain explicit
    # unknown expiry without mutating stock from a reporting GET request.
    for stock, ingredient in session.execute(select(BranchStock, Ingredient).join(Ingredient, Ingredient.id == BranchStock.ingredient_id)
                                             .where(BranchStock.branch_id == branch_id).order_by(Ingredient.id)):
        remainder = stock.quantity - tracked[ingredient.id]
        if remainder > 0:
            result.append({"id": None, "branch_id": branch_id, "ingredient_id": ingredient.id,
                           "ingredient_name": ingredient.name, "unit": ingredient.unit,
                           "initial_quantity": float(remainder), "remaining_quantity": float(remainder),
                           "expires_on": None, "days_to_expiry": None, "unit_cost": None, "value_at_risk": None,
                           "status": "unknown", "source": "legacy_unknown"})
    return result

def waste_analytics(session, branch_id, as_of=None, horizon_days=7):
    as_of = as_of or business_today()
    if not 1 <= horizon_days <= 90:
        raise BusinessError(422, "horizon_days must be between 1 and 90")
    batches = list_batches(session, branch_id, as_of, horizon_days)
    risks = defaultdict(list)
    for batch in batches:
        if batch["status"] == "expiring":
            risks[batch["ingredient_id"]].append(batch)
    # SQL aggregate counts completed dish sales once; no ingredient fanout.
    start = datetime.combine(as_of - timedelta(days=27), datetime.min.time()) - timedelta(hours=8)
    end = datetime.combine(as_of + timedelta(days=1), datetime.min.time()) - timedelta(hours=8)
    sales = {item_id: int(quantity) for item_id, quantity in session.execute(select(OrderLine.menu_item_id, func.sum(OrderLine.quantity)).join(Order, Order.id == OrderLine.order_id)
                 .where(Order.branch_id == branch_id, Order.status == "completed", Order.created_at >= start, Order.created_at < end)
                 .group_by(OrderLine.menu_item_id)).all()}
    maximum_sales = max(sales.values(), default=1) or 1
    availability = {r["menu_item_id"]: r for r in menu_availability(session, branch_id, as_of)}
    candidates = defaultdict(list)
    for component, ingredient in session.execute(select(RecipeComponent, Ingredient).join(Ingredient, Ingredient.id == RecipeComponent.ingredient_id)):
        if ingredient.id in risks:
            lots = risks[ingredient.id]
            candidates[component.menu_item_id].append({"ingredient_id": ingredient.id, "name": ingredient.name,
                "unit": ingredient.unit, "expiring_quantity": sum(b["remaining_quantity"] for b in lots),
                "days_to_expiry": min(b["days_to_expiry"] for b in lots), "required_per_portion": float(component.quantity)})
    promotions = []
    for item in session.scalars(select(MenuItem).where(MenuItem.is_active.is_(True)).order_by(MenuItem.id)):
        ingredients = candidates[item.id]
        if not ingredients or not availability[item.id]["sellable"]:
            continue
        days = min(i["days_to_expiry"] for i in ingredients)
        units = int(sales.get(item.id, 0))
        useful_portions = min(availability[item.id]["available_portions"],
                              int(max(i["expiring_quantity"] / i["required_per_portion"] for i in ingredients)))
        # Explicit deterministic heuristic, not a trained prediction or automatic discount.
        urgency = 50 * (horizon_days - days + 1) / (horizon_days + 1)
        popularity = 30 * units / maximum_sales
        coverage = 20 * min(useful_portions, 20) / 20
        promotions.append({"menu_item_id": item.id, "name": item.name, "score": round(urgency + popularity + coverage, 2),
            "reasons": [f"{i['name']}: {i['expiring_quantity']:g} {i['unit']} expires in {i['days_to_expiry']} day(s)" for i in ingredients]
                       + [f"{units} portions sold in the 28-day assessment window", f"{useful_portions} portions could use expiring stock"],
            "ingredients": ingredients, "available_portions": availability[item.id]["available_portions"], "recent_sales_quantity": units,
            "score_components": {"expiry_urgency": round(urgency, 2), "sales_popularity": round(popularity, 2), "usable_portions": round(coverage, 2)}})
    promotions.sort(key=lambda p: (-p["score"], p["menu_item_id"]))
    return {"branch_id": branch_id, "as_of": as_of.isoformat(), "horizon_days": horizon_days, "batches": batches,
        "summary": {"expiring_batches": sum(b["status"] == "expiring" for b in batches),
                    "expired_batches": sum(b["status"] == "expired" for b in batches),
                    "known_value_at_risk": round(sum(b["value_at_risk"] or 0 for b in batches), 2),
                    "unknown_expiry_batches": sum(b["status"] == "unknown" for b in batches)},
        "promotions": promotions,
        "methodology": "Current remaining inventory assessed against as_of; not a historical inventory reconstruction. Unknown expiry is excluded from waste valuation. Score = urgency (50) + relative 28-day sales (30) + usable portions capped at 20 (20). Expired stock is excluded from promotions."}

def discard_batch(session, batch_id, key, actor_user_id=None):
    key = request_key(key)
    try:
        batch = session.get(StockBatch, batch_id)
        if batch is None:
            raise BusinessError(404, "Stock batch not found")
        # Match checkout/receipt stock-then-batch lock order.
        stock = session.scalar(select(BranchStock).where(BranchStock.branch_id == batch.branch_id,
                               BranchStock.ingredient_id == batch.ingredient_id).with_for_update())
        if stock is None:
            raise BusinessError(409, "Batch has no aggregate stock row; reconcile inventory")
        batch = session.scalar(select(StockBatch).where(StockBatch.id == batch_id).with_for_update().execution_options(populate_existing=True))
        previous = session.scalar(select(StockBatchDiscard).where(StockBatchDiscard.request_key == key).with_for_update())
        if previous:
            if previous.batch_id != batch_id:
                raise BusinessError(409, "request_key was already used for a different discard")
            session.commit()
            return {"id": previous.id, "batch_id": batch_id, "discarded_quantity": float(previous.quantity), "idempotent_replay": True}
        if session.scalar(select(StockBatchDiscard.id).where(StockBatchDiscard.batch_id == batch_id)):
            raise BusinessError(409, "Batch was already discarded; replay using its original request_key")
        if batch.expires_on is None or batch.expires_on >= business_today():
            raise BusinessError(409, "Only expired stock batches can be discarded")
        if batch.remaining_quantity <= 0:
            raise BusinessError(409, "Batch has no remaining quantity")
        ensure_stock_batches(session, stock)
        quantity = batch.remaining_quantity
        stock.quantity -= quantity
        batch.remaining_quantity = 0
        movement = StockMovement(branch_id=batch.branch_id, ingredient_id=batch.ingredient_id,
                                 quantity_delta=-quantity, reason="expired_discard")
        session.add(movement)
        session.flush()
        record = StockBatchDiscard(batch_id=batch_id, request_key=key, quantity=quantity,
                                   actor_user_id=actor_user_id, movement_id=movement.id)
        session.add(record)
        session.flush()
        result = {"id": record.id, "batch_id": batch_id, "discarded_quantity": float(quantity), "idempotent_replay": False}
        session.commit()
        return result
    except BusinessError:
        session.rollback()
        raise
    except IntegrityError:
        session.rollback()
        previous = session.scalar(select(StockBatchDiscard).where(StockBatchDiscard.request_key == key))
        if previous and previous.batch_id == batch_id:
            return {"id": previous.id, "batch_id": batch_id, "discarded_quantity": float(previous.quantity), "idempotent_replay": True}
        raise BusinessError(409, "Discard conflicts with existing inventory records")
    except OperationalError as error:
        session.rollback()
        code = error.orig.args[0] if getattr(error.orig, "args", ()) else None
        raise BusinessError(409 if code in (1205, 1213) else 503,
                            "Discard lock conflict; retry with the same request_key" if code in (1205, 1213) else "The SQL store is unavailable") from error
