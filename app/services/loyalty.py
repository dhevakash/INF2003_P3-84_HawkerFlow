"""Audited point corrections share the customer lock used by checkout."""
from sqlalchemy import select

from app.models import Customer, LoyaltyAdjustment
from app.services.checkout import BusinessError


def correct_points(session, customer_id, payload, actor_id, *, remove=False):
    with session.begin():
        customer = session.scalar(select(Customer).where(Customer.id == customer_id).with_for_update())
        if customer is None:
            raise BusinessError('Customer not found.', 404)
        if customer.points != payload.expected_points:
            raise BusinessError('This points balance has changed. Refresh Points history and select the customer again.')
        target = customer.points - payload.amount if remove else payload.points
        if target < 0:
            raise BusinessError('Cannot remove more points than the customer currently has.', 422)
        delta = target - customer.points
        if not delta:
            raise BusinessError('Enter a different balance to record a points correction.', 422)
        adjustment = LoyaltyAdjustment(customer_id=customer.id, actor_user_id=actor_id,
            action='remove' if remove else 'edit', previous_points=customer.points,
            points=target, delta=delta, reason=payload.reason)
        session.add(adjustment)
        customer.points = target
        session.flush()
        result = {'adjustment_id': adjustment.id, 'customer_id': customer.id, 'points': target,
                  'previous_points': adjustment.previous_points, 'delta': delta}
    return result
