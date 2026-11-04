# Admin recipe editing

Deployed locally at http://localhost:8080 on 2026-11-04.

Admin can create or edit recipes with a menu-item dropdown, ingredient dropdowns,
quantities per serving, displayed units, Add/Remove ingredient controls and a save
confirmation. Staff can read named recipes; Customers cannot access them.
The backend independently enforces Admin-only writes.

Each save replaces a complete recipe in one transaction. Stale edits are rejected.
Recipes need distinct, existing ingredients and positive quantities with at most
three decimal places. Zero, negative, exponent strings, duplicate ingredients,
missing records and empty recipes are rejected.

Recipe saves and checkout share the menu-item lock. Checkout reads current recipe
components under a lock after waiting for a save, preventing partial recipes and
stale transaction snapshots. Existing orders, lines, movements, stock balances,
points and account IDs are not rewritten. Only subsequent sales use new quantities.
No database migration was needed.

## Verification

- 237 Python tests passed; 6 opt-in migration cases skipped and 39 integration
  cases deselected in that run.
- 39 interface tests passed, including recipe creation/editing, units, add/remove,
  confirmation/cancellation, validation, stale errors and non-Admin denial.
- 6 tests passed against real MariaDB/MongoDB, including concurrent recipe editors
  and a checkout waiting for a recipe save. That checkout deducted the complete
  new recipe, rather than its earlier transaction snapshot.
- 10 real HTTP interface tests passed against disposable MariaDB/MongoDB databases.
  The recipe flow created a recipe, sold an item, edited the recipe, verified that
  historical records and stock stayed unchanged by the edit, and verified that a
  later sale used the new quantities. Removing an ingredient preserved both sales.
- 11 live checks passed, including deployed asset equality, all three role flows,
  draft editing, backend denials, validation and stale-edit rejection.
- All live SQL tables were fingerprinted before and after live checks. Recipes,
  accounts, orders, movements and other SQL records were unchanged by verification.
  No valid live recipe mutation was submitted.

The app service was rebuilt and recreated. Versioned HTML asset references and
cache revalidation deliver the new editor on reload. Disposable preview/test
databases were removed; user databases were retained.

Interface automation uses jsdom with live HTTP APIs, not a native-browser visual
review. Reports are in the ChatGPT project mirror under `output/hawkerflow-recipes/`.
See `docs/RECIPE_MANAGEMENT.md` for the operating instructions and API behavior.
