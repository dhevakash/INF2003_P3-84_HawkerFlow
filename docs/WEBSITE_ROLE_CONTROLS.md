# Step 7: signup and role-specific website controls

The website supports Admin, Staff and Customer and is deployed with the
coordinated role/account activation upgrade. See ACCOUNT_ACTIVATION_AND_ROLLOUT.md
and the final release evidence for the current rollout status.

## Sign-in and public signup

The signed-out screen offers sign-in or **Create a customer account**. Public
signup accepts name, email and a confirmed password of 12-128 characters. There
is no role selector. The browser sends only the three fields accepted by the
customer-only backend and returns to sign-in after creation.

Admin/Staff creation belongs to the Admin Accounts screen. Passwords and tokens
are never placed in local storage, session storage, URL query strings or a
prefilled demo form. Refresh requires sign-in. Credential forms use POST even
when JavaScript is unavailable, to avoid default GET submission of passwords.

## Navigation and actions

| Area | Admin | Staff | Customer |
|---|---|---|---|
| Menu | Read, add, edit, mark unavailable, delete unused items | Same | Read |
| Orders | Read all and complete cash sales | Same | Own purchases |
| Stock, recipes and movements | Read and receive ingredients | Same | Hidden |
| Customer records | Read, add and edit operational records | Same | Hidden |
| Points history | All | All | Own |
| Sales and feedback insights | Available | Available | Hidden |
| Feedback | Create/edit/delete reviews for valid purchases; reply and manage replies | Read and add business replies only | Own purchase reviews and their replies |
| Preferences | Read, create, edit and delete customer profiles | Hidden | Read and save own preferences |
| Accounts | List safe account fields, create Staff/Admin, change roles | Hidden | Hidden |

Staff have no review submission, review edit/delete, reply edit/delete or
preference controls. This includes their own business replies. Customers receive
only their owned reviews, orders and points history from the backend.

Action forms appear above long tables. Form labels, password autocomplete,
keyboard focus indicators, live status messages, a confirmation dialog and a
single-column narrow-screen layout are included. User-provided text is inserted
with DOM text APIs instead of HTML.

The menu delete action explains that historically referenced items must be marked
unavailable. Role changes update the existing account ID; no account deletion or
recreation is used. Customers cannot be assigned to accounts without a customer
link, and the backend rejects demotion of the last Admin.

## Permission refresh and session state

The browser reads `/api/auth/me` before navigation and protected submissions. It
applies explicit allowlists for the three supported roles, hides and clears
obsolete controls when the stored role changes, and rejects unknown roles.

Logout and expired sessions clear results, passwords, form drafts, pending
checkout keys and the in-memory token. Session and navigation versions prevent
late responses from an old session/view from restoring private data or replacing
the current screen. API validation errors display messages without echoing
submitted values.

These controls improve the interface; they do not grant authorization. Direct
API requests remain subject to backend roles, ownership, current stored account
state and business validation. A new Admin-only `GET /api/accounts` supports the
account table; it returns only ID, email, role and customer ID, never a password
or password hash.

## Verification and repeatable tests

The verification report is
[evidence/website-controls-step7.md](../evidence/website-controls-step7.md).

Run the existing Python tests with the installed application dependencies.
`tests/test_account_listing.py` checks safe account fields and direct
unauthorized requests. The existing real MariaDB/MongoDB permission suite also
checks account listing.

For DOM interaction tests, use Node.js 22 or newer (verified with 26.3.0):

```powershell
cd tests/ui
npm ci
npm test
```

The pinned jsdom dependency is for testing only. The running application has no
Node dependency. The tests execute the actual shipped HTML/JavaScript and drive
the forms/events, including forged controls, session expiry, role changes,
stale responses, password mismatch, safe rendering and cash-sale retry keys.
jsdom does not verify CSS layout or native dialog rendering.

`tests/ui/real-api.test.mjs` repeats critical form flows against real HTTP
endpoints backed by both MariaDB and MongoDB. It requires
`RUN_UI_INTEGRATION=1`, `UI_TEST_BASE_URL=http://127.0.0.1:8097` and the
disposable preview created by `tests/ui/serve_fixture.py`. The fixture refuses
live database names and requires its SQL and Mongo database names to match
`hawkerflow_ui_<32 hex characters>_test`. The suite checks its fixture marker
and verifies that the served JavaScript matches the tested source before writes.

The verification used a separate preview container, an explicitly created SQL
database and a matching Mongo database. All temporary preview resources and the
scoped SQL grant were removed afterward. The live and restored test data were
compared before and after the automated suites.

## Verification limits and remaining work

The browser access host was unavailable, and Computer Use denied Chrome access
with "Computer Use was not approved to use Google Chrome." Visual desktop/mobile
layout and native dialog checks therefore remain unverified. The automated DOM
and real API tests are separate evidence and do not replace that visual check.

Account deactivation/reactivation and the coordinated release have since been
implemented in [ACCOUNT_ACTIVATION_AND_ROLLOUT.md](ACCOUNT_ACTIVATION_AND_ROLLOUT.md).
The original Step 7 evidence records the earlier UI-only verification; consult
the final release evidence for the delivered activation controls and rollout.
