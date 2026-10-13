"""Explicit mongomock unit tests. These do not prove server JSON validation.

Actual MongoDB validator/unique-index integration is tested separately.
"""
from datetime import datetime, timezone
from types import SimpleNamespace

import mongomock
import pytest
from fastapi import FastAPI
from fastapi import HTTPException
from fastapi.testclient import TestClient
from pymongo.errors import ServerSelectionTimeoutError

from app.db import get_session
from app.mongo import feedback_summary, get_database
from app.mongo_routes import get_ready_database, router
from app.security import current_user


class FakeSession:
    def __init__(self):
        self.closed = False
        self.orders = {1: SimpleNamespace(id=1, customer_id=1, branch_id=1, status="completed"),
                       2: SimpleNamespace(id=2, customer_id=2, branch_id=2, status="completed"),
                       3: SimpleNamespace(id=3, customer_id=1, branch_id=1, status="pending")}

    def get(self, model, identifier):
        if model.__name__ == "Order":
            return self.orders.get(identifier)
        return SimpleNamespace(id=identifier) if identifier in (1, 2) else None

    def close(self):
        self.closed = True


@pytest.fixture
def mongo_api():
    database = mongomock.MongoClient(tz_aware=True).hawkerflow_test
    database.reviews.create_index("order_id", unique=True)
    database.customer_profiles.create_index("customer_id", unique=True)
    user = SimpleNamespace(id=10, customer_id=1, branch_id=1, role="customer")
    session = FakeSession()
    application = FastAPI()
    application.include_router(router)
    application.dependency_overrides[current_user] = lambda: user
    application.dependency_overrides[get_ready_database] = lambda: database
    application.dependency_overrides[get_session] = lambda: session
    with TestClient(application) as client:
        yield client, database, user, session


def review_payload(**changes):
    return {"order_id": 1, "rating": 2, "text": "Rice was cold", "tags": ["Cold Food"], **changes}


def test_review_purchase_ownership_and_completed_rule(mongo_api):
    client, database, _, session = mongo_api
    assert client.post("/api/reviews", json=review_payload(order_id=2)).status_code == 403
    assert client.post("/api/reviews", json=review_payload(order_id=3)).status_code == 409
    assert client.post("/api/reviews", json=review_payload(order_id=999)).status_code == 404
    assert database.reviews.count_documents({}) == 0
    response = client.post("/api/reviews", json=review_payload())
    assert response.status_code == 201
    assert response.json()["customer_id"] == 1
    assert response.json()["branch_id"] == 1
    assert session.closed
    assert client.post("/api/reviews", json=review_payload()).status_code == 409


def test_sql_connection_closed_before_mongo_insert(mongo_api, monkeypatch):
    client, database, _, session = mongo_api
    original_insert = database.reviews.insert_one

    def guarded_insert(document):
        assert session.closed, "No SQL connection may span a MongoDB write"
        return original_insert(document)

    monkeypatch.setattr(database.reviews, "insert_one", guarded_insert)
    assert client.post("/api/reviews", json=review_payload()).status_code == 201


@pytest.mark.parametrize("changes", [
    {"rating": 0}, {"rating": 6}, {"rating": True}, {"text": "   "},
    {"tags": ["x" * 41]}, {"tags": ["tag"] * 11},
    {"category_ratings": {"food": True}}, {"category_ratings": {"food": 9}},
    {"category_ratings": {"unknown": 1}}, {"customer_id": 999}, {"replies": []},
])
def test_review_invalid_input_and_identity_override_rejected(mongo_api, changes):
    client, database, *_ = mongo_api
    assert client.post("/api/reviews", json=review_payload(**changes)).status_code == 422
    assert database.reviews.count_documents({}) == 0


def test_review_crud_normalizes_tags_and_enforces_owner(mongo_api):
    client, database, user, _ = mongo_api
    created = client.post("/api/reviews", json=review_payload(tags=[" Cold  Food ", "cold food", "Slow Service"]))
    identifier = created.json()["id"]
    assert created.json()["tags"] == ["cold food", "slow service"]
    assert client.patch(f"/api/reviews/{identifier}", json={"rating": None}).status_code == 422
    assert client.patch(f"/api/reviews/{identifier}", json={"moderation_status": "hidden"}).status_code == 403
    assert client.patch(f"/api/reviews/{identifier}", json={"rating": 3}).json()["rating"] == 3
    user.customer_id = 2
    assert client.patch(f"/api/reviews/{identifier}", json={"rating": 1}).status_code == 403
    assert client.delete(f"/api/reviews/{identifier}").status_code == 403
    user.customer_id = 1
    assert client.delete(f"/api/reviews/{identifier}").status_code == 200
    assert database.reviews.count_documents({}) == 0


def test_manager_reply_limit_and_moderation(mongo_api):
    client, _, user, _ = mongo_api
    identifier = client.post("/api/reviews", json=review_payload()).json()["id"]
    assert client.post(f"/api/reviews/{identifier}/replies", json={"text": "Thank you"}).status_code == 403
    user.role = "manager"
    for _ in range(20):
        assert client.post(f"/api/reviews/{identifier}/replies", json={"text": "Thank you"}).status_code == 201
    assert client.post(f"/api/reviews/{identifier}/replies", json={"text": "Thank you"}).status_code == 409
    assert client.patch(f"/api/reviews/{identifier}", json={"moderation_status": "hidden"}).status_code == 200
    assert len(client.get("/api/reviews").json()) == 1
    user.role = "customer"
    assert client.get("/api/reviews").json() == []


