from decimal import Decimal

import pytest
from sqlalchemy import event, select, text

from app.models import BranchStock, Ingredient, MenuItem, RecipeComponent
from app.schemas import RecipeInput
from app.services.checkout import checkout
from app.services.recipes import save_recipe
from tests.test_api import headers


ORIGINAL = [{'ingredient_id': 1, 'quantity': '2.000'}]
UPDATED = [{'ingredient_id': 1, 'quantity': '3.125'}, {'ingredient_id': 2, 'quantity': '0.500'}]
BODY = {'components': UPDATED, 'expected_components': ORIGINAL}


@pytest.fixture
def recipe_catalog(database):
    with database.begin() as session:
        session.add_all([Ingredient(id=2, name='Oil', unit='kg'), Ingredient(id=3, name='Eggs', unit='pcs'),
                         MenuItem(id=2, name='New meal', price=Decimal('6.00'))])
        session.flush()
        session.add_all([BranchStock(branch_id=1, ingredient_id=2, quantity=Decimal('10.000')),
                         BranchStock(branch_id=1, ingredient_id=3, quantity=Decimal('10.000'))])


def recipe_state(database):
    with database() as session:
        return [(row.menu_item_id, row.ingredient_id, row.quantity) for row in session.scalars(
            select(RecipeComponent).order_by(RecipeComponent.menu_item_id, RecipeComponent.ingredient_id))]


def history(database):
    with database() as session:
        return {table: [dict(row) for row in session.execute(text('SELECT * FROM '+table)).mappings()]
                for table in ('orders', 'order_lines', 'loyalty_transactions', 'stock_movements', 'branch_stock')}


def test_admin_can_add_edit_remove_ingredients_and_create_a_recipe(client, database, recipe_catalog):
    auth = headers(client, 'admin@example.test')
    before = history(database)
    result = client.put('/api/recipes/1', headers=auth, json=BODY)
    assert result.status_code == 200, result.text
    assert result.json()['components'] == UPDATED
    assert client.put('/api/recipes/1', headers=auth,
        json={'components': [UPDATED[1]], 'expected_components': UPDATED}).status_code == 200
    assert recipe_state(database) == [(1, 2, Decimal('0.500'))]
    assert client.put('/api/recipes/2', headers=auth,
        json={'components': ORIGINAL, 'expected_components': []}).status_code == 200
    assert history(database) == before


@pytest.mark.parametrize('email,status', [(None, 401), ('staff@example.test', 403), ('buyer@example.test', 403)])
def test_recipe_writes_are_admin_only(client, database, email, status):
    auth = headers(client, email) if email else {}
    before = recipe_state(database)
    assert client.put('/api/recipes/1', headers=auth, json=BODY).status_code == status
    assert recipe_state(database) == before


@pytest.mark.parametrize('email,status', [('admin@example.test', 200), ('staff@example.test', 200), ('buyer@example.test', 403)])
def test_recipe_and_ingredient_reads_follow_roles(client, email, status):
    auth = headers(client, email)
    response = client.get('/api/recipes', headers=auth)
    assert response.status_code == status
    assert client.get('/api/ingredients', headers=auth).status_code == status
    if status == 200:
        row = response.json()[0]
        assert (row['menu_item'], row['ingredient'], row['unit'], row['quantity']) == ('Rice meal', 'Rice', 'g', '2.000')


@pytest.mark.parametrize('quantity', ['0', '-1', '1.2345', '1e3', 'E', 'NaN', 'Infinity', '100000000000.000'])
def test_invalid_recipe_quantities_make_no_changes(client, database, quantity):
    auth = headers(client, 'admin@example.test')
    before = recipe_state(database)
    assert client.put('/api/recipes/1', headers=auth,
        json={'components': [{'ingredient_id': 1, 'quantity': quantity}], 'expected_components': ORIGINAL}).status_code == 422
    assert recipe_state(database) == before


@pytest.mark.parametrize('body', [
    {'components': [], 'expected_components': ORIGINAL},
    {'components': ORIGINAL * 2, 'expected_components': ORIGINAL},
    {'components': ORIGINAL, 'expected_components': ORIGINAL * 2},
    {'components': ORIGINAL},
    {'components': [{'ingredient_id': True, 'quantity': '1'}], 'expected_components': ORIGINAL},
    {'components': [{'ingredient_id': '1', 'quantity': '1'}], 'expected_components': ORIGINAL},
    {'components': ORIGINAL, 'expected_components': ORIGINAL, 'role': 'admin'}
])
def test_recipe_structure_validation(client, database, body):
    before = recipe_state(database)
    assert client.put('/api/recipes/1', headers=headers(client, 'admin@example.test'), json=body).status_code == 422
    assert recipe_state(database) == before


def test_missing_menu_ingredient_and_stale_recipe_are_rejected(client, database, recipe_catalog):
    auth = headers(client, 'admin@example.test')
    assert client.put('/api/recipes/999', headers=auth, json=BODY).status_code == 404
    assert client.put('/api/recipes/1', headers=auth,
        json={'components': [{'ingredient_id': 999, 'quantity': '1'}], 'expected_components': ORIGINAL}).status_code == 422
    assert client.put('/api/recipes/1', headers=auth,
        json={**BODY, 'expected_components': []}).status_code == 409
    assert recipe_state(database) == [(1, 1, Decimal('2.000'))]
    assert client.put('/api/recipes/1', headers=auth, json=BODY).status_code == 200
    assert client.put('/api/recipes/1', headers=auth, json=BODY).status_code == 409


def test_recipe_edit_affects_future_sales_only_and_retry_keeps_original_sale(client, database, recipe_catalog, cart):
    with database() as session:
        first = checkout(session, cart, 1)
    before = history(database)
    assert client.put('/api/recipes/1', headers=headers(client, 'admin@example.test'), json=BODY).status_code == 200
    assert history(database) == before
    with database() as session:
        assert checkout(session, cart, 1) == first
    assert history(database) == before
    with database() as session:
        second = checkout(session, cart.model_copy(update={'request_key': 'new-recipe-checkout'}), 1)
    assert second['order_id'] != first['order_id']
    with database() as session:
        assert session.get(BranchStock, (1, 1)).quantity == Decimal('4.875')
        assert session.get(BranchStock, (1, 2)).quantity == Decimal('9.500')
    after = history(database)
    for table in ('orders', 'order_lines', 'loyalty_transactions', 'stock_movements'):
        for row in before[table]:
            assert row in after[table]


def test_failed_recipe_insert_rolls_back_removals_and_quantity_updates(database, recipe_catalog):
    before = recipe_state(database)
    def fail_insert(mapper, connection, target):
        raise RuntimeError('Simulated recipe write failure')
    event.listen(RecipeComponent, 'before_insert', fail_insert)
    try:
        with database() as session, pytest.raises(RuntimeError, match='recipe write failure'):
            save_recipe(session, 1, RecipeInput(**BODY))
    finally:
        event.remove(RecipeComponent, 'before_insert', fail_insert)
    assert recipe_state(database) == before
