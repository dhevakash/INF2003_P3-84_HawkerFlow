# Customer point corrections

Admin can update a customer's available point balance or remove a chosen number of
points. Staff and Customers cannot perform manual corrections. Staff retain the
normal checkout earning/redemption operations; Customers can read their own history.

## Edit or remove points

1. Sign in as Admin and open **Points history**.
2. Use **Edit points** or **Remove points** beside a customer's history entry, or
   choose the customer in **Correct customer points** above the history.
3. **Set total balance** takes the corrected total. **Remove points** takes the
   amount to deduct from the available balance. A positive history-row amount is
   suggested when opening Remove points from that row; review it before saving.
4. Enter a reason, choose **Save points change**, review the before/after balance
   in the confirmation, and confirm.

Values must be whole numbers. Balances stay between zero and 2,147,483,647; removals
must be positive and cannot exceed the available balance. Removing the entire
available amount sets the balance to zero. Selecting customers with no recent
history is supported through the customer dropdown.

The balance is updated directly in SQL in the same transaction as an immutable
`loyalty_adjustments` audit entry. It records the customer, Admin account ID, action,
reason, signed change, previous balance, new balance and UTC time. Corrections
appear as **adjustment** entries with IDs prefixed by **A** in the website history.
Admins can open **Correction details** to see the audit information. Staff and
Customer history responses omit the private investigation note and Admin details;
Customers receive only their own entries.

Original earnings, redemptions, orders, account IDs and stock movements are not
edited or deleted. Removing points deducts available points; it does not delete
the selected historical transaction. This preserves evidence for fraud review.

## Consistency and API

Corrections lock the customer row, as checkout does, and require the previously
displayed balance. An intervening sale, redemption or correction causes a stale
edit to fail with `409`. Refresh Points history and select the customer again.
No-op corrections are rejected. An audit-write failure rolls back the balance.

Admin-only endpoints:

- `PUT /api/loyalty/customers/{customer_id}/points` with integer `points`, integer
  `expected_points` and a nonblank `reason`.
- `POST /api/loyalty/customers/{customer_id}/points/removals` with integer `amount`,
  integer `expected_points` and a nonblank `reason`.

Unauthenticated requests receive `401`; other roles receive `403`. Ordinary
customer updates do not accept point changes. Existing completed checkouts remain
idempotent, and subsequent checkout/redemption operations use the corrected balance.

## Existing database upgrade

Fresh databases include the audit table. Existing installations need migration
`004_loyalty_adjustments.py`, which adds the table without modifying old rows.
Verify a SQL backup and restore rehearsal first, then build and deploy:

```powershell
docker compose build app
docker compose stop app
docker compose run --rm --no-deps -e POINTS_MIGRATION_DATABASE_URL=mysql+pymysql://hawkerflow:hawkerflow_dev@mariadb:3306/hawkerflow app python database/migrations/004_loyalty_adjustments.py --database hawkerflow --allow-live
docker compose up -d --no-deps app
```

The explicit database must match the connection. Without `--allow-live`, only a
dedicated `hawkerflow_*_test` database is accepted. Repeating the migration validates
the existing table and reports `already_applied`. MariaDB DDL commits implicitly.
