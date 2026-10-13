# Final report outline and evidence plan

This file follows the supplied INF2003 final-report template. It is a plan for completing the final assessment after the group has run and understood the application; it is not a completed final report. Do not invent team contributions, learning reflections, experiments or performance results.

The final report must use Calibri Body 12 and at most ten body pages, excluding cover, references and appendix. The final submission is due 29 November 2026 at 11:30 PM Singapore time. Use a consistent established citation style such as IEEE.

| Template heading | Suggested body pages | Evidence to include |
|---|---:|---|
| Introduction | 0.75 | Problem, users, objectives, scope, exact contribution table agreed by members |
| System architecture Design and requirements | 1.5 | Architecture, data ownership, requirements, datasets, real/generated provenance |
| Implementation details of relational database and non-relational database | 5.0 | SQL ERD, key constraints, transactions, CRUD, queries; Mongo models, CRUD, validators, indexes and pipelines; matched comparison |
| Discussions | 1.75 | Measured correctness/performance, scalability, reliability, security, specific limitations |
| Reflection and takeaways | 1.0 | Actual lessons and decisions from each member, improvements justified by results |

## Introduction

Explain why a small F&B operator needs stock-aware orders, dependable reward accounting and feedback analysis. Define intended users, completed-cash-sale scope and excluded payments/refunds/expiry batches. State measurable goals such as rollback on shortage and no duplicated rewards on retry. Add a verified member responsibility table only once the group confirms its allocation.

## System architecture Design and requirements

Include a readable architecture diagram, identify the authoritative store for each fact and describe the browser/API/DB interactions. Explain why MongoDB is outside SQL checkout. Describe exact data sources, retrieval dates, licensing attribution, transformations, historical scope and synthetic assumptions. Show a concise ERD and document example in the body; put the full dictionary and larger diagram in an appendix.

Map requirements to acceptance checks, including staff/customer access, audit trails, stock integrity, review eligibility and same-input benchmark correctness. Explain DBMS and toolkit choices; avoid describing JSON customization as impossible in SQL or transactions as impossible in MongoDB.

## Implementation details of relational database and non-relational database

### Relational database implementation

- Describe tables, relationships and representative string/integer/decimal/date types.
- Explain foreign keys, checks, unique request keys, immutable price snapshots and why soft menu deletion protects order history.
- Show actual CRUD paths: create/edit/deactivate menu items; customer and restock management; retrieve orders and ledgers. Financial history deletion is deliberately restricted.
- Explain checkout's transaction boundary, row locking, deterministic lock order, loyalty accounting, request payload validation and rollback.
- Present advanced SQL including joins/aggregates, low-stock reports and any genuinely implemented nested/window queries. Do not claim unimplemented constructs merely to populate the rubric.
- Include query plans or index choices and verify revenue is not double-counted after joining order lines.

### Non-relational database implementation

- Explain that the review/profile models are designed independently for their access patterns. The comparison-only SQL review tables are fixtures, not a conversion of the full operational schema or a live replicated store.
- Show example documents with bounded tags/replies and optional preference structures; explain embedding decisions and limits.
- Demonstrate review CRUD, manager replies and profile updates with ownership checks.
- Include actual JSON-schema validation and unique/compound indexes; test them against a real MongoDB server.
- Walk through complaint-tag and monthly-rating pipelines with an example and verified output.
- Explain cross-store checks and service-outage behaviour.

### Comparison

Compare equivalent tag analysis over identical fixtures. Record data sizes, hardware/software, indexes, repetitions, warm-up, median/p95 and correctness. Interpret development/modeling trade-offs as well as timing. Include all results, even if the expected winner is slower. Label SQLite/mongomock unit tests separately from real DBMS integration and performance experiments.

## Discussions

Scalability: discuss index selectivity, dataset growth and bounded documents based on query plans/experiments; do not imply a single-machine test demonstrates distributed scaling.

Reliability: demonstrate shortage rollback, last-stock contention, retry idempotency, redemption safety and SQL behaviour while MongoDB is unavailable. Explain remaining distributed integrity and backup limitations.

Security: describe password hashing, token handling, role checks, branch restrictions, customer ownership and query parameterization. Distinguish implemented controls from production recommendations.

Include known limitations: historical location data, synthetic transactions/feedback, cash-sales-only, no real payments/refunds/expiry allocation and development deployment assumptions.

## Reflection and takeaways

Record the group's actual design changes, bugs resolved, results that changed decisions and lessons about relational/document modeling. Each member supplies their own contribution and reflection. A useful reflection identifies a concrete issue, the action taken, evidence and what would be changed next time.

## Reference and Appendix I

Cite dataset pages, licence, DBMS documentation and any borrowed material. Retain exact source identifiers and dates. Appendix I includes a private repository/download link with evaluator access, complete ERD, field dictionary, document validators, query/pipeline snippets, benchmark output and clean-install instructions as appropriate. Verify the code link rather than leaving a placeholder in the final submission.

## Other mandatory final deliverables

| Deliverable | Required format or limit | Final check |
|---|---|---|
| Report | PDF, ten body pages maximum | Render inspect and check actual page count |
| Slides | PowerPoint presentation | SQL and NoSQL design/demo/analysis are legible |
| Video | MP4, ten minutes maximum at normal speed | All five members appear/present and names are shown |
| Source/data/manual | One source archive included with final package | Reproduce setup on a clean machine; exclude libraries/secrets |
| Peer review | Follow emailed instructions | Each member submits their own contribution rating |

Presentation order is mandatory: background and datasets, SQL implementation/demo, NoSQL implementation/demo with rigorous comparison, then optional performance analysis. An honest completed implementation, explanations and measured evidence are more important than visual polish alone.
