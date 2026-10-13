# HawkerFlow

A local F&B inventory, loyalty and customer feedback platform for INF2003. The working prototype uses **MariaDB/InnoDB for stock, sales and points** and **MongoDB for reviews and flexible preferences**. Completed cash sales are simulated; no payment gateway is connected.

## Start here on Windows

1. Extract the supplied project ZIP. Open the `hawkerflow` folder in VS Code.
2. Install and start [Docker Desktop](https://docs.docker.com/desktop/setup/install/windows-install/), using Linux containers and its WSL 2 backend. Docker Desktop is free for education under its published terms. Follow the official prerequisites if Windows asks you to enable virtualization/WSL.
3. Open VS Code's terminal in the folder containing `compose.yaml`. Check Docker is running:

```powershell
docker version
docker compose version
```

4. Build and start the three components:

```powershell
docker compose up -d --build
docker compose ps
docker compose exec app python scripts/seed.py
```

5. Open **http://localhost:8000** in your browser. The first run downloads container images and Python dependencies. Source datasets are already bundled, so application seeding does not download data.

For health and troubleshooting:

```powershell
docker compose logs --tail 60 app
docker compose logs --tail 60 sql
docker compose logs --tail 60 mongo
```

Visit http://localhost:8000/api/health. Both stores should say `connected`. The interactive API reference is at http://localhost:8000/docs. A degraded status reports an unavailable database; the app never substitutes fake live data.

## Demo accounts

All three development accounts use **DemoPass123!**. The login screen has role shortcuts.

| Role | Email | Access |
|---|---|---|
| Manager | manager@hawkerflow.local | Menu/recipes, ingredients, restocking, all branches, customer preferences and analytics |
| Cashier | cashier@hawkerflow.local | Complete orders and inspect stock at assigned branch 1 |
| Customer | customer1@hawkerflow.local | Own orders, points, reviews and profile |

These are fictional development accounts. The included secrets and database credentials are for a localhost demonstration, not a network deployment. Change credentials and `SECRET_KEY`, add TLS and review permissions before exposing the app beyond localhost. Tokens expire after 60 minutes; sign out clears the browser session.

## What to demonstrate

1. As cashier, select a customer and dish, then complete a cash order. Stock, audit movements and points commit together.
2. Review the receipt, historical unit price and customer's points. Earning is one point per whole dollar of net sale; redeem 100 points for a $1 discount. Redemption must be a multiple of 100, affordable and no larger than the bill.
3. As manager, receive stock, edit a dish/recipe or deactivate it. Deactivation preserves prior receipts. A new menu item needs a recipe before it can be sold.
4. As customer, review an owned completed order, edit the review and update dietary preferences. An order can have one review at a time.
5. As manager, reply or moderate reviews, inspect branch sales, low stock, complaints and monthly ratings. Dates filter UTC timestamps with an exclusive end date. Gross item sales precede points discounts; branch totals are net sales.
6. Inspect the separately labelled UCI sentence sample. It has no invented local customer/order/branch links.

Notes on order lines are informational. They do not alter recipes or constitute an allergen-management feature. Refunds, real payments and distributed transactions remain outside this prototype.

## Extra-credit features

Manager intelligence now includes sales trends and rankings, stock forecasting, food-waste monitoring with explained promotion suggestions, and RFM customer loyalty insights. Orders show ingredient-based available portions and check shared ingredients across the cart. Checkout consumes dated stock by earliest expiry, excludes expired lots, and records batch allocations atomically with stock and points. Deliveries accept expiry and cost; managers can record audited expired-stock disposal.

Read [the extra-credit implementation and presentation guide](docs/EXTRA_CREDIT_GUIDE.md) for exact formulas, database techniques, demo steps, and professor questions. New verification is recorded separately in [the enhancement results](evidence/extra-credit/RESULTS.md).

After pulling these changes, run `docker compose up -d --build` and `docker compose exec app python scripts/seed.py`. This adds tables and preserves existing records and database volumes. Existing stock is labelled unknown expiry; the seed adds explicitly synthetic expiry lots using fixed receipt keys. Historical seed sales are August–September 2026: use **Manager intelligence → Use seeded sales dates** for demand/sales/loyalty, then **Return to today** for expiry monitoring. Forecasting uses current inventory and current expiry status even when you select historical demand dates. The fixed waste fixture assessment date is **13 October 2026**.

## Data and provenance

The bundled sources contain **107 historical NEA hawker-centre locations** and **1,000 UCI Yelp sentiment-labelled sentences**. The NEA period is January–September 2016. Five locations supply historical addresses for fictional branches. UCI's deliberately balanced sample has 500 positive and 500 negative sentences; it cannot estimate a local restaurant complaint rate.

Menu prices, recipes, quantities, customers, sales, loyalty entries, purchase-linked reviews and profiles are synthetic. Seed `20261002` generates 5 branches, 50 customers, 20 dishes, 15 ingredients, 68 recipe components, 75 stock rows, 200 completed orders, 100 reviews and 50 profiles. Customer 1 initially has 308 points earned through 19 sales. The initial sample sales span August–September 2026.

The seeder checks source hashes, preserves existing records and does not reset stock or historical prices. Re-running creates no duplicate fixture orders/reviews. UI smoke testing adds explicitly labelled verification records; these are separate from the deterministic seed counts. See `data/seed_run_manifest.json` and `evidence/seed-rerun.log`.

Source attribution and licences are in `docs/DATA_SOURCES.md`, source manifests and the app footer. Refresh only when you intend to update the cached source snapshot:

```powershell
docker compose exec app python scripts/fetch_locations.py
docker compose exec app python scripts/fetch_review_examples.py
```

Refreshing inside a container changes its working copy; preserve that refreshed copy explicitly if you intend to distribute it. The packaged snapshot is sufficient to reproduce the initial dataset.

## Development without a containerized app

Start only the database containers, install Python 3.12, and use a terminal in the project directory:

```powershell
docker compose up -d sql mongo
py -3.12 -m venv .venv
.venv\Scripts\python.exe -m pip install -r requirements-dev.txt
Copy-Item .env.example .env
.venv\Scripts\python.exe scripts/seed.py
.venv\Scripts\python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8000
```

On macOS/Linux use `python3 -m venv .venv` and `.venv/bin/python` in place of the Windows interpreter path. Native MariaDB and MongoDB servers also work if you provision the databases/users and set `SQL_URL`, `MONGO_URL` and `MONGO_DATABASE` explicitly. No live SQLite or mongomock fallback exists.

## Verification commands

Unit checks use explicit SQLite/mongomock fixtures. Run them separately from integration tests because configuration is loaded at import:

```powershell
.venv\Scripts\python.exe -m pytest tests/test_sql.py tests/test_mongo.py tests/test_inventory_features.py tests/test_advanced_analytics.py -q
```

The real-engine integration suite **clears its dedicated test records** and rejects SQL/Mongo database names not ending in `_test`. The Compose initialization scripts create these databases and scope the development account to them. Use a separate terminal for the test configuration:

```powershell
$env:SQL_URL = 'mysql+pymysql://hawkerflow:hawkerflow_dev@127.0.0.1:3307/hawkerflow_test'
$env:MONGO_URL = 'mongodb://hawkerflow:hawkerflow_mongo_dev@127.0.0.1:27018/?authSource=admin'
$env:MONGO_DATABASE = 'hawkerflow_test'
$env:RUN_INTEGRATION = '1'
.venv\Scripts\python.exe -m pytest tests/test_integration.py -q -rs
```

Do not seed the test database. The test suite creates independent fixtures. Close this terminal afterwards, or remove those environment variables before launching the demonstration app.

The measured comparison uses only separately named benchmark tables/collection; it never resets business records. A fresh terminal can run:

```powershell
.venv\Scripts\python.exe scripts/benchmark.py --sql-url 'mysql+pymysql://hawkerflow:hawkerflow_dev@127.0.0.1:3307/hawkerflow_benchmark' --mongo-url 'mongodb://hawkerflow:hawkerflow_mongo_dev@127.0.0.1:27018/?authSource=admin' --mongo-database hawkerflow_benchmark --sizes 1000 10000 50000 --warmups 5 --repetitions 30
```

This records matching answers, full-fetch median/p95 latency, every timing sample, engine/connector versions and execution plans. The supplied measurements came from real MariaDB **10.11.14** and MongoDB **7.0.16** on Linux. Compose pins the same engine releases, but Docker orchestration and a fresh Windows installation have not been executed in this workspace. Each teammate should complete the clean-install check before presentation.

For optional real browser acceptance, install its browser and run against a running, seeded app:

```powershell
.venv\Scripts\python.exe -m playwright install chromium
.venv\Scripts\python.exe tests/ui_smoke.py --base-url http://localhost:8000
```

The browser exercise deliberately creates labelled verification orders/menu records and an audited receipt, and cleans up its temporary review. Do not run it expecting a read-only exercise. Results/screenshots are recorded under `evidence/ui`.

## Submission materials and team handoff

- Progress DOCX: one cover plus two body pages, Calibri 12, supplied headings. Replace group number, all names and date before submitting by **4 October 2026, 11:30 PM Singapore time**.
- `docs/ARCHITECTURE.md`, diagrams and `data/schema.sql`: design and schemas.
- `docs/RUBRIC_TRACEABILITY.md`: every task, rubric and submission mapped to evidence or remaining team work.
- `docs/ACCEPTANCE.md`, `evidence/`: actual test and benchmark evidence.
- `docs/FINAL_REPORT_OUTLINE.md`: exact final-template sections and evidence plan.
- `docs/TEAM_PLAN.md`: proposed responsibilities, milestones and presentation order. Member contributions must reflect work actually done and understood.

Final deliverables are due **29 November 2026, 11:30 PM Singapore time**: report PDF (maximum 10 body pages, Calibri 12), informative PPTX, MP4 video (maximum 10 minutes, all five members presenting with names shown), and source/data/user manual. Follow background → SQL → NoSQL → optional evaluation. The group must write its own reflections, verify the clean installation, and record the all-member video. Do not claim those tasks are complete merely because this starter is available.

## Shutdown and recovery

```powershell
docker compose stop
docker compose start
```

Named volumes retain database records. `docker compose down` removes containers/network while retaining those named volumes. Avoid `docker compose down -v` unless you intentionally want to delete the demo databases. Restore from the provided source/seed for initial fixtures; export your own changed databases before any destructive reset.

If ports are occupied, change host port mappings and host `SQL_URL`/`MONGO_URL` accordingly; app-to-container URLs still use `sql:3306` and `mongo:27017`. If auth fails after changing Mongo credentials, the initialization script only runs on a new empty volume; existing users need an explicit authorized credential update.
