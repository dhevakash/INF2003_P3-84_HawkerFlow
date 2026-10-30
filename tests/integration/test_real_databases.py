"""Opt-in tests. SQLite cannot verify InnoDB locks or MongoDB server validators."""
from concurrent.futures import ThreadPoolExecutor
from decimal import Decimal
import os
from threading import Barrier
import uuid
import pytest
from pymongo import MongoClient
from pymongo.errors import DuplicateKeyError, WriteError
from sqlalchemy.orm import sessionmaker
from app.database import Base, make_engine
from app.models import Branch, BranchStock, Customer, Ingredient, MenuItem, RecipeComponent, User
from app.nosql import REVIEW_SCHEMA
from app.schemas import CheckoutInput
from app.services.checkout import BusinessError, checkout

pytestmark = pytest.mark.integration


@pytest.fixture
def real_databases():
    if os.getenv('RUN_DB_INTEGRATION') != '1':
        pytest.skip('Set RUN_DB_INTEGRATION=1 and dedicated *_test databases. See docs/TESTING.md.')
    sql_url = os.environ['TEST_DATABASE_URL']
    mongo_uri = os.environ['TEST_MONGO_URI']
    mongo_name = os.environ['TEST_MONGO_DATABASE']
    sql_engine = make_engine(sql_url)
    assert sql_engine.dialect.name in {'mysql', 'mariadb'}, 'Real MariaDB is required.'
    assert sql_engine.url.database.endswith('_test') and mongo_name.endswith('_test'), 'Use dedicated *_test databases.'
    Base.metadata.create_all(sql_engine)
    client = MongoClient(mongo_uri, serverSelectionTimeoutMS=3000)
    client.admin.command('ping')
    yield sessionmaker(bind=sql_engine, expire_on_commit=False), client[mongo_name]
    client.close()
    sql_engine.dispose()


def test_innodb_competing_checkouts_cannot_oversell(real_databases):
    factory, _ = real_databases
    label = uuid.uuid4().hex
    with factory.begin() as s:
        branch = Branch(name=label, address='integration test')
        ingredient = Ingredient(name=label, unit='g')
        item = MenuItem(name=label, price=Decimal('5.00'))
        customer = Customer(name=label, email=label+'@example.test', points=0)
        s.add_all([branch, ingredient, item, customer]); s.flush()
        user = User(email=label+'-manager@example.test', password_hash='not-a-login-account', role='manager')
        s.add(user); s.flush()
        ids = branch.id, ingredient.id, item.id, customer.id, user.id
        s.add_all([BranchStock(branch_id=branch.id, ingredient_id=ingredient.id, quantity=Decimal('2.000')),
                   RecipeComponent(menu_item_id=item.id, ingredient_id=ingredient.id, quantity=Decimal('2.000'))])
    barrier = Barrier(2)
    def attempt(number):
        payload = CheckoutInput(request_key=label+str(number), branch_id=ids[0], customer_id=ids[3],
                                 lines=[{'menu_item_id': ids[2], 'quantity': 1}])
        with factory() as s:
            barrier.wait(timeout=10)
            try:
                checkout(s, payload, ids[4]); return 'completed'
            except BusinessError:
                return 'rejected'
    with ThreadPoolExecutor(max_workers=2) as pool:
        assert sorted(pool.map(attempt, [1, 2])) == ['completed', 'rejected']
    with factory() as s:
        assert s.get(BranchStock, (ids[0], ids[1])).quantity == Decimal('0.000')


def test_mongodb_server_validator_and_unique_index(real_databases):
    from datetime import datetime, timezone
    _, db = real_databases
    name = 'validation_' + uuid.uuid4().hex
    collection = db.create_collection(name, validator={'$jsonSchema': REVIEW_SCHEMA})
    collection.create_index('order_id', unique=True)
    doc = {'order_id': 1, 'customer_id': 1, 'branch_id': 1, 'rating': 4,
           'text': 'Integration test', 'tags': ['food'], 'created_at': datetime.now(timezone.utc),
           'replies': [], 'source': 'application_purchase'}
    try:
        collection.insert_one(dict(doc))
        with pytest.raises(DuplicateKeyError):
            collection.insert_one(dict(doc))
        with pytest.raises(WriteError) as error:
            collection.insert_one({**doc, 'order_id': 2, 'rating': 99})
        assert error.value.code == 121
    finally:
        db.drop_collection(name)
