# Step 6: initial Admin and protected account creation

Initial Admin setup, protected account creation and the website controls are
implemented and deployed. The first Admin is a separate account; historical
identities are preserved. See ACCOUNT_ACTIVATION_AND_ROLLOUT.md for the release.

## Initial Admin on a fresh installation

After building the upgraded app against a new database:

```powershell
docker compose exec app python -m app.cli init-db
docker compose exec app python -m app.cli init-admin
docker compose exec app python -m app.cli seed
```

Enter an email and a nonblank password of 12-128 characters. Password entry is
hidden and requires confirmation. Do not use `-T` for interactive setup: it
needs a terminal capable of hiding password input. You can supply the email as
`init-admin --email your-address@example.com`; there is no password command
argument. An email must have the basic format accepted by customer signup.

Setup creates a separate Admin account with a generated ID and no customer
association. Existing Staff accounts are never promoted or replaced. No customer
points, orders, review authorship or account links are modified.

If **any** Admin already exists, setup returns its ID without asking for new
credentials, adding another Admin, changing its email or resetting any password.
Use protected account administration to create subsequent privileged accounts.

The optional `HAWKERFLOW_INITIAL_ADMIN_PASSWORD` environment variable supports
explicit unattended provisioning. A supplied value is validated and is never
printed; an empty value fails. Prefer interactive setup for local use, and keep
secrets out of shell arguments, source files and committed configuration.

Imports, web startup, schema initialization and demo seeding never create an
implicit Admin or use a default Admin password.

## Existing installations

Complete the role migration and deploy the upgraded app together before running
`init-admin` against the intended upgraded database. The current migration script
is intentionally a **test rehearsal** and refuses live database names; see
[ROLE_MIGRATION.md](ROLE_MIGRATION.md). Do not bypass that guard or recreate the
database. Initial Admin setup refuses legacy/unknown stored roles.

Existing `manager` and `cashier` accounts become Staff in place. Their IDs,
passwords, emails, customer links and historical order references remain intact.
Initial Admin setup then adds the separate Admin if none exists.

Setup uses a database-specific MariaDB `GET_LOCK` on a pinned connection until
its transaction finishes. Concurrent setup attempts therefore create only one
initial Admin. The lock is explicitly released before returning the connection
to the pool, including on failure. SQLite preview uses `BEGIN IMMEDIATE` before
checking for an existing Admin. A failed insert rolls back; a corrected retry
can run safely.

## Admin-only creation API

Sign in as Admin through `POST /api/auth/login`, then send:

```http
POST /api/accounts
Authorization: Bearer <admin access token>
Content-Type: application/json
```

```json
{
  "email": "new-staff@example.com",
  "password": "<new password of 12-128 characters>",
  "role": "staff"
}
```

The role must explicitly be `staff` or `admin`. A successful response is
`201` and contains only `id`, `email`, `role` and `customer_id: null`.
Passwords are stored using the existing salted password hashing function and
are never returned. New accounts sign in through the normal login endpoint.

- No valid session: `401`.
- Staff or Customer caller: `403`; creating a privileged account is forbidden.
- Invalid/missing role, invalid credentials or extra fields: `422`.
- Email already used by an account or customer record: `409`; the existing
  identity is not claimed, relinked, promoted or overwritten.
- Injected IDs, customer links, password hashes, points and privileged flags are
  rejected. The database assigns new account IDs.

The operation rechecks the actor's stored Admin role while holding Admin rows
in the same order as role changes. An Admin demotion that finishes first prevents
the creation from proceeding. Creation and role changes therefore use the
database permission state instead of relying solely on the website or JWT.

Public `POST /api/auth/signup` still creates **Customer only**, even for a signed-in
Admin. Customer creation belongs to that separate flow; protected privileged
creation does not attach accounts to historical customer records.

## Verification

`tests/test_account_setup.py` checks initial setup, repeat setup, concurrent
SQLite setup, hidden CLI entry, invalid input, transaction rollback, new account
sign-in, unauthorized requests, duplicate identities and stale authorization.

`tests/integration/test_initial_admin_real.py` checks committed setup and
concurrent connections in uniquely owned temporary MariaDB databases. Each
database is removed by its fixture. The expanded
`tests/integration/test_backend_roles_real.py` checks privileged creation and
sign-in against the restored MariaDB data with rollback, alongside real MongoDB
review/profile permission checks.

See [the Step 6 verification evidence](../evidence/account-setup-step6.md) for
the actual results and preservation checks. No persistent initial Admin has been
created in the live database during these tests.

References: [MariaDB GET_LOCK](https://mariadb.com/docs/server/reference/sql-functions/secondary-functions/miscellaneous-functions/get_lock)
and [SQLAlchemy transaction management](https://docs.sqlalchemy.org/en/20/orm/session_transaction.html).
