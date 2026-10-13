# HawkerFlow extra-credit implementation and presentation guide

This guide explains the five implemented enhancements, their database behaviour, and a repeatable demonstration. Read this before presenting. Operational data and expiry fixtures are synthetic teaching records; public NEA locations and the separate UCI review corpus retain their original provenance.

## What was implemented

| Feature | Where to find it | What it demonstrates |
|---|---|---|
| Smart stock forecasting | Manager intelligence → Stock forecast | Recorded ingredient consumption, zero-filled daily history, CTEs, SQL window averages, explainable restock estimates |
| Food-waste dashboard and promotion suggestions | Manager intelligence → Food waste & offers | Expiry batches, value-at-risk calculations, recipe joins, sales aggregates, deterministic recommendation ranking |
| Ingredient-aware ordering | Orders & points; Kitchen stock | Available portions, shared-ingredient cart checks, FEFO allocation, row locks, transactions, audit records and safe retries |
| Hawker analytics dashboard | Manager intelligence → Sales performance | Net revenue, daily charts, peak hours, dish ranks, previous-period comparisons and declining dishes |
| Customer loyalty insights | Manager intelligence → Customer loyalty | RFM scores, customer segments, CTEs, conditional SQL expressions and aggregation |

The existing MongoDB review analytics remains available under Review intelligence. The new inventory, revenue and loyalty features use MariaDB because they depend on relational operational records and transaction consistency.

## Exact implementation steps

1. Inspected the existing FastAPI routes, SQLAlchemy models, checkout transaction, seed generator, role controls and test suites. Existing checkout already atomically deducted aggregate stock and awarded points.
2. Split work across three parallel sub-agents: inventory/expiry transactions; forecasting/sales/RFM SQL; and the browser interface. Integration, database verification and this guide were handled centrally.
3. Added three tables: `stock_batches`, `stock_batch_allocations`, and `stock_batch_discards`. Existing table layouts are preserved. Schema initialization creates the added tables and backfills existing aggregate stock into batches with unknown expiry and unknown cost.
4. Extended deliveries with optional expiry dates and unit costs. A delivery creates a receipt, a batch and an audited positive stock movement within one transaction. Receipt replay checks the expiry and cost as well as branch, ingredient and quantity.
5. Extended checkout to reject dated expired stock and consume valid batches in earliest-expiry order. Allocations link each sale to its consumed batches. Stock, allocations, receipt lines, movements and points commit together.
6. Added read-only availability, waste and analytics APIs, preserving manager/cashier/customer permissions. Branch-specific cashier reads remain restricted to their assigned branch.
7. Added manager tabs, branch/date filters, an accessible revenue chart, forecast explanations, waste/promotion reasons and RFM customer filtering. Cart checks now aggregate shared recipe ingredients across different dishes.
8. Added known-result analytics tests, inventory failure tests and real MariaDB tests for the added queries and concurrent dated-batch checkout. Browser checks exercise the actual interface and mobile layout.
9. Regenerated the SQL schema and updated setup/presentation documentation. Test results for this enhancement are stored separately under `evidence/extra-credit` so earlier evidence is not mistaken for verification of the new features.

## Run and upgrade

From the project folder, with Docker Desktop running:

```powershell
docker compose up -d --build
docker compose exec app python scripts/seed.py
docker compose ps
```

Open **http://localhost:8000**. Login: **manager@hawkerflow.local**, password **DemoPass123!**. Cashier and customer role shortcuts use the same development password.

The seeder preserves existing records and uses stable keys for synthetic expiry fixtures. Repeating it does not duplicate sales or deliveries. Do not delete database volumes to upgrade. New demo lots are received after the historical orders, rather than assigned to historical sales retroactively.

The bundled expiry demonstration is assessed on **13 October 2026**: chicken expires 14 October, vegetables 15 October, and milk expired 12 October. For a presentation on another day, receive small new batches with dates relative to that day, or set the waste Analysis date to 13 October 2026 and explain that the remaining stock is still a current snapshot. Discard eligibility always uses today's Singapore date.

