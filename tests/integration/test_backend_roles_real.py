"""FastAPI permission tests using real MariaDB and MongoDB test stores."""
from datetime import datetime, timezone
import os
import uuid

from fastapi.testclient import TestClient
from pymongo import MongoClient
import pytest
from sqlalchemy import create_engine, event, func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import sessionmaker

from app.auth import hash_password
from app.models import Customer, Order, User

pytestmark = pytest.mark.integration


@pytest.fixture
def role_api(monkeypatch, password_hash):
    if os.getenv('RUN_BACKEND_ROLE_INTEGRATION') != '1':
        pytest.skip('Enable RUN_BACKEND_ROLE_INTEGRATION with a migrated SQL test copy.')
    engine = create_engine(os.environ['ROLE_API_TEST_DATABASE_URL'])
    assert engine.dialect.name in {'mysql', 'mariadb'}
    assert engine.url.database.endswith('_test') and engine.url.database != 'hawkerflow'
    connection = engine.connect()
    transaction = connection.begin()
    factory = sessionmaker(bind=connection, expire_on_commit=False, join_transaction_mode='create_savepoint')
    client = MongoClient(os.environ['ROLE_API_TEST_MONGO_URI'], serverSelectionTimeoutMS=5000, tz_aware=True)
    mongo_name = 'hawkerflow_roles_api_' + uuid.uuid4().hex + '_test'
    db = client[mongo_name]
    from app.database import get_session
    from app.main import app
    import app.auth as auth
    import app.routes as routes
    import app.nosql as nosql
    original_overrides = dict(app.dependency_overrides)
    monkeypatch.setattr(auth, 'SessionLocal', factory)
    monkeypatch.setattr(routes, 'engine', engine)
    monkeypatch.setattr(routes, 'mongo_db', lambda: db)
    monkeypatch.setattr(nosql, 'mongo_db', lambda: db)
    def sessions():
        with factory() as session:
            yield session
    app.dependency_overrides[get_session] = sessions
    try:
        nosql.initialize_mongo()
        with factory.begin() as session:
            orders = list(session.scalars(select(Order).order_by(Order.id)))
            first = orders[0]
            second = next(order for order in orders if order.customer_id != first.customer_id)
            third = next(order for order in orders if order.id not in {first.id, second.id})
            buyer = session.scalar(select(User).where(User.customer_id == first.customer_id, User.role == 'customer'))
            other = session.scalar(select(User).where(User.customer_id == second.customer_id, User.role == 'customer'))
            staff = session.scalar(select(User).where(User.role == 'staff').order_by(User.id))
            admin = User(email=uuid.uuid4().hex + '@admin.test', role='admin', password_hash=password_hash)
            session.add(admin)
            session.flush()
            info = {'buyer': buyer, 'other': other, 'staff': staff, 'admin': admin,
                    'first': first, 'second': second, 'third': third, 'factory': factory, 'db': db}
        for order in (first, second):
            db.reviews.insert_one({'order_id': order.id, 'customer_id': order.customer_id,
                'branch_id': order.branch_id, 'rating': 5, 'text': 'Original customer feedback',
                'tags': ['food'], 'category_ratings': {}, 'source': 'synthetic_purchase',
                'created_at': datetime.now(timezone.utc), 'replies': []})
            db.profiles.insert_one({'customer_id': order.customer_id, 'dietary_preferences': [], 'favourite_tags': ['food']})
        with TestClient(app) as api:
            info['api'] = api
            info['headers'] = {}
            for name in ('buyer', 'other', 'staff', 'admin'):
                login = api.post('/api/auth/login', json={'email': info[name].email,
                    'password': 'TestPass123!' if name == 'admin' else 'DemoPass123!'})
                assert login.status_code == 200, login.text
                info['headers'][name] = {'Authorization': 'Bearer ' + login.json()['access_token']}
            yield info
    finally:
        app.dependency_overrides.clear()
        app.dependency_overrides.update(original_overrides)
        if transaction.is_active:
            transaction.rollback()
        connection.close()
        engine.dispose()
        # Only the fresh, uniquely named fixture database can be removed here.
        assert mongo_name.startswith('hawkerflow_roles_api_') and mongo_name.endswith('_test')
        client.drop_database(mongo_name)
        client.close()


def review_body(order_id, text='Updated customer feedback'):
    return {'order_id': order_id, 'rating': 4, 'text': text, 'tags': ['service']}


