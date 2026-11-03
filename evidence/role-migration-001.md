# Role migration 001 rehearsal

Result: PASS

Test database: `hawkerflow_restore_20261030_165503_test`

The live application and its databases remain on the previous roles.

## Account mapping

| Account ID | Old role | New role |
|---|---|---|
| 1 | manager | staff |
| 2 | cashier | staff |

All 52 existing account IDs were retained.
No initial Admin was created; setup will implement that separately.

## Verification

- all 8 automated tests passed: PASS
- live database data and schema unchanged: PASS
- all non account sql tables unchanged: PASS
- account ids roles customer links correct: PASS
- account columns keys indexes preserved: PASS
- historical order account references unchanged: PASS
- both reporting views unchanged: PASS
- mongo documents indexes validators unchanged: PASS
- no broken references: PASS
- final database constraint has exact target roles: PASS

Automated tests: 8 run, 0 failures, 0 errors, 0 skipped.

## Next step

Implement the backend permissions, model/schema, signup, initial Admin setup, seeds, and website controls as a coordinated upgrade before live migration.
