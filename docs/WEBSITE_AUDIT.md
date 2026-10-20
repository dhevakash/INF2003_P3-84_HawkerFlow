# HawkerFlow website audit, redesign and quality assurance

Assessment date: **14 October 2026, Singapore**. Scope: the existing local FastAPI/MariaDB/MongoDB application. This report follows the supplied six-phase audit prompt and the requested change from teal to a more refined palette. It evaluates a coursework demonstration, not an approved public commercial service.

## 1. Overall assessment

The original app had useful, functioning workflows and clear data provenance. Its main weaknesses were small low-contrast text, hidden mobile navigation, generic login copy, repeated rounded panels, keyboard focus loss during rerenders, and insufficient recovery from read errors. The user had already struggled to locate the advanced features; this was a concrete discoverability problem.

The baseline covered thirteen role/view states at six widths. Axe reported **27 rule violations across those states** (repeated rule findings, not 27 distinct WCAG criteria), including colour contrast, heading order and missing login landmarks. Twenty mobile viewport cases had navigation destinations beyond the screen edge. There was no whole-document overflow, demonstrating that “no overflow” alone was an inadequate navigation test. Raw results and screenshots: `evidence/redesign/before`.

### Priorities and actions

| Priority | Original finding and location | Action |
|---|---|---|
| High | `.hint`, tables, badges and navigation used 9–12px text; muted text and badges failed contrast | Larger operational text, stronger neutral colours, checked semantic colours and controls |
| High | `.sidebar nav` and `.insight-tabs` scrolled horizontally, hiding manager features on small screens | Visible mobile navigation grid, wrapping insight tabs, direct Manager tools shortcuts |
| High | Changing views/tabs removed focus and the entire content shell | Heading focus on navigation, manual keyboard tabs, stable loading shell, focus restoration |
| High | Recipe requests could fail or race while the Save button remained available | Request guard, disable saving until loaded, explicit retry |
| High | SQL exception tracebacks could expose statements and bound values in logs | Log exception class only; private-value regression verifies omission |
| Medium | `/docs` and `/redoc` conflicted with the application's script CSP | Route-specific nonces and narrowly scoped resources; app script policy remains local |
| Medium | Index/assets lacked explicit revalidation, contributing to old UI after rebuild | `no-cache` revalidation with conditional 304 responses retained |
| Medium | Menu and stock lists had no actual search; read failures ended in a dead end | Dish/category and ingredient/low-stock filters, recoverable errors and no-results messages |
| Medium | Vague login slogans and repeated decorative framing | Operational copy, two actual workflow descriptions, restrained layout and no decorative orb |
| Medium | No visible demo data/usage notice | Local `/about` page linked from login and workspace; no invented operator or commercial terms |

### Revised direction

The interface now uses **charcoal, porcelain and deep burgundy**, with restrained brass accents. The direction is an operational ledger with an understated editorial introduction: calm contrast, useful density, clear labels and reliable controls. It retains the existing H identity, project name, four primary workspaces, all five advanced features, API contracts and database ownership.

Kept: the real checkout, stock, points and review workflows; meaningful menu grids; metric summaries; source attribution; estimates labelled as estimates; native controls and the lightweight stack. Redesigned: typography, palette, navigation, tables, metric bands, forms, loading/error states and manager tool discovery. Removed: decorative login orb, generic three-statement slogan row, ornamental left stripes, panel shadows and raw JSON/internal codes in product explanations.

## 2. AI-template pattern audit

“Present” is not automatically a defect. The decisions below distinguish useful patterns from decoration or poor usability. Low impact on an absent/not-applicable pattern means no material defect was found, not a request to add it.