def test_staff_can_only_read_and_reply_to_reviews(role_api):
    x = role_api
    api, db, auth = x['api'], x['db'], x['headers']['staff']
    order_id = x['first'].id
    before = db.reviews.find_one({'order_id': order_id})
    assert len(api.get('/api/reviews', headers=auth).json()) == 2
    assert api.post(f'/api/reviews/{order_id}/replies', headers=auth, json={'text': 'Thank you'}).status_code == 200
    replied = db.reviews.find_one({'order_id': order_id})
    assert replied['replies'][0]['manager_user_id'] == x['staff'].id
    assert {k: v for k, v in replied.items() if k != 'replies'} == {k: v for k, v in before.items() if k != 'replies'}
    for method, path, body in [
        ('POST', '/api/reviews', review_body(x['third'].id)),
        ('PUT', f'/api/reviews/{order_id}', review_body(order_id)),
        ('DELETE', f'/api/reviews/{order_id}', None),
        ('PUT', f'/api/reviews/{order_id}/replies/0', {'text': 'Unauthorized change'}),
        ('DELETE', f'/api/reviews/{order_id}/replies/0', None),
    ]:
        assert api.request(method, path, headers=auth, json=body).status_code == 403
    assert db.reviews.find_one({'order_id': order_id}) == replied
    assert db.reviews.count_documents({}) == 2


def test_staff_has_no_preference_profile_access(role_api):
    x = role_api
    api, db, auth = x['api'], x['db'], x['headers']['staff']
    before = list(db.profiles.find().sort('customer_id', 1))
    customer_id = x['first'].customer_id
    payload = {'dietary_preferences': ['vegetarian'], 'favourite_tags': ['food']}
    for method, path, body in [('GET', '/api/profiles', None), ('GET', '/api/profiles/me', None),
        ('PUT', '/api/profiles/me', payload), ('GET', f'/api/profiles/{customer_id}', None),
        ('PUT', f'/api/profiles/{customer_id}', payload), ('DELETE', f'/api/profiles/{customer_id}', None)]:
        assert api.request(method, path, headers=auth, json=body).status_code == 403
    assert list(db.profiles.find().sort('customer_id', 1)) == before


def test_admin_can_edit_and_delete_another_customers_review(role_api):
    x = role_api
    api, db, auth = x['api'], x['db'], x['headers']['admin']
    order = x['first']
    before = db.reviews.find_one({'order_id': order.id})
    assert api.put(f'/api/reviews/{order.id}', headers=auth, json=review_body(order.id)).status_code == 200
    after = db.reviews.find_one({'order_id': order.id})
    for key in ('customer_id', 'branch_id', 'order_id', 'created_at', 'source'):
        assert after[key] == before[key]
    assert after['updated_by_user_id'] == x['admin'].id
    assert api.delete(f'/api/reviews/{order.id}', headers=auth).status_code == 200
    assert db.reviews.find_one({'order_id': order.id}) is None
    with x['factory']() as session:
        assert session.get(Order, order.id) is not None


def test_admin_review_creation_uses_a_real_purchase_and_records_actor(role_api):
    x = role_api
    api, db, auth = x['api'], x['db'], x['headers']['admin']
    order = x['third']
    assert api.post('/api/reviews', headers=auth, json=review_body(order.id)).status_code == 201
    created = db.reviews.find_one({'order_id': order.id})
    assert created['customer_id'] == order.customer_id
    assert created['branch_id'] == order.branch_id
    assert created['created_by_user_id'] == x['admin'].id
    assert api.post('/api/reviews', headers=auth, json=review_body(2147483647)).status_code == 404
    assert api.post('/api/reviews', headers=auth, json={**review_body(order.id), 'customer_id': 999}).status_code == 422


def test_admin_can_manage_preference_profiles(role_api):
    x = role_api
    api, db, auth = x['api'], x['db'], x['headers']['admin']
    customer_id = x['second'].customer_id
    assert len(api.get('/api/profiles', headers=auth).json()) == 2
    assert api.get(f'/api/profiles/{customer_id}', headers=auth).status_code == 200
    payload = {'dietary_preferences': ['vegetarian'], 'favourite_tags': ['service']}
    assert api.put(f'/api/profiles/{customer_id}', headers=auth, json=payload).status_code == 200
    assert db.profiles.find_one({'customer_id': customer_id})['updated_by_user_id'] == x['admin'].id
    assert api.delete(f'/api/profiles/{customer_id}', headers=auth).status_code == 200
    assert api.put('/api/profiles/2147483647', headers=auth, json=payload).status_code == 404
    with x['factory']() as session:
        assert session.get(Customer, customer_id) is not None


