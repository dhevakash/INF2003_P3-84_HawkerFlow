# Acceptance and evidence plan

HawkerFlow is a teaching prototype, with simulated completed cash sales and no
real payment processing. A UI feature is not evidence that its database invariant
was tested. Record the test environment and command with every result.

## Evidence status

- Unit tests: **44 passed**, zero skipped/errors/failures; recorded in
  `evidence/unit.xml` and `.log`. SQLite/mongomock checks do **not** validate
  MariaDB row locks, MongoDB server schema enforcement, or production throughput.
- Real integration: **16 passed**, zero skipped/errors/failures; recorded in
  `evidence/integration.xml` and `.log`, against MariaDB 10.11.14 and MongoDB
  7.0.16. This suite includes real contention, constraints, views, ownership and
  validation checks. Mongo outage isolation uses an explicitly injected driver
  error, rather than a measured network outage.
- Real browser acceptance: **8 checks passed**, no JavaScript errors; recorded in
  `evidence/ui/ui-smoke-results.json` with screenshots. These cover role-specific
  workflows, real writes and dashboard aggregation. The exercise creates labelled
  verification records; it is not read-only.
- Real seed and replay: 200 initial sales, 100 purchase-linked reviews, 50 profiles
  and 1,000 separate external examples were loaded; re-running added zero fixture
  records. See `evidence/seed.log`, `seed-rerun.log`, and the seed manifest.
- Exported SQL schema: independently executed on a fresh native database,
  producing 12 tables and 2 views; `evidence/schema-export-check.json` records the
  result. This does not establish Docker or Windows setup compatibility.
- Real benchmark: measured on 2 October 2026; `evidence/benchmark.json` and `.csv`
  contain verified equal answers for 1k, 10k and 50k identical generated reviews,
  5 warmups and 30 repetitions. Both execution plans use the branch/rating index.
  Its outcome supports one indexed review analytics workload only.
- These bullets record the original prototype evidence. Added FEFO batches,
  demand estimates, food-waste suggestions, sales trends and RFM insights have
  separate current results in `evidence/extra-credit/RESULTS.md`. Refunds,
  real payments and cross-store distributed transactions remain outside scope.

## Reproducible validation

Run ordinary unit tests from the project directory:

```sh
pytest -q -rs tests/test_sql.py tests/test_mongo.py
```

Use disposable databases named `hawkerflow_test`. The integration fixture clears
records in those databases; it rejects other names. Prepare credentials and DBs
using the environment setup in the main README. Run these tests in a separate
process from the unit suite, since application settings are cached at import.

```sh
RUN_INTEGRATION=1 SQL_URL='mysql+pymysql://hawkerflow:hawkerflow_dev@127.0.0.1:3307/hawkerflow_test' MONGO_URL='mongodb://hawkerflow:hawkerflow_mongo_dev@127.0.0.1:27018/?authSource=admin' MONGO_DATABASE='hawkerflow_test' pytest -q -rs tests/test_integration.py
```

An unavailable real database is an integration failure, never a silent mock fallback.
The default suite skips this module when `RUN_INTEGRATION` is absent. Skips do not
count as passes and are not sufficient evidence of the invariants below.

## Acceptance matrix

| Case | Trigger | Required behavior and database evidence | Automated coverage |
|---|---|---|---|
| Atomic completed sale | Staff submits an in-stock order | Historical price and completed order stored; recipe stock deducted; audit movement and earned points committed together | `test_order_stock_points_are_committed_together` |
| Reporting views | One completed order contains two lines; another branch has no orders | Revenue view reports the order once and an empty branch at zero; low-stock view computes shortfall | `test_real_reporting_views_avoid_revenue_line_fanout` |
| Server SQL constraints | Direct ORM writes attempt negative stock and an unknown branch FK | Actual MariaDB rejects both; transaction rollback restores original stock | `test_mariadb_rejects_invalid_stock_foreign_keys_and_negative_quantity` |
| Mongo error isolation | Inject a driver server-selection error into review access | Review returns 503; real SQL checkout and points commit still succeed. This is fault injection, not a measured network outage | `test_injected_mongo_failure_does_not_block_real_sql_checkout` |
| Rollback | Second recipe ingredient has zero stock | 409; original quantities unchanged; no order, line, movement or points survives | `test_insufficient_second_ingredient_rolls_back_all_state` |
| Concurrent last serving | Two customers order the last available serving simultaneously | Exactly one sale; other request 409; stock zero, never negative; one points award | `test_concurrent_orders_cannot_oversell` |
| Safe request replay | Resubmit same checkout key and payload | Same order ID; one stock deduction and points award | `test_checkout_idempotency_and_payload_mismatch` |
| Concurrent request replay | Submit the same request key from two threads | Both resolve to one order, with same-key retry allowed for a lock conflict; one deduction and award | `test_concurrent_replay_creates_only_one_order` |
| Replay mismatch | Reuse key with changed quantity | 409; existing order stays unchanged | Same test |
| Price history | Manager changes menu price after an order | Existing line retains paid unit price; new order uses current price | `test_historical_price_survives_menu_update` |
| Redemption | Earn 120 points, redeem 100 on next $120 sale | $119 total; earn 119; final balance 139; insufficient/invalid redemptions rejected | `test_points_redemption_and_rejected_redemptions` |
| Concurrent redemption | With 120 points, submit two $1 sales each redeeming 100 points | One succeeds; other is rejected; final balance 20, never negative | `test_concurrent_redemptions_cannot_double_spend` |
| Stock receipt replay | Submit same receipt twice, then change amount with same key | One receipt and audit movement; altered replay rejected | `test_receive_stock_idempotency` |
| Staff scope and owner privacy | Customer accesses another order/loyalty account; cashier orders at another branch | Unauthorized reads/writes denied; customer cannot checkout or view managerial analytics | `test_authorization_and_customer_order_ownership` |
| Review provenance | Different customer tries to review an order; owner reviews twice | Ownership required; one review per completed order; normalized tags deduplicated | `test_review_ownership_unique_order_and_reply_permissions` |
| Moderator reply and analytics | Customer attempts reply; manager replies and queries feedback | Customer denied; manager reply succeeds; complaint count matches low-rated published review | Same test |
| Server-level Mongo protections | Insert malformed rating or duplicate order directly through driver | Validation code 121; duplicate-key rejection; required unique and compound indexes present | `test_mongo_database_validators_and_unique_indexes` |
| Flexible profile | Owner adds preferences/milestones; other owner tries to read/change | Schema-valid owner update succeeds; ownership and array bounds enforced | `test_profile_owner_and_schema_limits` |

