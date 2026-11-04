# Admin customer point corrections

Deployed locally at http://localhost:8080 on 2026-11-04.

Admin has **Edit points** and **Remove points** controls in Points history, plus
a customer selector for balances with no recent history. Editing sets the corrected
total; removing deducts a chosen amount. Both require whole numbers, a reason and
confirmation showing the before/after balance. Removal cannot make a balance negative.

The backend independently rejects Staff, Customer and unauthenticated corrections.
The customer row is locked and the displayed balance is checked before mutation.
The balance and a `loyalty_adjustments` audit entry commit together. Original
earnings, redemptions, orders, stock movements and account IDs remain intact.
Customers read only their own history; private investigation notes and Admin
audit fields are returned only to Admin. Checkout rejects point overflow cleanly.

## Verification

- 275 Python tests passed; 6 opt-in migration cases skipped and 42 integration
  cases deselected in that run.
- 46 interface tests passed, including correction/removal buttons, confirmation,
  invalid numbers/reasons, stale balances, non-Admin denial, safe note rendering
  and clearing private drafts on logout.
- 9 tests passed against real MariaDB/MongoDB. New concurrency cases covered
  corrections competing with earning, redemption and other corrections. Balances
  matched the original balance plus all committed ledger/audit changes.
- 11 interface flows passed against an isolated real HTTP app backed by disposable
  MariaDB/MongoDB databases. The new flow completed a sale, corrected/removed points,
  verified the actual SQL-backed balance and audit, preserved the original order,
  earning and stock movements, and checked ownership and backend denials.
- Migration 004 was rehearsed on a restored SQL backup, including idempotent repeat.
  Immediately before live migration, the app was stopped, a fresh SQL backup was
  taken, and that backup was restored and migrated successfully in another test DB.
  The live migration verified every original table's rows were unchanged.
- 13 live checks passed for deployed assets, all three role flows, draft controls,
  rejected invalid/stale/forbidden writes, unchanged balances and database health.
  All live SQL tables were fingerprinted before/after these checks and were unchanged.
  No valid customer points mutation was submitted to the live app during verification.

Backup: `C:\Users\cheet\HawkerFlow-backups\20261104-084008-before-points-edit\mariadb-predeploy.sql`.
Previous image: `hawkerflow-before-points-edit:20261104-084008`.
Reports and release manifest are in the ChatGPT project mirror under
`output/hawkerflow-loyalty/`. Owned disposable preview/test databases were removed.
See `docs/POINTS_CORRECTIONS.md` for operation, API and upgrade instructions.

Interface automation uses jsdom and live HTTP APIs rather than a native-browser
visual review. SQL and HTTP integration results are distinct from DOM-only tests.