def test_only_admin_can_edit_or_remove_business_replies(role_api):
    x = role_api
    api, db, order_id = x['api'], x['db'], x['first'].id
    for text in ('First reply', 'Second reply'):
        assert api.post(f'/api/reviews/{order_id}/replies', headers=x['headers']['staff'], json={'text': text}).status_code == 200
    auth = x['headers']['admin']
    assert api.put(f'/api/reviews/{order_id}/replies/0', headers=auth, json={'text': 'Moderated reply'}).status_code == 200
    replies = db.reviews.find_one({'order_id': order_id})['replies']
    assert replies[0]['manager_user_id'] == x['staff'].id
    assert replies[0]['updated_by_user_id'] == x['admin'].id
    assert api.delete(f'/api/reviews/{order_id}/replies/0', headers=auth).status_code == 200
    assert db.reviews.find_one({'order_id': order_id})['replies'][0]['text'] == 'Second reply'


def test_customer_self_service_cannot_cross_ownership_boundaries(role_api):
    x = role_api
    api, db, auth = x['api'], x['db'], x['headers']['buyer']
    own, other = x['first'], x['second']
    before_other = db.reviews.find_one({'order_id': other.id})
    assert [item['order_id'] for item in api.get('/api/reviews', headers=auth).json()] == [own.id]
    assert api.put(f'/api/reviews/{own.id}', headers=auth, json=review_body(own.id)).status_code == 200
    assert api.put(f'/api/reviews/{other.id}', headers=auth, json=review_body(other.id)).status_code == 404
    assert api.delete(f'/api/reviews/{other.id}', headers=auth).status_code == 404
    assert db.reviews.find_one({'order_id': other.id}) == before_other
    assert api.get('/api/profiles/me', headers=auth).json()['customer_id'] == own.customer_id
    assert api.put('/api/profiles/me', headers=auth,
                   json={'dietary_preferences': ['vegetarian'], 'favourite_tags': []}).status_code == 200
    assert api.get(f'/api/profiles/{other.customer_id}', headers=auth).status_code == 403
    assert api.post(f'/api/reviews/{own.id}/replies', headers=auth, json={'text': 'Pretend staff'}).status_code == 403
    assert api.delete(f'/api/reviews/{own.id}', headers=auth).status_code == 200
    assert api.post('/api/reviews', headers=auth, json=review_body(own.id)).status_code == 201


def test_role_change_preserves_ids_and_takes_effect_on_old_tokens(role_api):
    x = role_api
    api, auth, account_id = x['api'], x['headers']['admin'], x['staff'].id
    with x['factory']() as session:
        before = session.get(User, account_id)
        before_fields = (before.id, before.email, before.password_hash, before.customer_id)
    assert api.put(f'/api/accounts/{account_id}/role', headers=x['headers']['staff'], json={'role': 'admin'}).status_code == 403
    assert api.put(f'/api/accounts/{account_id}/role', headers=auth, json={'role': 'admin'}).status_code == 200
    assert api.get('/api/auth/me', headers=x['headers']['staff']).json()['role'] == 'admin'
    assert api.put(f'/api/accounts/{account_id}/role', headers=auth, json={'role': 'staff'}).status_code == 200
    assert api.get('/api/profiles', headers=x['headers']['staff']).status_code == 403
    with x['factory']() as session:
        after = session.get(User, account_id)
        assert (after.id, after.email, after.password_hash, after.customer_id) == before_fields


def signup_payload(**changes):
    return {'name': 'Signup Customer', 'email': 'signup-' + uuid.uuid4().hex + '@example.test',
            'password': 'NewCustomerPass123!', **changes}


def account_counts(factory):
    with factory() as session:
        return (session.scalar(select(func.count()).select_from(User)),
                session.scalar(select(func.count()).select_from(Customer)))


