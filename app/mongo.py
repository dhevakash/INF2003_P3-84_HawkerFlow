"""MongoDB connection, database-enforced schemas, and feedback analytics.

Runtime always uses a real MongoDB server. Tests inject mongomock explicitly.
"""
from datetime import datetime, timezone
from functools import lru_cache
from threading import RLock

from pymongo import ASCENDING, DESCENDING, MongoClient

from app.config import settings

NEGATIVE_TAGS = frozenset({
    "slow service", "cold food", "too spicy", "poor service", "wrong order",
    "small portion", "too expensive", "unclean", "long wait", "missing item",
})
CATEGORY_KEYS = ("food", "service", "value", "cleanliness", "ambience", "speed")
MAX_REPLIES = 20
_schema_lock = RLock()
_ready_client = None
_ready_database_name = None
_positive_id = {"bsonType": ["int", "long"], "minimum": 1}
_rating = {"bsonType": ["int", "long"], "minimum": 1, "maximum": 5}

REVIEW_SCHEMA = {
    "bsonType": "object",
    "required": ["order_id", "customer_id", "branch_id", "rating", "text", "tags",
                 "category_ratings", "replies", "moderation_status", "created_at", "updated_at"],
    "additionalProperties": False,
    "properties": {
        "_id": {"bsonType": "objectId"},
        "order_id": _positive_id, "customer_id": _positive_id, "branch_id": _positive_id,
        "rating": _rating,
        "text": {"bsonType": "string", "minLength": 1, "maxLength": 2000},
        "tags": {"bsonType": "array", "maxItems": 10, "uniqueItems": True,
                 "items": {"bsonType": "string", "minLength": 1, "maxLength": 40}},
        "category_ratings": {"bsonType": "object", "additionalProperties": False,
                             "properties": {key: _rating for key in CATEGORY_KEYS}},
        "moderation_status": {"enum": ["published", "hidden"]},
        "replies": {"bsonType": "array", "maxItems": MAX_REPLIES, "items": {
            "bsonType": "object", "required": ["author_user_id", "text", "created_at"],
            "additionalProperties": False, "properties": {
                "author_user_id": _positive_id,
                "text": {"bsonType": "string", "minLength": 1, "maxLength": 1000},
                "created_at": {"bsonType": "date"},
            }}},
        "created_at": {"bsonType": "date"}, "updated_at": {"bsonType": "date"},
    },
}
PROFILE_SCHEMA = {
    "bsonType": "object", "additionalProperties": False,
    "required": ["customer_id", "dietary_preferences", "favourite_categories",
                 "communication_preferences", "milestones", "updated_at"],
    "properties": {
        "_id": {"bsonType": "objectId"}, "customer_id": _positive_id,
        "dietary_preferences": {"bsonType": "array", "maxItems": 10, "uniqueItems": True,
            "items": {"bsonType": "string", "minLength": 1, "maxLength": 40}},
        "favourite_categories": {"bsonType": "array", "maxItems": 10, "uniqueItems": True,
            "items": {"bsonType": "string", "minLength": 1, "maxLength": 40}},
        "communication_preferences": {"bsonType": "object", "additionalProperties": False,
            "properties": {key: {"bsonType": "bool"} for key in ("email", "sms", "push")}},
        "milestones": {"bsonType": "object", "maxProperties": 20,
            "additionalProperties": {"bsonType": "string", "maxLength": 100}},
        "updated_at": {"bsonType": "date"},
    },
}
EXTERNAL_REVIEW_SCHEMA = {
    "bsonType": "object", "additionalProperties": False,
    "required": ["source_record_id", "text", "sentiment", "source"],
    "properties": {
        "_id": {"bsonType": "objectId"},
        "source_record_id": {"bsonType": ["int", "long"], "minimum": 0},
        "text": {"bsonType": "string", "minLength": 1, "maxLength": 2000},
        "sentiment": {"bsonType": ["int", "long"], "enum": [0, 1]},
        "source": {"enum": ["uci_yelp"]},
    },
}


@lru_cache(maxsize=1)
def get_client():
    return MongoClient(settings.mongo_url, serverSelectionTimeoutMS=2500,
                       connectTimeoutMS=2500, socketTimeoutMS=5000, tz_aware=True)


