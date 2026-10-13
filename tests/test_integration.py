"""Integration checks against REAL MariaDB and MongoDB, never SQLite/mongomock.

Opt in: RUN_INTEGRATION=1 SQL_URL=.../hawkerflow_test
MONGO_URL=mongodb://... MONGO_DATABASE=hawkerflow_test pytest -q -rs tests/test_integration.py
Dedicated databases ending in _test are mandatory; all records there are cleared.
When opt-in is absent these tests are explicitly SKIPPED, not validation evidence.
"""
import os
import threading
from concurrent.futures import ThreadPoolExecutor
from decimal import Decimal
from types import SimpleNamespace
from uuid import uuid4

import pytest

pytestmark = pytest.mark.skipif(
    os.environ.get("RUN_INTEGRATION") != "1",
    reason="Real DB integration not run: set RUN_INTEGRATION=1 and dedicated *_test databases",
)


@pytest.fixture(scope="module")
def real_system():
    from sqlalchemy.engine import make_url
    from fastapi.testclient import TestClient

    sql_url = os.environ.get("SQL_URL", "")
    mongo_url = os.environ.get("MONGO_URL", "")
    mongo_name = os.environ.get("MONGO_DATABASE", "")
    assert sql_url and mongo_url and mongo_name, "Explicit SQL_URL/MONGO_URL/MONGO_DATABASE required"
    parsed = make_url(sql_url)
    assert parsed.get_backend_name() in {"mysql", "mariadb"}, "Real MariaDB/MySQL required"
    assert (parsed.database or "").endswith("_test"), "SQL database must end _test (data will be cleared)"
    assert mongo_name.endswith("_test"), "Mongo database must end _test (data will be cleared)"
    from app.config import settings
    assert make_url(settings.sql_url).database == parsed.database, "App SQL settings already differ"
    assert settings.mongo_database == mongo_name, "App Mongo settings already differ"
    from app.db import Base, SessionLocal, engine, init_db
    from app.mongo import initialize_mongo
    from app.main import app
    import app.models as models

    # Unavailable real stores cause a failure, never a skip or fallback.
    with engine.connect() as connection:
        from sqlalchemy import text
        version = connection.execute(text("SELECT VERSION()")).scalar_one()
        assert "mariadb" in version.lower(), "This suite validates MariaDB specifically"
    mongo_db = initialize_mongo()
    init_db()
    with TestClient(app) as client:
        yield SimpleNamespace(client=client, models=models, Session=SessionLocal,
                              engine=engine, Base=Base, mongo=mongo_db)


@pytest.fixture()
def system(real_system):
    from app.security import hash_password, _attempts, _attempt_lock
    s = real_system
    # Each test resets fixtures, including the process-local login rate-limit state.
    with _attempt_lock:
        _attempts.clear()
    with s.engine.begin() as connection:
        for table in reversed(s.Base.metadata.sorted_tables):
            connection.execute(table.delete())
    for name in ("reviews", "customer_profiles"):
        s.mongo[name].delete_many({})
    m = s.models
    with s.Session() as db:
        db.add_all([
            m.Branch(id=1, name="Test Branch", address="Test Road", postal_code="123456"),
            m.Branch(id=2, name="Other Branch", address="Other Road", postal_code="234567"),
            m.Customer(id=1, name="Owner", email="owner@test.local"),
            m.Customer(id=2, name="Other", email="other@test.local"),
            m.MenuItem(id=1, name="Test Meal", category="meal", price=Decimal("120.00")),
            m.Ingredient(id=1, name="Rice", unit="portion"),
            m.Ingredient(id=2, name="Sauce", unit="portion"),
        ])
        db.flush()
        db.add_all([
            m.RecipeComponent(menu_item_id=1, ingredient_id=1, quantity=Decimal("2")),
            m.BranchStock(branch_id=1, ingredient_id=1, quantity=Decimal("100"), reorder_level=5),
            m.BranchStock(branch_id=1, ingredient_id=2, quantity=Decimal("100"), reorder_level=5),
            m.BranchStock(branch_id=2, ingredient_id=1, quantity=Decimal("100"), reorder_level=5),
        ])
        credentials = [
            ("manager", "manager@test.local", None, None),
            ("cashier", "cashier@test.local", None, 1),
            ("customer", "owner@test.local", 1, None),
            ("customer", "other@test.local", 2, None),
        ]
        for index, (role, email, customer_id, branch_id) in enumerate(credentials, 1):
            db.add(m.User(id=index, name=email, email=email, role=role,
                          password_hash=hash_password("TestPassword!123"),
                          customer_id=customer_id, branch_id=branch_id, is_active=True))
        db.commit()
    headers = {}
    for key, email in (("manager", "manager@test.local"), ("cashier", "cashier@test.local"),
                       ("owner", "owner@test.local"), ("other", "other@test.local")):
        response = s.client.post("/api/auth/login", json={"email": email, "password": "TestPassword!123"})
        assert response.status_code == 200, response.text
        headers[key] = {"Authorization": "Bearer " + response.json()["access_token"]}
    s.headers = headers
    yield s


