from decimal import Decimal

import pytest
from sqlalchemy import event, func, select, text
from sqlalchemy.exc import IntegrityError

from app.loyalty import MAX_POINTS
from app.models import BranchStock, Customer, LoyaltyAdjustment, Order
from app.schemas import PointsEditInput
from app.services.checkout import BusinessError, checkout
from app.services.loyalty import correct_points
from tests.test_api import headers


EDIT = {'points': 80, 'expected_points': 100, 'reason': ' Fraud correction '}
REMOVE = {'amount': 30, 'expected_points': 80, 'reason': 'Fraudulent points removed'}


def points_state(database):
    with database() as session:
        return (session.get(Customer, 1).points,
                session.scalar(select(func.count()).select_from(LoyaltyAdjustment)))


def test_admin_edits_and_removes_points_with_before_after_audit(client, database):
    auth = headers(client, 'admin@example.test')
    response = client.put('/api/loyalty/customers/1/points', headers=auth, json=EDIT)
    assert response.status_code == 200, response.text
    assert response.json()['delta'] == -20
    removal = client.post('/api/loyalty/customers/1/points/removals', headers=auth, json=REMOVE)
    assert removal.status_code == 200, removal.text
    assert removal.json()['points'] == 50
    with database() as session:
        entries = list(session.scalars(select(LoyaltyAdjustment).order_by(LoyaltyAdjustment.id)))
        assert [(row.action, row.previous_points, row.points, row.delta, row.actor_user_id) for row in entries] == [
            ('edit', 100, 80, -20, 4), ('remove', 80, 50, -30, 4)]
        assert entries[0].reason == 'Fraud correction'
    history = client.get('/api/loyalty', headers=auth).json()
    assert history[0]['kind'] == 'adjustment'
    assert history[0]['reason'] == REMOVE['reason']
    assert history[0]['order_id'] is None


def test_admin_can_increase_or_clear_a_balance(client, database):
    auth = headers(client, 'admin@example.test')
    assert client.put('/api/loyalty/customers/1/points', headers=auth,
        json={**EDIT, 'points': 120}).status_code == 200
    assert client.post('/api/loyalty/customers/1/points/removals', headers=auth,
        json={**REMOVE, 'amount': 120, 'expected_points': 120}).status_code == 200
    assert points_state(database) == (0, 2)


@pytest.mark.parametrize('email,status', [(None, 401), ('staff@example.test', 403), ('buyer@example.test', 403)])
@pytest.mark.parametrize('remove', [False, True])
def test_only_admin_can_correct_points(client, database, email, status, remove):
    auth = headers(client, email) if email else {}
    response = (client.post('/api/loyalty/customers/1/points/removals', headers=auth,
        json={**REMOVE, 'expected_points': 100}) if remove else
        client.put('/api/loyalty/customers/1/points', headers=auth, json=EDIT))
    assert response.status_code == status
    assert points_state(database) == (100, 0)


@pytest.mark.parametrize('changes', [{'points': -1}, {'points': MAX_POINTS+1}, {'points': 1.5},
    {'points': '80'}, {'points': '1e3'}, {'points': True}, {'expected_points': '100'},
    {'expected_points': True}, {'reason': '   '}, {'reason': 'x'*256}, {'role': 'admin'}])
def test_points_edit_validation_cannot_change_database(client, database, changes):
    response = client.put('/api/loyalty/customers/1/points', headers=headers(client, 'admin@example.test'), json={**EDIT, **changes})
    assert response.status_code == 422
    assert points_state(database) == (100, 0)


@pytest.mark.parametrize('amount', [0, -1, 101, '10', '1e3', 1.5, True, MAX_POINTS+1])
def test_invalid_or_excess_removal_cannot_change_database(client, database, amount):
    response = client.post('/api/loyalty/customers/1/points/removals', headers=headers(client, 'admin@example.test'),
        json={**REMOVE, 'amount': amount, 'expected_points': 100})
    assert response.status_code == 422
    assert points_state(database) == (100, 0)


def test_missing_unchanged_and_stale_balances_are_rejected(client, database):
    auth = headers(client, 'admin@example.test')
    assert client.put('/api/loyalty/customers/999/points', headers=auth, json=EDIT).status_code == 404
    assert client.put('/api/loyalty/customers/1/points', headers=auth, json={**EDIT, 'points': 100}).status_code == 422
    assert client.put('/api/loyalty/customers/1/points', headers=auth, json={**EDIT, 'expected_points': 99}).status_code == 409
    assert points_state(database) == (100, 0)
    assert client.put('/api/loyalty/customers/1/points', headers=auth, json=EDIT).status_code == 200
    assert client.put('/api/loyalty/customers/1/points', headers=auth, json=EDIT).status_code == 409
    assert points_state(database) == (80, 1)


