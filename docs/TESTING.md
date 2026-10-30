# Testing and evidence

## Local checks

```powershell
.\.venv\Scripts\python.exe -m pytest -m "not integration" -q
```

Tests use a fresh SQLite database per test. They cover checkout changes, shortage rollback, idempotency, changed-payload rejection, redemption, historical prices, missing/inactive items, combined ingredient requirements, constraints, receipts, API role checks, ownership and input validation. Pipeline-shape assertions do not prove MongoDB execution correctness.

## Real MariaDB and MongoDB tests

The default run skips integration tests. They must use dedicated databases whose names end in `_test`. The test suite creates its own uniquely named records. SQL records remain available for inspection; only the temporary MongoDB validation collection is removed. Never point these commands at a production database.

Create the SQL test database once in the local Docker environment:

```powershell
docker compose exec mariadb mariadb -uroot -proot_local_only -e "CREATE DATABASE IF NOT EXISTS hawkerflow_test; GRANT ALL ON hawkerflow_test.* TO 'hawkerflow'@'%';"
```

Run the opt-in tests inside the app container:

```powershell
docker compose exec -e RUN_DB_INTEGRATION=1 -e TEST_DATABASE_URL=mysql+pymysql://hawkerflow:hawkerflow_dev@mariadb:3306/hawkerflow_test -e TEST_MONGO_URI=mongodb://mongo:27017 -e TEST_MONGO_DATABASE=hawkerflow_test app python -m pytest tests/integration -q
```

The tests exercise two simultaneous checkouts competing for the final ingredient quantity, plus actual MongoDB unique-index and document-validator rejection. A pass on these tests still does not cover every race or failure mode. Add concurrent point redemption, MongoDB outage during a completed sale, purchase-ownership API checks against real databases, and restart recovery.

Capture actual output in `evidence/`, including DBMS versions and the command used. Do not edit skipped tests into passed results. SQLite preview, mock tests and source inspection are distinct from server integration evidence.

## Benchmark

```powershell
docker compose exec app python scripts/benchmark.py --rows 10000 --repetitions 20
docker compose cp app:/code/evidence ./evidence-from-container
```

The runner stores normalized review/tag tables in SQL and tag arrays in MongoDB, loads exactly the same generated inputs, checks both answers against a Python reference result, performs three warmups and alternates query order across repeated timings. Both have run/rating indexes; their full index structures differ and should be disclosed. The raw timings, SQL explain plan and versions are saved as JSON. MongoDB explain capture and CPU/RAM/resource-limit notes remain team tasks. Existing experiment runs are retained under distinct identifiers; plan storage cleanup after preserving evidence.

## Fresh machine rehearsal

A teammate should extract the ZIP, follow only README.md, build the containers, seed both stores, run tests and complete the walkthrough. Record any missing instruction and fix the manual before final packaging.
