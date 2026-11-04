# Step 5: Customer-only public signup

Customer-only public signup, the website form, Admin setup and protected account
creation are implemented and deployed. See ACCOUNT_ACTIVATION_AND_ROLLOUT.md and
the final release evidence for the delivered system.

## API

Send `POST /api/auth/signup` without needing a login. The only accepted JSON
fields are `name`, `email`, and `password`, plus optional `birthday` and
`confirm_password`, for example:

```json
{
  "name": "Alex Tan",
  "email": "alex@example.test",
  "password": "ChooseYourOwnPassword",
  "confirm_password": "ChooseYourOwnPassword",
  "birthday": "2000-02-29"
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
- Birthday is optional. Omit it or send `null` to leave it unset. A supplied date
  must use `YYYY-MM-DD`, be a real calendar date on or after `1000-01-01` (the
  supported SQL DATE range), and not be in the future in Singapore time.
- The website requires matching password confirmation and sends it to the server.
  The API also checks confirmation whenever it is supplied; existing API clients
  sending only a password remain supported. Confirmation is never stored.

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

- The signup suite covers successful signup/login, password hashing, role/ID
  injection, duplicates across both tables, invalid details, leap days, future
  birthdays, confirmation mismatch, insert failure/rollback, and ownership.
- Real MariaDB tests exercise competing signups for the same email and a failed
  second insert, verifying one complete account or no account, respectively.
- The website is exercised against disposable MariaDB/MongoDB databases, including
  immediate sign-in, a zero balance, empty own purchases and loyalty history,
  and saved birthdays. See `evidence/CUSTOMER_SIGNUP_BIRTHDAY.md` for current results.

## Customer account summary

After signing in, Customers see their current **Points balance** and saved birthday
(when supplied), plus **View my purchases**. A new account has zero points and no
purchases or loyalty entries. The summary refreshes from `GET /api/customers/me`,
which uses the authenticated customer link; query parameters cannot choose another
customer. Staff and Admin receive 403 on this self-service endpoint. Birthdays are
not returned by the operational customer list. Logout and access changes clear
the private summary.

Birthday is stored in MariaDB `customers.birthday` as a nullable DATE. Existing
customers retain `NULL`; no birthday, reward, age restriction or promotion is
invented for them. Birthday-based features can be added separately later.

## Existing database upgrade

Fresh installations use the updated model/generated schema. For an existing
database, back up both stores and rehearse `005_customer_birthday.py` twice on a
restored SQL copy first. It adds only the nullable birthday column, verifies all
existing rows, and preserves any birthdays when rerun. Apply it before starting
the updated app image:

```powershell
docker compose run --rm -T --no-deps -e BIRTHDAY_MIGRATION_DATABASE_URL=mysql+pymysql://hawkerflow:hawkerflow_dev@mariadb:3306/hawkerflow app python database/migrations/005_customer_birthday.py --database hawkerflow --allow-live
```

Use an app image containing migration 005, or mount the current repository at
`/code` with `PYTHONPATH=/code` during the migration. The explicit live option is
needed only for an existing local/live database; rehearsal targets must have
matching `hawkerflow_*_test` names.

Implementation references: [Pydantic extra-field validation](https://docs.pydantic.dev/latest/concepts/models/)
and [SQLAlchemy transaction framing](https://docs.sqlalchemy.org/en/20/orm/session_basics.html).
