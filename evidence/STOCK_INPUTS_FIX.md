# Stock input fixes

Deployed locally at http://localhost:8080 on 2026-11-03.

The previous correction form showed readonly Branch/Ingredient ID inputs, which
required selecting a table action. Both stock forms now use named Branch and
Ingredient dropdowns. Choosing an ingredient directly loads its balance and unit
and enables the correction quantity/reason. Changing branches clears stale choices
and balances. The table's Edit stock action remains available.

Stock quantities use decimal text inputs. Input/paste handling rejects letters,
exponent notation, signs, commas and more than three decimal places. Submission
also validates the complete quantity. Backend stock input schemas reject exponent
quantity strings and require integer receipt IDs. Existing numeric bounds, role
checks, audit history and stale-edit protection remain in force.

Verification:

- 32 interface tests passed, including direct selection, enabled/disabled fields,
  branch changes, per-ingredient units, typed/pasted invalid input and forged submits.
- 95 focused Python API/permission tests passed, including invalid receipt IDs,
  exponent quantity strings and preservation of stock on rejected requests.
- 9 real HTTP interface tests passed against disposable MariaDB/MongoDB databases.
  They covered correction through dropdowns, receipt entry, audit history, backend
  input validation, role boundaries, sign-in and existing order protection.
- 15 checks passed against the deployed app, including matching HTML/JS/CSS,
  direct stock selection, rejected typed `e` and rejected exponent API strings.
  Live stock/order values were unchanged by verification.

Only the app service was rebuilt/recreated; no database migration was needed.
Disposable preview/test databases were removed. The live report is in the ChatGPT
project mirror at `output/hawkerflow-stock-inputs/live-check.json`.
Interface automation uses jsdom and live HTTP APIs rather than a native browser.
