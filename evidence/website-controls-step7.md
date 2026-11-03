# Step 7: signup, navigation and role-specific website controls

Result: PASS

The source is ready for coordinated deployment; the live website remains on its current image.

## Implemented behavior

- Public Customer signup, password confirmation and normal sign-in; no public role selector.
- Explicit Admin/Staff/Customer navigation allowlists; legacy or unknown roles cannot open a workspace.
- Admin and Staff share menu/customer operations, cash sales, stock receipts, recipes, movements and insights.
- Staff feedback controls are limited to reading and adding business replies; preferences and moderation are absent.
- Customers manage their own purchase reviews and preferences through ownership-protected endpoints.
- Admins manage accounts and roles in place, reviews, business replies and customer preferences.
- The new GET /api/accounts is Admin-only and exposes no credentials or password hashes.
- Permission state is refreshed before navigation and writes; logout/expiry discard stale responses and drafts.
- Untrusted content is rendered as text; API validation inputs are not echoed in website errors.

## Verification

- Python unit/regression: 167 passed; 6 opt-in migration tests skipped.
- Real database API/setup: 30 passed.
- Website DOM interaction: 20 passed.
- Website forms using real MariaDB/MongoDB APIs: 7 passed.
- Total: 224 passed.

The DOM suites execute the shipped HTML and JavaScript. The real-API suite uses a separate local fixture with both DBMSs; it does not substitute fake endpoint responses. DOM testing does not verify browser layout.

Visual review was blocked: the browser host was unavailable and Computer Use denied Google Chrome access. Desktop/mobile layout and native dialog rendering remain unverified.

## Data preservation

- python unit and regression tests pass: PASS
- real database api and setup tests pass: PASS
- website dom interaction tests pass: PASS
- website forms against real mariadb mongodb pass: PASS
- live records and schema unchanged: PASS
- restored test records preserved after rollback: PASS
- account ids roles customer links preserved: PASS
- historical order account links preserved: PASS
- restored mongo documents indexes validators unchanged: PASS
- no broken test references: PASS
- owned preview databases and sql grant removed: PASS

## Remaining rollout work

The permanent initial Admin, live role migration and deployment remain pending. Account deactivation is not added by this UI step; it needs a separate backend/schema change before the full target policy can claim that capability.
No existing account is deleted or recreated to rename its role.