def test_original_orders_earnings_redemptions_and_movements_are_preserved(client, database, cart):
    with database() as session:
        checkout(session, cart.model_copy(update={'redeem_points': 50}), 1)
    tables = ('orders', 'order_lines', 'loyalty_transactions', 'stock_movements', 'users')
    def history():
        with database() as session:
            return {table: list(session.execute(text('SELECT * FROM '+table)).mappings()) for table in tables}
    before = history()
    assert client.put('/api/loyalty/customers/1/points', headers=headers(client, 'admin@example.test'),
        json={**EDIT, 'points': 10, 'expected_points': 54}).status_code == 200
    assert history() == before
    with database() as session:
        assert session.get(Customer, 1).points == 10
        assert session.get(Order, 1).total == Decimal('4.50')


def test_audit_failure_rolls_back_balance(database):
    def reject(mapper, connection, target):
        raise RuntimeError('Simulated audit failure')
    event.listen(LoyaltyAdjustment, 'before_insert', reject)
    try:
        with database() as session, pytest.raises(RuntimeError, match='audit failure'):
            correct_points(session, 1, PointsEditInput(**EDIT), 4)
    finally:
        event.remove(LoyaltyAdjustment, 'before_insert', reject)
    assert points_state(database) == (100, 0)


def test_customer_sees_only_own_corrections_and_investigation_notes_stay_admin_only(client):
    auth = headers(client, 'admin@example.test')
    assert client.put('/api/loyalty/customers/1/points', headers=auth, json=EDIT).status_code == 200
    assert client.put('/api/loyalty/customers/2/points', headers=auth,
        json={**EDIT, 'points': 20, 'expected_points': 0}).status_code == 200
    own = client.get('/api/loyalty', headers=headers(client, 'buyer@example.test')).json()
    assert len(own) == 1 and own[0]['customer_id'] == 1 and own[0]['delta'] == -20
    staff = client.get('/api/loyalty', headers=headers(client, 'staff@example.test')).json()
    assert len(staff) == 2
    for entry in own+staff:
        assert not {'reason', 'actor_user_id', 'previous_points', 'points'} & entry.keys()


def test_checkout_and_corrections_share_current_balance(client, database, cart):
    auth = headers(client, 'admin@example.test')
    with database() as session:
        checkout(session, cart, 1)
    assert client.put('/api/loyalty/customers/1/points', headers=auth, json=EDIT).status_code == 409
    assert points_state(database) == (105, 0)
    assert client.put('/api/loyalty/customers/1/points', headers=auth,
        json={**EDIT, 'points': 0, 'expected_points': 105}).status_code == 200
    with database() as session, pytest.raises(BusinessError, match='Insufficient points'):
        checkout(session, cart.model_copy(update={'request_key': 'after-fraud-correction', 'redeem_points': 1}), 1)
    assert points_state(database) == (0, 1)


def test_points_limit_rejects_overflowing_sale_without_partial_changes(client, database, cart):
    assert client.put('/api/loyalty/customers/1/points', headers=headers(client, 'admin@example.test'),
        json={**EDIT, 'points': MAX_POINTS}).status_code == 200
    with database() as session, pytest.raises(BusinessError, match='supported limit'):
        checkout(session, cart, 1)
    with database() as session:
        assert session.get(Customer, 1).points == MAX_POINTS
        assert session.scalar(select(func.count()).select_from(Order)) == 0
        assert session.get(BranchStock, (1, 1)).quantity == Decimal('10.000')


@pytest.mark.parametrize('changes', [{'points': -1}, {'delta': 1}, {'action': 'erase'}, {'reason': ' '},
                                    {'action': 'remove', 'points': 120, 'delta': 20}])
def test_database_checks_reject_invalid_adjustment_rows(database, changes):
    with database() as session, pytest.raises(IntegrityError):
        with session.begin():
            session.add(LoyaltyAdjustment(**{**dict(customer_id=1, actor_user_id=4, action='edit',
                previous_points=100, points=80, delta=-20, reason='Fraud correction'), **changes}))
