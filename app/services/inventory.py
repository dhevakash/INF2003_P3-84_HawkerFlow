from sqlalchemy import select
from app.models import BranchStock, StockMovement, StockReceipt
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
