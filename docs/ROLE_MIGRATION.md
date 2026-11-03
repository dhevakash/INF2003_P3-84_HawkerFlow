# Role migration 001: test rehearsal

This document records the historical Step 3 test rehearsal. The full upgrade is
now delivered through migration 002 and the coordinated release described in
ACCOUNT_ACTIVATION_AND_ROLLOUT.md. The standalone migration 001 CLI below remains
test-only; do not use it as the live rollout entry point.

## Mapping and preserved identities

- `manager` becomes `staff` on the same account row.
- `cashier` becomes `staff` on the same account row.
- `customer` remains `customer`.
- Account IDs, emails, password hashes, customer links, historical orders, stock
  receipts, and MongoDB review/reply references must remain intact.
- No existing operational account is promoted to Admin. Initial Admin setup is
  a separate later implementation step.

The final `users.ck_user_role` constraint allows `admin`, `staff`, and `customer`.
This is a database-role migration, not proof that the new roles can already sign
in and use the application with their final permissions.

## Migration behavior

The migration is `database/migrations/001_admin_staff_customer.py`. It requires
an explicit `ROLE_MIGRATION_DATABASE_URL`; it never defaults to the live
application URL. This rehearsal release refuses database names that do not end
in `_test` and refuses database engines other than MariaDB.

It validates the existing roles and constraint, obtains a migration lock, then:

1. Replaces the role check with a temporary check allowing both old and new roles.
2. Updates the two legacy roles to `staff`, preserving every account row.
3. Replaces the temporary check with the final three-role check.
4. Checks that only the intended account role values changed.

Each constraint replacement uses a single `ALTER TABLE` statement. MariaDB DDL
commits implicitly, so the whole sequence cannot be rolled back as one
transaction. The phases support rerunning after an interruption. A completed
migration is a no-op on repeat runs.

There is no automatic downgrade: combining Manager and Cashier into Staff loses
the distinction between their old roles. Recovery must use the original
per-account snapshot or a verified backup, rather than guessing which Staff
accounts used to be Managers.

## Running the test rehearsal

Use the restored database `hawkerflow_restore_20261030_165503_test` and the
project's installed SQLAlchemy/PyMySQL dependencies. Set
`ROLE_MIGRATION_DATABASE_URL` to its connection URL, then run the migration
script with Python. It can run without importing the old application's models.

For the automated rehearsal, set `RUN_ROLE_MIGRATION_INTEGRATION=1` and run
`tests/test_role_migration.py` with Python or the project test runner. The script
checks target safety, allowed and rejected roles, unchanged account fields,
historical order/receipt preservation, absence of an implicit Admin, and
repeatability. The two target-guard tests run without a database; the integration
tests are skipped unless explicitly enabled.

After the rehearsal, compare all SQL tables, both reporting views, all MongoDB
collections, indexes, validators, and purchase/account references against the
pre-migration snapshot. Only the SQL user-role values and role check should differ.
Record the outcome and retained account IDs before moving to backend permissions.

## Later application upgrade

Update the model/generated schema, backend role checks, customer-only signup,
initial Admin setup, seeds, fixtures, and website controls together before
applying the migration to live data. Staff review permissions are read/reply
only; Staff have no preference-profile permissions. Admin owns cross-customer
review/profile administration. Customers retain their own self-service access.

Reference: [MariaDB ALTER TABLE](https://mariadb.com/docs/server/reference/sql-statements/data-definition/alter/alter-table)
and [implicit commits](https://mariadb.com/docs/server/reference/sql-statements/transactions/sql-statements-that-cause-an-implicit-commit).
