# Redesign verification — 14 October 2026, Singapore

This run verifies the charcoal/porcelain/burgundy redesign of the existing local application. The test environment uses Windows, host Python 3.13.7, Playwright Chromium, Docker FastAPI, MariaDB 10.11.14 and MongoDB 7.0.16. No mock fallback is used by the website.

## Actual outcomes

| Check | Result | Raw evidence |
|---|---|---|
| Unit and HTTP-quality tests | **72 passed**, no failures/skips | `unit.xml` |
| Real MariaDB/MongoDB integration | **19 passed**, no failures/skips | `integration.xml` |
| Keyboard, search, recovery and session browser checks | **8 passed**, zero page errors | `flows/results.json` |
| Existing core browser workflows | **8 passed**, zero JavaScript errors | `core-ui/ui-smoke-results.json` |
| Advanced-feature browser workflows | **7 passed**, zero JavaScript errors | `extra-credit-ui/results.json` |
| Actual served documentation/info routes | **3 passed**, zero console/page errors | `documentation.json` |
| Responsive geometry/navigation | **84 cases passed** across 14 states and 6 widths | `after/audit.json` |
| Automated accessibility | **28 scans, zero rule violations** (14 desktop + 14 mobile) | `after/audit.json` |
| Source checks | JavaScript syntax and diff whitespace checks passed | `node --check app/static/app.js`; `git diff --check` |

The integration suite only clears dedicated databases ending `_test`. It checks real InnoDB locking, rollback, replay, dates, view/CTE/window compatibility and MongoDB server validation. An old test assumed Singapore's calendar date for UTC reports and failed between Singapore midnight and 08:00; its report date is now derived from the recorded UTC order. This is a test correction, not a change to report semantics.

New browser flow checks are read-only and include explicitly injected HTTP failures. Existing core/extra-credit suites create labelled verification records: an inactive menu item/completed order, receiving/disposal audit records and a temporary review. Review cleanup and preference restoration are part of the core suite. The expiry receive/discard pair restores its starting aggregate and usable stock. Audit records remain intentionally.

## Before and after

| Measurement | Before | After |
|---|---:|---:|
| States inspected | 13 | 14 (adds information page) |
| Axe rule violations across desktop states | 27 | 0 |
| Whole-document overflow cases | 0/78 | 0/84 |
| Cases with navigation outside visible viewport | 20/78 | 0/84 |
| CSS + JS encoded response bodies | 76,317 bytes | 27,401 bytes |

The payload change is **64.1% smaller**, based on actual browser resource timing entries. Before resources were uncompressed; after responses use gzip. These totals exclude headers and test helpers. No runtime UI framework, external font or image dependency was added. The workspace's normal assets are local.

All required widths were inspected: **320, 375, 768, 1024, 1440 and 1920px**. Width checks deliberately test both document overflow and whether navigation destinations are visible. A horizontally scrolling nav can pass the first and fail the second.

Desktop/mobile screenshots under `before` and `after` show login, role-specific orders/feedback/stock, all five manager report categories, and the new information page. Root visually inspected desktop login, mobile reports/navigation, menu/bill hierarchy and the information presentation. Screenshots are real browser captures rather than illustrative designs.

## Local performance measurements

Five fresh, unthrottled desktop Chromium contexts navigated to the real localhost app, signed in with the manager demo account and opened inventory. A pinned **web-vitals 4.2.4** test helper measured LCP/INP/CLS. Page navigation away flushed final measurements. Samples and resource entries are preserved in `after/audit.json`; summary calculation is in `summary.json`.

| Metric | Local sample p75 | Range | Interpretation |
|---|---:|---:|---|
| LCP | **140 ms** | 120–144 ms | Text/local-asset initial page, no image or font download |
| INP | **16 ms** | 16 ms in five runs | Tested sign-in/navigation interactions; browser timings are quantized |
| CLS | **0.001483** | 0–0.001483 | Very small shifts in the measured session windows |

Sample p75 uses nearest-rank `sorted_values[ceil(0.75 × n) − 1]`. These are **local lab samples**, not the 75th percentile of real user traffic. Network/CPU throttling, constrained phones, Safari/Firefox, traffic/load profiles and field Core Web Vitals remain unverified. No production performance claim is made. [Core Web Vitals guidance](https://web.dev/articles/vitals), [measurement library](https://github.com/GoogleChrome/web-vitals).

The baseline browser audit also retained raw native PerformanceObserver timings. It did not originally use the web-vitals helper, so no official before/after Core Web Vitals improvement is claimed. Payload reduction and navigation/accessibility changes are directly comparable.

## Accessibility boundaries

Axe tags: WCAG 2 A/AA, WCAG 2.1 AA, WCAG 2.2 AA and best practice. Automated contrast, landmarks, heading order and accessible semantics improved to zero detected violations in inspected states. Keyboard checks verify skip targets, Enter sign-in, manual tabs/focus, named table regions and recovery actions. Palette contrast was also calculated.

Manual-review `incomplete` results remain recorded around native controls and review content/glyph areas. A zero automated violation count is not complete WCAG conformance. No full screen-reader or real-device certification is claimed. [WCAG 2.2](https://www.w3.org/TR/WCAG22/).

## Reproduction

Install the existing pinned development requirements and Playwright Chromium, start the seeded app, and run from the project root. Do not use a test-database-configured terminal for browser runs against the ordinary demo.

```powershell
.venv\Scripts\python.exe -m pytest tests/test_sql.py tests/test_mongo.py tests/test_inventory_features.py tests/test_advanced_analytics.py tests/test_web_quality.py -q -p no:cacheprovider --junitxml=evidence/redesign/unit.xml
.venv\Scripts\python.exe tests/ui_redesign_flows.py
.venv\Scripts\python.exe tests/ui_documentation.py
.venv\Scripts\python.exe tests/ui_smoke.py --output evidence/redesign/core-ui
.venv\Scripts\python.exe tests/ui_extra_credit.py --output evidence/redesign/extra-credit-ui
.venv\Scripts\python.exe tests/ui_design_audit.py --phase after --strict
```

The read-only design audit needs two development helpers in ignored `evidence/redesign/tools`: `axe.min.js` from `https://cdnjs.cloudflare.com/ajax/libs/axe-core/4.10.3/axe.min.js`, and `web-vitals.iife.js` from `https://unpkg.com/web-vitals@4.2.4/dist/web-vitals.iife.js`. They were downloaded for the audit, are excluded from the Docker context and are not loaded by product pages.

Real integration runs in a separate process:

```powershell
$env:SQL_URL='mysql+pymysql://hawkerflow:hawkerflow_dev@127.0.0.1:3307/hawkerflow_test'
$env:MONGO_URL='mongodb://hawkerflow:hawkerflow_mongo_dev@127.0.0.1:27018/?authSource=admin'
$env:MONGO_DATABASE='hawkerflow_test'
$env:RUN_INTEGRATION='1'
.venv\Scripts\python.exe -m pytest tests/test_integration.py -q -rs -p no:cacheprovider --junitxml=evidence/redesign/integration.xml
```

## Scope and remaining human review

The visual direction and user flows are substantially refined. Local demo credentials and signing secret, process-local throttling, no server token revocation and no approved retention/operator/contact policies remain explicitly documented at `/about`. Public deployment, real personal-data use and full legal/accessibility approval require deployment-specific review. The report scores this as a **local coursework product**, not a certified public service.
