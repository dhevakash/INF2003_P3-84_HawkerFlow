#!/usr/bin/env python3
"""Create reproducible teaching fixtures without resetting application records.

Real data: NEA centre names and historical addresses only.
Synthetic data: fictional branches, menu, recipes, people, stock, sales,
points, reviews and preferences. Operational orders use real checkout logic.
"""
import argparse
import hashlib
import json
import random
import sys
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
SEED = 20261002
PASSWORD = "DemoPass123!"
SEED_PREFIX = "hawkerflow-demo-v1-"
BASE_DATE = datetime(2026, 8, 25, 9, 0)


def load_inputs():
    manifest = json.loads((ROOT / "data/source_manifest.json").read_text())
    for filename, attributes in manifest["files"].items():
        content = (ROOT / "data" / filename).read_bytes()
        if hashlib.sha256(content).hexdigest() != attributes["sha256"]:
            raise RuntimeError(f"Source checksum mismatch: {filename}. Refresh with fetch_locations.py.")
    return (json.loads((ROOT / "data/demo_branches.json").read_text()),
            json.loads((ROOT / "data/menu_recipes.json").read_text()))


def seed_sql(order_count=200):
    from sqlalchemy import func, select, update
    from app.db import SessionLocal, init_db
    from app.models import (Branch, BranchStock, Customer, Ingredient, LoyaltyTransaction,
                            MenuItem, Order, RecipeComponent, StockMovement, User)
    from app.security import hash_password
    from app.sql_service import checkout

    branch_input, catalogue = load_inputs()
    init_db()
    rng = random.Random(SEED)
    with SessionLocal() as session:
        # Stable fixture IDs make cross-store associations reproducible. Existing
        # fixtures are preserved; incompatible occupied IDs fail instead of overwrite.
        def ensure(model, identity, values, distinguishing):
            existing = session.get(model, identity)
            if existing:
                if any(getattr(existing, field) != values[field] for field in distinguishing):
                    raise RuntimeError(f"Seed fixture ID collision in {model.__tablename__}: {identity}")
                return existing
            row = model(**values)
            session.add(row)
            session.flush()
            return row

        for branch in branch_input:
            values = {key: branch[key] for key in ("id", "name", "address", "postal_code")}
            ensure(Branch, branch["id"], values, ["name"])
        for customer_id in range(1, 51):
            values = {"id": customer_id, "name": f"Demo Customer {customer_id:02d}",
                      "email": f"customer{customer_id}@hawkerflow.local"}
            ensure(Customer, customer_id, values, ["email"])
        for ingredient in catalogue["ingredients"]:
            ensure(Ingredient, ingredient["id"], ingredient, ["name", "unit"])
        for item in catalogue["menu_items"]:
            values = {key: item[key] for key in ("id", "name", "category")}
            values.update(price=Decimal(item["price"]), is_active=True)
            ensure(MenuItem, item["id"], values, ["name"])
            for ingredient_id, quantity in item["recipe"].items():
                key = (item["id"], int(ingredient_id))
                if session.get(RecipeComponent, key) is None:
                    session.add(RecipeComponent(menu_item_id=key[0], ingredient_id=key[1], quantity=Decimal(quantity)))
        for branch in branch_input:
            for ingredient in catalogue["ingredients"]:
                key = (branch["id"], ingredient["id"])
                if session.get(BranchStock, key) is None:
                    initial = Decimal("1000" if ingredient["unit"] == "each" else "100000")
                    reorder = Decimal("900" if ingredient["unit"] == "each" else "10000")
                    if ingredient["id"] == 1:
                        initial, reorder = Decimal("40000"), Decimal("35000")
                    if ingredient["id"] in (8, 9):
                        initial, reorder = Decimal("5000"), Decimal("4500")
                    session.add(BranchStock(branch_id=key[0], ingredient_id=key[1], quantity=initial, reorder_level=reorder))
                    session.add(StockMovement(branch_id=key[0], ingredient_id=key[1], quantity_delta=initial,
                                              reason="seed_opening", created_at=BASE_DATE - timedelta(days=1)))
        for email, role, name, customer_id, branch_id in (
                ("manager@hawkerflow.local", "manager", "Demo Manager", None, None),
                ("cashier@hawkerflow.local", "cashier", "Demo Cashier", None, 1),
                ("customer1@hawkerflow.local", "customer", "Demo Customer 01", 1, None)):
            if session.scalar(select(User).where(User.email == email)) is None:
                session.add(User(email=email, name=name, password_hash=hash_password(PASSWORD),
                                 role=role, customer_id=customer_id, branch_id=branch_id, is_active=True))
        session.commit()
        created = 0
        seed_orders = []
        for index in range(order_count):
            # Random draws happen even for an existing order, preserving later fixtures.
            item_ids = rng.sample(range(1, 21), rng.randint(1, 3))
            lines = [{"menu_item_id": item_id, "quantity": rng.randint(1, 3), "notes": ""} for item_id in item_ids]
            if index == 0:
                lines = [{"menu_item_id": 1, "quantity": 2, "notes": ""},
                         {"menu_item_id": 19, "quantity": 2, "notes": ""}]
            payload = {"branch_id": 1 if index == 0 else index % 5 + 1,
                       "customer_id": 1 if index < 15 else (index - 15) % 50 + 1,
                       "request_key": SEED_PREFIX + f"order-{index:04d}",
                       "redeem_points": 0, "lines": lines}
            existing = session.scalar(select(Order).where(Order.request_key == payload["request_key"]))
            session.rollback()  # checkout owns a fresh transaction
            if existing is None:
                result = checkout(session, payload)
                order = session.get(Order, result["id"])
                historical = BASE_DATE + timedelta(hours=index * 4)
                order.created_at = historical
                session.execute(update(StockMovement).where(StockMovement.order_id == order.id).values(created_at=historical))
                session.execute(update(LoyaltyTransaction).where(LoyaltyTransaction.order_id == order.id).values(created_at=historical))
                session.commit()
                created += 1
            else:
                order = session.get(Order, existing.id)
            seed_orders.append({"id": order.id, "customer_id": order.customer_id,
                                "branch_id": order.branch_id, "created_at": order.created_at,
                                "status": order.status})
        users = {user.email: user.id for user in session.scalars(select(User))}
        counts = {model.__tablename__: session.scalar(select(func.count()).select_from(model))
                  for model in (Branch, Customer, MenuItem, Ingredient, RecipeComponent, BranchStock,
                                StockMovement, Order, LoyaltyTransaction, User)}
        return seed_orders, users, {"created_orders_this_run": created, "sql_row_counts": counts}


