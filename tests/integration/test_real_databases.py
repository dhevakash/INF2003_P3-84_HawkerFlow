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
        user = User(email=label+'-staff@example.test', password_hash='not-a-login-account', role='staff')
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


def test_concurrent_signup_creates_one_linked_customer_with_birthday(real_databases):
    from datetime import date
    from fastapi import HTTPException
    from sqlalchemy import func, select
    from sqlalchemy.exc import IntegrityError
    from app.auth import verify_password
    from app.routes import signup
    from app.schemas import SignupInput
    factory, _ = real_databases
    email = uuid.uuid4().hex+'@signup.test'
    barrier = Barrier(2)
    def attempt(number):
        with factory() as session:
            barrier.wait(timeout=10)
            try:
                signup(SignupInput(name='Concurrent buyer', email=email, birthday='2000-02-29',
                    password='ConcurrentSignupPass123!', confirm_password='ConcurrentSignupPass123!'), session=session)
                return 'created'
            except (IntegrityError, HTTPException) as error:
                if isinstance(error, HTTPException):
                    assert error.status_code == 409
                return 'duplicate'
    with ThreadPoolExecutor(max_workers=2) as pool:
        assert sorted(pool.map(attempt, [1, 2])) == ['created', 'duplicate']
    with factory() as session:
        assert session.scalar(select(func.count()).select_from(User).where(User.email == email)) == 1
        assert session.scalar(select(func.count()).select_from(Customer).where(Customer.email == email)) == 1
        account = session.scalar(select(User).where(User.email == email))
        customer = session.get(Customer, account.customer_id)
        assert customer.birthday == date(2000, 2, 29) and customer.points == 0 and account.role == 'customer'
        assert verify_password('ConcurrentSignupPass123!', account.password_hash)


def test_real_signup_second_insert_failure_leaves_no_customer_or_login(real_databases):
    from sqlalchemy import event, func, select
    from sqlalchemy.exc import IntegrityError
    from app.routes import signup
    from app.schemas import SignupInput
    factory, _ = real_databases
    email = uuid.uuid4().hex+'@signup-failure.test'
    def fail(mapper, connection, account):
        if account.email == email:
            raise IntegrityError('injected account insert failure', {}, RuntimeError('injected'))
    event.listen(User, 'before_insert', fail)
    try:
        with factory() as session, pytest.raises(IntegrityError):
            signup(SignupInput(name='Rollback buyer', email=email, birthday='2000-02-29', password='RollbackSignupPass123!'), session=session)
    finally:
        event.remove(User, 'before_insert', fail)
    with factory() as session:
        assert session.scalar(select(func.count()).select_from(User).where(User.email == email)) == 0
        assert session.scalar(select(func.count()).select_from(Customer).where(Customer.email == email)) == 0


def test_account_disable_waits_for_mongo_reply_then_deletion_preserves_author(real_databases, monkeypatch):
    from threading import Event
    from fastapi import HTTPException
    from app.auth import Principal, document_writer
    from app.services.account_management import delete_unused_account, lock_account
    factory, db = real_databases
    label = uuid.uuid4().hex
    with factory.begin() as session:
        admin = User(email=label+'-admin@example.test', role='admin', password_hash='not-a-login-account')
        staff = User(email=label+'-staff@example.test', role='staff', password_hash='not-a-login-account')
        session.add_all([admin, staff]); session.flush()
        admin_id, staff_id = admin.id, staff.id
    monkeypatch.setattr('app.auth.SessionLocal', factory)
    writer_locked, allow_reply, disable_started, disable_done = (Event() for _ in range(4))
    def write_reply():
        guard = document_writer(Principal(staff_id, 'staff', None, 0))
        next(guard)
        try:
            writer_locked.set()
            assert allow_reply.wait(10)
            db.reviews.insert_one({'account_test': label, 'replies': [{'manager_user_id': staff_id, 'text': 'Retain author'}]})
        finally:
            guard.close()
    def disable_and_delete():
        assert writer_locked.wait(10)
        disable_started.set()
        with factory.begin() as session:
            account = lock_account(session, Principal(admin_id, 'admin', None), staff_id)
            account.active = False
            account.session_version += 1
        disable_done.set()
        with factory.begin() as session:
            account = lock_account(session, Principal(admin_id, 'admin', None), staff_id)
            with pytest.raises(HTTPException) as error:
                delete_unused_account(session, account, lambda: db)
            assert error.value.status_code == 409 and 'reviews' in error.value.detail
    with ThreadPoolExecutor(max_workers=2) as pool:
        writer = pool.submit(write_reply)
        deleter = pool.submit(disable_and_delete)
        try:
            assert disable_started.wait(10)
            assert not disable_done.wait(0.2), 'Disable must wait for the in-flight Mongo author lock.'
        finally:
            allow_reply.set()
        writer.result(timeout=15); deleter.result(timeout=15)
    with factory() as session:
        assert session.get(User, staff_id) is not None and not session.get(User, staff_id).active
    assert db.reviews.count_documents({'account_test': label}) == 1


