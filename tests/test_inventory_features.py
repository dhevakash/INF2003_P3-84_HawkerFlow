"""Inventory logic tests. SQLite does not prove InnoDB lock behavior."""
from datetime import timedelta
from decimal import Decimal
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event, func, select
from sqlalchemy.orm import sessionmaker

from app.db import Base, get_session
from app.models import (Branch, BranchStock, Customer, Ingredient, MenuItem,
                        Order, RecipeComponent, StockBatch, StockBatchAllocation,
                        StockBatchDiscard, StockMovement, User)
from app.security import current_user
from app.sql_routes import router
from app.sql_service import (BusinessError, backfill_stock_batches, business_today,
                             checkout, discard_batch, list_batches, menu_availability,
                             receive_stock, sellable_stock_quantities, waste_analytics)


@pytest.fixture
def factory(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'inventory.sqlite'}", connect_args={"check_same_thread": False})
    @event.listens_for(engine, "connect")
    def foreign_keys(connection, _):
        connection.execute("PRAGMA foreign_keys=ON")
    Base.metadata.create_all(engine)
    factory = sessionmaker(engine, expire_on_commit=False)
    with factory() as db:
        db.add_all([Branch(id=1, name="One", address="Address", postal_code="123456"),
                    Branch(id=2, name="Two", address="Address", postal_code="123456"),
                    Customer(id=1, name="Customer", email="customer@test.local"),
                    Ingredient(id=1, name="Rice", unit="g"), Ingredient(id=2, name="Chicken", unit="g"),
                    MenuItem(id=1, name="Chicken Rice", category="Meals", price=5),
                    MenuItem(id=2, name="Rice", category="Meals", price=2)])
        db.flush()
        db.add_all([User(id=1, name="Manager", email="manager@test.local", password_hash="unused", role="manager"),
                    BranchStock(branch_id=1, ingredient_id=1, quantity=1000, reorder_level=100),
                    BranchStock(branch_id=1, ingredient_id=2, quantity=0, reorder_level=100),
                    RecipeComponent(menu_item_id=1, ingredient_id=1, quantity=100),
                    RecipeComponent(menu_item_id=1, ingredient_id=2, quantity=50),
                    RecipeComponent(menu_item_id=2, ingredient_id=1, quantity=100)])
        db.commit()
    yield factory
    engine.dispose()


def receipt(db, key, quantity, expiry=None, ingredient=2, cost=None):
    return receive_stock(db, {"branch_id": 1, "ingredient_id": ingredient, "quantity": quantity,
        "request_key": key, "expires_on": expiry, "unit_cost": cost})


def order(key="test", quantity=1):
    return {"branch_id": 1, "customer_id": 1, "request_key": key,
            "lines": [{"menu_item_id": 1, "quantity": quantity}]}


def count(db, model):
    return db.scalar(select(func.count()).select_from(model))


def test_backfill_preserves_unknown_expiry_and_is_repeatable(factory):
    with factory() as db:
        backfill_stock_batches(db)
        backfill_stock_batches(db)
        batch = db.scalar(select(StockBatch))
        assert batch.expires_on is None and batch.unit_cost is None
        assert batch.remaining_quantity == 1000 and batch.source == "legacy_unknown"
        assert count(db, StockBatch) == 1 and count(db, StockMovement) == 0


def test_fefo_consumption_and_order_replay_are_audited(factory):
    today = business_today()
    with factory() as db:
        unknown = receipt(db, "unknown", 50)
        later = receipt(db, "later", 100, today + timedelta(days=5))
        sooner = receipt(db, "soon", 40, today)
        result = checkout(db, order())
        assert db.get(StockBatch, sooner["batch_id"]).remaining_quantity == 0
        assert db.get(StockBatch, later["batch_id"]).remaining_quantity == 90
        assert db.get(StockBatch, unknown["batch_id"]).remaining_quantity == 50
        assert count(db, StockBatchAllocation) == 3  # rice + two chicken batches
        allocations = db.scalars(select(StockBatchAllocation).where(StockBatchAllocation.order_id == result["id"])).all()
        assert sum(a.quantity for a in allocations) == 150
        assert checkout(db, order())["idempotent_replay"] is True
        assert count(db, StockBatchAllocation) == 3


def test_expired_stock_is_excluded_and_failed_checkout_rolls_back(factory):
    with factory() as db:
        expired = receipt(db, "expired", 500, business_today() - timedelta(days=1))
        receipt(db, "fresh", 40, business_today() + timedelta(days=2))
        assert sellable_stock_quantities(db, 1)[2] == 40
        availability = menu_availability(db, 1)[0]
        assert availability["available_portions"] == 0 and not availability["sellable"]
        assert availability["limiting_ingredients"][0]["name"] == "Chicken"
        assert len(availability["recipe_ingredients"]) == 2
        before = count(db, StockMovement)
        with pytest.raises(BusinessError, match="expired batches"):
            checkout(db, order())
        assert db.get(BranchStock, (1, 1)).quantity == 1000
        assert db.get(BranchStock, (1, 2)).quantity == 540
        assert db.get(StockBatch, expired["batch_id"]).remaining_quantity == 500
        assert count(db, Order) == count(db, StockBatchAllocation) == 0
        assert count(db, StockMovement) == before
        # Legacy backfill attempted for rice rolls back too.
        assert not db.scalar(select(StockBatch).where(StockBatch.ingredient_id == 1))


