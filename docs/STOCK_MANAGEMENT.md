# Stock management

Admin can correct existing ingredient quantities, in addition to receiving deliveries.
Staff can receive deliveries and read stock movements. Customers cannot manage stock.

## Correct a quantity

1. Sign in as Admin and open **Stock**.
2. Choose a **Branch** and **Ingredient** in **Correct stock quantity**, or choose
   **Edit stock** beside the relevant table row. The current balance loads automatically.
3. Enter the correct quantity in the displayed unit and explain the reason.
4. Choose **Save stock correction** and confirm.

The quantity can increase, decrease or become zero. Negative quantities are rejected.
Branch and Ingredient are dropdowns of configured stock records. Quantity fields
accept plain digits and up to three decimal places. Letters, `e`/`E` exponent
notation, signs and commas are rejected in the form and in string API quantities.
Receipt Branch and Ingredient IDs must be integer JSON values.
**Stock movements** records the old and new quantities, signed difference, Admin account
ID, reason and time. Adjustments cannot be edited or deleted through the API.

If a sale, receipt or another correction changes that stock after it was displayed,
the backend rejects the stale correction. Refresh Stock, select the row again and
review its latest balance before submitting.

Use **Receive ingredients** for actual deliveries; it creates a receipt rather than
replacing the current balance. Neither operation edits any existing order, order line,
historical price, customer points transaction or account ID. Already placed orders
have no edit or delete endpoint, including for Admin.

## Database upgrade

Fresh databases created from the current models include the adjustment table and
movement link. Existing databases need migration `003_stock_adjustments.py` after
the role and activation upgrades. A verified SQL backup and a test restore must
precede a live upgrade. MariaDB DDL commits implicitly.

Build the new app image, stop app writes, then use an explicit intended database:

```powershell
docker compose build app
docker compose stop app
docker compose run --rm --no-deps -e STOCK_MIGRATION_DATABASE_URL=mysql+pymysql://hawkerflow:hawkerflow_dev@mariadb:3306/hawkerflow app python database/migrations/003_stock_adjustments.py --database hawkerflow --allow-live
docker compose up -d --no-deps app
```

The migration preserves existing rows, checks the known movement constraint, adds
the adjustment table and nullable foreign key, and verifies all original table
contents. Repeating it reports `already_applied`. Without `--allow-live`, only a
matching, explicitly selected `hawkerflow_*_test` database is accepted.
