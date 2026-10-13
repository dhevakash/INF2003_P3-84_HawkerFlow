# Extra-credit verification — 13 October 2026

All five requested enhancements are implemented. This run used Windows 11, Python 3.13.7 for host tests, the local Docker app, MariaDB 10.11.14/InnoDB, and MongoDB 7.0.16. Detailed versions are in `environment.json`.

| Verification | Actual result | Evidence |
|---|---|---|
| Full unit suite | **60 passed**, zero failures or skips | `unit.xml` |
| Real database integration | **19 passed**, zero failures or skips | `integration.xml` |
| New feature browser checks | **7 passed**, no JavaScript errors | `ui/results.json` and desktop/mobile screenshots |
| Existing workflow browser checks | **8 passed**, no JavaScript errors | `core-ui/ui-smoke-results.json` and screenshots |
| JavaScript syntax | Passed | `node --check app/static/app.js` |
| Exported schema | 15 operational tables, 3 reporting views | `data/schema.sql`; `environment.json` |
| Seed upgrade/replay | 15 synthetic expiry batches added initially; rerun created 0 sales, 0 batches and 0 reviews | `data/seed_run_manifest.json` |
| Source whitespace check | Passed | `git diff --check` |

The unit checks use explicit SQLite/mongomock fixtures; they do not prove InnoDB row locking. The real integration suite uses only dedicated `hawkerflow_test` databases, clears its own fixtures, and rejects other database names. It exercised the added CTE/window/date queries on MariaDB, expiry exclusion, FEFO allocations, delivery metadata replay, disposal audits, and competing orders for one dated serving, alongside existing checkout, loyalty, authorization and MongoDB checks.

The new browser suite verified live available portions, historical sales, all-branch reporting, nonzero equal-period comparisons, declining dishes, demand forecasts, daily SQL averages, RFM segment filtering, expiry status/value, promotion reasons/scores, and mobile layout. It received and discarded a small verification batch through the UI and confirmed that the ingredient's original aggregate and usable quantities were restored. The core browser suite verified menu/recipe updates, checkout, price history, receiving, customer review/profile actions, manager replies, review deletion, and cashier restrictions.

Browser testing writes labelled verification records. Its audit records remain; the core suite leaves an inactive verification menu item, one completed verification order and a stock receipt, preserving receipt integrity. The temporary review is deleted and preferences restored. These records are separate from the deterministic teaching fixtures.

## Commands used

Unit suite:

```powershell
.venv\Scripts\python.exe -m pytest tests/test_sql.py tests/test_mongo.py tests/test_inventory_features.py tests/test_advanced_analytics.py -q -p no:cacheprovider --junitxml=evidence/extra-credit/unit.xml
```

Integration suite, in a separate process/terminal:

```powershell
$env:SQL_URL = 'mysql+pymysql://hawkerflow:hawkerflow_dev@127.0.0.1:3307/hawkerflow_test'
$env:MONGO_URL = 'mongodb://hawkerflow:hawkerflow_mongo_dev@127.0.0.1:27018/?authSource=admin'
$env:MONGO_DATABASE = 'hawkerflow_test'
$env:RUN_INTEGRATION = '1'
.venv\Scripts\python.exe -m pytest tests/test_integration.py -q -rs -p no:cacheprovider --junitxml=evidence/extra-credit/integration.xml
```

Browser checks against the seeded live app, outside that test-configured terminal:

```powershell
.venv\Scripts\python.exe tests/ui_extra_credit.py
.venv\Scripts\python.exe tests/ui_smoke.py --output evidence/extra-credit/core-ui
```

Build and export:

```powershell
docker compose up -d --build app
.venv\Scripts\python.exe scripts/export_schema.py
node --check app/static/app.js
git diff --check
```

An initial real-database run caught a MariaDB integer-SUM result returned as Decimal during promotion scoring. Sales quantities are now explicitly normalized to integers before the score arithmetic; the real-engine promotion test passes. Explicit UTF-8 reads/writes in the seeder also fixed Windows fixture-name comparisons. Both stores remain genuine live databases; no mock fallback was added.

## Presentation boundaries

Forecasts and promotions use transparent rules, not trained models. Forecast stock is current even when its demand-history date is historical. Unknown legacy expiry is explicitly labelled and requires verification; unknown cost is excluded from known monetary risk. Expired lots are blocked in checkout. Suggested promotions do not publish discounts. Real payments, refunds and distributed SQL/Mongo transactions remain outside scope.

The earlier files in the parent `evidence` folder record the original prototype and benchmark. This enhancement did not remeasure that benchmark, and its old timings should not be presented as new measurements.