## 1. Smart stock forecasting

**Problem:** A manager needs to estimate when stock will run out and how much to receive.

**Data flow:** completed checkout → negative `stock_movements` with reason `sale` → daily ingredient usage → demand average → current usable stock → suggested replenishment.

Formulas for the default 28-day history and 7-day coverage plus 2-day lead time:

```text
average daily usage = total recorded ingredient consumption / 28 calendar days
estimated days remaining = current usable quantity / average daily usage
recommended restock = max(0, average daily usage × (7 + 2) − current usable quantity)
```

Example: 56 kg consumed in 28 days means 2 kg/day. With 6 kg usable stock, the estimate is 3 days left and a suggested restock of 12 kg for nine days of coverage. This is an illustrative example, not a promise about fixture quantities.

A calendar CTE creates zero-sale days; an `AVG(...) OVER (... ROWS BETWEEN 6 PRECEDING AND CURRENT ROW)` calculates the seven-day rolling trend. The replenishment estimate uses the full selected-window average; the seven-day average is a separate trend column. The first six trend rows average the available preceding rows.

**Important distinction:** Analysis date changes the historical demand cutoff. Stock and expiry exclusions use the current snapshot and current Singapore date, returned as `stock_as_of`. This feature does not reconstruct past inventory. Historical recorded consumption is used instead of recomputing old sales from today's recipe.

If there are no recorded sales for an ingredient, the exhaustion estimate is absent and the data status is insufficient history. Zero usable stock is still flagged separately as out of stock. The method is a transparent average-demand estimate, not a trained machine-learning model; it does not model seasonality or future spoilage during the coverage period.

**What to say:** “We use recorded consumption, including days with no sales, to estimate ingredient demand. The formula compares that demand against current usable stock and explains the replenishment suggestion.”

## 2. Food-waste dashboard and promotion suggestions

**Problem:** Ingredients can expire before they are sold, and a manager needs to identify dishes that can use them.

Every delivery can record `expires_on` and `unit_cost`, expressed in the ingredient's stock unit. For example, a stock unit of grams requires a cost per gram, not per kilogram.

```text
days to expiry = expiry date − selected analysis date
expired = days to expiry < 0
expiring = 0 ≤ days to expiry ≤ selected horizon (default 7)
known value at risk = remaining quantity × unit cost for expired/expiring lots
```

Unknown expiry stays unknown. Unknown costs are omitted from the known monetary total; they are not treated as known zero-cost inventory. Quantities with different units are not summed into one misleading total.

Recipe joins find dishes that use expiring ingredients. Completed order-line aggregates measure popularity in a 28-day assessment window. Only active dishes with sufficient usable stock are candidates. Expired ingredients are excluded from the suggestion's usable quantities.

The ranking is a documented heuristic:

```text
score = expiry urgency (maximum 50)
      + relative recent dish sales (maximum 30)
      + usable expiring-stock portions, capped at 20 (maximum 20)

urgency = 50 × (horizon − nearest days to expiry + 1) / (horizon + 1)
popularity = 30 × dish portions sold / highest dish portions sold
portion contribution = 20 × min(useful portions, 20) / 20
```

If there are no recent sales, popularity contributes zero. Each suggestion shows the ingredient, expiry, recent sales and score components. The suggested useful portions are bounded by the full recipe's available portions. Promotions advise the manager; they do not publish discounts or alter menu prices automatically.

`v_stock_batch_inventory` provides a reusable joined batch/ingredient/branch view. Expiry classification uses an explicit assessment date in the service, making demonstrations repeatable.

**What to say:** “The system shows which stock is approaching expiry, calculates its known cost, and explains which dishes could use it. The manager can inspect why each suggestion ranks highly.”

## 3. Ingredient-aware ordering and FEFO

**Problem:** A dish depends on several ingredients, and two users can try to buy the last serving at the same time.

