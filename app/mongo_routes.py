"""Purchase-linked review and profile API with explicit cross-store ownership checks."""
from contextlib import contextmanager
from datetime import date, datetime, time, timezone
from typing import Literal

from bson import ObjectId
from bson.errors import InvalidId
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, ConfigDict, Field, field_validator
from pymongo.errors import DuplicateKeyError, PyMongoError
from sqlalchemy.orm import Session

from app.db import get_session
from app.models import Customer, Order
from app.security import current_user, require_roles
from app.mongo import (CATEGORY_KEYS, MAX_REPLIES, feedback_summary, get_database,
                       serialize_document, utcnow)

router = APIRouter(prefix="/api", tags=["feedback and profiles"])


def normalize_list(values):
    if not isinstance(values, list):
        raise ValueError("Expected an array of strings")
    if len(values) > 10:
        raise ValueError("At most 10 entries are allowed")
    normalized = []
    for value in values:
        if not isinstance(value, str):
            raise ValueError("Entries must be strings")
        value = " ".join(value.strip().lower().split())
        if not 1 <= len(value) <= 40:
            raise ValueError("Entries must contain 1–40 characters")
        if value not in normalized:
            normalized.append(value)
    return normalized


class StrictBody(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ReviewInput(StrictBody):
    order_id: int = Field(gt=0, strict=True)
    rating: int = Field(ge=1, le=5, strict=True)
    text: str = Field(min_length=1, max_length=2000)
    tags: list[str] = Field(default_factory=list, max_length=10)
    category_ratings: dict[str, int] = Field(default_factory=dict)

    @field_validator("text", mode="before")
    @classmethod
    def trim_text(cls, value):
        if not isinstance(value, str) or not value.strip():
            raise ValueError("Text must not be blank")
        return value.strip()

    @field_validator("tags", mode="before")
    @classmethod
    def normalize_tags(cls, value):
        return normalize_list(value)

    @field_validator("category_ratings", mode="before")
    @classmethod
    def validate_categories(cls, value):
        if not isinstance(value, dict) or any(key not in CATEGORY_KEYS for key in value):
            raise ValueError(f"Category ratings support: {', '.join(CATEGORY_KEYS)}")
        if any(type(rating) is not int or not 1 <= rating <= 5 for rating in value.values()):
            raise ValueError("Category ratings must be integers from 1 to 5")
        return value


class ReviewPatch(StrictBody):
    rating: int | None = Field(default=None, ge=1, le=5, strict=True)
    text: str | None = Field(default=None, min_length=1, max_length=2000)
    tags: list[str] | None = Field(default=None, max_length=10)
    category_ratings: dict[str, int] | None = None
    moderation_status: Literal["published", "hidden"] | None = None

    @field_validator("rating", "text", "tags", "category_ratings", "moderation_status", mode="before")
    @classmethod
    def no_explicit_null(cls, value):
        if value is None:
            raise ValueError("Omit unchanged fields; null is not supported")
        return value

    @field_validator("text", mode="before")
    @classmethod
    def trim_text(cls, value):
        return ReviewInput.trim_text(value)

    @field_validator("tags", mode="before")
    @classmethod
    def normalize_tags(cls, value):
        return normalize_list(value)

    @field_validator("category_ratings", mode="before")
    @classmethod
    def validate_categories(cls, value):
        return ReviewInput.validate_categories(value)


class ReplyInput(StrictBody):
    text: str = Field(min_length=1, max_length=1000)

    @field_validator("text", mode="before")
    @classmethod
    def trim_text(cls, value):
        return ReviewInput.trim_text(value)


class CommunicationPreferences(StrictBody):
    email: bool | None = Field(default=None, strict=True)
    sms: bool | None = Field(default=None, strict=True)
    push: bool | None = Field(default=None, strict=True)

    @field_validator("email", "sms", "push", mode="before")
    @classmethod
    def no_null(cls, value):
        if value is None:
            raise ValueError("Use true or false, or omit the preference")
        return value


class ProfileInput(StrictBody):
    dietary_preferences: list[str] = Field(default_factory=list, max_length=10)
    favourite_categories: list[str] = Field(default_factory=list, max_length=10)
    communication_preferences: CommunicationPreferences = Field(default_factory=CommunicationPreferences)
    milestones: dict[str, str] = Field(default_factory=dict)

    @field_validator("dietary_preferences", "favourite_categories", mode="before")
    @classmethod
    def normalize_preferences(cls, value):
        return normalize_list(value)

    @field_validator("milestones", mode="before")
    @classmethod
    def validate_milestones(cls, value):
        if not isinstance(value, dict) or len(value) > 20:
            raise ValueError("At most 20 milestone labels are supported")
        for key, label in value.items():
            if (not isinstance(key, str) or not 1 <= len(key) <= 40 or
                    not key.replace("_", "").isalnum() or
                    not isinstance(label, str) or len(label) > 100):
                raise ValueError("Milestones need short alphanumeric keys and text labels")
        return value


@contextmanager
def mongo_errors():
    try:
        yield
    except DuplicateKeyError as error:
        raise HTTPException(409, "A review already exists for this order") from error
    except PyMongoError as error:
        raise HTTPException(503, "Feedback database unavailable; please retry later") from error


def get_ready_database():
    """Retry schema initialization after an offline startup before accepting writes."""
    with mongo_errors():
        return get_database()


def object_id(value):
    try:
        return ObjectId(value)
    except (InvalidId, TypeError) as error:
        raise HTTPException(422, "Invalid document identifier") from error


def require_owner_or_manager(user, customer_id):
    if user.role != "manager" and (user.role != "customer" or user.customer_id != customer_id):
        raise HTTPException(403, "Only the customer owner or a manager can change this record")


def find_owned_review(database, identifier, user):
    review = database.reviews.find_one({"_id": object_id(identifier)})
    if not review:
        raise HTTPException(404, "Review not found")
    require_owner_or_manager(user, review["customer_id"])
    return review


def validate_review_order(session, user, order_id):
    """Return detached identifiers; SQL connection closes before Mongo writes."""
    order = session.get(Order, order_id)
    if not order:
        raise HTTPException(404, "Order not found")
    require_owner_or_manager(user, order.customer_id)
    if order.status != "completed":
        raise HTTPException(409, "Only completed orders can be reviewed")
    result = {"order_id": order.id, "customer_id": order.customer_id, "branch_id": order.branch_id}
    session.close()
    return result


@router.get("/reviews")
def list_reviews(branch_id: int | None = Query(default=None, gt=0),
                 limit: int = Query(default=100, ge=1, le=200),
                 user=Depends(current_user), database=Depends(get_ready_database)):
    query = {} if user.role == "manager" else {"moderation_status": "published"}
    if branch_id is not None:
        query["branch_id"] = branch_id
    with mongo_errors():
        return [serialize_document(doc) for doc in database.reviews.find(query)
                .sort([("created_at", -1), ("_id", -1)]).limit(limit)]


@router.post("/reviews", status_code=201)
def create_review(payload: ReviewInput, user=Depends(current_user),
                  session: Session = Depends(get_session), database=Depends(get_ready_database)):
    ids = validate_review_order(session, user, payload.order_id)
    now = utcnow()
    document = {**ids, **payload.model_dump(), "replies": [], "moderation_status": "published",
                "created_at": now, "updated_at": now}
    with mongo_errors():
        inserted = database.reviews.insert_one(document)
        document["_id"] = inserted.inserted_id
    return serialize_document(document)


@router.patch("/reviews/{identifier}")
def update_review(identifier: str, payload: ReviewPatch, user=Depends(current_user),
                  database=Depends(get_ready_database)):
    changes = payload.model_dump(exclude_unset=True)
    if not changes:
        raise HTTPException(422, "Provide at least one field to update")
    if "moderation_status" in changes and user.role != "manager":
        raise HTTPException(403, "Only managers may moderate reviews")
    with mongo_errors():
        review = find_owned_review(database, identifier, user)
        changes["updated_at"] = utcnow()
        updated = database.reviews.update_one({"_id": review["_id"]}, {"$set": changes})
        if not updated.matched_count:
            raise HTTPException(404, "Review no longer exists")
        return serialize_document(database.reviews.find_one({"_id": review["_id"]}))


@router.delete("/reviews/{identifier}")
def delete_review(identifier: str, user=Depends(current_user), database=Depends(get_ready_database)):
    with mongo_errors():
        review = find_owned_review(database, identifier, user)
        deleted = database.reviews.delete_one({"_id": review["_id"]})
        if not deleted.deleted_count:
            raise HTTPException(404, "Review no longer exists")
    return {"deleted": True}


@router.post("/reviews/{identifier}/replies", status_code=201)
def reply_review(identifier: str, payload: ReplyInput,
                 user=Depends(require_roles("manager")), database=Depends(get_ready_database)):
    oid = object_id(identifier)
    now = utcnow()
    reply = {"author_user_id": user.id, "text": payload.text, "created_at": now}
    with mongo_errors():
        result = database.reviews.update_one(
            {"_id": oid, f"replies.{MAX_REPLIES - 1}": {"$exists": False}},
            {"$push": {"replies": reply}, "$set": {"updated_at": now}})
        if not result.matched_count:
            if not database.reviews.find_one({"_id": oid}, {"_id": 1}):
                raise HTTPException(404, "Review not found")
            raise HTTPException(409, "Reply limit reached (20 per review)")
        return serialize_document(database.reviews.find_one({"_id": oid}))


@router.get("/profiles/{customer_id}")
def get_profile(customer_id: int, user=Depends(current_user), database=Depends(get_ready_database)):
    require_owner_or_manager(user, customer_id)
    with mongo_errors():
        document = database.customer_profiles.find_one({"customer_id": customer_id})
    if not document:
        raise HTTPException(404, "Profile not found; save preferences to create it")
    return serialize_document(document)


@router.put("/profiles/{customer_id}")
def put_profile(customer_id: int, payload: ProfileInput, user=Depends(current_user),
                session: Session = Depends(get_session), database=Depends(get_ready_database)):
    require_owner_or_manager(user, customer_id)
    if not session.get(Customer, customer_id):
        raise HTTPException(404, "Customer not found")
    session.close()
    document = {"customer_id": customer_id, **payload.model_dump(), "updated_at": utcnow()}
    document["communication_preferences"] = payload.communication_preferences.model_dump(exclude_unset=True)
    with mongo_errors():
        database.customer_profiles.update_one({"customer_id": customer_id}, {"$set": document}, upsert=True)
        return serialize_document(database.customer_profiles.find_one({"customer_id": customer_id}))


@router.get("/analytics/feedback")
def feedback_analytics(branch_id: int | None = Query(default=None, gt=0),
                       start: date | None = None, end: date | None = None,
                       user=Depends(require_roles("manager")), database=Depends(get_ready_database)):
    if start and end and end <= start:
        raise HTTPException(422, "End date must be later than start date (end-exclusive)")
    start_at = datetime.combine(start, time.min, tzinfo=timezone.utc) if start else None
    end_at = datetime.combine(end, time.min, tzinfo=timezone.utc) if end else None
    with mongo_errors():
        return feedback_summary(database, branch_id, start_at, end_at)


@router.get("/analytics/external-feedback")
def external_feedback(user=Depends(require_roles("manager")), database=Depends(get_ready_database)):
    """Summarize source-labelled sentences, never pretend these are local orders."""
    with mongo_errors():
        collection = database.external_review_examples
        counts = {row["_id"]: row["count"] for row in collection.aggregate([
            {"$match": {"source": "uci_yelp"}},
            {"$group": {"_id": "$sentiment", "count": {"$sum": 1}}},
        ], maxTimeMS=5000)}
        examples = []
        for sentiment in (0, 1):
            for row in collection.find({"source": "uci_yelp", "sentiment": sentiment})\
                    .sort("source_record_id", 1).limit(5):
                examples.append({"id": row["source_record_id"], "text": row["text"],
                                 "sentiment": row["sentiment"]})
    return {"source": "UCI Yelp sentence sample", "total": sum(counts.values()),
            "positive": counts.get(1, 0), "negative": counts.get(0, 0), "examples": examples,
            "limitation": "Sentence sentiment labels are benchmark data, not local customer satisfaction or star ratings."}