def test_real_public_signup_and_login_have_only_customer_access(role_api):
    x = role_api
    body = signup_payload()
    before = account_counts(x['factory'])
    response = x['api'].post('/api/auth/signup', json=body)
    assert response.status_code == 201 and response.json()['role'] == 'customer'
    account = response.json()
    assert account_counts(x['factory']) == (before[0] + 1, before[1] + 1)
    with x['factory']() as session:
        assert session.get(User, account['id']).customer_id == account['customer_id']
        assert session.get(Customer, account['customer_id']).points == 0
    login = x['api'].post('/api/auth/login', json={'email': body['email'].upper(), 'password': body['password']})
    assert login.status_code == 200 and login.json()['role'] == 'customer'
    auth = {'Authorization': 'Bearer ' + login.json()['access_token']}
    assert x['api'].get('/api/orders', headers=auth).json() == []
    assert x['api'].get('/api/profiles/me', headers=auth).json()['customer_id'] == account['customer_id']
    assert x['api'].post('/api/menu', headers=auth, json={'name': 'Forbidden', 'price': '5.00'}).status_code == 403
    assert x['api'].put(f"/api/accounts/{account['id']}/role", headers=auth, json={'role': 'admin'}).status_code == 403


@pytest.mark.parametrize('role', ['admin', 'staff'])
def test_real_public_signup_rejects_privileged_role_requests(role_api, role):
    before = account_counts(role_api['factory'])
    assert role_api['api'].post('/api/auth/signup', json=signup_payload(role=role)).status_code == 422
    assert account_counts(role_api['factory']) == before


def test_real_signup_duplicate_account_keeps_existing_identity(role_api):
    x = role_api
    before = account_counts(x['factory'])
    staff_id, staff_role = x['staff'].id, x['staff'].role
    assert x['api'].post('/api/auth/signup', json=signup_payload(email=' ' + x['staff'].email.upper() + ' ')).status_code == 409
    assert account_counts(x['factory']) == before
    with x['factory']() as session:
        staff = session.get(User, staff_id)
        assert staff.role == staff_role and staff.email == x['staff'].email


def test_real_signup_does_not_attach_to_existing_customer_history(role_api):
    x = role_api
    email = 'unclaimed-' + uuid.uuid4().hex + '@example.test'
    with x['factory'].begin() as session:
        customer = Customer(name='Existing customer', email=email, points=900)
        session.add(customer)
        session.flush()
        customer_id = customer.id
    before = account_counts(x['factory'])
    assert x['api'].post('/api/auth/signup', json=signup_payload(email=email)).status_code == 409
    assert account_counts(x['factory']) == before
    with x['factory']() as session:
        assert session.get(Customer, customer_id).points == 900
        assert session.scalar(select(User).where(User.customer_id == customer_id)) is None


def test_real_signup_second_write_failure_rolls_back_customer(role_api):
    x = role_api
    body = signup_payload()
    before = account_counts(x['factory'])
    def fail_insert(mapper, connection, account):
        if account.email == body['email']:
            raise IntegrityError('simulated account write failure', {}, RuntimeError('injected test failure'))
    event.listen(User, 'before_insert', fail_insert)
    try:
        assert x['api'].post('/api/auth/signup', json=body).status_code == 409
    finally:
        event.remove(User, 'before_insert', fail_insert)
    assert account_counts(x['factory']) == before
    assert x['api'].post('/api/auth/signup', json=body).status_code == 201


def test_real_admin_session_cannot_turn_public_signup_into_admin_creation(role_api):
    x = role_api
    response = x['api'].post('/api/auth/signup?role=admin', headers=x['headers']['admin'], json=signup_payload())
    assert response.status_code == 201 and response.json()['role'] == 'customer'
    with x['factory']() as session:
        assert session.get(User, x['admin'].id).role == 'admin'


@pytest.mark.parametrize('role', ['staff', 'admin'])
def test_real_admin_creates_privileged_account_and_new_account_can_sign_in(role_api, role):
    x = role_api
    before = account_counts(x['factory'])
    body = {'email': 'created-' + uuid.uuid4().hex + '@example.test',
            'password': 'NewPrivilegedPass123!', 'role': role}
    response = x['api'].post('/api/accounts', headers=x['headers']['admin'], json=body)
    assert response.status_code == 201, response.text
    account = response.json()
    assert set(account) == {'id', 'email', 'role', 'customer_id', 'active'}
    assert account['role'] == role and account['customer_id'] is None
    assert account_counts(x['factory']) == (before[0] + 1, before[1])
    login = x['api'].post('/api/auth/login', json={'email': body['email'].upper(), 'password': body['password']})
    assert login.status_code == 200 and login.json()['role'] == role
    auth = {'Authorization': 'Bearer ' + login.json()['access_token']}
    assert x['api'].get('/api/stock', headers=auth).status_code == 200
    assert x['api'].put(f"/api/accounts/{x['staff'].id}/role", headers=auth,
                       json={'role': 'admin'}).status_code == (200 if role == 'admin' else 403)
    if role == 'staff':
        assert x['api'].put(f"/api/reviews/{x['first'].id}", headers=auth,
                           json=review_body(x['first'].id)).status_code == 403
        assert x['api'].get('/api/profiles', headers=auth).status_code == 403


