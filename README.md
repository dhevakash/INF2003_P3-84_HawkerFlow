# HawkerFlow starter project

INF2003 Team 84. A runnable starting point for the F&B inventory, loyalty and feedback application in the supplied progress report. Open this folder in VS Code. The final report and its template are not included or edited.

This is a working starter, not a finished assessed submission. See [docs/STATUS.md](docs/STATUS.md) for implemented functionality, remaining work and verification limits. The rubric rewards the team's implementation, justification, testing and presentation; a scaffold alone cannot secure a grade.

## Start here on Windows

Admin/Staff/Customer account rules and upgrade instructions:
[ACCOUNT_ACTIVATION_AND_ROLLOUT.md](docs/ACCOUNT_ACTIVATION_AND_ROLLOUT.md).

These commands are for a fresh database. Existing installations must first
complete the coordinated role upgrade described in
[docs/ACCOUNT_ACTIVATION_AND_ROLLOUT.md](docs/ACCOUNT_ACTIVATION_AND_ROLLOUT.md); rebuilding alone does not migrate
the existing role constraint or accounts.

1. Extract the ZIP, then use **File → Open Folder** in VS Code and select the inner `hawkerflow-starter` folder containing `compose.yaml`.
2. Start Docker Desktop. In **Terminal → New Terminal**, run:

```powershell
docker compose up -d --build
docker compose ps
docker compose exec app python -m app.cli init-db
docker compose exec app python -m app.cli init-admin
docker compose exec app python -m app.cli seed
```

The `init-admin` command asks for your Admin email and a hidden password entered
twice. Use a nonblank password of 12-128 characters. If an Admin already exists,
the command leaves every account and password unchanged. See
[docs/ADMIN_ACCOUNT_SETUP.md](docs/ADMIN_ACCOUNT_SETUP.md).

3. Open http://localhost:8080. Open http://localhost:8080/docs for the interactive API explorer, and http://localhost:8080/api/health to check both stores.

| Role | Email | Password |
|---|---|---|
| Admin | Your setup email | Your setup password |
| Staff (legacy manager email) | manager@hawkerflow.local | DemoPass123! |
| Staff (legacy cashier email) | cashier@hawkerflow.local | DemoPass123! |
| Customer 1 | customer1@hawkerflow.local | DemoPass123! |

The seed command uses synthetic demonstration accounts and can be repeated without duplicating its orders, stock or profiles. Keep default DB credentials on your local machine only. Ports bind to localhost. No payment processor is involved.

If ports 8000, 3306 or 27017 are already used by your earlier HawkerFlow installation, stop that project first (`docker compose stop` from its folder), or change only the host side of this starter's port mappings. Internal container addresses stay the same. Avoid deleting volumes to solve a port conflict.

## Develop with the VS Code Python debugger

Python 3.12 is the tested version. Install the VS Code Python and Python Debugger extensions. With database containers running:

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements-lock.txt
Copy-Item .env.example .env
.\.venv\Scripts\python.exe -m app.cli init-db
.\.venv\Scripts\python.exe -m app.cli init-admin
.\.venv\Scripts\python.exe -m app.cli seed
.\.venv\Scripts\python.exe -m uvicorn app.main:app --reload --port 8001
```

Open http://localhost:8001. Directly invoking the virtual environment's Python avoids PowerShell activation-policy errors. The provided F5 debugger uses port 8000; stop the Docker app first or change the debug port. On macOS/Linux use `python3 -m venv .venv` and `.venv/bin/python`; adjust the VS Code interpreter path accordingly.

## Optional SQL-only preview without Docker

Before creating `.env`, the default database is local SQLite and MongoDB is disabled:

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements-lock.txt
.\.venv\Scripts\python.exe -m app.cli init-db --sql-only
.\.venv\Scripts\python.exe -m app.cli init-admin
.\.venv\Scripts\python.exe -m app.cli seed --sql-only
.\.venv\Scripts\python.exe -m uvicorn app.main:app --reload
```

If `.env` already exists, it overrides these defaults: temporarily rename it or set `DATABASE_URL=sqlite:///./preview.sqlite` and leave `MONGO_URI` empty in it. SQL-only preview supports interface/domain development. It cannot demonstrate MongoDB, InnoDB locking or the matched benchmark, and is not the final assessment environment.

## Where to work

| Path | Purpose |
|---|---|
| `app/models.py` | Twelve SQL tables, relationships through foreign keys, checks and indexes |
| `app/services/checkout.py` | Atomic checkout, row locks, stock checks, price snapshots and idempotency |
| `app/services/inventory.py` | Audited ingredient receipts |
| `app/nosql.py` | MongoDB validators, unique/multikey indexes and aggregation pipelines |
| `app/routes.py` | SQL CRUD, sales, feedback, preferences, role checks and ownership checks |
| `app/analytics.py` | Reporting views, aggregate joins, nested query and CTE/window ranking |
| `app/static/` | Small working browser interface; extend its forms here |
| `app/cli.py` | Schema initialization, deterministic seed and external dataset import |
| `database/` | Inspectable SQL DDL, queries, MongoDB schemas and ER diagram |
| `data/` | Provided raw files and provenance notes |
| `tests/` | Local tests plus opt-in real DBMS integration tests |
| `scripts/benchmark.py` | Matched SQL/MongoDB review-tag benchmark runner |
| `docs/RUBRIC_MAP.md` | Assessment requirement → implementation → evidence still needed |
| `docs/BACKLOG.md` | Prioritized work for the five workstreams |
| `evidence/` | Save actual test logs, explain plans and benchmark JSON here |

## Next step

Follow [docs/DEMO_WALKTHROUGH.md](docs/DEMO_WALKTHROUGH.md), then take the P0 tasks in [docs/BACKLOG.md](docs/BACKLOG.md). Capture real MariaDB and MongoDB evidence before claiming those features are verified. The package includes setup and code documentation, not your final report, slides or video.
