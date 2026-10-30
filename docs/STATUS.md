# Implementation status

## Working starter code

- SQL model with 12 tables, one-to-many and many-to-many relations, DECIMAL money, foreign keys, checks, unique keys and indexes.
- Manager menu create/read/update/delete. Deleting an item used by historical sales is blocked; it can instead be marked inactive.
- Customer create/read/update, order history, points ledger, ingredient stock and audited receipts.
- Atomic checkout with recipe-based deduction, locked stock/customer records, a unique request key, payload comparison on retry and snapshotted prices.
- MongoDB review create/read/update/delete, manager replies, customer preferences, validators and indexes.
- Negative-tag aggregation and monthly ratings; SQL reporting views, join aggregates, CTE/window ranking and a nested aggregate query.
- Synthetic seed: five fictional branches, 50 customers, 20 menu items, 15 ingredients, 200 orders; 40 synthetic purchase reviews and 50 preference documents when MongoDB is configured.
- Browser login, data tables, single-item checkout, restock form and review submission. The API supports multi-item checkout and the other CRUD actions.
- Runnable matched benchmark and opt-in real DBMS tests. These are experiment tools, not measured findings.

## Intentionally unfinished

1. Recipe create/update/delete and branch/ingredient administration screens. Recipes are currently seeded and readable; a new menu item cannot be sold until its recipe is configured. Add recipe editing with validation and consistent locking before changing recipes during live checkout.
2. Menu/customer CRUD forms, multi-item cart controls, review editing/deletion, manager reply and profile forms in the UI. Their existing API endpoints can be demonstrated in `/docs` while these screens are built.
3. Real DBMS concurrency, validation, outage and performance evidence on your machines.
4. The actual UCI Yelp sentence dataset. Only the supplied readme is bundled. The import command fails clearly if the real data is absent or its row count is wrong.
5. Migration tooling: `create_all()` constructs missing tables but does not migrate existing columns. Add Alembic or versioned migrations before evolving the schema with retained data.
6. Account management, password resets, per-cashier branch assignment, pagination beyond the first 100 API rows, production deployment hardening, and conflict-aware review editing.
7. Optional extra-credit analytics, if chosen after the core features work: rolling ingredient usage forecast and explainable reorder suggestions. Expiry-batch allocation, refunds and payment gateways remain outside the initial proposal scope.

## Evidence boundary

The local automated suite exercises domain/API behavior using SQLite and checks pipeline construction. It does not verify MariaDB/InnoDB locking, MariaDB CHECK enforcement or MongoDB server validators. Real-server tests are explicitly marked `integration` and opt-in. This environment has no Docker engine, so no real MariaDB/MongoDB benchmark, throughput result or concurrency success is claimed by this package. Generate and retain those results using docs/TESTING.md.

All records seeded by this package are synthetic except the historical NEA address snapshot. The UCI collection, when imported, is external sentiment data and is never linked to fictional orders or branches.