@pytest.mark.parametrize('actor', [None, 'staff', 'buyer'])
def test_real_privileged_creation_rejects_non_admin_without_writes(role_api, actor):
    x = role_api
    before = account_counts(x['factory'])
    body = {'email': 'forbidden-' + uuid.uuid4().hex + '@example.test',
            'password': 'NewPrivilegedPass123!', 'role': 'admin'}
    response = x['api'].post('/api/accounts', headers=x['headers'][actor] if actor else {}, json=body)
    assert response.status_code == (403 if actor else 401)
    assert account_counts(x['factory']) == before


def test_real_privileged_creation_rejects_duplicate_historical_account(role_api):
    x = role_api
    before = account_counts(x['factory'])
    with x['factory']() as session:
        original = session.get(User, x['staff'].id)
        identity = (original.id, original.role, original.password_hash, original.customer_id, original.email)
    response = x['api'].post('/api/accounts', headers=x['headers']['admin'],
        json={'email': x['staff'].email.upper(), 'password': 'NewPrivilegedPass123!', 'role': 'admin'})
    assert response.status_code == 409 and account_counts(x['factory']) == before
    with x['factory']() as session:
        original = session.get(User, x['staff'].id)
        assert (original.id, original.role, original.password_hash, original.customer_id, original.email) == identity


@pytest.mark.parametrize('extra', [{'id': 1}, {'customer_id': 1}, {'role': 'customer'}])
def test_real_privileged_creation_rejects_identity_injection(role_api, extra):
    x = role_api
    before = account_counts(x['factory'])
    response = x['api'].post('/api/accounts', headers=x['headers']['admin'],
        json={'email': 'invalid-' + uuid.uuid4().hex + '@example.test',
              'password': 'NewPrivilegedPass123!', 'role': 'staff', **extra})
    assert response.status_code == 422 and account_counts(x['factory']) == before


def test_real_account_listing_excludes_passwords_and_requires_admin(role_api):
    x = role_api
    result = x['api'].get('/api/accounts', headers=x['headers']['admin'])
    assert result.status_code == 200
    assert all(set(row) == {'id', 'email', 'role', 'customer_id', 'active'} for row in result.json())
    assert 'password' not in result.text
    assert x['api'].get('/api/accounts').status_code == 401
    for name in ('staff', 'buyer'):
        assert x['api'].get('/api/accounts', headers=x['headers'][name]).status_code == 403


def test_real_deactivation_revokes_sessions_and_preserves_historical_actor(role_api):
    x = role_api
    api, account_id, admin = x['api'], x['staff'].id, x['headers']['admin']
    with x['factory']() as session:
        user = session.get(User, account_id)
        identity = (user.id, user.email, user.password_hash, user.role, user.customer_id)
        orders_before = list(session.execute(select(Order.id, Order.cashier_user_id).order_by(Order.id)))
    assert api.put(f'/api/accounts/{account_id}/status', headers=x['headers']['buyer'], json={'active': False}).status_code == 403
    assert api.put(f'/api/accounts/{account_id}/status', headers=admin, json={'active': False}).status_code == 200
    assert api.get('/api/stock', headers=x['headers']['staff']).status_code == 401
    assert api.post('/api/auth/login', json={'email': x['staff'].email, 'password': 'DemoPass123!'}).status_code == 401
    assert api.put(f'/api/accounts/{account_id}/status', headers=admin, json={'active': True}).status_code == 200
    assert api.get('/api/stock', headers=x['headers']['staff']).status_code == 401
    assert api.post('/api/auth/login', json={'email': x['staff'].email, 'password': 'DemoPass123!'}).status_code == 200
    with x['factory']() as session:
        user = session.get(User, account_id)
        assert (user.id, user.email, user.password_hash, user.role, user.customer_id) == identity
        assert list(session.execute(select(Order.id, Order.cashier_user_id).order_by(Order.id))) == orders_before
