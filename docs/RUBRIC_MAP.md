# Assessment map

The supplied project brief gives the group project 50% of the module grade, split equally between relational and non-relational work. Within the project, the listed weights are progress proposal 10%, presentation 25%, final report 25%, and project quality/implementation 40%. The starter targets the implementation requirements. It does not replace the team's assessed explanation, report or video.

| Requirement in supplied brief | Starter location | Team evidence needed |
|---|---|---|
| Appropriate application using SQL and NoSQL | `docs/ARCHITECTURE.md`, API modules | Explain ownership of each fact and why the stores differ |
| Sufficient, appropriate datasets | `data/README.md`, seed/import commands | Show actual counts and distinguish real addresses, synthetic sales and external Yelp sentences |
| Relational ER design and varied types/relations | `database/er_diagram.mmd`, `app/models.py` | Verify DDL on MariaDB; explain all keys and associative tables |
| SQL construction and CRUD | CLI + menu/customer/order/stock endpoints | Demo successful writes, updates and a valid deletion; show SQL state afterwards |
| SQL constraints and advanced functions | Checkout, reporting views, CTE/window rank, nested query | Show rollback, duplicate-key rejection, FK/check rejection and correct analytics |
| NoSQL schema and document design | Validators, reviews, profiles | Show nested categories, bounded replies and why documents fit these records |
| Substantial NoSQL manipulation | Review CRUD, replies, profiles | Demo actual MongoDB CRUD and role/ownership failures, not only JSON in browser memory |
| Advanced NoSQL operations | `$match`, `$unwind`, `$group`, `$sort`, date grouping; indexes | Verify pipelines on MongoDB; show returned results and an explain plan |
| Well-tested, accurate, useful implementation | `tests/`, `docs/TESTING.md` | Run real DBMS tests; collect failure and success evidence |
| Performance comparison / extra credit | `scripts/benchmark.py` | Same inputs and results, declared indexes, repeated timings, versions, hardware and limitations |
| Reproducible source/data/manual archive | README, pinned lock file, raw data and docs | Test a fresh extraction on another teammate's machine |
| Presentation clarity and required sequence | `docs/DEMO_WALKTHROUGH.md` | Background → SQL demo → NoSQL demo → optional evaluation; all five members present; <=10 minutes |

Extra-credit work should solve a useful problem and have evidence. A forecasting screen or attractive interface alone is insufficient if the underlying database operations are not implemented and explained.

Source documents: `INF2003_project_description(1).pdf` (Tasks and Assessment Criteria), `Project_QA1(1).pdf` (language/data/UI clarifications), and `84_INF2003_Progress_Report.docx` (Team 84 agreed application and data plan). The final-report template is not modified or populated.
