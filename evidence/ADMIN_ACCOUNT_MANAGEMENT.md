# Admin account management verification

Verified on 4 November 2026. The local Docker app at `http://localhost:8080` was rebuilt with the account tools. Both live databases were backed up before the rebuild; no MariaDB schema migration was needed.

## Results

- **340 Python backend tests passed.** Six optional migration tests skipped; 44 integration cases were excluded from this unit/API run. Checks include all three roles, strict account payloads, atomic Customer creation, duplicate email conflicts, preserved identities/history, password/session revocation, last-Admin protection, deletion checks and Mongo availability failure.
- **55 DOM UI tests passed.** These cover default active accounts, global search including disabled accounts, status views, Customer dropdown/name input, email/name editing, reset confirmation, password clearing, own-password sign-out, deletion confirmation and forged Staff/Customer controls.
- **11 real MariaDB/MongoDB transaction tests passed.** These include a concurrent checkout versus unused-account deletion, and a concurrent Mongo reply versus account disable/delete. The author account and reply were retained.
- **13 UI-to-HTTP integration flows passed** against a separately seeded disposable MariaDB/MongoDB preview. They exercise Customer creation, edited identity, password reset and revocation, safe unused-account deletion, linked purchase/reply rejection, and the established role, stock, recipe, points and review flows.
- **Localhost verification passed.** Admin, Staff and Customer sign-in succeeded; deployed HTML/JS/CSS match source and use revalidation. Admin account search/status views and editors work. Staff/Customer account-management requests return 403. Invalid/unsafe Admin requests are rejected. These live checks submitted no valid data mutations.
- Before/after fingerprints confirmed **all records unchanged across 14 live SQL tables and three Mongo collections**, including **54 accounts and 200 orders**. Passwords, account IDs, customer links, points and purchase records were preserved.

UI verification used jsdom with mocked and real HTTP responses; it did not include a native browser visual inspection. The disposable preview and both sets of owned test databases were removed after checks.

See [account management](../docs/ACCOUNT_MANAGEMENT.md) for the controls, API contracts and deletion rules.