| # | Pattern | Original status | Final status | Exact location, impact and decision |
|---|---|---|---|---|
| 1 | Dramatic gradients | Absent | Absent | Global surfaces; Low. Flat surfaces already suited this operations tool; retained. |
| 2 | Default Lucide icons | Absent | Absent | Primary navigation; Low. No Lucide dependency. Existing small symbols are decorative and now hidden from assistive technology. |
| 3 | White backgrounds without hierarchy | Partially Present | Absent | Workspace `.card`, `.metric`; Medium. Original panels looked too similar. Porcelain canvas, metric bands, ledger tables and restrained panels now have different roles. White table surfaces remain intentional. |
| 4 | Rainbow/inconsistent accents | Absent | Absent | Global and status badges; Low. One primary accent with distinct semantic status colours, not arbitrary colour categories. |
| 5 | Excessive drop shadows | Partially Present | Absent | `.card`, `.toast`; Low. Original shadows were subtle rather than a major defect, but added little. Removed in favour of clear borders and surface contrast. |
| 6 | Repeated three-feature cards | Partially Present | Partially Present | Login slogan row and `.metrics`; Medium. Removed the generic login trio. Three-value summaries remain where actual metrics require them, styled as a summary band. |
| 7 | Excessive emoji | Absent | Absent | All views; Low. No emoji decoration added. |
| 8 | Glassmorphism | Absent | Absent | All surfaces; Low. Opaque surfaces preserve readability. |
| 9 | Formulaic AI copy/em-dash habits | Partially Present | Absent | Login slogan and workspace descriptions; Medium. Replaced vague “better flow” copy with cash sales, ingredient batches and order-history tasks. Legitimate dataset punctuation was retained. |
| 10 | Unintentional default typography | Present | Absent | `body` declared Inter without a loaded font or rationale; Medium. Explicit offline Segoe UI operations type and a restrained Georgia introductory headline now serve different purposes. |
| 11 | Generic left-border stripes | Partially Present | Absent | `.explanation-box`, `.reply`; Low. Replaced decorative side stripes with spacing, labels and neutral surfaces. |
| 12 | Fabricated testimonials | Absent | Absent | Customer feedback; Low. Purchase-linked synthetic reviews remain labelled demo data. The UCI corpus is a separate research sample, not an endorsement. |
| 13 | Repetitive bento grids | Partially Present | Partially Present | Manager summaries and two-column reports; Medium. Layout now follows summaries, tables and explanations. Functional menu/metric grids remain; no decorative bento composition introduced. |
| 14 | Decorative fake terminals | Absent | Absent | All pages; Low. Technical documentation is functional, not a fake terminal preview. |
| 15 | Generic marketing catchphrases | Partially Present | Absent | Login headline/body; Medium. Replaced aspirational filler with the counter-to-kitchen workflow and actual actions. |
| 16 | Excessive checkmark lists | Absent | Absent | Login and reports; Low. No repetitive benefit checklist added. |
| 17 | Arbitrary pricing tiers | Not Applicable | Not Applicable | No subscription/checkout pricing page; Low. Actual menu prices remain operational data. |
| 18 | Missing authentic product demonstration | Absent | Absent | Orders, stock, reviews and intelligence; Low. These are real interactive workflows with real database-backed results. No stock imagery or mock counters needed. |
| 19 | Identical rounded corners everywhere | Present | Partially Present | Cards/controls/tags/badges; Medium. Panels 8px, controls 6px, tags 3px and status badges 4px now distinguish roles. Coherent modest rounding is intentionally retained. |
| 20 | Generic purple-and-black SaaS theme | Absent | Absent | Global; Low. Charcoal/burgundy is restrained and tied to the workspace identity, without purple gradients or SaaS decoration. |
| 21 | Missing loading/empty/error states | Partially Present | Absent for tested flows | Views, recipes, filters, external feedback; High. Concise status/busy states, disabled unsafe actions, no-results messages and retry controls are tested. |
| 22 | Decorative radial orbs/glow | Present | Absent | `.login-story:after`; Low. Removed the oversized outline circle because it conveyed no information. |
| 23 | Dot-grid backgrounds | Absent | Absent | Global; Low. No background pattern introduced. |
| 24 | Sparkles/AI decorations | Absent | Absent | All pages; Low. No themed decoration added. |
| 25 | Attention-seeking animated arrows | Absent | Absent | Navigation/action arrows; Low. Static directional symbols remain where useful. Motion respects reduced-motion preferences. |
| 26 | Missing appropriate usage/terms information | Partially Present | Partially Present | Login/workspace footer; Medium. `/about#usage` explains local demo use. Reviewed commercial terms remain pending an actual operator and deployment scope. |
| 27 | Missing privacy information | Present | Partially Present | Login/workspace footer; Medium for demo, High before real-data deployment. `/about#privacy` describes actual stores/session/retention limits. A deployment-specific approved policy still requires human review. |
| 28 | Excessive hover animation | Absent | Absent | Buttons/menu items; Low. Clear hover/focus feedback retained without movement. |
| 29 | Distracting neon | Absent | Absent | Global; Low. Muted accent and semantic colours only. |
| 30 | Generic pastel palette | Partially Present | Absent | Pale mint UI accents; Low. Mint was coherent rather than inherently wrong; replaced under the user's explicit palette preference with porcelain, charcoal and burgundy. |

