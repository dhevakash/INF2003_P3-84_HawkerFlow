"""One SQL transaction owns order, ingredient deductions and points changes."""
from collections import defaultdict
from decimal import Decimal
import hashlib
import json
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from app.models import (Branch, BranchStock, Customer, LoyaltyTransaction, MenuItem,
                        Order, OrderLine, RecipeComponent, StockMovement)


class BusinessError(Exception):
    def __init__(self, message, status=409):
        super().__init__(message)
        self.status = status


def request_digest(payload, actor_id):
    content = payload.model_dump(mode='json', exclude={'request_key'})
    content['lines'] = sorted(content['lines'], key=lambda line: line['menu_item_id'])
    content['actor_user_id'] = actor_id
    return hashlib.sha256(json.dumps(content, sort_keys=True).encode()).hexdigest()


def order_result(order):
    return {'order_id': order.id, 'subtotal': format(order.subtotal, '.2f'),
            'discount': format(order.discount, '.2f'), 'total': format(order.total, '.2f'),
            'customer_id': order.customer_id, 'branch_id': order.branch_id}


def order_detail(session, order):
    """Human-readable receipt: dish names, per-line paid prices, and points moved.

    Line totals use the OrderLine.unit_price snapshot taken at sale time, never the
    live menu price, so historical receipts stay accurate when prices change later.
    """
    branch = session.get(Branch, order.branch_id)
    rows = session.execute(
        select(OrderLine, MenuItem.name)
        .join(MenuItem, MenuItem.id == OrderLine.menu_item_id)
        .where(OrderLine.order_id == order.id)
        .order_by(OrderLine.id)
    ).all()
    lines = [{'menu_item_id': line.menu_item_id, 'name': name, 'quantity': line.quantity,
              'unit_price': format(line.unit_price, '.2f'),
              'line_total': format(line.unit_price * line.quantity, '.2f')}
             for line, name in rows]
    points = {kind: delta for kind, delta in session.execute(
        select(LoyaltyTransaction.kind, LoyaltyTransaction.delta)
        .where(LoyaltyTransaction.order_id == order.id)).all()}
    return {'order_id': order.id, 'created_at': order.created_at.isoformat() + 'Z',
            'branch': {'id': order.branch_id, 'name': branch.name if branch else None},
            'customer_id': order.customer_id,
            'lines': lines,
            'subtotal': format(order.subtotal, '.2f'),
            'discount': format(order.discount, '.2f'),
            'total': format(order.total, '.2f'),
            'points_earned': points.get('earn', 0),
            'points_redeemed': -points.get('redeem', 0)}


def _validate_retry(order, digest):
    if order.request_hash != digest:
        raise BusinessError('Request key was already used for a different checkout.')
    return order_result(order)


def checkout(session, payload, actor_id, *, created_at=None):
    """Use a fresh Session. Real contention requires MariaDB/InnoDB, not SQLite."""
    digest = request_digest(payload, actor_id)
    try:
        with session.begin():
            previous = session.scalar(select(Order).where(Order.request_key == payload.request_key))
            if previous:
                return _validate_retry(previous, digest)
            # Stable order for stock locks reduces deadlock risk between carts.
            wanted_ids = sorted(line.menu_item_id for line in payload.lines)
            items = {item.id: item for item in session.scalars(
                select(MenuItem).where(MenuItem.id.in_(wanted_ids)).order_by(MenuItem.id).with_for_update()
            )}
            if len(items) != len(wanted_ids) or any(not item.active for item in items.values()):
                raise BusinessError('A menu item is unavailable.', 422)
            recipes = list(session.scalars(select(RecipeComponent).where(
                RecipeComponent.menu_item_id.in_(wanted_ids))))
            configured = {r.menu_item_id for r in recipes}
            if configured != set(wanted_ids):
                raise BusinessError('Every sold item must have a recipe configured.', 422)
            quantities = {line.menu_item_id: line.quantity for line in payload.lines}
            needed = defaultdict(lambda: Decimal('0.000'))
            for component in recipes:
                needed[component.ingredient_id] += component.quantity * quantities[component.menu_item_id]
            stocks = {stock.ingredient_id: stock for stock in session.scalars(
                select(BranchStock).where(BranchStock.branch_id == payload.branch_id,
                    BranchStock.ingredient_id.in_(sorted(needed)))
                .order_by(BranchStock.ingredient_id).with_for_update())}
            for ingredient_id, quantity in needed.items():
                if ingredient_id not in stocks or stocks[ingredient_id].quantity < quantity:
                    raise BusinessError(f'Insufficient stock for ingredient {ingredient_id}.')
            customer = session.scalar(select(Customer).where(Customer.id == payload.customer_id).with_for_update())
            if not customer or not customer.active:
                raise BusinessError('Customer is unavailable.', 422)
            subtotal = sum((items[line.menu_item_id].price * line.quantity for line in payload.lines), Decimal('0.00'))
            discount = Decimal(payload.redeem_points) / Decimal('100')
            if payload.redeem_points > customer.points or discount > subtotal:
                raise BusinessError('Insufficient points or redemption exceeds subtotal.')
            total = (subtotal - discount).quantize(Decimal('0.01'))
            order = Order(request_key=payload.request_key, request_hash=digest,
                branch_id=payload.branch_id, customer_id=customer.id, cashier_user_id=actor_id,
                subtotal=subtotal, discount=discount, total=total)
            if created_at is not None:
                order.created_at = created_at
            session.add(order)
            session.flush()
            for line in payload.lines:
                session.add(OrderLine(order_id=order.id, menu_item_id=line.menu_item_id,
                    quantity=line.quantity, unit_price=items[line.menu_item_id].price))
            for ingredient_id, quantity in needed.items():
                stocks[ingredient_id].quantity -= quantity
                session.add(StockMovement(branch_id=payload.branch_id, ingredient_id=ingredient_id,
                    delta=-quantity, order_id=order.id, created_at=order.created_at))
            # Teaching rule: 100 points = SGD 1; earn floor(net amount in SGD).
            earned = int(total)
            customer.points += earned - payload.redeem_points
            if payload.redeem_points:
                session.add(LoyaltyTransaction(customer_id=customer.id, order_id=order.id,
                    kind='redeem', delta=-payload.redeem_points, created_at=order.created_at))
            if earned:
                session.add(LoyaltyTransaction(customer_id=customer.id, order_id=order.id,
                    kind='earn', delta=earned, created_at=order.created_at))
            result = order_result(order)
        return result
    except IntegrityError:
        session.rollback()
        # A concurrent retry may have won the unique request-key race.
        with session.begin():
            previous = session.scalar(select(Order).where(Order.request_key == payload.request_key))
            if previous:
                return _validate_retry(previous, digest)
        raise
