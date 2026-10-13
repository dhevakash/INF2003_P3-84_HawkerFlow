# Verification and measured comparison

This evidence describes the implemented prototype as tested on 2 October 2026. It does not claim production readiness, a fresh Windows installation, or completed human presentation/reflection work.

## Verified checks

| Evidence | Result | What it establishes |
|---|---:|---|
| `evidence/unit.xml` | 44 passed | SQL service logic with explicit SQLite fixtures; Mongo route logic with explicit mongomock fixtures |
| `evidence/integration.xml` | 16 passed, no skips | Actual MariaDB/Mongo transactions, concurrency, constraints, access control and validators |
| `evidence/ui/ui-smoke-results.json` | 8 scenarios passed, no JavaScript errors | Live browser workflows, role changes, menu/recipe edits, checkout/restocking, review/profile CRUD, analytics and mobile layout |
| `evidence/seed.log` and `seed-rerun.log` | Full load and nondoubling rerun | 200 synthetic orders, 100 purchase-linked reviews, 50 profiles and 1,000 separately labelled external sentences |

The integration checks exercise competing requests for the final stock item, concurrent points redemption, duplicate request replay, changed-payload rejection, atomic insufficient-stock rollback, historical price snapshots, receipt deduplication, SQL CHECK and foreign-key enforcement, Mongo unique indexes/server validators, and role/ownership boundaries. Injecting a Mongo driver failure returns an explicit 503 while a real SQL checkout still succeeds; this is a controlled fault test, not a measured network outage.

## Repeated functionality in both databases

The benchmark counts approved negative complaint tags in low-rating reviews at one branch. Both databases receive identical synthetic review IDs, ratings, branches and unique tag lists. SQL normalizes the tags into a child table; Mongo embeds them in an array. Every fully fetched answer is checked for equality. This repeatable analytical comparison is separate from the production data split and does not introduce runtime synchronization.

Environment: Python 3.12.14; MariaDB 10.11.14-MariaDB-0ubuntu0.24.04.1; MongoDB 7.0.16; SQLAlchemy 2.1.2; PyMongo 4.18.2. Five warmups and 30 repeated timings per database at each size. Indexed query plans, all timing samples, fixture counts and answers are retained in `evidence/benchmark.json`.

| Reviews per store | SQL median (ms) | SQL p95 (ms) | Mongo median (ms) | Mongo p95 (ms) | Answers |
|---:|---:|---:|---:|---:|---|
| 1,000 | 0.347 | 0.425 | 0.397 | 0.493 | Identical |
| 10,000 | 1.073 | 1.202 | 1.089 | 1.248 | Identical |
| 50,000 | 4.996 | 8.194 | 5.086 | 11.149 | Identical |

The small observed differences do not support a universal database ranking. This is one warm-cache analytical workload on one machine; connector overhead, CPU scheduling and background load influence the results. It is not a throughput, cold-cache, write-contention or distributed-scaling study. The implemented decision rests chiefly on transactional invariants for sales/stock/points and bounded flexible documents for feedback/preferences. SQL can also store JSON; MongoDB also supports transactions. Neither engine is inherently restricted to the simplified roles used by this prototype.

## Reproduction and remaining work

Use the commands in `README.md`; run integration tests only against the separately named `_test` databases. The browser acceptance script intentionally creates labelled verification records. Seed counts describe the initial deterministic fixture; a used demonstration database will contain extra transactions. Benchmark tables/collection are isolated from business records.

Compose pins the exact tested engine releases, but Docker orchestration itself and a fresh Windows installation remain unverified. Every member should perform the clean-install checklist and understand both database implementations. Before final submission, replace group/member placeholders, write truthful individual contributions and reflections, complete the final report using the supplied outline, and record the all-member video.
