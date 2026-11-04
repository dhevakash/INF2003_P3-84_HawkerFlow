# Recipe management

Admin can create and edit recipes. Staff can read recipes with ingredient names,
quantities per serving and units. Customers cannot access recipes. Recipe writes
are protected by backend authorization, independently of website controls.

## Edit a recipe

1. Sign in as Admin and open **Recipes**.
2. Choose a menu item in the editor, or use **Edit recipe** beside a recipe.
3. Choose ingredients from the dropdowns and enter the quantity needed for one
   serving, using the unit shown. Use **Add ingredient** or **Remove ingredient**
   to change the list.
4. Choose **Save recipe**, review the confirmation, and confirm.

A new menu item can be selected to configure its first recipe. Each recipe needs
between 1 and 100 distinct ingredients with positive quantities and at most three
decimal places. Duplicate ingredients, zero, negative values and exponent quantity
strings are rejected. Ingredient units are read from the ingredient catalogue.

Saving replaces the recipe in one transaction. If another Admin has changed it
since it was loaded, the save is rejected: refresh Recipes and select the item
again to review the latest version.

## Historical data and checkout

Recipe changes apply to future sales. They do not change existing orders, order
lines, stock balances, stock movements, loyalty transactions or account IDs.
New sales deduct stock using the updated per-serving quantities. Retrying an
already completed checkout still returns its original order without new deductions.

Recipe editing and checkout lock the same menu item before reading or changing
components. Checkout reads the current components under a lock, so a sale cannot
use a partly saved recipe or an older transaction snapshot after waiting for an edit.

The feature uses the existing `recipe_components` table; no database migration is
needed. The API provides `GET /api/recipes`, `GET /api/ingredients` for operational
roles, and Admin-only `PUT /api/recipes/{item_id}`. A write supplies `components` and
the previously displayed `expected_components`; both are lists of ingredient IDs
and quantities. No ingredient can appear twice in either list.
