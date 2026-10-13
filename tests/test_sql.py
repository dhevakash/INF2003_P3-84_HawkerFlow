"""SQLite unit tests: verify logic/constraints, NOT MariaDB locking behavior.

Real InnoDB race tests belong to test_integration.py. SQLite ignores FOR UPDATE.
"""
from datetime import datetime
from decimal import Decimal
from types import SimpleNamespace
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event, func, select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import sessionmaker
from app.db import Base, get_session
from app.models import Branch, BranchStock, Customer, Ingredient, LoyaltyTransaction, MenuItem, Order, OrderLine, RecipeComponent, StockMovement, StockReceipt
from app.security import current_user
from app.sql_routes import router
from app.sql_service import BusinessError, checkout, list_inventory, loyalty_summary, receive_stock, sales_analytics
from app.sql_views import create_views

@pytest.fixture
def factory(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'unit.sqlite'}", connect_args={"check_same_thread": False})
    @event.listens_for(engine, "connect")
    def foreign_keys(connection, _):
        connection.execute("PRAGMA foreign_keys=ON")
    Base.metadata.create_all(engine)
    factory = sessionmaker(engine, expire_on_commit=False)
    with factory() as session:
        session.add_all([Branch(id=1, name="One", address="Address", postal_code="123456"), Branch(id=2, name="Two", address="Address", postal_code="654321"), Customer(id=1, name="Akash", email="akash@example.test"), Customer(id=2, name="Arya", email="arya@example.test"), Ingredient(id=1, name="Rice", unit="g"), Ingredient(id=2, name="Chicken", unit="g"), MenuItem(id=1, name="Chicken Rice", category="Meals", price=Decimal("5.50")), MenuItem(id=2, name="Rice Bowl", category="Meals", price=Decimal("2.20"))])
        session.flush()
        session.add_all([RecipeComponent(menu_item_id=1, ingredient_id=1, quantity=100), RecipeComponent(menu_item_id=1, ingredient_id=2, quantity=50), RecipeComponent(menu_item_id=2, ingredient_id=1, quantity=80), BranchStock(branch_id=1, ingredient_id=1, quantity=1000, reorder_level=200), BranchStock(branch_id=1, ingredient_id=2, quantity=500, reorder_level=100)])
        session.commit()
    yield factory
    engine.dispose()

def payload(key="unit-order", customer=1, lines=None, points=0, branch=1):
    return {"branch_id": branch, "customer_id": customer, "request_key": key, "redeem_points": points, "lines": lines or [{"menu_item_id": 1, "quantity": 2, "notes": "Sauce aside"}]}

def count(session, model):
    return session.scalar(select(func.count()).select_from(model))

def test_checkout_atomic_stock_points_and_price(factory):
    with factory() as session:
        result = checkout(session, payload())
        assert result["total"] == 11.0
        assert result["points_earned"] == result["loyalty_balance"] == 11
        assert result["lines"][0]["unit_price"] == 5.50
        assert session.get(BranchStock, (1, 1)).quantity == 800
        assert session.get(BranchStock, (1, 2)).quantity == 400
        assert count(session, StockMovement) == 2
        assert count(session, Order) == 1

def test_reporting_views_refresh_and_count_orders_without_line_fanout(factory):
    create_views(factory.kw["bind"])
    create_views(factory.kw["bind"])  # startup is repeatable
    with factory() as session:
        checkout(session, payload(lines=[{"menu_item_id": 1, "quantity": 1},
                                          {"menu_item_id": 2, "quantity": 1}]))
        rows = session.execute(text("SELECT * FROM v_completed_branch_revenue ORDER BY branch_id")).mappings().all()
        assert rows[0]["completed_orders"] == 1
        assert float(rows[0]["net_revenue"]) == 7.70
        assert rows[1]["completed_orders"] == 0
        assert rows[1]["net_revenue"] == 0
        assert session.execute(text("SELECT * FROM v_low_stock")).all() == []
        session.get(BranchStock, (1, 1)).quantity = Decimal("200")
        session.commit()
        low = session.execute(text("SELECT * FROM v_low_stock")).mappings().one()
        assert low["branch_name"] == "One"
        assert low["ingredient_name"] == "Rice"
        assert low["shortfall"] == 0

