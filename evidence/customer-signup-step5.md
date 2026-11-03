# Step 5: customer-only public signup

Result: PASS

Signup source is ready for the coordinated role upgrade; the live app has not been rebuilt or migrated.

## Implemented behavior

- Public POST /api/auth/signup accepts only name, email and password; the server always assigns Customer.
- Submitted roles, privileged flags, account/customer IDs, points and password hashes are rejected.
- Customer and login records are inserted in one transaction; a failed second write rolls back the customer.
- Existing accounts and customer history cannot be claimed or overwritten by signing up with their email.
- Passwords are hashed; successful responses contain no password or password hash.
- New customers can sign in and are blocked from Staff/Admin operations.
- The prior backend permission tests continue to pass.

## Test results

- Unit/regression: 122 passed, 6 opt-in tests skipped.
- Real MariaDB/MongoDB API tests: 15 passed.

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

Privileged account creation/setup, the initial Admin, and website signup/navigation remain for the subsequent agreed steps.
No initial Admin was created in live or restored data; real API tests used rolled-back temporary accounts and private MongoDB fixture databases.
