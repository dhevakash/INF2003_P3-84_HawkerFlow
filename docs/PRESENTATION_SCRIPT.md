# HawkerFlow presentation script and recording plan

Working draft dated 2 October 2026. Target duration: **9 minutes**, leaving one minute below the brief's ten-minute maximum. This is a presentation preparation pack, not a completed group video.

Replace Group [ID] and all five member names. Put each speaker's actual name on screen during their segment. Speaking allocations below are suggested presentation roles, not claims about individual contributions. Rehearse the application and rerun the evidence on the submission machine before recording.

## Run order

| Slides | Suggested speaker | Time | Subject |
|---|---|---|---|
| 1–2 | Member 1 [full name] | 0:00–1:35 | Background and data |
| 3–4 | Member 2 [full name] | 1:35–3:05 | Architecture and relational design |
| 5–6 | Member 3 [full name] | 3:05–4:55 | SQL transaction and demonstration |
| 7–8 | Member 4 [full name] | 4:55–6:35 | MongoDB implementation and demonstration |
| 9–11 | Member 5 [full name] | 6:35–9:00 | Comparison, verification and conclusion |

## Slide talk track

### 1. HawkerFlow

**Member 1 [full name], 0:00–0:40 (40 seconds)**

Introduce your full name and group. HawkerFlow connects completed cash sales, ingredient stock, loyalty points and verified-order feedback. This is a fictional teaching chain. The interface and databases run locally. Explain that the presentation moves from background and data to SQL, then MongoDB and a controlled comparison. Replace the group and member placeholders before recording.

### 2. Business problem and data provenance

**Member 1 [full name], 0:40–1:35 (55 seconds)**

Our users are cashiers, customers and managers. Cashiers need accurate ingredient stock during checkout. Customers need points balances and purchase-linked feedback. Managers need revenue and complaint summaries. We downloaded 107 historical NEA location records and select five as fictional demonstration branches. We preserve 1,000 UCI Yelp sentences as a separate reference corpus, with 500 positive and 500 negative labels. They do not belong to invented local orders. Our seed generator adds 50 customers, 20 menu items, 15 ingredients, 200 completed orders, 100 labelled synthetic reviews and 50 profiles. The source manifests record URLs, checksums and retrieval dates.

Source evidence: https://data.gov.sg/datasets/d_68a42f09f350881996d83f9cd73ab02f/view; https://archive.ics.uci.edu/dataset/331/sentiment+labelled+sentences; data/source_manifest.json; data/review_source_manifest.json; docs/DATA_SOURCES.md

### 3. Application architecture and data ownership

**Member 2 [full name], 1:35–2:15 (40 seconds)**

The browser calls a Python FastAPI backend. SQLAlchemy accesses MariaDB and PyMongo accesses MongoDB. The browser never connects to the databases directly. SQL owns completed orders, ingredient quantities and loyalty entries. MongoDB owns flexible reviews and optional customer preferences. The backend derives the customer and branch from a completed order before writing a review. MongoDB cannot enforce a foreign key into SQL. Checkout stays in one SQL transaction, so a review-store outage does not reverse a committed sale.

Source evidence: docs/ARCHITECTURE.md

### 4. Relational model and integrity rules

**Member 2 [full name], 2:15–3:05 (50 seconds)**

The twelve-table operational model includes branches, customers, users, menu items, ingredients, recipes, stock, orders, lines, movements, receipts and loyalty transactions. Three bridge tables resolve many-to-many relationships. A separate line identifier permits repeated menu items with different notes. DECIMAL avoids floating-point money errors. Quantities must remain valid, and foreign keys protect SQL relationships. Order lines preserve the paid unit price, so updating the menu leaves previous sales unchanged. Stock movement and point ledgers make changes traceable. The full ER diagram accompanies the report.

Source evidence: app/models.py; docs/diagrams/erd.mmd

### 5. Atomic checkout and safe request replay

**Member 3 [full name], 3:05–4:05 (60 seconds)**

Checkout is the main transactional demonstration. The backend authorizes the staff branch, validates the active menu and calculates ingredient requirements. It binds the request key to the submitted payload. It locks the customer for redemption and locks stock in a deterministic order. Server-side prices determine the total. One point accrues per whole dollar of the net sale. Customers redeem 100 points for a one-dollar discount, subject to sufficient balance and sale value. Order lines, stock deductions, stock movements and loyalty entries commit together. If a second ingredient is missing, all changes roll back. Replaying a committed key returns the original order. Reusing it with a different payload returns a conflict. Show a completed sale and then an unchanged request replay.

Source evidence: app/sql_service.py; tests/test_integration.py

### 6. SQL demonstration and failure evidence

**Member 3 [full name], 4:05–4:55 (50 seconds)**

Show the inventory page and complete a sale. Verify the required ingredients decrease and the points ledger records the award. Replay the stock receipt to show its idempotency protection. Then show the integration evidence for shortage rollback, concurrent last-serving checkout, concurrent redemption and historical-price preservation. Do not imitate concurrency with two sequential clicks. The branch revenue view aggregates completed orders once and includes empty branches at zero. Direct MariaDB tests reject negative stock and invalid foreign keys. This slide demonstrates database behaviour, rather than treating a successful UI click as proof of correctness.

Source evidence: evidence/ui/03-inventory.png; docs/ACCEPTANCE.md; tests/test_integration.py

### 7. MongoDB documents and review lifecycle