## 3. Design system

### Typography and spacing

Operational content uses the local **Segoe UI** stack, with system/Arial fallbacks and no font downloads. Body text is 16px; labels and tables 14px; supporting text 12–13px. Headings follow h1 → h2 → h3. Monetary and numeric table data use tabular figures. Georgia is limited to the login introduction, providing character without compromising dense data reading.

Spacing tokens are **4, 8, 12, 16, 24, 32 and 48px**. Layout spacing follows content grouping rather than a repeated decorative card template. Metric labels/explanations remain visible on mobile.

### Colours

| Token/use | Value | Rationale |
|---|---|---|
| Charcoal navigation | `#272328` | Stable workspace anchor |
| Burgundy action/accent | `#713747` | Primary actions, selected tabs, chart lines |
| Porcelain canvas | `#f7f4ef` | Warm neutral with clear white ledgers |
| Main text | `#30292e` | Strong reading contrast |
| Muted text | `#625963` | Secondary text without low contrast |
| Surface divider | `#ded8d3` | Structural table/panel separation |
| Input border | `#94848d` | Visible control boundary |
| Success | `#345e47` on `#e9f0e8` | Distinct status, not the brand accent |
| Warning | `#815316` on `#fff0d9` | Expiry/reorder attention |
| Error | `#a12f2d` on `#fff0ed` | Failure and destructive actions |
| Brass | `#ad8c56` | Small accents on the dark brand area, not low-contrast body text |

