# Account activation and coordinated role rollout

The release implements Admin, Staff and Customer roles, customer-only public
signup, initial Admin setup, Admin-only privileged account creation/role changes,
and login-account deactivation/reactivation. Staff can read feedback and add
business replies; review administration and access to customer preferences are
reserved for Admin. Customers retain their own review/preference self-service.

## Account activation

`PUT /api/accounts/{id}/status` accepts exactly `{"active": false}` or
`{"active": true}`. Only an active Admin can call it. The Admin Accounts screen
has corresponding confirmation controls. Deactivation never deletes the account,
changes its ID/password/customer link, or alters historical orders.

Every status transition increments the account's private `session_version`.
Signed tokens contain that version, and every authenticated request checks it
against the current account. Disabled accounts cannot sign in; old tokens remain
invalid after reactivation. A fresh sign-in is required. Tokens from before this
release lack the version claim and require a fresh sign-in as well.

Role changes, privileged creation and activation changes lock Admin rows in the
same order and recheck the acting account's stored active Admin status. The last
**active** Admin cannot be demoted or deactivated. Inactive Admin rows do not count
as a recovery account. Repeating an unchanged status request makes no additional
session-version change.

Account activation is separate from operational customer activation. It does not
change purchases, points or customer preference records.

## Migration

`database/migrations/002_account_activation.py` is the coordinated entry point.
It maps Manager/Cashier to Staff in place using migration 001, then adds
`users.active` (default true) and `users.session_version` (default zero), with
database checks. All existing accounts remain active. Other account fields and
all historical table/view records are fingerprinted before and after.

The connection is supplied explicitly in `ACCOUNT_MIGRATION_DATABASE_URL`.
`--database` must name the same database. Test databases ending in `_test` are
the default allowed targets. A live target additionally requires `--allow-live`.
The standalone 001 CLI remains a test rehearsal command.

MariaDB DDL commits implicitly. The migration is restartable and a successful
rerun is a no-op; it does not promise transaction rollback of all DDL phases.
It refuses unfamiliar activation/version column definitions or constraints.

## Upgrade sequence

1. Take fresh SQL and MongoDB backups and restore them into separate test
   databases. Verify records, schema, indexes, validators and account references.
2. Rehearse migration 002 twice and run the API/website tests against isolated
   test databases. Retain the backup hashes and old application image tag.
3. Save the tested source and build the new image. Keep the current container
   running until the build finishes.
4. Stop only the app container and verify that live data still matches the
   verified backup. If it changed, take and verify a fresh backup first.
5. Run migration 002 with the explicit live URL, exact database and
   `--allow-live`. Run it again to check repeatability.
6. Bootstrap one separate Admin using explicitly supplied credentials. Do not
   promote a legacy Staff account or assume that the new Admin has ID 1.
7. Update MongoDB validators/indexes using `initialize_mongo()`; preserve all
   documents. Configure a private JWT signing secret outside Git.
8. Start the upgraded app, check both database connections and all three sign-in
   roles, and verify that forbidden direct API requests are rejected.
9. Compare all original account identities/password hashes, historical SQL
   records, MongoDB documents/indexes and purchase references. Only role values,
   the new activation/session fields, intended validators and one initial Admin
   may differ.

Do not run demo seeding as an account migration and do not delete database volumes.
If verification fails, keep the app stopped and inspect the retained verified
backup. Restoring the old image alone does not reverse role/data/schema changes.
Recovery should restore the verified backups to separate recovery databases and
point the retained compatible image at those copies, preserving the failed
upgrade for inspection.

## Verification

The release tests include direct backend rejection, historical identity
preservation, last-active-Admin protection, concurrent deactivation, signed-out
and expired sessions, old-token rejection after reactivation, public privilege
injection, customer ownership, Staff reply-only boundaries, and real SQL/Mongo
website form flows.

The rollout evidence is [FINAL_ROLE_UPGRADE.md](../evidence/FINAL_ROLE_UPGRADE.md).
Credentials are generated locally outside the repository and are never included
in test logs or evidence. Visual browser layout/native-dialog review was blocked
by the browser computer-use permission check; the automated DOM/HTTP evidence is
reported separately.