```text
portions supported by an ingredient = floor(usable ingredient stock / recipe quantity)
dish available portions = minimum across all required ingredients
```

The browser checks the combined cart's recipe requirements, including ingredients shared by different dishes. Availability is a snapshot; another cashier may change stock before checkout. The server therefore checks the requirements again under row locks.

Checkout sequence:

1. Authorize staff and branch; validate customer, menu, recipe, quantity and points.
2. Check the unique request key and payload hash.
3. Lock the customer, menu and stock records in a consistent order.
4. Lock the ingredient's batches and check usable quantities. A batch whose expiry is before today's Singapore date is unavailable; a batch expiring today remains eligible.
5. Consume dated batches in earliest-expiry order, then batches with unknown expiry. Record `stock_batch_allocations` for traceability.
6. Write the completed order, historical prices, aggregate stock deductions, movements and points.
7. Commit everything together, or roll back everything on failure.

FEFO means **First Expiry, First Out**. It uses expiry dates, not arrival dates. Unknown-expiry legacy stock remains sellable for compatibility, but the app explicitly labels it for verification; an unknown date is not a verified food-safety assurance.

Expired disposal is an explicit manager action in Kitchen stock. It sets the remaining batch quantity to zero, deducts aggregate stock and records the manager and stock movement. Replaying the same request key cannot discard stock twice. The database retains the audit record.

**What to say:** “The UI gives availability guidance, while MariaDB protects the final transaction. Our concurrent test sends two requests for one dated serving and verifies that one succeeds and one is rejected.”

## 4. Hawker analytics dashboard

**Problem:** A manager needs reliable sales trends without overstating revenue.

Net revenue comes from completed `orders.total`, after loyalty discounts. Gross dish sales come from `order_lines.quantity × order_lines.unit_price`, using the historical paid unit price. These are aggregated separately: joining every line into order revenue would count an order total repeatedly.

The dashboard includes total net revenue, order count, average order value, daily revenue, peak hours, quantity-based dish rankings, branch revenue and declining dishes. `DENSE_RANK()` gives equal ranks to dishes with equal quantities.

The comparison period immediately precedes the selected range and has the same number of days. Percentage change is `(current − previous) / previous × 100`. When the previous value is zero, the result is “No comparison baseline,” not an invented percentage. A dish is marked for review when its quantity declined against the previous period.

Sales dates and peak-hour labels use stored UTC timestamps. The end date is exclusive: start 1 September and end 1 October includes September only. Add eight hours if explaining a UTC hour as Singapore local time.

**What to say:** “We separate net order revenue from gross item revenue to avoid multiplying totals through joins. Window functions rank dishes, while equal-duration periods provide a consistent comparison.”

## 5. Customer loyalty insights

RFM means **Recency, Frequency, Monetary value**:

- Recency: calendar days since the customer's latest completed order before the UTC analysis-date cutoff, using all earlier history.
- Frequency: completed orders during the preceding 90 days by default.
- Monetary: net completed order spending in that same window.

| Score | Recency days | Frequency | Net spend SGD |
|---|---|---|---|
| 5 | ≤ 7 | ≥ 10 | ≥ 100 |
| 4 | ≤ 14 | ≥ 6 | ≥ 50 |
| 3 | ≤ 30 | ≥ 3 | ≥ 20 |
| 2 | ≤ 60 | ≥ 1 | > 0 |
| 1 | Older recorded visit | — | — |
| 0 | No recorded visit | No orders in window | No spend in window |

Conditions are evaluated from the highest score down. Segment rules are evaluated in this order: No orders; Dormant (frequency zero); At risk (recency over 30 days); Champions (R/F/M each at least 4); Loyal (F at least 3); Big spenders (M at least 4); Recent customers.

Branch filtering means recency, frequency and spending are assessed for that branch. Customers with no orders are retained through outer joins. The segment is a transparent rule-based label, not a prediction of churn. It does not change the points ledger or send customers any messages.

