from sqlalchemy import select
from app.models import BranchStock, StockAdjustment, StockMovement, StockReceipt
from app.services.checkout import BusinessError


def restock(session, payload, actor_id):
    with session.begin():
        stock = session.scalar(select(BranchStock).where(
            BranchStock.branch_id == payload.branch_id,
            BranchStock.ingredient_id == payload.ingredient_id).with_for_update())
        if stock is None:
            raise BusinessError('Configure the branch/ingredient stock row first.', 422)
        receipt = StockReceipt(**payload.model_dump(), actor_user_id=actor_id)
        session.add(receipt)
        session.flush()
        stock.quantity += payload.quantity
        session.add(StockMovement(branch_id=payload.branch_id,
            ingredient_id=payload.ingredient_id, delta=payload.quantity, receipt_id=receipt.id))
        return {'receipt_id': receipt.id, 'quantity': str(stock.quantity)}


def adjust_stock(session, branch_id, ingredient_id, payload, actor_id):
    """Lock and compare the displayed balance before committing an audited correction."""
    with session.begin():
        stock = session.scalar(select(BranchStock).where(
            BranchStock.branch_id == branch_id,
            BranchStock.ingredient_id == ingredient_id).with_for_update())
        if stock is None:
            raise BusinessError('Stock record not found.', 404)
        if stock.quantity != payload.expected_quantity:
            raise BusinessError('Stock has changed since you opened it. Refresh Stock and try again.')
        delta = payload.quantity - stock.quantity
        if not delta:
            raise BusinessError('Enter a different quantity to record a correction.', 422)
        adjustment = StockAdjustment(branch_id=branch_id, ingredient_id=ingredient_id,
            previous_quantity=stock.quantity, quantity=payload.quantity,
            actor_user_id=actor_id, reason=payload.reason)
        session.add(adjustment)
        session.flush()
        stock.quantity = payload.quantity
        session.add(StockMovement(branch_id=branch_id, ingredient_id=ingredient_id,
            delta=delta, adjustment_id=adjustment.id, created_at=adjustment.created_at))
        result = {'adjustment_id': adjustment.id, 'previous_quantity': str(adjustment.previous_quantity),
                  'quantity': str(stock.quantity)}
    return result