def test_insufficient_later_ingredient_rolls_back_everything(factory):
    with factory() as session:
        session.get(BranchStock, (1, 2)).quantity = 1
        session.commit()
        with pytest.raises(BusinessError, match="Insufficient stock"):
            checkout(session, payload())
        assert session.get(BranchStock, (1, 1)).quantity == 1000
        assert count(session, Order) == count(session, OrderLine) == count(session, StockMovement) == count(session, LoyaltyTransaction) == 0

def test_duplicate_key_replay_does_not_repeat_stock_or_points(factory):
    with factory() as session:
        first = checkout(session, payload())
        replay = checkout(session, payload())
        assert first["id"] == replay["id"]
        assert replay["idempotent_replay"] is True
        assert session.get(BranchStock, (1, 1)).quantity == 800
        assert count(session, Order) == 1
        assert count(session, LoyaltyTransaction) == 1

@pytest.mark.parametrize("change", [{"customer_id": 2}, {"redeem_points": 100}, {"branch_id": 2}, {"lines": [{"menu_item_id": 1, "quantity": 3, "notes": ""}]}])
def test_duplicate_key_mismatched_payload_rejected(factory, change):
    with factory() as session:
        checkout(session, payload())
        body = payload()
        body.update(change)
        with pytest.raises(BusinessError, match="different order"):
            checkout(session, body)
        assert count(session, Order) == 1

def test_historical_prices_survive_menu_price_changes(factory):
    with factory() as session:
        first = checkout(session, payload())
        session.get(MenuItem, 1).price = Decimal("9.90")
        session.commit()
        second = checkout(session, payload("second"))
        assert session.get(OrderLine, first["lines"][0]["id"]).unit_price == Decimal("5.50")
        assert second["total"] == 19.80

def test_redemption_ledger_discount_and_earn_after_discount(factory):
    with factory() as session:
        session.add(LoyaltyTransaction(customer_id=1, points_delta=200, event_type="opening"))
        session.commit()
        result = checkout(session, payload(points=100))
        assert result["total"] == 10.0
        assert result["points_earned"] == 10
        assert result["loyalty_balance"] == 110
        assert loyalty_summary(session, 1)["balance"] == 110
        with pytest.raises(BusinessError, match="Not enough"):
            checkout(session, payload("second", points=200))
        assert count(session, Order) == 1

def test_redemption_cannot_exceed_bill(factory):
    with factory() as session:
        session.add(LoyaltyTransaction(customer_id=1, points_delta=1200, event_type="opening"))
        session.commit()
        with pytest.raises(BusinessError, match="exceed the bill"):
            checkout(session, payload(points=1200))
        assert count(session, Order) == 0

@pytest.mark.parametrize("body", [payload(points=50), payload(lines=[{"menu_item_id": 1, "quantity": 0}]), payload(lines=[{"menu_item_id": 1, "quantity": True}])])
def test_service_rejects_invalid_input(factory, body):
    with factory() as session:
        with pytest.raises(BusinessError) as error:
            checkout(session, body)
        assert error.value.status_code == 422

def test_shared_ingredient_aggregate_and_duplicate_item_lines(factory):
    with factory() as session:
        result = checkout(session, payload(lines=[{"menu_item_id": 1, "quantity": 1}, {"menu_item_id": 1, "quantity": 1}, {"menu_item_id": 2, "quantity": 2}]))
        assert result["total"] == 15.4
        assert len(result["lines"]) == 3
        assert session.get(BranchStock, (1, 1)).quantity == 640

def test_missing_recipe_prevents_checkout(factory):
    with factory() as session:
        session.add(MenuItem(id=3, name="No Recipe", category="Meals", price=1))
        session.commit()
        with pytest.raises(BusinessError, match="no configured recipe"):
            checkout(session, payload(lines=[{"menu_item_id": 3, "quantity": 1}]))

def test_stock_receipts_deduplicated_audited_and_payload_checked(factory):
    with factory() as session:
        body = {"branch_id": 1, "ingredient_id": 1, "quantity": "50.1250", "request_key": "receipt-one"}
        result = receive_stock(session, body)
        assert result["quantity"] == 1050.125
        assert receive_stock(session, body)["idempotent_replay"] is True
        assert count(session, StockReceipt) == count(session, StockMovement) == 1
        with pytest.raises(BusinessError, match="different receipt"):
            receive_stock(session, {**body, "quantity": 99})