**What to say:** “RFM turns completed order history into explainable customer groups. The scores and segment rules are visible, and customers with no purchases are still represented.”

## Presentation walkthrough

1. Log in as manager and open **Manager intelligence → Sales performance**.
2. Click **Use seeded sales dates**. This selects 25 August–28 September 2026, with 28 September exclusive. Explain that fixture sales are historical, so today's range may contain few orders.
3. Show net revenue, gross dish sales, rankings, daily chart and peak UTC hours. Select All branches to show branch comparisons. Click **Compare seeded periods** to use 10–28 September against the preceding equal-length period; this supplies a nonzero comparison baseline and examples of declining dishes.
4. Open **Stock forecast** and select a branch. Show one ingredient's usage, usable quantity, estimated days and suggested replenishment. Expand daily usage to show zero-sale days and the rolling average. Explain that stock is current even when demand history is historical.
5. Open **Customer loyalty**. Show one customer's R/F/M values, expand the scoring thresholds and filter a customer segment.
6. Click **Return to today**, then open **Food waste & offers**. For the fixed expiry fixtures use Analysis date **2026-10-13** if needed. Show an expiring batch, an expired batch, known value and one promotion's reasons and score.
7. Open **Kitchen stock**. Show total, usable and expired quantities. Receive a small batch with its expiry and cost if a live write is part of your rehearsed demo. Explain the units before entering the cost.
8. Open **Orders & points**. Explain available portions and ingredients shared by two dishes. Complete an in-stock cash order, then show the receipt, ingredient reduction and points.
9. Show the automated MariaDB concurrency and rollback evidence. Sequential UI clicks do not demonstrate simultaneous contention.

Suggested extra-credit narration takes about three minutes. Fit it into the existing ten-minute recording by shortening repeated basic UI steps. All five members should still explain their assigned substantive work.

## Questions you should be ready to answer

| Question | Answer |
|---|---|
| Why SQL here? | Orders, recipes, batches and points have explicit relationships; checkout requires atomic multi-record changes and row locking. |
| Why keep MongoDB? | Reviews and preferences have flexible nested fields and their own aggregation workload. They do not participate in the stock-and-points commit. |
| Is forecasting AI? | It is a documented average-demand estimate with SQL analytics, not a trained model. |
| What happens when recipes change? | Future availability follows the current recipe; historical consumption comes from recorded stock movements. Historical paid prices remain in order lines. |
| Can the app oversell? | The browser provides a snapshot; the server locks stock and batches before committing. Tests exercise competing requests for the final serving. |
| What does a retry do? | A stable unique request key returns the prior result; changing its payload is rejected. This covers checkout, receiving and disposal. |
| What if expiry or cost is missing? | It stays explicitly unknown. Unknown expiry is not included in expiry-risk calculations, and unknown cost is excluded from known value. |
| Does a promotion go live automatically? | No. It is an explained suggestion; a manager decides what to offer. |
| What if there is no sales history? | The app shows insufficient history and omits the exhaustion estimate. It still reports current stock shortages. |
| What did you actually test? | See `evidence/extra-credit` for this run. SQLite tests check calculations; real MariaDB tests check query compatibility, constraints and concurrency; browser checks verify the screens and workflows. |

## Verification and evidence

The enhancement's actual results and commands are recorded in `evidence/extra-credit/RESULTS.md`. Historical evidence in the parent `evidence` folder belongs to the earlier prototype. Use the latest enhancement results when presenting these features.

Core source files: `app/models.py`, `app/sql_service.py`, `app/sql_routes.py`, `app/advanced_analytics.py`, `app/advanced_routes.py`, `app/sql_views.py`, `app/static/app.js`, and `scripts/seed.py`. Exported schema: `data/schema.sql`.

Remaining boundaries: simulated cash payments, no refunds or distributed transaction, no automated discount publication, no trained forecasting/churn model, and no reconstruction of historical inventory. Synthetic records demonstrate behaviour rather than establish real-world demand accuracy.