def get_database():
    client = get_client()
    if _ready_client is not client or _ready_database_name != settings.mongo_database:
        initialize_mongo()
    return client[settings.mongo_database]


def initialize_mongo():
    """Fail visibly if server/permissions are unavailable; never substitute a mock."""
    with _schema_lock:
        return _initialize_mongo_unlocked()


def _initialize_mongo_unlocked():
    global _ready_client, _ready_database_name
    client = get_client()
    _ready_client = None
    _ready_database_name = None
    database = client[settings.mongo_database]
    database.command("ping")
    existing = set(database.list_collection_names())
    for name, schema in (("reviews", REVIEW_SCHEMA), ("customer_profiles", PROFILE_SCHEMA),
                         ("external_review_examples", EXTERNAL_REVIEW_SCHEMA)):
        validator = {"$jsonSchema": schema}
        if name in existing:
            database.command("collMod", name, validator=validator,
                             validationLevel="strict", validationAction="error")
        else:
            database.create_collection(name, validator=validator,
                                       validationLevel="strict", validationAction="error")
    database.reviews.create_index("order_id", unique=True, name="one_review_per_order")
    database.reviews.create_index([("branch_id", ASCENDING), ("created_at", DESCENDING)],
                                 name="branch_review_date")
    database.reviews.create_index([("customer_id", ASCENDING), ("created_at", DESCENDING)],
                                 name="customer_review_date")
    database.reviews.create_index("tags", name="review_tags")
    database.customer_profiles.create_index("customer_id", unique=True,
                                            name="one_profile_per_customer")
    database.external_review_examples.create_index("source_record_id", unique=True,
                                                   name="external_source_record")
    database.external_review_examples.create_index("sentiment", name="external_sentiment")
    # Mark readiness only after every validator and unique index succeeded.
    _ready_client = client
    _ready_database_name = settings.mongo_database
    return database


def utcnow():
    return datetime.now(timezone.utc)


def serialize_document(document):
    if document is None:
        return None
    document = dict(document)
    document["id"] = str(document.pop("_id"))
    return document


def feedback_pipeline(branch_id=None, start=None, end=None):
    """Count reviews mentioning each negative tag, not tag repetitions.

    Low-rated means rating <= 2. Date interval is start-inclusive/end-exclusive.
    "$setUnion" makes even legacy repeated tags count once per review.
    """
    match = {"moderation_status": "published"}
    if branch_id is not None:
        match["branch_id"] = branch_id
    if start is not None or end is not None:
        match["created_at"] = {}
        if start is not None:
            match["created_at"]["$gte"] = start
        if end is not None:
            match["created_at"]["$lt"] = end
    return [
        {"$match": match},
        {"$facet": {
            "complaints": [
                {"$match": {"rating": {"$lte": 2}}},
                {"$project": {"tags": {"$setUnion": ["$tags", []]}}},
                {"$unwind": "$tags"},
                {"$match": {"tags": {"$in": sorted(NEGATIVE_TAGS)}}},
                {"$group": {"_id": "$tags", "count": {"$sum": 1}}},
                {"$sort": {"count": -1, "_id": 1}},
                {"$limit": 20},
                {"$project": {"_id": 0, "tag": "$_id", "count": 1}},
            ],
            "rating_trends": [
                {"$group": {"_id": {"$dateToString": {"format": "%Y-%m", "date": "$created_at"}},
                            "average": {"$avg": "$rating"}, "count": {"$sum": 1}}},
                {"$sort": {"_id": 1}},
                {"$project": {"_id": 0, "month": "$_id", "average": 1, "count": 1}},
            ],
            "total": [{"$count": "count"}],
        }},
    ]


def feedback_summary(database, branch_id=None, start=None, end=None):
    rows = list(database.reviews.aggregate(feedback_pipeline(branch_id, start, end), maxTimeMS=5000))
    result = rows[0] if rows else {}
    totals = result.get("total", [])
    return {"complaints": result.get("complaints", []),
            "rating_trends": result.get("rating_trends", []),
            "total_reviews": totals[0]["count"] if totals else 0,
            "method": "published reviews; complaints count distinct mentions in reviews rated 1–2",
            "negative_tags": sorted(NEGATIVE_TAGS)}