def test_account_deletion_and_checkout_cannot_leave_broken_purchase_links(real_databases):
    from fastapi import HTTPException
    from sqlalchemy import func, select
    from app.auth import Principal
    from app.models import Order
    from app.services.account_management import delete_unused_account, lock_account
    factory, db = real_databases
    label = uuid.uuid4().hex
    with factory.begin() as session:
        branch = Branch(name=label, address='Account deletion test')
        ingredient = Ingredient(name=label, unit='g')
        item = MenuItem(name=label, price=Decimal('5.00'))
        customer = Customer(name=label, email=label+'@example.test', points=0)
        admin = User(email=label+'-admin@example.test', role='admin', password_hash='not-a-login-account')
        staff = User(email=label+'-staff@example.test', role='staff', password_hash='not-a-login-account')
        session.add_all([branch, ingredient, item, customer, admin, staff]); session.flush()
        buyer = User(email=customer.email, customer_id=customer.id, role='customer', active=False, password_hash='not-a-login-account')
        session.add(buyer); session.flush()
        ids = branch.id, ingredient.id, item.id, customer.id, admin.id, staff.id, buyer.id
        session.add_all([BranchStock(branch_id=branch.id, ingredient_id=ingredient.id, quantity=Decimal('10.000')),
                         RecipeComponent(menu_item_id=item.id, ingredient_id=ingredient.id, quantity=Decimal('1.000'))])
    barrier = Barrier(2)
    def sale():
        with factory() as session:
            barrier.wait(timeout=10)
            try:
                checkout(session, CheckoutInput(request_key=label, branch_id=ids[0], customer_id=ids[3],
                    lines=[{'menu_item_id': ids[2], 'quantity': 1}]), ids[5])
                return 'sold'
            except BusinessError:
                return 'unavailable'
    def deletion():
        with factory.begin() as session:
            barrier.wait(timeout=10)
            try:
                account = lock_account(session, Principal(ids[4], 'admin', None), ids[6])
                delete_unused_account(session, account, lambda: db)
                return 'deleted'
            except HTTPException as error:
                assert error.status_code == 409
                return 'retained'
    with ThreadPoolExecutor(max_workers=2) as pool:
        first, second = pool.submit(sale), pool.submit(deletion)
        results = first.result(timeout=15), second.result(timeout=15)
    assert results in [('sold', 'retained'), ('unavailable', 'deleted')]
    with factory() as session:
        orders = session.scalar(select(func.count()).select_from(Order).where(Order.customer_id == ids[3]))
        assert bool(orders) == (session.get(Customer, ids[3]) is not None)
        assert bool(orders) == (session.get(User, ids[6]) is not None)


@pytest.mark.parametrize('competitor', ['correction', 'checkout'])
def test_stock_correction_cannot_overwrite_a_competing_change(real_databases, competitor):
    from sqlalchemy import func, select
    from app.models import Order, StockAdjustment, StockMovement
    from app.schemas import StockAdjustmentInput
    from app.services.inventory import adjust_stock
    factory, _ = real_databases
    label = uuid.uuid4().hex
    with factory.begin() as session:
        branch = Branch(name=label, address='stock correction integration test')
        ingredient = Ingredient(name=label, unit='g')
        item = MenuItem(name=label, price=Decimal('5.00'))
        customer = Customer(name=label, email=label+'@example.test', points=0)
        user = User(email=label+'@admin.test', password_hash='not-a-login-account', role='admin')
        session.add_all([branch, ingredient, item, customer, user]); session.flush()
        ids = branch.id, ingredient.id, item.id, customer.id, user.id
        session.add_all([BranchStock(branch_id=branch.id, ingredient_id=ingredient.id, quantity=Decimal('2.000')),
                         RecipeComponent(menu_item_id=item.id, ingredient_id=ingredient.id, quantity=Decimal('2.000'))])
    barrier = Barrier(2)
    def attempt(number):
        with factory() as session:
            barrier.wait(timeout=10)
            try:
                if number == 1 and competitor == 'checkout':
                    payload = CheckoutInput(request_key=label, branch_id=ids[0], customer_id=ids[3],
                                            lines=[{'menu_item_id': ids[2], 'quantity': 1}])
                    checkout(session, payload, ids[4])
                else:
                    adjust_stock(session, ids[0], ids[1], StockAdjustmentInput(
                        quantity='0.000', expected_quantity='2.000', reason='Concurrent physical count'), ids[4])
                return 'completed'
            except BusinessError as error:
                assert error.status == 409
                return 'rejected'
    with ThreadPoolExecutor(max_workers=2) as pool:
        assert sorted(pool.map(attempt, [0, 1])) == ['completed', 'rejected']
    with factory() as session:
        assert session.get(BranchStock, (ids[0], ids[1])).quantity == Decimal('0.000')
        adjustment_count = session.scalar(select(func.count()).select_from(StockAdjustment).where(StockAdjustment.branch_id == ids[0]))
        order_count = session.scalar(select(func.count()).select_from(Order).where(Order.branch_id == ids[0]))
        assert adjustment_count + order_count == 1
        movement = session.scalar(select(StockMovement).where(StockMovement.branch_id == ids[0]))
        assert movement.delta == Decimal('-2.000')


