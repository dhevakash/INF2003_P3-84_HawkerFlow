# Step 5: Customer-only public signup

Customer-only public signup, the website form, Admin setup and protected account
creation are implemented and deployed. See ACCOUNT_ACTIVATION_AND_ROLLOUT.md and
the final release evidence for the delivered system.

## API

Send `POST /api/auth/signup` without needing a login. The only accepted JSON
fields are `name`, `email`, and `password`, for example:

```json
{
  "name": "Alex Tan",
  "email": "alex@example.test",
  "password": "ChooseYourOwnPassword"
}
```

On success the endpoint returns `201` and the generated account ID, email,
`role: "customer"`, and customer ID. It never returns a password, password hash,
or login token. Sign in afterward using the existing `POST /api/auth/login`.

## Validation and server-owned values

- Names are trimmed, required, and limited to 120 characters.
- Emails are trimmed, lowercased, limited to 180 characters, and checked for
  basic email syntax. Duplicate checks and login are case-insensitive.
- Signup passwords must contain 12-128 characters and cannot consist entirely
  of whitespace. Password whitespace is preserved and passwords are hashed
  using the application's existing password hasher.
- A submitted `role` field is rejected with `422`, including `admin`, `staff`,
  or even `customer`. The server alone assigns `customer`.
- Privileged flags, nested account objects, account/customer IDs, points,
  password hashes, and all other extra JSON fields are rejected with `422`.
- Role query parameters or an existing Admin session cannot change the assigned
  signup role: a valid public signup still creates a Customer.
- The server sets opening points to zero and creates an active customer record.

## Atomic account creation and existing data

The customer and linked login account are created in one MariaDB transaction.
If either insert fails, neither record is retained. Database unique constraints
remain the final guard against duplicate inserts, including a duplicate race.

An email already present in either `users` or `customers` returns `409`.
Public signup does not reuse, claim, overwrite, promote, or reset that existing
record. This also protects operational customer records that do not yet have
login accounts: possession of an email string is not proof of ownership of that
customer's purchases or points.

Existing account IDs, passwords, roles, customer links, orders, and loyalty data
are preserved. New IDs are assigned by the database; the caller cannot select
them.

Signup does not write MongoDB or depend on it being available. The existing
customer profile endpoint can return default preferences until the customer
saves a preference profile.

## Validation results

- 122 unit/regression tests passed, including 38 signup tests.
- 15 API tests passed against real MariaDB/MongoDB test stores, including the
  previous role-permission tests and seven signup cases.
- Six separately enabled migration tests were skipped in the unit run; their
  step 3 rehearsal already passed.
- Tests cover successful signup/login, password hashing, role/identity injection,
  invalid details, duplicate emails, existing-customer ownership, failure of the
  second insert, rollback/retry, and Customer-only permissions after signup.
- Test SQL changes were rolled back, and temporary MongoDB fixture databases
  were removed. Live records/schemas and restored account/history data were
  verified unchanged.

The recorded result is `evidence/customer-signup-step5.md`.

## Remaining agreed steps

Implement repeatable initial Admin setup and protected privileged-account
creation next. Add signup/navigation controls in the UI step. Rebuild and apply
the live role migration only when the coordinated upgrade is ready.

Implementation references: [Pydantic extra-field validation](https://docs.pydantic.dev/latest/concepts/models/)
and [SQLAlchemy transaction framing](https://docs.sqlalchemy.org/en/20/orm/session_basics.html).
