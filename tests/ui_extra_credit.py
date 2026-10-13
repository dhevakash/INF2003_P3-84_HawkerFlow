"""Live UI checks for the five enhancements; writes/discards one labelled batch.

Run after seeding a live app. Existing inventory quantity is unchanged by the
receive/discard pair; audit records remain deliberately. No mocked API data.
"""
import argparse
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

from playwright.sync_api import expect, sync_playwright


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", default="http://127.0.0.1:8000")
    parser.add_argument("--output", default="evidence/extra-credit/ui")
    args = parser.parse_args()
    output = Path(args.output)
    output.mkdir(parents=True, exist_ok=True)
    result = {"base_url": args.base_url, "checks": [], "js_errors": [], "writes": {}}
    with sync_playwright() as pw:
        browser = pw.chromium.launch()
        context = browser.new_context(base_url=args.base_url, viewport={"width": 1440, "height": 1000})
        page = context.new_page()
        page.on("pageerror", lambda error: result["js_errors"].append(str(error)))
        page.goto("/")
        page.locator('[data-demo="manager"]').click()
        page.locator('#login-form button[type="submit"]').click()
        expect(page.locator("#workspace")).to_be_visible(timeout=15000)

        def loaded():
            expect(page.locator("#content > .loading")).to_have_count(0, timeout=15000)
            expect(page.locator("#page-error")).to_be_hidden()
            expect(page.locator("#content .form-error")).to_have_count(0)

        def api(path):
            token = page.evaluate("sessionStorage.getItem('hf_token')")
            response = context.request.get("/api" + path, headers={"Authorization": "Bearer " + token})
            assert response.ok, response.text()
            return response.json()

        def tab(name, heading):
            page.locator(f'[data-insight-tab="{name}"]').click()
            expect(page.get_by_role("heading", name=heading, exact=True)).to_be_visible(timeout=15000)
            loaded()

        def check_mobile(name):
            page.set_viewport_size({"width": 390, "height": 844})
            assert page.evaluate("document.documentElement.scrollWidth <= innerWidth + 1"), name
            page.screenshot(path=str(output / f"mobile-{name}.png"), full_page=True)
            page.set_viewport_size({"width": 1440, "height": 1000})

        loaded()
        availability = api("/menu/availability?branch_id=1")
        assert any(row["sellable"] for row in availability)
        expect(page.locator("#content")).to_contain_text("portions")
        result["checks"].append("Ingredient-aware menu shows live available portions")

        page.locator('[data-view="dashboard"]').click()
        expect(page.get_by_role("heading", name="Daily net revenue", exact=True)).to_be_visible(timeout=15000)
        with page.expect_response(lambda r: "/api/analytics/dashboard?" in r.url):
            page.locator("#demo-analysis").click()
        loaded()
        page.locator("#branch-selector").select_option("")
        with page.expect_response(lambda r: "/api/analytics/dashboard?" in r.url and "branch_id" not in r.url):
            page.locator('#dashboard-filters button[type="submit"]').click()
        loaded()
        expect(page.locator("#content svg")).to_have_count(1)
        dashboard = api("/analytics/dashboard?start=2026-08-25&end=2026-09-28")
        assert dashboard["summary"]["orders"] >= 200
        page.screenshot(path=str(output / "sales.png"), full_page=True)
        check_mobile("sales")
        result["checks"].append("Seeded sales, all branches, actual revenue chart and mobile layout")

        with page.expect_response(lambda r: "/api/analytics/dashboard?" in r.url):
            page.locator("#compare-analysis").click()
        loaded()
        comparison = api("/analytics/dashboard?start=2026-09-10&end=2026-09-28")
        assert comparison["summary"]["previous_net_revenue"] > 0
        assert comparison["summary"]["revenue_change_pct"] is not None
        assert comparison["underperforming"]
        expect(page.locator("#start-date")).to_have_value("2026-09-10")
        page.screenshot(path=str(output / "sales-comparison.png"), full_page=True)
        result["checks"].append("Equal-period preset has a real comparison baseline and declining dishes")

        tab("forecast", "Ingredient demand & restock forecast")
        expect(page.locator("#content")).to_contain_text("Current on hand")
        forecast = api("/analytics/forecast?branch_id=1&as_of=2026-09-28")
        assert any(row["average_daily_usage"] > 0 for row in forecast["ingredients"])
        assert forecast["stock_basis"] == "current_snapshot"
        expect(page.locator("#insight-panel details summary")).to_be_visible()
        page.locator("#insight-panel details summary").click()
        expect(page.locator("#insight-panel")).to_contain_text("7-day average")
        page.screenshot(path=str(output / "forecast.png"), full_page=True)
        check_mobile("forecast")
        result["checks"].append("Recorded-demand forecasts and expandable rolling SQL averages")

        tab("loyalty", "Customer loyalty insights")
        loyalty = api("/analytics/loyalty?branch_id=1&as_of=2026-09-28")
        assert len(loyalty["customers"]) >= 50
        segment = loyalty["segments"][0]["segment"]
        page.locator("#loyalty-segment").select_option(segment)
        expect(page.locator("#loyalty-customers")).to_contain_text(segment)
        page.locator("#loyalty-segment").select_option("")
        page.screenshot(path=str(output / "loyalty.png"), full_page=True)
        check_mobile("loyalty")
        result["checks"].append("RFM customer scores, segment filter, and mobile layout")

        page.locator("#today-analysis").click()
        loaded()
        tab("waste", "Expiry watchlist")
        page.locator("#as-of-date").fill("2026-10-13")
        with page.expect_response(lambda r: "/api/analytics/waste?" in r.url):
            page.locator('#dashboard-filters button[type="submit"]').click()
        loaded()
        waste = api("/analytics/waste?branch_id=1&as_of=2026-10-13")
        assert waste["summary"]["expiring_batches"] >= 2
        assert waste["summary"]["expired_batches"] >= 1
        assert waste["promotions"]
        expect(page.locator(".promotion-card").first).to_be_visible()
        page.locator(".promotion-card details summary").first.click()
        expect(page.locator(".promotion-card").first).to_contain_text("expiry urgency")
        page.screenshot(path=str(output / "waste-promotions.png"), full_page=True)
        check_mobile("waste")
        result["checks"].append("Expiry statuses, known value and promotion score/reasons")

        page.locator('[data-view="inventory"]').click()
        expect(page.locator("#receive-form")).to_be_visible(timeout=15000)
        loaded()
        stock = api("/inventory?branch_id=1")[0]
        yesterday = (datetime.now(timezone(timedelta(hours=8))).date() - timedelta(days=1)).isoformat()
        form = page.locator("#receive-form")
        form.locator('[name="ingredient_id"]').select_option(str(stock["ingredient_id"]))
        form.locator('[name="quantity"]').fill("1")
        form.locator('[name="expires_on"]').fill(yesterday)
        form.locator('[name="unit_cost"]').fill("0.0123")
        with page.expect_response(lambda r: r.url.endswith("/api/inventory/receive") and r.request.method == "POST") as received:
            form.locator('button[type="submit"]').click()
        assert received.value.ok, received.value.text()
        delivery = received.value.json()
        result["writes"]["verification_batch"] = delivery["batch_id"]
        expect(page.locator(f'[data-discard="{delivery["batch_id"]}"]')).to_be_visible(timeout=15000)
        page.once("dialog", lambda dialog: dialog.accept())
        with page.expect_response(lambda r: r.url.endswith(f'/api/inventory/batches/{delivery["batch_id"]}/discard')) as discarded:
            page.locator(f'[data-discard="{delivery["batch_id"]}"]').click()
        assert discarded.value.ok, discarded.value.text()
        expect(page.locator(f'[data-discard="{delivery["batch_id"]}"]')).to_have_count(0, timeout=15000)
        loaded()
        after = next(row for row in api("/inventory?branch_id=1") if row["ingredient_id"] == stock["ingredient_id"])
        assert after["quantity"] == stock["quantity"]
        assert after["sellable_quantity"] == stock["sellable_quantity"]
        page.screenshot(path=str(output / "inventory-batches.png"), full_page=True)
        check_mobile("inventory")
        result["checks"].append("Dated/costed delivery and audited expired disposal leave original quantity intact")
        assert not result["js_errors"], result["js_errors"]
        result["status"] = "passed"
        (output / "results.json").write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
        print(json.dumps(result, indent=2))
        browser.close()


if __name__ == "__main__":
    main()