## Database comparison experiment

The benchmark loads the **same generated review documents** into normalized SQL
review/tag tables and Mongo documents. Each record has the same ID, branch,
rating, and distinct tags. Both queries count mentions of allowlisted complaint
tags on reviews rated 1–2 for a selected branch. Group counts are verified equal
before every timing run; all timed results are also checked. The included run uses
1k, 10k and 50k reviews, 5 warmups and 30 full-fetch repetitions for median/p95.
Compound indexes and query plans are recorded. No synthetic timing data are used.

```sh
python scripts/benchmark.py --sql-url 'mysql+pymysql://hawkerflow:hawkerflow_dev@127.0.0.1:3307/hawkerflow_benchmark' --mongo-url 'mongodb://hawkerflow:hawkerflow_mongo_dev@127.0.0.1:27018/?authSource=admin' --mongo-database hawkerflow_benchmark --sizes 1000 10000 50000 --warmups 5 --repetitions 30 --output evidence/benchmark.json
```

Only SQL `benchmark_reviews`, `benchmark_review_tags`, and Mongo
`hawkerflow_benchmark.benchmark_reviews` are reset by this script. Business data
are untouched. The benchmark does not invoke the live multi-facet dashboard: it
compares an equivalent single tag-count query, excluding monthly trend work.
Record machine/server versions, run date, connector versions, warmup count, and
indexes beside results. Discuss normalized SQL joins versus embedded tag arrays;
exclude dataset-loading time from query timings. Re-run on the submission machine
before making performance claims. Connector/network, warm caches, container CPU
quotas, and background load limit generalizability.

The included run used MariaDB **10.11.14** and MongoDB **7.0.16**, with Python
3.12.14. Compose pins these same engine releases. Docker orchestration and a fresh
Windows installation have **not** been executed; the group must verify them from
the manual. Measured full-fetch latencies were:

| Reviews | MariaDB median / p95 (ms) | MongoDB median / p95 (ms) |
|---:|---:|---:|
| 1,000 | 0.347 / 0.425 | 0.397 / 0.493 |
| 10,000 | 1.073 / 1.202 | 1.089 / 1.248 |
| 50,000 | 4.996 / 8.194 | 5.086 / 11.149 |

Both stores gave the same counts. The small median differences in this run do
not establish a general advantage; both models support this indexed workload.
The SQL plan uses a range scan on branch/rating and a primary-key lookup into the
tag table. MongoDB uses a branch/rating index scan then fetches embedded tags.

## Short demo acceptance sequence

1. Login as cashier; show inventory, complete a sale, then show stock and points.
2. Replay the same request to prove no duplicate sale, then attempt an out-of-stock
   order and show unchanged data. Automated concurrency evidence supports the
   last-serving case; do not simulate a race with sequential UI clicks.
3. Login as customer; show own loyalty balance, preferences and verified-order
   review. Show another account's write being denied.
4. Login as manager; reply to a review, show branch revenue and low-stock report,
   then Mongo complaint-tag aggregation and rating trends.
5. Show tested constraints/indexes and the measured comparison, explaining its
   single-workload scope and shared-machine limitations.

The final video must stay within 10 minutes at normal speed, include all five
members, and present background, SQL, then NoSQL (evaluation optional). Individual
names must be visible. Retain clear source attribution and synthetic-data labels.

## Remaining group acceptance

Follow the manual on a fresh group machine and retain its setup/demo result.
Replace progress-report identity placeholders and confirm actual member ownership.
Write the final report and each member's reflection. Finalize the available
11-slide working presentation and nine-minute five-speaker script with actual
names and contributions, then record the human video, complete peer review and
the prescribed final submission.
Re-run evaluation on the final environment if reporting results for that machine.
