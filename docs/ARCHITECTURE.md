# Architecture and business rules

The browser calls FastAPI over HTTP. The backend checks identity and permissions before calling the transactional SQL services or the MongoDB document operations. Clients never connect directly to either database.

| Data | Owner | Reason |
|---|---|---|
| Branches, customers, users, menu, ingredients, recipes | MariaDB | Structured references and cross-row integrity |
| Stock, receipts/movements, orders/lines and points ledger | MariaDB/InnoDB | Atomic changes and locked balances |
| Purchase reviews, optional category ratings, replies | MongoDB | Nested optional fields read together with a review |
| Customer preferences | MongoDB | Optional arrays with independent document updates |
| External UCI sentence examples | Separate MongoDB collection | No authentic relationship to operational purchases |

Customer/order/branch identifiers are copied into review documents only after SQL purchase ownership is checked. There are no cross-database foreign keys or distributed transactions. A MongoDB failure must not undo a completed SQL checkout. Keeping these stores consistent under customer/order deletion is a future lifecycle concern; orders are retained in this starter.

## Checkout rules

1. Authenticated cashier/manager submits a unique request key and cart.
2. An existing matching request returns the original result. A changed payload using that key is rejected.
3. Load and lock menu rows; require active items and configured recipes.
4. Sum ingredients across all cart lines. Lock affected branch-stock records in ingredient order and reject shortages.
5. Lock the customer's points balance. Validate redemption.
6. Insert the order and historical price snapshots, deduct stock, append movement/points ledgers and commit once. Any exception rolls back the transaction.

Teaching assumptions: currency is SGD; 100 points redeem SGD 1; points earned are the whole-dollar floor of the amount after redemption; recipes and stock quantities use grams throughout the seed. Money is SQL DECIMAL/Python Decimal. A redemption cannot exceed either the existing point balance or the subtotal. No discount, refunds, taxes, payment gateways or expiry allocation are implied beyond these rules.

The menu-row locks also prevent price edits while a checkout snapshots its prices. They can serialize sales of the same menu item across branches, which is a performance trade-off to measure and refine. Future recipe updates must follow a consistent lock protocol. SQL sessions are request-scoped; one Session is never shared by concurrent requests.

## NoSQL design

`reviews`: one document per completed order; unique `order_id`; integer rating 1-5; text; up to ten unique tags; optional food/service/value ratings; at most twenty embedded manager replies. A conditional atomic append prevents reply-array overflow. `profiles`: unique `customer_id` with bounded preference arrays. Both application input validation and database validators are used.

The benchmark uses separate `benchmark_*` tables/collection and a fresh run identifier so it never reinterprets operational reviews or overwrites previous experiment runs.

## Official implementation references

- SQLAlchemy transactions: https://docs.sqlalchemy.org/en/20/orm/session_basics.html
- MariaDB `FOR UPDATE`: https://mariadb.com/docs/server/reference/sql-statements/data-manipulation/selecting-data/for-update
- MongoDB schema validation: https://www.mongodb.com/docs/manual/core/schema-validation/
- FastAPI JWT authentication guidance: https://fastapi.tiangolo.com/tutorial/security/oauth2-jwt/

## Security and reliability work to complete

Use a random JWT secret when sharing, keep DB ports private, use dedicated DB accounts, add rate limiting and TLS for deployment, and implement role/branch assignment before any real use. NoSQL public replies should eventually expose an appropriate public staff identity instead of internal account identifiers. Backups, recovery rehearsal, migrations and real outage tests remain team tasks. This starter is for local demonstration with synthetic accounts.