def test_stock_receipt_creates_missing_branch_stock(factory):
    with factory() as session:
        receive_stock(session, {"branch_id": 2, "ingredient_id": 1, "quantity": 10, "request_key": "new-stock"})
        assert session.get(BranchStock, (2, 1)).quantity == 10

def test_checks_and_foreign_keys(factory):
    with factory() as session:
        session.add(MenuItem(name="Bad", category="Meals", price=-1))
        with pytest.raises(IntegrityError):
            session.commit()
        session.rollback()
        session.add(BranchStock(branch_id=999, ingredient_id=1, quantity=10, reorder_level=0))
        with pytest.raises(IntegrityError):
            session.commit()

def test_analytics_end_exclusive_and_no_line_join_doublecount(factory):
    with factory() as session:
        first = checkout(session, payload(lines=[{"menu_item_id": 1, "quantity": 1}, {"menu_item_id": 2, "quantity": 1}]))
        session.get(Order, first["id"]).created_at = datetime(2026, 10, 1)
        second = checkout(session, payload("end-order"))
        session.get(Order, second["id"]).created_at = datetime(2026, 10, 2)
        session.commit()
        result = sales_analytics(session, datetime(2026, 10, 1), datetime(2026, 10, 2))
        assert result["branches"][0]["orders"] == 1
        assert result["branches"][0]["revenue"] == 7.70
        assert len(result["menu"]) == 2
        session.get(BranchStock, (1, 1)).quantity = 100
        session.commit()
        assert len(list_inventory(session, 1, low_only=True)) == 1

@pytest.fixture
def api(factory):
    app = FastAPI()
    app.include_router(router)
    identity = {"user": SimpleNamespace(id=1, role="manager", customer_id=None, branch_id=None)}
    def sessions():
        with factory() as session:
            yield session
    app.dependency_overrides[get_session] = sessions
    app.dependency_overrides[current_user] = lambda: identity["user"]
    with TestClient(app) as client:
        yield client, identity

def test_cashier_branch_and_manager_mutation_restrictions(api):
    client, identity = api
    identity["user"] = SimpleNamespace(role="cashier", branch_id=1, customer_id=None)
    assert client.post("/api/orders", json=payload(branch=2)).status_code == 403
    assert client.get("/api/inventory?branch_id=2").status_code == 403
    assert client.post("/api/menu", json={"name": "X", "category": "Y", "price": 1}).status_code == 403
    assert client.get("/api/analytics/sales?start=2026-10-01&end=2026-10-02").status_code == 403
    assert client.post("/api/orders", json=payload()).status_code == 201

def test_customer_own_orders_points_only(api):
    client, identity = api
    one = client.post("/api/orders", json=payload()).json()
    other = client.post("/api/orders", json=payload("other", customer=2)).json()
    identity["user"] = SimpleNamespace(role="customer", customer_id=1, branch_id=None)
    assert client.get(f"/api/orders/{one['id']}").status_code == 200
    assert client.get(f"/api/orders/{other['id']}").status_code == 403
    assert len(client.get("/api/orders").json()) == 1
    assert client.get("/api/loyalty/2").status_code == 403
    assert client.get("/api/customers").status_code == 403
    assert client.post("/api/orders", json=payload("forbidden")).status_code == 403

def test_menu_crud_recipe_and_soft_delete(api):
    client, _ = api
    item = client.post("/api/menu", json={"name": "New Rice", "category": "Meals", "price": 3}).json()
    assert client.put(f"/api/menu/{item['id']}/recipe", json=[{"ingredient_id": 1, "quantity": 20}]).status_code == 200
    assert client.patch(f"/api/menu/{item['id']}", json={"price": "3.50"}).json()["price"] == 3.5
    assert client.patch(f"/api/menu/{item['id']}", json={"price": None}).status_code == 422
    assert client.delete(f"/api/menu/{item['id']}").status_code == 200
    assert item["id"] not in [x["id"] for x in client.get("/api/menu").json()]
    assert client.post("/api/orders", json=payload(lines=[{"menu_item_id": item["id"], "quantity": 1}])).status_code == 409
