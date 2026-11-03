# Step 4: backend role enforcement

Backend role enforcement is implemented and deployed for Admin, Staff and
Customer. Signup, Admin setup, website controls and account activation are also
delivered. See ACCOUNT_ACTIVATION_AND_ROLLOUT.md and the final release evidence.

## Role checks

`app/roles.py` defines the canonical roles. Login and every authenticated request
reject unknown or unmigrated roles. The server loads the current role from the
account table on each request, so promotion/demotion applies to existing tokens.
The tokens carry account identity, not a caller-selected role.

| Backend operation | Allowed roles |
|---|---|
| Menu changes, customer operations, checkout, stock receipts/movements, recipes, SQL/MongoDB analytics | Admin, Staff |
| Shared menu/branch reads | All three signed-in roles |
| Orders, loyalty history, review reads | Admin/Staff: all; Customer: own records only |
| Create/edit/delete purchase reviews | Admin: verified purchase context; Customer: own verified purchases |
| Add a business reply | Admin, Staff |
| Edit/delete a business reply | Admin only |
| Own preference profile | Customer; Admin when linked to a customer record |
| List or manage any customer's preference profile | Admin only |
| Change an account's role | Admin only |

Staff cannot create, edit, delete, or moderate purchase reviews; cannot edit or
delete even their own business replies; and cannot read or change preference
profiles. These restrictions apply to direct HTTP requests, regardless of the
website's visible controls.

## Administrative endpoints

- `PUT /api/accounts/{account_id}/role`: for example, body `{"role":"staff"}`;
  the permitted values are `admin`, `staff`, and `customer`.
  Keeps the account ID, email, password hash, and customer link. It protects the
  last Admin and requires a linked customer before assigning the Customer role.
- `PUT /api/reviews/{order_id}` and `DELETE /api/reviews/{order_id}` now allow
  Admin review administration, while retaining Customer ownership restrictions.
- `PUT /api/reviews/{order_id}/replies/{reply_index}` and the corresponding
  `DELETE` endpoint are Admin-only. Reply indices are zero-based. The server
  checks the expected reply array before updating, returning `409` if it changed.
- `GET /api/profiles` lists profiles for Admin.
- `GET`, `PUT`, and `DELETE /api/profiles/{customer_id}` administer one customer's
  profile. The SQL customer must exist. Staff and Customer callers are rejected
  before MongoDB is accessed.

Review administration preserves purchase/customer identity and original author
references. New reviews and edits record the acting account ID. Editing a
business reply retains its original `manager_user_id`; that historical field is
not renamed or reassigned.

## Supporting schema and seed updates

The application model and regenerated SQL schema use the new role values. The
demo operational accounts retain their existing email addresses but seed as
Staff. Seeded sales and stock receipts look up the actual account ID, so an
initial Admin created beforehand will not be overwritten or accidentally used
as the historical cashier. Repeated demo seeding remains supported.

## Validation

- 84 unit/regression tests passed; 6 opt-in migration integration tests were
  skipped in that run (their separate step 3 rehearsal already passed).
- 8 additional direct API tests passed against the real migrated MariaDB copy
  and isolated MongoDB fixture databases.
- Tests cover all three role logins, operational permissions, forbidden requests,
  review/profile ownership and administration, account role changes, existing
  token behavior, last-Admin protection, and seed identity preservation.
- SQL integration changes were rolled back. Only freshly created, uniquely
  named MongoDB fixture databases were removed. Restored test records, IDs, and
  historical references were preserved; live records and schemas were unchanged.

The recorded result is `evidence/backend-permissions-step4.md`.

## Remaining agreed steps

Public Customer-only signup, protected privileged-account creation, repeatable
initial Admin setup, and website navigation/forms remain to be implemented.
No persistent initial Admin has been created by this step. Do not rebuild the
live app with these backend changes until the live account-role migration and
the remaining setup/UI changes are ready together.

Implementation references: [FastAPI dependencies and permissions](https://fastapi.tiangolo.com/advanced/security/oauth2-scopes/),
[SQLAlchemy external test transactions](https://docs.sqlalchemy.org/en/20/orm/session_transaction.html),
and [MongoDB conditional atomic updates](https://www.mongodb.com/docs/manual/core/write-operations-atomicity/).
