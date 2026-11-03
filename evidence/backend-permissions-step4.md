# Step 4: backend role permissions

Result: PASS

Backend source is ready for the coordinated role upgrade; the live app has not been rebuilt or migrated.

## Implemented behavior

- Admin and Staff can use the prior Manager/Cashier operational features.
- Staff can read reviews and add replies; review/reply edits or deletion and every preference-profile endpoint reject Staff.
- Admin can manage reviews, replies and customer preference profiles, and assign account roles.
- Customers retain their own review/profile access and cannot cross ownership boundaries.
- Unknown and unmigrated roles fail closed. Existing tokens use the account role currently stored in the database.
- Role assignment preserves account identity and protects the last Admin.
- Models, generated SQL, fixtures and demo seed role values use the canonical roles.

## Test results

- Unit/regression: 84 passed, 6 opt-in tests skipped.
- Real MariaDB/MongoDB API tests: 8 passed.

## Data preservation

- unit and existing regression tests pass: PASS
- real mariadb mongo api tests pass: PASS
- live records and schema unchanged: PASS
- migrated test sql records preserved after rollback: PASS
- migrated test account ids roles links preserved: PASS
- historical order account links preserved: PASS
- restored mongo documents indexes validators unchanged: PASS
- no broken test references: PASS

## Remaining steps

Customer-only public signup, privileged account creation/setup, the initial Admin, and website navigation remain for the subsequent agreed steps.
No initial Admin was created in live or restored data; real API tests used rolled-back temporary accounts and private MongoDB fixture databases.
