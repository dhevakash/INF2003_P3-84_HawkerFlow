from decimal import Decimal

import pytest
from sqlalchemy import event, func, select
from sqlalchemy.exc import IntegrityError

from app.models import BranchStock, Order, OrderLine, StockAdjustment, StockMovement
from app.schemas import StockAdjustmentInput
from app.services.checkout import checkout
from app.services.inventory import adjust_stock
from tests.test_backend_roles import headers


BODY = {'quantity': '7.125', 'expected_quantity': '10.000', 'reason': ' Physical count correction '}


def test_admin_corrects_stock_both_ways_with_audit_and_zero_is_valid(client, database):
    auth = headers(client, 'admin@example.test')
    for old, quantity in [('10.000', '7.125'), ('7.125', '12.500'), ('12.500', '0.000')]:
        response = client.put('/api/stock/1/1', headers=auth, json={**BODY, 'quantity': quantity, 'expected_quantity': old})
        assert response.status_code == 200, response.text
        with database() as session:
            assert session.get(BranchStock, (1, 1)).quantity == Decimal(quantity)
            adjustment = session.get(StockAdjustment, response.json()['adjustment_id'])
            assert (adjustment.previous_quantity, adjustment.quantity, adjustment.actor_user_id, adjustment.reason) == (
                Decimal(old), Decimal(quantity), 4, BODY['reason'].strip())
            movement = session.scalar(select(StockMovement).where(StockMovement.adjustment_id == adjustment.id))
            assert movement.delta == Decimal(quantity) - Decimal(old)
            assert movement.order_id is None and movement.receipt_id is None
    history = client.get('/api/stock/movements', headers=auth).json()
    assert history[0]['kind'] == 'adjustment'
    assert history[0]['reason'] == BODY['reason'].strip()
    assert history[0]['actor_user_id'] == 4


@pytest.mark.parametrize('email,status', [(None, 401), ('staff@example.test', 403), ('buyer@example.test', 403)])
def test_non_admin_stock_corrections_are_rejected_without_changes(client, database, email, status):
    auth = headers(client, email) if email else {}
    assert client.put('/api/stock/1/1', headers=auth, json=BODY).status_code == status
    with database() as session:
        assert session.get(BranchStock, (1, 1)).quantity == Decimal('10.000')
        assert session.scalar(select(func.count()).select_from(StockAdjustment)) == 0
        assert session.scalar(select(func.count()).select_from(StockMovement)) == 0


@pytest.mark.parametrize('changes', [{'quantity': '-0.001'}, {'quantity': '0.0001'},
    {'quantity': '100000000000.000'}, {'quantity': 'NaN'}, {'reason': '   '}, {'reason': 'x'*256},
    {'expected_quantity': '-1'}, {'quantity': '1e3'}, {'quantity': '2E4'},
    {'expected_quantity': '1e1'}, {'order_id': 1}, {'actor_user_id': 1}])
def test_stock_correction_validation(client, database, changes):
    auth = headers(client, 'admin@example.test')
    assert client.put('/api/stock/1/1', headers=auth, json={**BODY, **changes}).status_code == 422
    with database() as session:
        assert session.get(BranchStock, (1, 1)).quantity == Decimal('10.000')
        assert session.scalar(select(func.count()).select_from(StockAdjustment)) == 0


@pytest.mark.parametrize('changes', [{'quantity': 'e'}, {'quantity': '1e3'}, {'quantity': '2E4'},
    {'quantity': '1.2345'}, {'quantity': '1,000'}, {'branch_id': '1e0'}, {'ingredient_id': '1e0'},
    {'branch_id': True}, {'ingredient_id': 1.5}])
def test_receipt_rejects_nonplain_numbers_without_changing_stock(client, database, changes):
    auth = headers(client, 'admin@example.test')
    body = {'branch_id': 1, 'ingredient_id': 1, 'quantity': '1.125'}
    assert client.post('/api/stock/receipts', headers=auth, json={**body, **changes}).status_code == 422
    with database() as session:
        assert session.get(BranchStock, (1, 1)).quantity == Decimal('10.000')


def test_missing_unchanged_and_stale_balances_cannot_create_adjustments(client, database):
    auth = headers(client, 'admin@example.test')
    assert client.put('/api/stock/999/1', headers=auth, json=BODY).status_code == 404
    assert client.put('/api/stock/1/1', headers=auth, json={**BODY, 'quantity': '10.000'}).status_code == 422
    assert client.put('/api/stock/1/1', headers=auth, json={**BODY, 'expected_quantity': '9.000'}).status_code == 409
    assert client.post('/api/stock/receipts', headers=auth,
                       json={'branch_id': 1, 'ingredient_id': 1, 'quantity': '2.000'}).status_code == 201
    assert client.put('/api/stock/1/1', headers=auth, json=BODY).status_code == 409
    with database() as session:
        assert session.get(BranchStock, (1, 1)).quantity == Decimal('12.000')
        assert session.scalar(select(func.count()).select_from(StockAdjustment)) == 0


def test_audit_failure_rolls_back_stock_and_adjustment(database):
    def reject_movement(mapper, connection, target):
        raise RuntimeError('Simulated audit write failure')
    event.listen(StockMovement, 'before_insert', reject_movement)
    try:
        with database() as session, pytest.raises(RuntimeError, match='audit write failure'):
            adjust_stock(session, 1, 1, StockAdjustmentInput(**BODY), 4)
    finally:
        event.remove(StockMovement, 'before_insert', reject_movement)
    with database() as session:
        assert session.get(BranchStock, (1, 1)).quantity == Decimal('10.000')
        assert session.scalar(select(func.count()).select_from(StockAdjustment)) == 0


def test_corrections_do_not_rewrite_orders_and_admin_cannot_edit_or_delete_orders(client, database, cart):
    with database() as session:
        order_id = checkout(session, cart, 1)['order_id']
    auth = headers(client, 'admin@example.test')
    before = client.get('/api/orders', headers=auth).json()
    assert client.put('/api/stock/1/1', headers=auth, json={**BODY, 'expected_quantity': '8.000'}).status_code == 200
    for method in ('PUT', 'PATCH', 'DELETE'):
        assert client.request(method, '/api/orders/' + str(order_id), headers=auth, json={'total': '0.00'}).status_code == 404
    assert client.get('/api/orders', headers=auth).json() == before
    with database() as session:
        assert session.get(Order, order_id).total == Decimal('5.00')
        assert session.scalar(select(OrderLine).where(OrderLine.order_id == order_id)).quantity == 1


def test_stock_movement_requires_exactly_one_origin(database):
    with database() as session, pytest.raises(IntegrityError):
        with session.begin():
            session.add(StockMovement(branch_id=1, ingredient_id=1, delta=Decimal('-1.000')))
