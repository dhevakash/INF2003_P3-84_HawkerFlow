# Starter verification record

Verified on 30 October 2026 using Python 3.12 in an isolated local environment.

| Check | Result |
|---|---|
| Automated local/domain/API suite | 22 passed |
| Real MariaDB/MongoDB integration tests | 2 skipped; services not available in this environment |
| Fresh SQL schema and view construction | Passed on SQLite preview |
| Seed command, run twice | Stable: 5 branches, 50 customers, 20 menu items, 15 ingredients, 200 orders |
| Stock ledger reconciliation | All 75 branch/ingredient balances equal their summed movements |
| Seeded application smoke check | Login, HTML/JS assets and eight SQL data/report endpoints returned successfully |
| Benchmark findings | Not run; no timings are claimed |

The local suite produced one dependency deprecation warning about the TestClient HTTP transport. It did not affect the passing tests. The pinned requirements record the dependency versions used.

These results validate a working starting point. They are not evidence that MariaDB locking, MongoDB validators or Docker startup have already been exercised. Run and retain the actual integration checks on your laptop as described in TESTING.md. The final UI, real data import and team-specific extensions are listed in BACKLOG.md.
