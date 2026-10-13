# Team plan and submission schedule

The progress report is due 4 October 2026 at 11:30 PM Singapore time. The final package is due 29 November 2026 at 11:30 PM Singapore time. The report builder deliberately retains placeholders for the unknown group number, five member names and submission date. Replace these before submission.

## Responsibilities to agree

| Workstream | Primary responsibility | Independent review |
|---|---|---|
| Member 1 | SQL schema, ERD, constraints and analytical queries | Member 2 checks consistency and historical totals |
| Member 2 | Checkout, restocking, loyalty and concurrency | Member 5 tests rollback, retries and overselling |
| Member 3 | MongoDB models, validators, CRUD, indexes and pipelines | Member 1 checks modeling/comparison equivalence |
| Member 4 | Backend integration, role controls and browser interface | Member 3 checks customer ownership and review behaviour |
| Member 5 | Dataset provenance, seed generation, benchmarks and clean setup | Member 4 reproduces installation and data loading |

These are proposed allocations, not claimed student contributions. All members must understand both DBMSs, contribute to the final report and present in the final video. Agree named ownership in a shared work log and review actual commits/tests weekly.

## Milestones

| Period | Completion evidence |
|---|---|
| 2–4 Oct | Scope approved by group; data sample inspected; ERD/document model checked; two-page progress body verified; identities filled |
| 5–18 Oct | Real stores initialized; CRUD working; deterministic data load; four screens connected |
| 19 Oct–1 Nov | Transaction and loyalty tests; Mongo validation/pipeline tests; branch permissions; query plans |
| 2–15 Nov | Real DBMS concurrent tests; comparable benchmark with verified output; failure behaviour; clean install |
| 16–22 Nov | Feature freeze; verified contribution log; draft ten-page report; slides and demonstration script |
| 23–29 Nov | All-member rehearsal/recording; ten-minute video check; final PDF/source archive inspection; submission |

## Demonstration plan

| Segment | Target time | Evidence |
|---|---:|---|
| Background and data | 1:15 | Business scenario; exact real/generated provenance |
| SQL design and checkout | 2:00 | ERD; successful sale; price snapshot; points and ingredient movements |
| SQL integrity and analytics | 1:45 | Shortage rollback; retries/contention; branch analytics and indexes |
| MongoDB design and workflows | 2:00 | Review/profile documents; ownership/validation; manager reply; tag pipeline |
| Comparison and conclusions | 2:00 | Same-input correctness; measured results; limitations and lessons |

The 9:00 target leaves room for transitions while staying under ten minutes. Assign these segments to all five members and show names on screen. Follow the mandated background → SQL → NoSQL → optional performance order.

## Submission preparation

For progress, fill identity placeholders, confirm every Current Deliverables claim matches files and test logs, and check two body pages in Word/PDF. Do not submit a source archive instead of the required progress report.

For final, include report PDF, slides, MP4 video and one data/source/user-manual archive in the submission package. Verify evaluator repository access if using a link. Do not include DB binaries, installed dependency folders, private credentials or fabricated benchmark output. The manual must permit a fresh installation, schema initialization, data loading and repeatable demonstration.

Each week, collect actual evidence in a shared log: feature, author, reviewer, commit, command run, result and remaining issue. Reflection and peer review should describe real contributions.