def test_profile_ownership_validation_and_no_point_balance(mongo_api):
    client, _, user, session = mongo_api
    payload = {"dietary_preferences": [" Halal ", "halal"], "favourite_categories": ["Rice"],
               "communication_preferences": {"email": True}, "milestones": {"first_review": "earned"}}
    saved = client.put("/api/profiles/1", json=payload)
    assert saved.status_code == 200
    assert saved.json()["dietary_preferences"] == ["halal"]
    assert saved.json()["communication_preferences"] == {"email": True}
    assert session.closed
    assert client.get("/api/profiles/1").status_code == 200
    assert client.put("/api/profiles/1", json={**payload, "points_balance": 100}).status_code == 422
    assert client.put("/api/profiles/2", json=payload).status_code == 403
    user.role = "manager"
    assert client.put("/api/profiles/999", json=payload).status_code == 404


def test_feedback_aggregation_counts_distinct_negative_low_rating_mentions(mongo_api):
    client, database, user, _ = mongo_api
    when = datetime(2026, 9, 1, tzinfo=timezone.utc)
    for identifier, branch, rating, tags, status in [
        (10, 1, 1, ["cold food", "cold food", "fast service"], "published"),
        (11, 1, 2, ["cold food", "slow service"], "published"),
        (12, 1, 5, ["cold food"], "published"),
        (13, 2, 1, ["slow service"], "published"),
        (14, 1, 1, ["slow service"], "hidden"),
    ]:
        database.reviews.insert_one({"order_id": identifier, "branch_id": branch, "rating": rating,
                                    "tags": tags, "moderation_status": status, "created_at": when})
    result = feedback_summary(database, branch_id=1)
    assert result["complaints"] == [{"count": 2, "tag": "cold food"}, {"count": 1, "tag": "slow service"}]
    assert result["total_reviews"] == 3
    assert result["rating_trends"][0]["count"] == 3
    assert result["rating_trends"][0]["average"] == pytest.approx(8 / 3)
    assert feedback_summary(database, branch_id=1, end=when)["total_reviews"] == 0
    assert client.get("/api/analytics/feedback").status_code == 403
    user.role = "manager"
    assert client.get("/api/analytics/feedback?branch_id=1").json()["total_reviews"] == 3
    assert client.get("/api/analytics/feedback?start=2026-09-02&end=2026-09-01").status_code == 422


def test_unavailable_mongo_returns_503_without_secret_details(mongo_api, monkeypatch):
    client, database, *_ = mongo_api

    def unavailable(*args, **kwargs):
        raise ServerSelectionTimeoutError("mongodb://private-user:secret@internal-host")

    monkeypatch.setattr(database.reviews, "find", unavailable)
    response = client.get("/api/reviews")
    assert response.status_code == 503
    assert "secret" not in response.text


def test_malformed_review_identifier(mongo_api):
    client, *_ = mongo_api
    assert client.patch("/api/reviews/not-an-id", json={"rating": 2}).status_code == 422


def test_external_sentence_analytics_separate_from_purchase_reviews(mongo_api):
    client, database, user, _ = mongo_api
    for identifier in range(14):
        database.external_review_examples.insert_one({"source_record_id": identifier,
            "text": f"Original sample sentence {identifier}", "sentiment": identifier % 2,
            "source": "uci_yelp"})
    assert client.get("/api/analytics/external-feedback").status_code == 403
    user.role = "manager"
    result = client.get("/api/analytics/external-feedback").json()
    assert result["total"] == 14
    assert result["positive"] == result["negative"] == 7
    assert len(result["examples"]) == 10
    assert "not local" in result["limitation"]
    assert database.reviews.count_documents({}) == 0


def test_schema_readiness_retries_after_offline_without_unvalidated_writes(monkeypatch):
    import app.mongo as mongo_module

    class FakeCollection:
        def create_index(self, *args, **kwargs):
            return kwargs.get("name", "index")

    class FakeDatabase:
        offline = True
        validators = {}
        reviews = FakeCollection()
        customer_profiles = FakeCollection()
        external_review_examples = FakeCollection()

        def command(self, *args, **kwargs):
            if self.offline:
                raise ServerSelectionTimeoutError("offline")
            return {"ok": 1}

        def list_collection_names(self):
            return []

        def create_collection(self, name, **kwargs):
            self.validators[name] = kwargs["validator"]

    database = FakeDatabase()

    class FakeClient:
        def __getitem__(self, _):
            return database

    client = FakeClient()
    monkeypatch.setattr(mongo_module, "get_client", lambda: client)
    monkeypatch.setattr(mongo_module, "_ready_client", None)
    monkeypatch.setattr(mongo_module, "_ready_database_name", None)
    with pytest.raises(HTTPException) as error:
        get_ready_database()
    assert error.value.status_code == 503
    assert mongo_module._ready_client is None
    assert database.validators == {}
    database.offline = False
    assert get_ready_database() is database
    assert mongo_module._ready_client is client
    assert set(database.validators) == {"reviews", "customer_profiles", "external_review_examples"}
    assert database.validators["reviews"]["$jsonSchema"]["additionalProperties"] is False