def payload(**updates):
    result = {"branch_id": 1, "customer_id": 1, "request_key": str(uuid4()),
              "redeem_points": 0, "lines": [{"menu_item_id": 1, "quantity": 1, "notes": ""}]}
    result.update(updates)
    return result


def checkout(s, body=None, role="manager"):
    response = s.client.post("/api/orders", json=body or payload(), headers=s.headers[role])
    assert response.status_code in (200, 201), response.text
    return response.json()


def count(db, model):
    from sqlalchemy import func, select
    return db.scalar(select(func.count()).select_from(model))


def test_order_stock_points_are_committed_together(system):
    s = system
    order = checkout(s)
    assert Decimal(str(order["total"])) == Decimal("120")
    assert order["points_earned"] == 120
    with s.Session() as db:
        assert db.get(s.models.BranchStock, (1, 1)).quantity == Decimal("98")
        assert count(db, s.models.Order) == 1
        assert count(db, s.models.OrderLine) == 1
        assert count(db, s.models.StockMovement) == 1
        assert count(db, s.models.LoyaltyTransaction) == 1
    response = s.client.get("/api/loyalty/1", headers=s.headers["owner"])
    assert response.status_code == 200
    assert response.json()["balance"] == 120


def test_real_reporting_views_avoid_revenue_line_fanout(system):
    from sqlalchemy import text
    s = system
    checkout(s, payload(lines=[{"menu_item_id": 1, "quantity": 1, "notes": "one"},
                              {"menu_item_id": 1, "quantity": 1, "notes": "two"}]))
    with s.Session() as db:
        db.get(s.models.BranchStock, (1, 1)).reorder_level = 97
        db.commit()
    with s.engine.connect() as db:
        row = db.execute(text("SELECT * FROM v_completed_branch_revenue WHERE branch_id=1")).mappings().one()
        assert row["completed_orders"] == 1
        assert row["net_revenue"] == 240  # Two lines must not double-count the order total.
        empty_branch = db.execute(text("SELECT * FROM v_completed_branch_revenue WHERE branch_id=2")).mappings().one()
        assert empty_branch["completed_orders"] == empty_branch["net_revenue"] == 0
        low = db.execute(text("SELECT * FROM v_low_stock WHERE branch_id=1 AND ingredient_id=1")).mappings().one()
        assert low["quantity"] == 96
        assert low["shortfall"] == 1


def test_mariadb_rejects_invalid_stock_foreign_keys_and_negative_quantity(system):
    from sqlalchemy.exc import DBAPIError, IntegrityError
    s, m = system, system.models
    with s.Session() as db:
        db.get(m.BranchStock, (1, 1)).quantity = Decimal("-1")
        # PyMySQL reports MariaDB's CHECK error 4025 as OperationalError rather
        # than IntegrityError; require the specific server code in either case.
        with pytest.raises(DBAPIError) as check_error:
            db.flush()
        assert check_error.value.orig.args[0] == 4025, "MariaDB CHECK must reject negative stock"
        db.rollback()
        assert db.get(m.BranchStock, (1, 1)).quantity == 100
        db.add(m.BranchStock(branch_id=99999, ingredient_id=1, quantity=1, reorder_level=0))
        with pytest.raises(IntegrityError) as fk_error:
            db.flush()
        assert fk_error.value.orig.args[0] == 1452, "MariaDB FK must reject missing branch"
        db.rollback()
        assert db.get(m.BranchStock, (99999, 1)) is None