def test_checkout_waits_for_recipe_save_and_uses_the_complete_new_recipe(real_databases):
    from threading import Event, local
    from sqlalchemy import event, select
    from app.schemas import RecipeInput
    from app.services.recipes import save_recipe
    factory, _ = real_databases
    label = uuid.uuid4().hex
    with factory.begin() as session:
        branch = Branch(name=label, address='recipe concurrency test')
        ingredients = [Ingredient(name=label+'-a', unit='g'), Ingredient(name=label+'-b', unit='g')]
        item = MenuItem(name=label, price=Decimal('5.00'))
        customer = Customer(name=label, email=label+'@example.test', points=0)
        user = User(email=label+'@staff.test', password_hash='not-a-login-account', role='staff')
        session.add_all([branch, *ingredients, item, customer, user]); session.flush()
        ids = branch.id, item.id, customer.id, user.id, ingredients[0].id, ingredients[1].id
        for ingredient, quantity in zip(ingredients, ['2.000', '3.000']):
            session.add_all([BranchStock(branch_id=branch.id, ingredient_id=ingredient.id, quantity=Decimal('20.000')),
                RecipeComponent(menu_item_id=item.id, ingredient_id=ingredient.id, quantity=Decimal(quantity))])
    writer_paused, release_writer, sale_snapshot = Event(), Event(), Event()
    worker = local()
    engine = factory.kw['bind']
    def observe(connection, cursor, statement, parameters, context, executemany):
        sql = statement.lstrip().lower()
        if getattr(worker, 'role', '') == 'editor' and sql.startswith('update recipe_components '):
            writer_paused.set()
            assert release_writer.wait(15), 'Recipe writer was not released.'
        if getattr(worker, 'role', '') == 'sale' and sql.startswith('select orders.'):
            sale_snapshot.set()
    def edit():
        worker.role = 'editor'
        with factory() as session:
            return save_recipe(session, ids[1], RecipeInput(
                components=[{'ingredient_id': ids[4], 'quantity': '4.000'}, {'ingredient_id': ids[5], 'quantity': '5.000'}],
                expected_components=[{'ingredient_id': ids[4], 'quantity': '2.000'}, {'ingredient_id': ids[5], 'quantity': '3.000'}]))
    def sell():
        worker.role = 'sale'
        with factory() as session:
            return checkout(session, CheckoutInput(request_key=label, branch_id=ids[0], customer_id=ids[2],
                lines=[{'menu_item_id': ids[1], 'quantity': 1}]), ids[3])
    event.listen(engine, 'after_cursor_execute', observe)
    try:
        with ThreadPoolExecutor(max_workers=2) as pool:
            editor = pool.submit(edit)
            try:
                assert writer_paused.wait(10)
                sale = pool.submit(sell)
                assert sale_snapshot.wait(10)
            finally:
                release_writer.set()
            editor.result(timeout=20); sale.result(timeout=20)
    finally:
        release_writer.set()
        event.remove(engine, 'after_cursor_execute', observe)
    with factory() as session:
        assert session.get(BranchStock, (ids[0], ids[4])).quantity == Decimal('16.000')
        assert session.get(BranchStock, (ids[0], ids[5])).quantity == Decimal('15.000')


