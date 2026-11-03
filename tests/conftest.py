from decimal import Decimal
import pytest
from sqlalchemy.orm import sessionmaker
from app.database import Base, make_engine
from app.models import Branch, BranchStock, Customer, Ingredient, MenuItem, RecipeComponent, User
from app.auth import hash_password
from app.analytics import initialize_views


@pytest.fixture(scope='session')
def password_hash():
    return hash_password('TestPass123!')


@pytest.fixture
def database(tmp_path, password_hash):
    engine = make_engine(f'sqlite:///{tmp_path / "test.sqlite"}')
    Base.metadata.create_all(engine)
    initialize_views(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    with factory.begin() as s:
        s.add_all([Branch(id=1, name='Test Branch', address='Fictional'),
            Customer(id=1, name='Buyer', email='buyer@example.test', points=100),
            Customer(id=2, name='Other', email='other@example.test', points=0),
            Ingredient(id=1, name='Rice', unit='g'), MenuItem(id=1, name='Rice meal', price=Decimal('5.00'))])
        s.flush()
        s.add_all([User(id=1, email='staff@example.test', role='staff', password_hash=password_hash),
            User(id=2, email='buyer@example.test', role='customer', customer_id=1, password_hash=password_hash),
            User(id=3, email='other@example.test', role='customer', customer_id=2, password_hash=password_hash),
            User(id=4, email='admin@example.test', role='admin', password_hash=password_hash),
            User(id=5, email='staff2@example.test', role='staff', password_hash=password_hash),
            BranchStock(branch_id=1, ingredient_id=1, quantity=Decimal('10.000')),
            RecipeComponent(menu_item_id=1, ingredient_id=1, quantity=Decimal('2.000'))])
    yield factory
    engine.dispose()


@pytest.fixture
def cart():
    from app.schemas import CheckoutInput
    return CheckoutInput(request_key='test-checkout-0001', branch_id=1, customer_id=1,
                         lines=[{'menu_item_id': 1, 'quantity': 1}])


@pytest.fixture
def client(database, monkeypatch):
    from fastapi.testclient import TestClient
    from app.main import app
    from app.database import get_session
    import app.auth as auth
    import app.routes as routes
    monkeypatch.setattr(auth, 'SessionLocal', database)
    monkeypatch.setattr(routes, 'engine', database.kw['bind'])
    def session_override():
        with database() as session:
            yield session
    app.dependency_overrides[get_session] = session_override
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()
