# Final Admin / Staff / Customer upgrade

Result: PASS. Deployed 2026-10-30 23:08:16 +08:00.

Website: http://localhost:8080

## Delivered

- Three canonical roles enforced by MariaDB constraints, backend permissions and website controls.
- Manager and Cashier became Staff on their existing account rows. Staff reviews are read/reply only; Staff cannot access preference profiles.
- Customer-only public signup, owned review/preference self-service and Admin-only privileged creation/role/status administration.
- Account deactivation preserves IDs/history, blocks sign-in and permanently invalidates old sessions. Reactivation requires fresh sign-in.
- The last active Admin is protected against demotion/deactivation, including concurrent requests.
- One separate initial Admin was created: admin@hawkerflow.local, account ID 53. Password and JWT secret remain local and outside Git.

## Verification

- Python unit/regression: 181 passed, 6 opt-in migration tests skipped.
- Real MariaDB/MongoDB API/setup/migration/concurrency: 33 passed.
- Website DOM interaction: 21 passed.
- Website forms against real MariaDB/MongoDB APIs: 8 passed.
- Total: 243 passed.
- Live Admin, Staff and Customer sign-ins, both database connections and direct forbidden API requests passed.
- Served HTML, JavaScript and CSS match the tested source bytes.

## Preservation

- original account ids passwords emails customer links preserved: PASS
- roles mapped in place: PASS
- original accounts remain active with initial session version: PASS
- all other sql records preserved: PASS
- historical order account links preserved: PASS
- views preserved: PASS
- mongo documents and indexes preserved: PASS
- no broken references: PASS
- only expected initial admin added: PASS
- updated mongo validators installed: PASS

The original 52 accounts remain; the only added login account is the initial Admin. Historical orders, stock, loyalty, reviews and profiles were preserved.

## Recovery artifacts

- Fresh backups, restored and verified before migration: C:\Users\cheet\HawkerFlow-backups\20261030-224804-before-role-upgrade
- Retained compatible rollback image: hawkerflow-before-role-upgrade:20261030-230737
- The prior image tag was unavailable. The rollback image was reconstructed from the running old container source and locked dependencies, then checked before migration.
- The upgraded release test copy is retained as hawkerflow_release_93fbe035faf240cdb52eba221a182ac0_test. Disposable website test databases and grants were removed.
- Recovery must pair a compatible image with restored databases; changing the image alone does not reverse the migration.

## Verification limit

Visual browser layout/native-dialog inspection was blocked by Computer Use browser permissions. Automated DOM, real HTTP/database flows and live backend permission checks passed.

Documentation status paragraphs were refreshed after rollout; no implementation files were changed after verification.
