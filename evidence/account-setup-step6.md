# Step 6: initial Admin and protected account creation

Result: PASS

The tested source is ready for the coordinated role upgrade. The live website has not been rebuilt or migrated.

## Implemented behavior

- Explicit init-admin setup prompts for an email and a hidden, confirmed password.
- If any Admin already exists, setup does not request credentials, create another Admin or reset a password.
- Concurrent setup processes create one initial Admin using a MariaDB named lock or SQLite immediate transaction.
- Setup inserts a separate Admin; existing Staff/Customer identities and purchase references are preserved.
- Authenticated Admins can POST /api/accounts to create Staff or additional Admin accounts.
- The stored Admin role is rechecked under the same row-lock order used for role changes.
- Unauthenticated callers receive 401 and Staff/Customer callers receive 403 with no account changes.
- Privileged account creation rejects injected IDs/customer links and duplicate existing emails.
- New Admin and Staff accounts can sign in; public signup remains Customer-only.

## Test results

- Unit/regression: 162 passed; 6 opt-in migration tests skipped.
- Real MariaDB/MongoDB API and setup: 29 passed.

## Data preservation

- unit and regression tests pass: PASS
- real mariadb mongo api and setup tests pass: PASS
- live records and schema unchanged: PASS
- restored test sql records preserved after rollback: PASS
- restored account ids roles customer links preserved: PASS
- historical order account links preserved: PASS
- restored mongo documents indexes validators unchanged: PASS
- no broken test references: PASS
- owned temporary setup databases removed: PASS

## Rollout status

No persistent initial Admin was created in the live or restored databases. Setup tests used owned temporary SQL databases, which were removed; API tests rolled back their SQL changes.
Choose the initial Admin credentials when performing the coordinated upgrade. Website forms/navigation are the next agreed step.
