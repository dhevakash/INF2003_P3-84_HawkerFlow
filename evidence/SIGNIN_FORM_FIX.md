# Sign-in form reset fix

Status: deployed locally at http://localhost:8080 on 2026-10-30.

## Cause and change

The menu and customer forms contain controls named `id`. Browsers expose those
controls through `form.id`, shadowing the form's ID property. Resolving that value
with `getElementById` returned null and sign-in failed while resetting editors.
The same issue affected sign-out and successful editor submissions.

Reset handlers now pass the form element directly and read its ID attribute with
`getAttribute('id')`. String IDs used by reset buttons remain supported.

## Verification

- Added browser named-control behavior to the jsdom harness; its default behavior
  had missed this browser difference.
- Before the fix, all three new role sign-in regressions reproduced the exact
  `Cannot read properties of null (reading 'reset')` error.
- After the fix, all 25 interface tests passed, including editor saves, sign-out,
  role changes and session expiry.
- Rebuilt and recreated only the Docker app service. No account or database
  changes were needed.
- Live HTTP checks confirmed the deployed HTML and JavaScript match the tested
  source. The DOM harness signed in the existing Admin, Staff and Customer,
  loaded real records and signed out successfully for each role. Both databases
  remain connected. This verification used jsdom rather than a native browser.

Live check report: the ChatGPT project mirror's
`output/hawkerflow-signin-fix/live-ui-smoke.json` (12 passing checks).
