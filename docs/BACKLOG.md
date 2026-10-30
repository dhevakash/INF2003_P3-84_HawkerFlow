# Team implementation backlog

Assign an owner and reviewer before beginning each task. Workstreams below are suggestions; they do not claim any member has performed the work.

| Priority | Workstream | Task | Completion evidence |
|---|---|---|---|
| P0 | All five | Run the Docker setup on at least two laptops | Both health checks connected; seed counts match |
| P0 | SQL design | Review the 12 tables against real business rules, add recipe/ingredient administration and versioned migrations | Valid/invalid recipe tests; updated ER/DDL; migration rehearsal |
| P0 | Transactions | Run real competing checkouts, retries and points redemption tests | One final portion creates one sale; no negative balances; retry adds no second order |
| P0 | MongoDB | Run real validator/index tests and complete feedback/profile UI actions | Review CRUD + rejected invalid/duplicate review; manager reply; profile update |
| P0 | Backend/UI | Multi-item cart, menu/customer editing, usable branch/customer/item selectors and consistent error states | Browser workflow works without manually typing database IDs |
| P0 | Data/evaluation | Obtain and import the real 1,000-row UCI Yelp subset with attribution | External examples count=1000; no fake branch/order links |
| P1 | SQL design | Add useful low-stock and ingredient usage analytics | SQL query with verified expected answer and index rationale |
| P1 | Transactions | Check concurrent menu/recipe edits, deadlock behavior and retry handling | Real-server integration evidence and clear error behavior |
| P1 | MongoDB | Explain aggregation plan and evaluate multikey/compound indexes | Before/after explain data using the same query/results |
| P1 | Data/evaluation | Run matched benchmark at several row counts on real DBMSs | JSON timing files, same outputs, versions/hardware, interpretation |
| P1 | All five | Rehearse the complete required demo sequence | <=10-minute run; every member explains their contribution |
| P2 | Analytics | Add rolling-average ingredient demand and reorder recommendations | Disclosed assumptions, enough dates, held-out error or worked validation |
| P2 | Reliability | Backups/restoration, DB outage behavior and pagination | Reproducible recovery/outage tests |

Avoid adding expiry-batch tracking or external payments without explicitly revising the original proposal scope. Complete and explain the core database evidence before selecting additional features.