def test_injected_mongo_failure_does_not_block_real_sql_checkout(system, monkeypatch):
    from pymongo.errors import ServerSelectionTimeoutError
    import app.mongo_routes as routes
    s = system
    def unavailable():
        raise ServerSelectionTimeoutError("Explicit integration fault injection")
    monkeypatch.setattr(routes, "get_database", unavailable)
    response = s.client.get("/api/reviews", headers=s.headers["owner"])
    assert response.status_code == 503, response.text
    order = checkout(s)
    assert order["total"] == 120
    assert s.client.get("/api/loyalty/1", headers=s.headers["owner"]).json()["balance"] == 120


def test_insufficient_second_ingredient_rolls_back_all_state(system):
    s, m = system, system.models
    with s.Session() as db:
        db.add(m.RecipeComponent(menu_item_id=1, ingredient_id=2, quantity=1))
        db.get(m.BranchStock, (1, 2)).quantity = 0
        db.commit()
    response = s.client.post("/api/orders", json=payload(), headers=s.headers["manager"])
    assert response.status_code == 409, response.text
    with s.Session() as db:
        assert db.get(m.BranchStock, (1, 1)).quantity == 100
        assert db.get(m.BranchStock, (1, 2)).quantity == 0
        for model in (m.Order, m.OrderLine, m.StockMovement, m.LoyaltyTransaction):
            assert count(db, model) == 0


def test_concurrent_orders_cannot_oversell(system):
    s, m = system, system.models
    with s.Session() as db:
        db.get(m.BranchStock, (1, 1)).quantity = 2
        db.commit()
    barrier = threading.Barrier(2)
    def submit(customer_id):
        body = payload(customer_id=customer_id)
        barrier.wait(timeout=10)
        return s.client.post("/api/orders", json=body, headers=s.headers["manager"])
    with ThreadPoolExecutor(max_workers=2) as executor:
        responses = list(executor.map(submit, (1, 2)))
    assert sum(r.status_code in (200, 201) for r in responses) == 1, [r.text for r in responses]
    assert sum(r.status_code == 409 for r in responses) == 1, [r.text for r in responses]
    with s.Session() as db:
        assert db.get(m.BranchStock, (1, 1)).quantity == 0
        for model in (m.Order, m.OrderLine, m.StockMovement, m.LoyaltyTransaction):
            assert count(db, model) == 1


def test_checkout_idempotency_and_payload_mismatch(system):
    s, m = system, system.models
    body = payload()
    first, second = checkout(s, body), checkout(s, body)
    assert first["id"] == second["id"]
    altered = dict(body, lines=[{"menu_item_id": 1, "quantity": 2, "notes": ""}])
    response = s.client.post("/api/orders", json=altered, headers=s.headers["manager"])
    assert response.status_code == 409, response.text
    with s.Session() as db:
        assert count(db, m.Order) == count(db, m.StockMovement) == count(db, m.LoyaltyTransaction) == 1
        assert db.get(m.BranchStock, (1, 1)).quantity == 98


def test_concurrent_replay_creates_only_one_order(system):
    s, m = system, system.models
    body = payload()
    barrier = threading.Barrier(2)
    def submit(_):
        barrier.wait(timeout=10)
        return s.client.post("/api/orders", json=body, headers=s.headers["manager"])
    with ThreadPoolExecutor(max_workers=2) as executor:
        responses = list(executor.map(submit, range(2)))
    # A lock conflict may require the documented same-key retry; it cannot
    # create a second sale, stock movement, or award.
    resolved = []
    for response in responses:
        if response.status_code == 409:
            response = s.client.post("/api/orders", json=body, headers=s.headers["manager"])
        assert response.status_code in (200, 201), response.text
        resolved.append(response.json())
    assert resolved[0]["id"] == resolved[1]["id"]
    with s.Session() as db:
        assert db.get(m.BranchStock, (1, 1)).quantity == 98
        for model in (m.Order, m.OrderLine, m.StockMovement, m.LoyaltyTransaction):
            assert count(db, model) == 1