Calculated examples: white/burgundy **8.98:1**; muted/white **6.71:1**; muted/porcelain **6.12:1**; input border/white **3.53:1**. Browser axe checks complement these calculations. The goal follows [WCAG 2.2 contrast and navigation requirements](https://www.w3.org/TR/WCAG22/), but this report does not assert complete WCAG conformance.

### Components and responsive conventions

Primary buttons indicate the main action; secondary/text actions remain distinct. Focus outlines are visible, controls have generous targets, disabled states explain availability, and errors are announced. Ledger tables have captions, column scope, meaningful scroll-region names and keyboard scrolling when they overflow. Charts have accessible names and expandable data tables.

Desktop has persistent navigation and content-dependent columns. Tablet and mobile collapse columns, retain usable forms, display navigation in a visible grid and wrap intelligence tabs. Tables scroll inside named regions instead of overflowing the page. Reduced-motion preferences disable smooth scrolling. The implementation preserves native controls and adds no UI framework or runtime font/image dependencies.

## 4. Technical quality

### Functional verification

See `evidence/redesign/RESULTS.md` for the final counts, commands and raw artefacts. New read-only flow checks cover keyboard skip links, Enter sign-in, focus placement, dish/category and ingredient/reorder filters, empty-state recovery, direct manager shortcuts, Arrow/Space/Home/End tabs, recipe request failure/disabled-save/retry, read-error retry and scoped session cleanup.

Read-error and recipe failures are explicit browser HTTP fault injections, not claims of a real database outage. Existing live browser workflows are rerun separately for checkout, stock receiving, historical prices, reviews, preferences, replies, deletion and role restrictions. Real MariaDB tests remain separate from SQLite/mongomock checks.

### Accessibility and responsive findings

After redesign, **14 states × 6 widths = 84 responsive cases** passed the document-overflow/navigation-visibility checks at **320, 375, 768, 1024, 1440 and 1920px**. Fourteen desktop and fourteen mobile axe scans found **zero automated rule violations**. The 14 states cover login; all manager workspaces/five report tabs; customer orders/feedback; cashier orders/stock; and demo information.

Keyboard tests verify focus, skip targets, manual tabs and recovery actions. The tabs follow the [W3C manual-activation pattern](https://www.w3.org/WAI/ARIA/apg/patterns/tabs/), suitable when switching requires a network response. Visual screenshot review checked desktop login, mobile navigation/reports and information density.

Axe still returns manual-review contrast candidates around native inputs and review glyph/content areas; these are recorded as incomplete checks, not silently converted into passes. Palette calculations and screenshots support the implemented contrast, but a complete assistive-technology audit, screen-reader testing, browser/device coverage and every possible user-generated content combination remain outside this verification.

### Performance

Final five-run local measurements and payload changes are recorded in `evidence/redesign/RESULTS.md`. These use fresh Chromium contexts on localhost, a real sign-in and inventory navigation, and a test-only pinned [GoogleChrome web-vitals](https://github.com/GoogleChrome/web-vitals) helper. The helper is not loaded by the product and sends no telemetry to an external service.

Built-in gzip reduces JS/CSS payloads and large responses. Conditional cache revalidation retains 304 support and addresses stale versions after rebuilding. The normal workspace uses local assets, no external font requests and no image downloads. API documentation has separately disclosed external libraries.

These are **lab measurements**, not field data from a user population. Good Core Web Vitals targets are LCP ≤2.5s, INP ≤200ms and CLS ≤0.1, assessed at the user-traffic 75th percentile. No field-percentile claim is made. [Google's Web Vitals guidance](https://web.dev/articles/vitals)

### Security and reliability

API authorization and database ownership were preserved. Scripts remain self-only in the workspace. CSP protects base/object/form destinations; camera, microphone and geolocation permissions are denied. Documentation uses response-specific nonces and narrowly scoped dependencies rather than loosening the workspace script policy. SQL failures log exception class without bound customer data, statements or private driver details; regression tests prove these exclusions.

Known local development credentials and signing key remain for reproducible demonstrations. Sign-out clears browser credentials but does not revoke an already issued server token. Login throttling is process-local. These limitations are visible in the demo notice; this is not a production security certification.

## 5. Outstanding issues

No unresolved functional regression was found in the recorded checks. The following limits remain explicit:

- **Public operator and legal review:** no verified operator, support/DPO contact, approved retention schedule, complete deletion workflow or reviewed commercial service terms are supplied. Do not invent these. Before real personal-data use, the operator must assess applicable purposes, notification/consent, protection, retention and accountability obligations. [PDPC's official obligations overview](https://www.pdpc.gov.sg/overview-of-pdpa/the-legislation/personal-data-protection-act/data-protection-obligations)
- **Production deployment:** replace demo credentials/secrets, define HTTPS/hosting, review session revocation and distributed abuse protection, and establish backup/incident practices for the actual deployment.
- **Accessibility coverage:** zero automated violations is not full conformance. Conduct screen-reader and real-device testing, especially long dynamic tables, validation announcements and user-generated review content.
- **Performance coverage:** no real-user field data, mobile network/CPU-throttled benchmark, load test or Safari/Firefox matrix is claimed. Lab results are specific to this local environment and interactions.
- **Product/data limits:** transactions, expiry lots and local reviews are synthetic; public location data is historical. Cash payments are simulated. Forecasts and offers are explainable estimates. No refunds, payment gateway or automated offer publication was added.
- **Scale:** long histories and report tables still need pagination/server-side search for a larger operational deployment. Current client filtering is intentionally sized to the teaching fixtures.

## 6. Final quality assessment

**Editorial assessment: 88/100 for the local coursework product.** This is a design/engineering judgement, not a Lighthouse score, legal approval or production certification.

| Dimension | Score | Evidence and reason for withheld points |
|---|---:|---|
| Visual identity and originality | 17/20 | Controlled burgundy/charcoal palette, offline typography, distinct ledger/summary composition; the existing simple initial mark is preserved rather than inventing a brand programme. |
| UI/UX and usability | 18/20 | Visible mobile navigation, direct advanced-feature links, meaningful filters, clear dates and keyboard focus/recovery; dense histories still need pagination at scale. |
| Functionality and reliability | 19/20 | Preserved real database workflows, automated rollback/concurrency/role checks, safer recipe requests and retry states; scope remains simulated cash operations. |
| Responsiveness and accessibility | 13/15 | 84 layout cases, 28 zero-violation axe scans, keyboard checks and higher contrast; full screen-reader/device conformance is not established. |
| Performance and technical quality | 12/15 | Compressed local assets, no font/image overhead, measured lab vitals, security/cache fixes; field measurements and constrained-device/load coverage remain unverified. |
| Content quality and credibility | 9/10 | Specific operational copy, transparent synthetic/source data and truthful demo/privacy notice; real operator contact and approved deployment policies require human input. |

The evidence files distinguish baseline observations, implemented changes, measured outcomes and outstanding human review. The website's current state can be inspected at `http://localhost:8000`; the full source and databases remain in the existing project.
