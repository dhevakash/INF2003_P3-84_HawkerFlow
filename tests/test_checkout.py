from decimal import Decimal
import pytest
from pydantic import ValidationError
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from app.models import BranchStock, Customer, LoyaltyTransaction, MenuItem, Order, OrderLine, RecipeComponent, StockMovement
from app.schemas import CheckoutInput, MenuInput, RestockInput, ReviewInput
from app.services.checkout import BusinessError, checkout
from app.services.inventory import restock


def count(session, model):
    return session.scalar(select(func.count()).select_from(model))


def test_checkout_updates_order_stock_points_together(database, cart):
    with database() as s:
        assert checkout(s, cart, 1)['total'] == '5.00'
    with database() as s:
        assert s.get(BranchStock, (1, 1)).quantity == Decimal('8.000')
        assert s.get(Customer, 1).points == 105
        assert count(s, Order) == count(s, OrderLine) == count(s, StockMovement) == 1


def test_shortage_rolls_back_everything(database, cart):
    cart.lines[0].quantity = 6
    with database() as s, pytest.raises(BusinessError):
        checkout(s, cart, 1)
    with database() as s:
        assert count(s, Order) == count(s, LoyaltyTransaction) == 0
        assert s.get(Customer, 1).points == 100
        assert s.get(BranchStock, (1, 1)).quantity == Decimal('10.000')


def test_identical_retry_returns_one_order(database, cart):
    with database() as s:
        first = checkout(s, cart, 1)
        assert checkout(s, cart, 1) == first
    with database() as s:
        assert count(s, Order) == 1
        assert s.get(Customer, 1).points == 105


def test_key_cannot_be_reused_for_changed_cart(database, cart):
    with database() as s:
        checkout(s, cart, 1)
    cart.lines[0].quantity = 2
    with database() as s, pytest.raises(BusinessError, match='different checkout'):
        checkout(s, cart, 1)


def test_redemption_is_audited(database, cart):
    cart.redeem_points = 100
    with database() as s:
        assert checkout(s, cart, 1)['total'] == '4.00'
    with database() as s:
        assert s.get(Customer, 1).points == 4
        assert sorted(s.scalars(select(LoyaltyTransaction.delta))) == [-100, 4]


def test_insufficient_points_rolls_back(database, cart):
    cart.redeem_points = 101
    with database() as s, pytest.raises(BusinessError):
        checkout(s, cart, 1)
    with database() as s:
        assert count(s, Order) == 0
        assert s.get(BranchStock, (1, 1)).quantity == Decimal('10.000')


def test_historical_price_is_a_snapshot(database, cart):
    with database() as s:
        checkout(s, cart, 1)
    with database.begin() as s:
        s.get(MenuItem, 1).price = Decimal('9.00')
    with database() as s:
        assert s.scalar(select(OrderLine.unit_price)) == Decimal('5.00')


def test_item_without_recipe_cannot_be_sold(database, cart):
    with database.begin() as s:
        s.delete(s.get(RecipeComponent, (1, 1)))
    with database() as s, pytest.raises(BusinessError, match='recipe'):
        checkout(s, cart, 1)


def test_inactive_item_cannot_be_sold(database, cart):
    with database.begin() as s:
        s.get(MenuItem, 1).active = False
    with database() as s, pytest.raises(BusinessError):
        checkout(s, cart, 1)


def test_multi_item_cart_combines_shared_ingredients(database, cart):
    with database.begin() as s:
        s.add(MenuItem(id=2, name='Second meal', price=Decimal('6.00')))
        s.flush()
        s.add(RecipeComponent(menu_item_id=2, ingredient_id=1, quantity=Decimal('3.000')))
    payload = CheckoutInput(request_key='shared-ingredient', branch_id=1, customer_id=1,
                            lines=[{'menu_item_id': 1, 'quantity': 1}, {'menu_item_id': 2, 'quantity': 2}])
    with database() as s:
        checkout(s, payload, 1)
    with database() as s:
        assert s.get(BranchStock, (1, 1)).quantity == Decimal('2.000')
        assert count(s, StockMovement) == 1


def test_stock_check_constraint_rejects_negative_balance(database):
    with pytest.raises(IntegrityError):
        with database.begin() as s:
            s.get(BranchStock, (1, 1)).quantity = Decimal('-1')


def test_movement_requires_a_matching_receipt_or_sale(database):
    with pytest.raises(IntegrityError):
        with database.begin() as s:
            s.add(StockMovement(branch_id=1, ingredient_id=1, delta=Decimal('1.000')))


def test_restock_writes_receipt_and_movement(database):
    with database() as s:
        result = restock(s, RestockInput(branch_id=1, ingredient_id=1, quantity='3.000'), 1)
        assert Decimal(result['quantity']) == Decimal('13.000')
    with database() as s:
        movement = s.scalar(select(StockMovement))
        assert movement.receipt_id == result['receipt_id']
        assert movement.delta == Decimal('3.000')


def test_money_input_rejects_extra_decimal_places():
    with pytest.raises(ValidationError):
        MenuInput(name='Example', price='3.999')


def test_cart_rejects_duplicate_items():
    with pytest.raises(ValidationError):
        CheckoutInput(request_key='duplicate-cart', branch_id=1, customer_id=1,
            lines=[{'menu_item_id': 1, 'quantity': 1}, {'menu_item_id': 1, 'quantity': 2}])


def test_review_rejects_duplicate_tags_and_invalid_nested_ratings():
    with pytest.raises(ValidationError):
        ReviewInput(order_id=1, rating=5, text='Example review', tags=['food', 'food'])
    with pytest.raises(ValidationError):
        ReviewInput(order_id=1, rating=5, text='Example review', category_ratings={'food': 9})