def test_concurrent_redemptions_cannot_double_spend(system):
    s, m = system, system.models
    checkout(s)  # 120 earned points.
    with s.Session() as db:
        db.get(m.MenuItem, 1).price = Decimal("1")
        db.commit()
    barrier = threading.Barrier(2)
    def submit(_):
        body = payload(redeem_points=100)
        barrier.wait(timeout=10)
        return s.client.post("/api/orders", json=body, headers=s.headers["manager"])
    with ThreadPoolExecutor(max_workers=2) as executor:
        responses = list(executor.map(submit, range(2)))
    assert sum(r.status_code in (200, 201) for r in responses) == 1, [r.text for r in responses]
    assert sum(r.status_code == 409 for r in responses) == 1, [r.text for r in responses]
    accepted = next(r.json() for r in responses if r.status_code in (200, 201))
    assert accepted["loyalty_balance"] == 20
    assert accepted["total"] == 0
    with s.Session() as db:
        assert count(db, m.Order) == 2
        assert count(db, m.LoyaltyTransaction) == 2  # Earn once, redeem once; no zero award.
        assert db.get(m.BranchStock, (1, 1)).quantity == 96
    assert s.client.get("/api/loyalty/1", headers=s.headers["owner"]).json()["balance"] == 20


def test_historical_price_survives_menu_update(system):
    s = system
    original = checkout(s)
    response = s.client.patch("/api/menu/1", json={"price": "15.00"}, headers=s.headers["manager"])
    assert response.status_code == 200, response.text
    old = s.client.get(f"/api/orders/{original['id']}", headers=s.headers["owner"])
    assert old.status_code == 200
    assert Decimal(str(old.json()["lines"][0]["unit_price"])) == 120
    assert Decimal(str(old.json()["total"])) == 120
    newer = checkout(s)
    assert Decimal(str(newer["lines"][0]["unit_price"])) == 15


def test_points_redemption_and_rejected_redemptions(system):
    s, m = system, system.models
    response = s.client.post("/api/orders", json=payload(redeem_points=100), headers=s.headers["manager"])
    assert response.status_code == 409, response.text  # Initial balance is zero.
    checkout(s)  # Earn 120 points.
    invalid = s.client.post("/api/orders", json=payload(redeem_points=50), headers=s.headers["manager"])
    assert invalid.status_code in (409, 422), invalid.text
    discounted = checkout(s, payload(redeem_points=100))
    assert Decimal(str(discounted["total"])) == 119
    assert discounted["points_earned"] == 119
    assert discounted["loyalty_balance"] == 139  # 120 - 100 + 119.
    response = s.client.get("/api/loyalty/1", headers=s.headers["owner"])
    assert response.json()["balance"] == 139
    with s.Session() as db:
        assert count(db, m.Order) == 2
        assert count(db, m.LoyaltyTransaction) == 3


def test_receive_stock_idempotency(system):
    s, m = system, system.models
    body = {"branch_id": 1, "ingredient_id": 1, "quantity": 3, "request_key": str(uuid4())}
    for _ in range(2):
        response = s.client.post("/api/inventory/receive", json=body, headers=s.headers["manager"])
        assert response.status_code in (200, 201), response.text
    mismatch = s.client.post("/api/inventory/receive", json=dict(body, quantity=4), headers=s.headers["manager"])
    assert mismatch.status_code == 409, mismatch.text
    with s.Session() as db:
        assert db.get(m.BranchStock, (1, 1)).quantity == 103
        assert count(db, m.StockMovement) == 1
        assert count(db, m.StockReceipt) == 1


def test_authorization_and_customer_order_ownership(system):
    s = system
    order = checkout(s)
    assert s.client.get("/api/menu").status_code == 401
    assert s.client.get(f"/api/orders/{order['id']}", headers=s.headers["other"]).status_code in (403, 404)
    assert s.client.get("/api/loyalty/1", headers=s.headers["other"]).status_code in (403, 404)
    assert s.client.get("/api/analytics/sales", headers=s.headers["owner"]).status_code == 403
    assert s.client.post("/api/orders", json=payload(), headers=s.headers["owner"]).status_code == 403
    assert s.client.post("/api/orders", json=payload(branch_id=2), headers=s.headers["cashier"]).status_code == 403
    assert s.client.post("/api/inventory/receive", json={"branch_id": 1, "ingredient_id": 1,
        "quantity": 1, "request_key": str(uuid4())}, headers=s.headers["cashier"]).status_code == 403


