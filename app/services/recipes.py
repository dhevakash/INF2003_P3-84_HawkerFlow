"""Replace a complete recipe while holding the same parent lock as checkout."""
from sqlalchemy import select

from app.models import Ingredient, MenuItem, RecipeComponent
from app.services.checkout import BusinessError


def save_recipe(session, item_id, payload):
    with session.begin():
        item = session.scalar(select(MenuItem).where(MenuItem.id == item_id).with_for_update())
        if item is None:
            raise BusinessError('Menu item not found.', 404)
        current = {row.ingredient_id: row for row in session.scalars(select(RecipeComponent)
            .where(RecipeComponent.menu_item_id == item_id)
            .order_by(RecipeComponent.ingredient_id).with_for_update())}
        expected = {row.ingredient_id: row.quantity for row in payload.expected_components}
        if {key: row.quantity for key, row in current.items()} != expected:
            raise BusinessError('This recipe has changed. Refresh Recipes and select the menu item again.')
        wanted = {row.ingredient_id: row.quantity for row in payload.components}
        known = set(session.scalars(select(Ingredient.id).where(Ingredient.id.in_(wanted))))
        if known != set(wanted):
            raise BusinessError('An ingredient no longer exists. Refresh Recipes and try again.', 422)
        for ingredient_id, row in current.items():
            if ingredient_id not in wanted:
                session.delete(row)
        for ingredient_id, quantity in wanted.items():
            if ingredient_id in current:
                current[ingredient_id].quantity = quantity
            else:
                session.add(RecipeComponent(menu_item_id=item_id, ingredient_id=ingredient_id, quantity=quantity))
        session.flush()
        result = {'menu_item_id': item_id, 'components': [
            {'ingredient_id': ingredient_id, 'quantity': format(quantity, '.3f')}
            for ingredient_id, quantity in sorted(wanted.items())]}
    return result
