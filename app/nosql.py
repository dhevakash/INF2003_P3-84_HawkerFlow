"""MongoDB owns reviews/preferences. External examples never impersonate purchases."""
from functools import lru_cache
from pymongo import ASCENDING, MongoClient
from app.config import MONGO_DATABASE, MONGO_URI
from app.services.checkout import BusinessError

NUMBER = {'bsonType': ['int', 'long']}
RATING = {**NUMBER, 'minimum': 1, 'maximum': 5}
TAG_ARRAY = {'bsonType': 'array', 'maxItems': 10, 'uniqueItems': True,
             'items': {'bsonType': 'string', 'minLength': 1, 'maxLength': 40}}
REVIEW_SCHEMA = {
    'bsonType': 'object',
    'required': ['order_id', 'customer_id', 'branch_id', 'rating', 'text', 'tags', 'created_at', 'replies', 'source'],
    'properties': {
        'order_id': {**NUMBER, 'minimum': 1}, 'customer_id': {**NUMBER, 'minimum': 1},
        'branch_id': {**NUMBER, 'minimum': 1}, 'rating': RATING,
        'text': {'bsonType': 'string', 'minLength': 3, 'maxLength': 2000},
        'tags': TAG_ARRAY, 'created_at': {'bsonType': 'date'}, 'updated_at': {'bsonType': 'date'},
        'source': {'enum': ['synthetic_purchase', 'application_purchase']},
        'category_ratings': {'bsonType': 'object', 'additionalProperties': False,
            'properties': {name: RATING for name in ('food', 'service', 'value')}},
        'replies': {'bsonType': 'array', 'maxItems': 20, 'items': {
            'bsonType': 'object', 'required': ['manager_user_id', 'text', 'created_at'],
            'properties': {'manager_user_id': NUMBER, 'text': {'bsonType': 'string', 'minLength': 1, 'maxLength': 1000},
                           'created_at': {'bsonType': 'date'}}}},
    }
}
PROFILE_SCHEMA = {'bsonType': 'object', 'required': ['customer_id', 'dietary_preferences', 'favourite_tags'],
    'properties': {'customer_id': {**NUMBER, 'minimum': 1}, 'dietary_preferences': TAG_ARRAY,
                   'favourite_tags': TAG_ARRAY, 'updated_at': {'bsonType': 'date'}}}
EXTERNAL_SCHEMA = {'bsonType': 'object', 'required': ['source', 'source_row', 'text', 'sentiment'],
    'properties': {'source': {'enum': ['UCI_YELP']}, 'source_row': NUMBER,
                   'text': {'bsonType': 'string'}, 'sentiment': {**NUMBER, 'minimum': 0, 'maximum': 1}}}


@lru_cache
def mongo_db():
    if not MONGO_URI:
        raise BusinessError('MongoDB is not configured. Use the Docker setup for NoSQL features.', 503)
    client = MongoClient(MONGO_URI, serverSelectionTimeoutMS=3000, tz_aware=True)
    client.admin.command('ping')
    return client[MONGO_DATABASE]


def initialize_mongo():
    db = mongo_db()
    for name, schema in [('reviews', REVIEW_SCHEMA), ('profiles', PROFILE_SCHEMA), ('external_examples', EXTERNAL_SCHEMA)]:
        if name in db.list_collection_names():
            db.command('collMod', name, validator={'$jsonSchema': schema}, validationLevel='strict', validationAction='error')
        else:
            db.create_collection(name, validator={'$jsonSchema': schema}, validationLevel='strict', validationAction='error')
    db.reviews.create_index([('order_id', ASCENDING)], unique=True, name='uq_review_order')
    db.reviews.create_index([('branch_id', ASCENDING), ('created_at', ASCENDING)], name='ix_review_branch_time')
    db.reviews.create_index([('rating', ASCENDING), ('tags', ASCENDING)], name='ix_review_rating_tags')
    db.profiles.create_index('customer_id', unique=True)
    db.external_examples.create_index([('source', ASCENDING), ('source_row', ASCENDING)], unique=True)


def complaint_pipeline(branch_id=None):
    match = {'rating': {'$lte': 2}}
    if branch_id is not None:
        match['branch_id'] = branch_id
    return [{'$match': match}, {'$unwind': '$tags'},
            {'$group': {'_id': '$tags', 'count': {'$sum': 1}}}, {'$sort': {'count': -1, '_id': 1}}]


def monthly_pipeline():
    return [{'$group': {'_id': {'branch_id': '$branch_id',
                'month': {'$dateToString': {'format': '%Y-%m', 'date': '$created_at', 'timezone': 'UTC'}}},
                'average_rating': {'$avg': '$rating'}, 'reviews': {'$sum': 1}}},
            {'$sort': {'_id.month': 1, '_id.branch_id': 1}}]