def test_review_ownership_unique_order_and_reply_permissions(system):
    s = system
    order = checkout(s)
    body = {"order_id": order["id"], "rating": 2, "text": "Cold food",
            "tags": [" Cold Food ", "cold food"], "category_ratings": {"food": 2}}
    denied = s.client.post("/api/reviews", json=body, headers=s.headers["other"])
    assert denied.status_code in (403, 404), denied.text
    created = s.client.post("/api/reviews", json=body, headers=s.headers["owner"])
    assert created.status_code in (200, 201), created.text
    review = created.json()
    assert review["tags"] == ["cold food"]
    assert s.client.post("/api/reviews", json=body, headers=s.headers["owner"]).status_code == 409
    path = f"/api/reviews/{review['id']}"
    assert s.client.patch(path, json={"text": "Changed"}, headers=s.headers["other"]).status_code in (403, 404)
    assert s.client.post(path + "/replies", json={"text": "Reply"}, headers=s.headers["owner"]).status_code == 403
    assert s.client.post(path + "/replies", json={"text": "Thank you"}, headers=s.headers["manager"]).status_code in (200, 201)
    feedback = s.client.get("/api/analytics/feedback?branch_id=1", headers=s.headers["manager"])
    assert feedback.status_code == 200, feedback.text
    assert feedback.json()["complaints"] == [{"tag": "cold food", "count": 1}]
    assert feedback.json()["total_reviews"] == 1
    assert s.client.get("/api/analytics/feedback", headers=s.headers["owner"]).status_code == 403


def test_mongo_database_validators_and_unique_indexes(system):
    from pymongo.errors import DuplicateKeyError, WriteError
    s = system
    order = checkout(s)
    created = s.client.post("/api/reviews", json={"order_id": order["id"], "rating": 2,
        "text": "Cold food", "tags": ["cold food"], "category_ratings": {}}, headers=s.headers["owner"])
    assert created.status_code in (200, 201), created.text
    document = s.mongo.reviews.find_one({"order_id": order["id"]})
    duplicate = {key: value for key, value in document.items() if key != "_id"}
    with pytest.raises(DuplicateKeyError):
        s.mongo.reviews.insert_one(duplicate)
    invalid = dict(duplicate, order_id=9999, rating=6)
    with pytest.raises(WriteError) as error:
        s.mongo.reviews.insert_one(invalid)
    assert error.value.code == 121, "Server schema validation must reject rating=6"
    with pytest.raises(WriteError) as extra_error:
        s.mongo.reviews.insert_one(dict(duplicate, order_id=9998, points_balance=999999))
    assert extra_error.value.code == 121, "Extra financial fields must be rejected by Mongo schema"
    options = s.mongo.reviews.options()
    assert options["validationAction"] == "error"
    assert options["validationLevel"] == "strict"
    assert "$jsonSchema" in options["validator"]
    indexes = s.mongo.reviews.index_information()
    assert indexes["one_review_per_order"]["unique"] is True
    assert indexes["branch_review_date"]["key"] == [("branch_id", 1), ("created_at", -1)]
    assert s.mongo.customer_profiles.index_information()["one_profile_per_customer"]["unique"] is True
    with pytest.raises(WriteError) as profile_error:
        s.mongo.customer_profiles.insert_one({"customer_id": 1})
    assert profile_error.value.code == 121


def test_profile_owner_and_schema_limits(system):
    s = system
    body = {"dietary_preferences": ["vegetarian"], "favourite_categories": ["meal"],
            "communication_preferences": {"email": True}, "milestones": {"first_visit": "earned"}}
    assert s.client.put("/api/profiles/1", json=body, headers=s.headers["other"]).status_code in (403, 404)
    response = s.client.put("/api/profiles/1", json=body, headers=s.headers["owner"])
    assert response.status_code == 200, response.text
    assert response.json()["customer_id"] == 1
    assert s.client.get("/api/profiles/1", headers=s.headers["other"]).status_code in (403, 404)
    oversized = dict(body, dietary_preferences=["x"] * 11)
    assert s.client.put("/api/profiles/1", json=oversized, headers=s.headers["owner"]).status_code == 422


def test_advanced_reports_execute_on_real_mariadb(system):
    """Exercise CTEs, window functions and UTC/date expressions on MariaDB."""
    from datetime import timedelta
    from app.sql_service import business_today
    s = system
    checkout(s)
    today = business_today()
    tomorrow = today + timedelta(days=1)
    paths = [
        f"/api/analytics/dashboard?branch_id=1&start={today}&end={tomorrow}",
        f"/api/analytics/forecast?branch_id=1&as_of={tomorrow}&window_days=7",
        f"/api/analytics/loyalty?branch_id=1&as_of={tomorrow}",
        f"/api/analytics/waste?branch_id=1&as_of={today}",
    ]
    reports = []
    for path in paths:
        response = s.client.get(path, headers=s.headers["manager"])
        assert response.status_code == 200, response.text
        reports.append(response.json())
        assert s.client.get(path, headers=s.headers["owner"]).status_code == 403
    assert reports[0]["summary"]["net_revenue"] == 120
    assert reports[0]["menu"][0]["rank"] == 1
    assert reports[1]["ingredients"][0]["average_daily_usage"] == pytest.approx(2 / 7, abs=0.0001)
    assert reports[2]["customers"][0]["frequency"] == 1
    assert reports[2]["customers"][1]["segment"] == "No orders"


