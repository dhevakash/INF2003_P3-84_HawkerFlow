# Admin stock editing

Deployed locally at http://localhost:8080 on 2026-11-03.

Admin can select **Stock → Edit stock**, change a quantity up or down (including
zero), enter a reason and confirm. Staff retain receipt entry and movement history;
they cannot correct balances. Customers cannot manage inventory. The backend
enforces these boundaries independently of visible controls.

Each correction writes the before/after quantities, actor account ID, reason and
timestamp, plus a signed stock movement in the same transaction. A row lock and
comparison with the displayed quantity prevent overwriting intervening sales,
receipts or corrections. Already placed orders remain read-only for every role.

## Verification

- 198 Python tests passed; 6 opt-in migration tests skipped and 35 integration
  cases deselected in that run.
- 30 interface regression tests passed.
- 4 tests passed against real MariaDB/MongoDB, including competing checkouts and
  simultaneous correction/correction and correction/checkout attempts.
- 9 interface tests passed against an isolated real HTTP app backed by disposable
  MariaDB/MongoDB databases. The new flow verified quantity correction, audit
  history, stale-edit rejection, Staff/Customer denial and unchanged placed orders.
- Migration 003 was rehearsed on a restored SQL backup; repeating it reported
  `already_applied`. A fresh backup taken while app writes were stopped was also
  restored and migrated successfully before applying the live schema upgrade.
- Live migration verified that every original table's original column values
  remained unchanged. No account IDs or historical orders were rewritten.
- 11 live checks passed: deployed assets match source, all three roles sign in,
  stock controls follow role rules, backend permissions and order protection hold,
  both databases connect, and live stock/order values remain unchanged by checks.

Interface automation uses jsdom with browser named-form-property behavior and real
HTTP APIs; it does not constitute a native-browser visual review.

Backup: `C:\Users\cheet\HawkerFlow-backups\20261103-161107-before-stock-edit\mariadb-predeploy.sql`.
Previous app image: `hawkerflow-before-stock-edit:20261103-161107`.
Release manifest and live report are in the ChatGPT project mirror under
`output/hawkerflow-stock-edit/`. Disposable preview/test databases were removed.
See `docs/STOCK_MANAGEMENT.md` for operation and migration details.