def test_competing_recipe_editors_cannot_overwrite_the_same_original(real_databases):
    from sqlalchemy import select
    from app.schemas import RecipeInput
    from app.services.recipes import save_recipe
    factory, _ = real_databases
    label = uuid.uuid4().hex
    with factory.begin() as session:
        item = MenuItem(name=label, price=Decimal('5.00'))
        ingredient = Ingredient(name=label, unit='g')
        session.add_all([item, ingredient]); session.flush()
        ids = item.id, ingredient.id
        session.add(RecipeComponent(menu_item_id=item.id, ingredient_id=ingredient.id, quantity=Decimal('2.000')))
    barrier = Barrier(2)
    def edit(quantity):
        with factory() as session:
            barrier.wait(timeout=10)
            try:
                save_recipe(session, ids[0], RecipeInput(
                    components=[{'ingredient_id': ids[1], 'quantity': quantity}],
                    expected_components=[{'ingredient_id': ids[1], 'quantity': '2.000'}]))
                return 'completed'
            except BusinessError as error:
                assert error.status == 409
                return 'rejected'
    with ThreadPoolExecutor(max_workers=2) as pool:
        assert sorted(pool.map(edit, ['3.000', '4.000'])) == ['completed', 'rejected']
    with factory() as session:
        assert session.get(RecipeComponent, ids).quantity in {Decimal('3.000'), Decimal('4.000')}


@pytest.mark.parametrize('mode', ['earning', 'redemption', 'another_correction'])
def test_points_corrections_cannot_lose_checkout_or_other_corrections(real_databases, mode):
    from sqlalchemy import func, select
    from app.models import LoyaltyAdjustment, LoyaltyTransaction, Order
    from app.schemas import PointsEditInput, PointsRemovalInput
    from app.services.loyalty import correct_points
    factory, _ = real_databases
    label = uuid.uuid4().hex
    with factory.begin() as session:
        branch = Branch(name=label, address='points concurrency test')
        ingredient = Ingredient(name=label, unit='g')
        item = MenuItem(name=label, price=Decimal('5.00'))
        customer = Customer(name=label, email=label+'@example.test', points=100)
        actor = User(email=label+'@admin.test', password_hash='not-a-login-account', role='admin')
        session.add_all([branch, ingredient, item, customer, actor]); session.flush()
        ids = branch.id, ingredient.id, item.id, customer.id, actor.id
        session.add_all([BranchStock(branch_id=branch.id, ingredient_id=ingredient.id, quantity=Decimal('20.000')),
            RecipeComponent(menu_item_id=item.id, ingredient_id=ingredient.id, quantity=Decimal('2.000'))])
    barrier = Barrier(2)
    def attempt(number):
        with factory() as session:
            barrier.wait(timeout=10)
            try:
                if number == 0:
                    if mode == 'redemption':
                        correct_points(session, ids[3], PointsRemovalInput(amount=100, expected_points=100, reason='Fraud'), ids[4], remove=True)
                    else:
                        correct_points(session, ids[3], PointsEditInput(points=80, expected_points=100, reason='Fraud'), ids[4])
                elif mode == 'another_correction':
                    correct_points(session, ids[3], PointsRemovalInput(amount=25, expected_points=100, reason='Fraud'), ids[4], remove=True)
                else:
                    checkout(session, CheckoutInput(request_key=label, branch_id=ids[0], customer_id=ids[3],
                        redeem_points=100 if mode == 'redemption' else 0,
                        lines=[{'menu_item_id': ids[2], 'quantity': 1}]), ids[4])
                return 'completed'
            except BusinessError as error:
                assert error.status == 409
                return 'rejected'
    with ThreadPoolExecutor(max_workers=2) as pool:
        outcomes = list(pool.map(attempt, [0, 1]))
    with factory() as session:
        balance = session.get(Customer, ids[3]).points
        adjustments = list(session.scalars(select(LoyaltyAdjustment).where(LoyaltyAdjustment.customer_id == ids[3])))
        transactions = list(session.scalars(select(LoyaltyTransaction).where(LoyaltyTransaction.customer_id == ids[3])))
        assert balance == 100 + sum(row.delta for row in adjustments) + sum(row.delta for row in transactions)
        if mode == 'earning':
            assert outcomes[1] == 'completed'
            assert balance == (85 if outcomes[0] == 'completed' else 105)
        elif mode == 'redemption':
            assert sorted(outcomes) == ['completed', 'rejected']
            assert balance == (0 if outcomes[0] == 'completed' else 4)
        else:
            assert sorted(outcomes) == ['completed', 'rejected']
            assert len(adjustments) == 1 and balance in {75, 80}