def test_expiry_fefo_receipt_replay_and_discard_on_real_mariadb(system):
    from datetime import timedelta
    from sqlalchemy import select, text
    from app.sql_service import business_today
    s, m = system, system.models
    today = business_today()
    with s.Session() as db:
        db.get(m.BranchStock, (1, 1)).quantity = 0
        db.commit()
    def receive(key, quantity, expiry):
        body = {"branch_id": 1, "ingredient_id": 1, "quantity": quantity,
                "request_key": key, "expires_on": str(expiry), "unit_cost": "1.00"}
        response = s.client.post("/api/inventory/receive", json=body, headers=s.headers["manager"])
        assert response.status_code == 200, response.text
        return response.json(), body
    expired, _ = receive("expired-batch", 4, today - timedelta(days=1))
    later, _ = receive("later-batch", 3, today + timedelta(days=4))
    sooner, body = receive("sooner-batch", 1, today)
    replay = s.client.post("/api/inventory/receive", json=body, headers=s.headers["manager"])
    assert replay.json()["idempotent_replay"]
    available = s.client.get("/api/menu/availability?branch_id=1", headers=s.headers["cashier"]).json()
    assert available[0]["available_portions"] == 2
    order = checkout(s)
    with s.Session() as db:
        assert db.get(m.StockBatch, expired["batch_id"]).remaining_quantity == 4
        assert db.get(m.StockBatch, sooner["batch_id"]).remaining_quantity == 0
        assert db.get(m.StockBatch, later["batch_id"]).remaining_quantity == 2
        allocations = db.scalars(select(m.StockBatchAllocation).where(m.StockBatchAllocation.order_id == order["id"])).all()
        assert sum(row.quantity for row in allocations) == 2
        assert len(allocations) == 2
        assert len(db.execute(text("SELECT * FROM v_stock_batch_inventory WHERE branch_id=1")).all()) == 2
    waste = s.client.get(f"/api/analytics/waste?branch_id=1&as_of={today}", headers=s.headers["manager"]).json()
    assert waste["summary"]["expired_batches"] == 1
    assert waste["summary"]["known_value_at_risk"] == 6
    path = f"/api/inventory/batches/{expired['batch_id']}/discard"
    for _ in range(2):
        response = s.client.post(path, json={"request_key": "dispose-expired"}, headers=s.headers["manager"])
        assert response.status_code == 200, response.text
    with s.Session() as db:
        assert db.get(m.BranchStock, (1, 1)).quantity == 2
        assert count(db, m.StockBatchDiscard) == 1


def test_concurrent_orders_cannot_oversell_dated_batch(system):
    from datetime import timedelta
    from app.sql_service import business_today
    s, m = system, system.models
    with s.Session() as db:
        db.get(m.BranchStock, (1, 1)).quantity = 0
        db.commit()
    response = s.client.post("/api/inventory/receive", json={"branch_id": 1,
        "ingredient_id": 1, "quantity": 2, "expires_on": str(business_today() + timedelta(days=1)),
        "request_key": "last-dated-serving"}, headers=s.headers["manager"])
    assert response.status_code == 200, response.text
    batch_id = response.json()["batch_id"]
    barrier = threading.Barrier(2)
    def submit(customer):
        barrier.wait(timeout=10)
        return s.client.post("/api/orders", json=payload(customer_id=customer), headers=s.headers["manager"])
    with ThreadPoolExecutor(max_workers=2) as executor:
        responses = list(executor.map(submit, [1, 2]))
    assert sorted(r.status_code for r in responses) == [201, 409], [r.text for r in responses]
    with s.Session() as db:
        assert db.get(m.StockBatch, batch_id).remaining_quantity == 0
        assert db.get(m.BranchStock, (1, 1)).quantity == 0
        assert count(db, m.StockBatchAllocation) == count(db, m.Order) == 1