def seed_mongo(seed_orders, users, review_count=100):
    from app.mongo import initialize_mongo, NEGATIVE_TAGS
    database = initialize_mongo()
    rng = random.Random(SEED + 1)
    negatives = sorted(NEGATIVE_TAGS)
    positive = ["fast service", "great value", "friendly staff", "fresh food", "good portion"]
    created = 0
    manager_id = users["manager@hawkerflow.local"]
    for index, order in enumerate(seed_orders[:review_count]):
        if order["status"] != "completed":
            raise RuntimeError("Review fixture is not linked to a completed SQL order")
        rating = rng.choices([1, 2, 3, 4, 5], weights=[8, 12, 15, 30, 35])[0]
        tags = rng.sample(negatives if rating <= 2 else positive, rng.randint(1, 3))
        timestamp = order["created_at"].replace(tzinfo=timezone.utc) + timedelta(hours=2)
        replies = []
        if index % 8 == 0:
            replies.append({"author_user_id": manager_id,
                            "text": "Thank you for your feedback. Our demo team will follow up.",
                            "created_at": timestamp + timedelta(hours=1)})
        document = {"order_id": order["id"], "customer_id": order["customer_id"],
                    "branch_id": order["branch_id"], "rating": rating,
                    "text": "Synthetic teaching review: " + ", ".join(tags) + ".",
                    "tags": sorted(set(tags)), "category_ratings": {"food": rating, "service": max(1, rating - 1)} if index % 3 == 0 else {},
                    "replies": replies, "moderation_status": "published",
                    "created_at": timestamp, "updated_at": timestamp + timedelta(hours=1) if replies else timestamp}
        result = database.reviews.update_one({"order_id": order["id"]}, {"$setOnInsert": document}, upsert=True)
        created += result.upserted_id is not None
    for customer_id in range(1, 51):
        first_visit = min(order["created_at"] for order in seed_orders if order["customer_id"] == customer_id)
        document = {"customer_id": customer_id,
                    "dietary_preferences": ["less spicy"] if customer_id % 3 == 0 else [],
                    "favourite_categories": ["Rice"] if customer_id % 2 else ["Noodles", "Drinks"],
                    "communication_preferences": {"email": True, "sms": False},
                    "milestones": {"first_visit": first_visit.date().isoformat()} if customer_id % 2 else {},
                    "updated_at": first_visit.replace(tzinfo=timezone.utc)}
        database.customer_profiles.update_one({"customer_id": customer_id}, {"$setOnInsert": document}, upsert=True)
    manifest = json.loads((ROOT / "data/review_source_manifest.json").read_text())
    filename = "external_review_examples.json"
    content = (ROOT / "data" / filename).read_bytes()
    if hashlib.sha256(content).hexdigest() != manifest["files"][filename]["sha256"]:
        raise RuntimeError("External review snapshot checksum mismatch")
    for document in json.loads(content):
        database.external_review_examples.update_one({"source_record_id": document["source_record_id"]},
                                                     {"$setOnInsert": document}, upsert=True)
    return {"created_reviews_this_run": int(created),
            "mongo_document_counts": {name: database[name].count_documents({})
                                       for name in ("reviews", "customer_profiles", "external_review_examples")}}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--orders", type=int, default=200)
    parser.add_argument("--reviews", type=int, default=100)
    parser.add_argument("--sql-only", action="store_true", help="Explicitly seed SQL only; never claims Mongo data loaded")
    args = parser.parse_args()
    if not 100 <= args.orders <= 200 or not 0 <= args.reviews <= args.orders:
        parser.error("Teaching fixture supports 100–200 orders and 0–order-count reviews")
    if not args.sql_only:
        from app.mongo import initialize_mongo
        initialize_mongo()  # fail before SQL mutation when the second store is unavailable
    orders, users, result = seed_sql(args.orders)
    if not args.sql_only:
        result.update(seed_mongo(orders, users, args.reviews))
    result.update(seed=SEED, generated_at_utc=datetime.now(timezone.utc).isoformat(),
                  real_fields=["source centre name", "historical address", "postal code extracted from address"],
                  synthetic_fields="All fictional branch affiliations and operational records, reviews and preferences",
                  seed_order_prefix=SEED_PREFIX, sql_only=args.sql_only)
    (ROOT / "data/seed_run_manifest.json").write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