def test_receipt_metadata_is_part_of_replay_identity(factory):
    with factory() as db:
        expiry = business_today() + timedelta(days=3)
        first = receipt(db, "delivery", "123.1250", expiry, cost="0.0150")
        replay = receipt(db, "delivery", "123.1250", expiry.isoformat(), cost="0.0150")
        assert replay["idempotent_replay"] and replay["batch_id"] == first["batch_id"]
        assert count(db, StockBatch) == 1
        with pytest.raises(BusinessError, match="different receipt"):
            receipt(db, "delivery", "123.1250", expiry + timedelta(days=1), cost="0.0150")
        with pytest.raises(BusinessError, match="different receipt"):
            receipt(db, "delivery", "123.1250", expiry, cost="0.0250")


def test_waste_values_preserve_units_and_promotions_exclude_expired(factory):
    with factory() as db:
        today = business_today()
        receipt(db, "old", 100, today - timedelta(days=1), cost="0.02")
        receipt(db, "soon", 150, today + timedelta(days=1), cost="0.02")
        report = waste_analytics(db, 1, today)
        assert report["summary"] == {"expiring_batches": 1, "expired_batches": 1,
                                     "known_value_at_risk": 5.0, "unknown_expiry_batches": 1}
        assert report["promotions"][0]["name"] == "Chicken Rice"
        promotion = report["promotions"][0]
        assert promotion["available_portions"] == 3
        assert promotion["ingredients"][0]["expiring_quantity"] == 150
        assert promotion["recent_sales_quantity"] == 0
        assert round(sum(promotion["score_components"].values()), 2) == promotion["score"]
        assert report["batches"][-1]["status"] == "unknown"
        assert "expiring_quantity" not in report["summary"]


def test_discard_is_audited_idempotent_and_cannot_remove_fresh_stock(factory):
    with factory() as db:
        old = receipt(db, "old", 100, business_today() - timedelta(days=1))
        fresh = receipt(db, "fresh", 150, business_today())
        before = count(db, StockMovement)
        discarded = discard_batch(db, old["batch_id"], "discard-one", 1)
        assert discarded["discarded_quantity"] == 100
        assert db.get(BranchStock, (1, 2)).quantity == 150
        audit = db.scalar(select(StockBatchDiscard))
        assert audit.actor_user_id == 1
        assert db.get(StockMovement, audit.movement_id).reason == "expired_discard"
        assert discard_batch(db, old["batch_id"], "discard-one", 1)["idempotent_replay"]
        assert count(db, StockMovement) == before + 1
        with pytest.raises(BusinessError, match="Only expired"):
            discard_batch(db, fresh["batch_id"], "fresh-discard", 1)
        with pytest.raises(BusinessError, match="different discard"):
            discard_batch(db, fresh["batch_id"], "discard-one", 1)


def test_inventory_api_authorization_and_contract(factory):
    app = FastAPI()
    app.include_router(router)
    identity = {"user": SimpleNamespace(id=1, role="manager", branch_id=None)}
    def sessions():
        with factory() as db:
            yield db
    app.dependency_overrides[get_session] = sessions
    app.dependency_overrides[current_user] = lambda: identity["user"]
    with TestClient(app) as client:
        response = client.post("/api/inventory/receive", json={"branch_id": 1, "ingredient_id": 2,
            "quantity": 100, "request_key": "api-receipt", "expires_on": business_today().isoformat(), "unit_cost": 0.02})
        assert response.status_code == 200, response.text
        assert response.json()["batch_id"]
        assert client.get("/api/menu/availability?branch_id=1").json()[0]["available_portions"] == 2
        assert client.get("/api/inventory/batches?branch_id=1").status_code == 200
        assert client.get("/api/analytics/waste?branch_id=1").json()["summary"]["expiring_batches"] == 1
        identity["user"] = SimpleNamespace(id=2, role="cashier", branch_id=1)
        assert client.get("/api/menu/availability?branch_id=2").status_code == 403
        assert client.get("/api/inventory/batches?branch_id=2").status_code == 403
        assert client.get("/api/analytics/waste?branch_id=1").status_code == 403
        assert client.post("/api/inventory/batches/1/discard", json={"request_key": "x"}).status_code == 403


def test_corrupt_batch_totals_fail_closed(factory):
    with factory() as db:
        receipt(db, "fresh", 100, business_today())
        db.get(BranchStock, (1, 2)).quantity = 10
        db.commit()
        assert sellable_stock_quantities(db, 1)[2] == 0
        with pytest.raises(BusinessError):
            checkout(db, order())
        assert count(db, Order) == 0