**Member 4 [full name], 4:55–5:50 (55 seconds)**

Reviews are documents because the optional category ratings, arrays of tags and bounded replies belong together in our access pattern. Profiles accept optional preferences without competing with the SQL points ledger. The implementation supports creation, reading, editing and deletion or moderation, plus manager replies. Strict validators require correct identifiers and BSON dates, enforce ratings from one to five, and bound text and array sizes. A unique order index permits one review per order. The backend verifies purchase ownership before a write. Customers can edit their own content, while managers control replies and moderation. Show a customer review and then a manager reply.

Source evidence: app/mongo_routes.py; app/mongo.py

### 8. Feedback analytics and query indexes

**Member 4 [full name], 5:50–6:35 (45 seconds)**

The complaint aggregation filters published reviews rated one or two for a selected branch and date range. It expands distinct tags, keeps an explicit negative allowlist and counts mentions. Positive tags such as fast service never become complaints. Tag normalization and deduplication mean one review contributes at most one mention per tag. A separate aggregation calculates monthly average ratings and review counts. Explain the branch/date indexes used by the dashboard. The benchmark uses a branch/rating index in both databases. Show the feedback dashboard and its underlying MongoDB pipeline or explain plan. The balanced UCI corpus remains a separate reference collection and cannot establish a local complaint rate.

Source evidence: app/mongo_routes.py; evidence/benchmark.json

### 9. Measured SQL and MongoDB comparison

**Member 5 [full name], 6:35–7:40 (65 seconds)**

This experiment implements the same low-rating complaint-tag query in normalized SQL review and tag tables and in MongoDB documents. Fixtures contain the same identifiers, ratings and distinct tags at one thousand, ten thousand and fifty thousand reviews. Each timed result matches across databases. The run uses five warmups and thirty repetitions, recording full-fetch median and p95 latency. SQL medians are 0.347, 1.073 and 4.996 milliseconds. Mongo medians are 0.397, 1.089 and 5.086 milliseconds. Both execution plans use the branch/rating index. The local run used MariaDB 10.11.14, MongoDB 7.0.16 and Python 3.12.14. Timings include connectors and loopback communication, use warm caches and cover one generated workload. These small differences do not establish a universal SQL or NoSQL winner. Re-run on the presentation machine.

Source evidence: evidence/benchmark.json; evidence/benchmark.csv

### 10. Verification, boundaries and remaining work

**Member 5 [full name], 7:40–8:30 (50 seconds)**

The unit suite has forty-four passing tests. Unit tests use lightweight stores and cannot establish MariaDB lock behaviour or MongoDB server validation. The separately executed real integration suite has sixteen passing tests and covers transaction rollback, concurrent checkout and redemption, request replay, ownership, reporting views, database constraints and Mongo validators. Refer to the latest integration log for the current count rather than treating skipped tests as passes. We also captured UI smoke evidence. Scope remains completed cash sales without a real payment gateway. Refunds, expiry batches, demand forecasting and distributed transactions are future work. Before final submission, the team must rerun on its own machines, inspect the deployment instructions and record all five named presenters.

Source evidence: evidence/unit.xml; evidence/integration.xml; evidence/ui-smoke.log; docs/ACCEPTANCE.md

### 11. Design conclusion

**Member 5 [full name], 8:30–9:00 (30 seconds)**

Our choice follows ownership and workload. SQL protects the order, stock and loyalty transaction as a single unit. MongoDB stores related review content and flexible preferences with validation and deliberate indexes. The comparison returns matching answers and reports measured costs for one workload. The supplied code, source data, setup guide and tests let another person reproduce the prototype. This concludes the database demonstration.

## Live demonstration cues

Use the UI walkthrough in the user manual and the acceptance sequence in `docs/ACCEPTANCE.md`. Keep transitions inside the allocated slide time.

1. **SQL segment:** log in as cashier, complete one in-stock sale, inspect ingredient deductions and customer points, then show the unchanged result of a safe request replay. Show one stock receipt and its unchanged replay. If the UI does not expose a replay action, use the prepared API example or integration test evidence.
2. **SQL failure evidence:** explain the real concurrent last-serving and redemption tests. Do not present sequential UI clicks as a concurrency test. Show the shortage rollback test and its assertions instead of inventing a live failure result.
3. **MongoDB segment:** switch to the customer account, create or edit a review for an owned completed order, and update preferences. Switch to manager to add a reply and show complaint analysis. Use a review ID from the live database.
4. **Comparison:** show the included measured table and matching-result evidence. Explain exactly one indexed workload, warm caches and connector costs. If remeasurement changes the values, update both the deck and report.

## Recording checklist

- Every member presents a substantive segment and displays their name.
- Keep the required order: background/data, SQL implementation/demo, MongoDB implementation/demo, then comparison.
- Record readable application windows and explain database behaviour while showing it.
- Distinguish historical public locations, genuine external sentence examples and generated operational data.
- Use the actual test logs. A skipped integration test is not a pass.
- Record at normal speed and keep the final MP4 within ten minutes.
- Replace the cover placeholders and verify the final PPTX in the software used for presentation.
- Include the final video, slides, final report, data/source code and user manual in the required submission set.

## Honest project boundaries

The prototype implements completed cash sales. It does not implement a real payment gateway, refunds, expiry allocation, demand forecasting or a distributed transaction across the two databases. The MongoDB outage check uses fault injection. It does not measure a real network outage. A future enhancement must not appear as an implemented demonstration.
