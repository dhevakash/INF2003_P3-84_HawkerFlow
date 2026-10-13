"""Real-browser acceptance exercise against a running, seeded HawkerFlow app.

Writes one labelled smoke dish/order/review and one audited restock receipt.
The review is deleted; the smoke dish is left inactive for receipt integrity.
Run outside pytest: python tests/ui_smoke.py --base-url http://127.0.0.1:8000
"""
import argparse
import json
import time
from pathlib import Path

from playwright.sync_api import sync_playwright, expect


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-url", default="http://127.0.0.1:8000")
    parser.add_argument("--browser", default=None, help="Optional Chrome executable; otherwise use installed Playwright Chromium")
    parser.add_argument("--output", default="evidence/ui")
    args = parser.parse_args()
    output = Path(args.output)
    output.mkdir(parents=True, exist_ok=True)
    results = {"base_url": args.base_url, "checks": [], "writes": {}, "js_errors": []}
    name = f"UI smoke dish {int(time.time())}"

    with sync_playwright() as playwright:
        launch_options = {"args": ["--no-sandbox", "--disable-dev-shm-usage"]}
        if args.browser:
            launch_options["executable_path"] = args.browser
        browser = playwright.chromium.launch(**launch_options)
        context = browser.new_context(viewport={"width": 1440, "height": 1000}, base_url=args.base_url)
        page = context.new_page()
        page.on("pageerror", lambda error: results["js_errors"].append(str(error)))
        page.goto("/")
        page.screenshot(path=str(output / "01-login.png"), full_page=True)

        def loaded():
            expect(page.get_by_text("Working…", exact=True)).to_have_count(0, timeout=15000)
            expect(page.locator("#content > .loading")).to_have_count(0, timeout=15000)
            expect(page.locator("#page-error")).to_be_hidden()

        def login(role):
            page.locator(f'[data-demo="{role}"]').click()
            page.locator('#login-form button[type="submit"]').click()
            expect(page.locator("#workspace")).to_be_visible(timeout=15000)
            loaded()

        def logout():
            page.locator("#logout").click()
            expect(page.locator("#login-screen")).to_be_visible()

        def view(name):
            page.locator(f'[data-view="{name}"]').click()
            loaded()

        def api(path):
            token = page.evaluate("sessionStorage.getItem('hf_token')")
            response = context.request.get(f"/api{path}", headers={"Authorization": f"Bearer {token}"})
            assert response.ok, f"GET {path}: {response.status} {response.text()}"
            return response.json()

        def submit_response(selector, suffix, method):
            with page.expect_response(lambda r: r.url.split("?")[0].endswith(suffix) and r.request.method == method) as pending:
                page.locator(selector).click()
            response = pending.value
            assert response.ok, f"{method} {suffix}: {response.status} {response.text()}"
            return response.json()

        login("manager")
        expect(page.locator('[data-view="dashboard"]')).to_be_visible()
        page.locator("#customer-selector").select_option("1")
        loaded()
        before_orders = api("/orders?branch_id=1")
        results["before_order_count"] = len(before_orders)
        before_points = api("/loyalty/1")["balance"]
        stock = api("/inventory?branch_id=1")
        assert stock, "Seeded branch requires ingredients"
        ingredient = stock[0]
        page.locator(".manager-form > summary").click()
        form = page.locator("#menu-form")
        form.locator('[name="name"]').fill(name)
        form.locator('[name="category"]').fill("UI smoke verification")
        form.locator('[name="price"]').fill("2.00")
        dish = submit_response('#menu-form button[type="submit"]', "/api/menu", "POST")
        loaded()
        results["writes"]["menu_item_id"] = dish["id"]
        page.locator(".manager-form > summary").click()
        with page.expect_response(lambda r: r.url.endswith(f'/api/menu/{dish["id"]}/recipe') and r.request.method == "GET"):
            page.locator("#recipe-dish").select_option(str(dish["id"]))
        recipe_input = page.locator(f'[data-recipe-ingredient="{ingredient["ingredient_id"]}"]')
        expect(recipe_input).to_be_visible()
        recipe_input.fill("0.0001")
        recipe = submit_response('#recipe-form button[type="submit"]', f'/api/menu/{dish["id"]}/recipe', "PUT")
        assert recipe == [{"ingredient_id": ingredient["ingredient_id"], "quantity": 0.0001}]
        results["checks"].append("Manager menu and recipe creation use real SQL APIs")

        page.locator(f'[data-add="{dish["id"]}"]').click()
        page.locator(f'[data-notes="{dish["id"]}"]').fill("Real UI smoke order")
        order = submit_response("#checkout", "/api/orders", "POST")
        loaded()
        results["writes"]["order_id"] = order["id"]
        assert order["total"] == 2.0 and order["customer_id"] == 1 and order["status"] == "completed"
        assert len(api("/orders?branch_id=1")) == len(before_orders) + 1
        assert api("/loyalty/1")["balance"] == before_points + order["points_earned"]
        after_stock = next(row for row in api("/inventory?branch_id=1") if row["ingredient_id"] == ingredient["ingredient_id"])
        assert abs(after_stock["quantity"] - (ingredient["quantity"] - .0001)) < .00001
        expect(page.locator(".receipt")).to_contain_text(f'Order #{order["id"]}')
        page.locator("#close-receipt").click()
        expect(page.locator(".receipt")).to_have_count(0)
        results["checks"].append("Checkout updates receipt, one order, loyalty points and recipe stock")
        page.screenshot(path=str(output / "02-orders.png"), full_page=True)

        view("inventory")
        page.locator('#receive-form [name="ingredient_id"]').select_option(str(ingredient["ingredient_id"]))
        page.locator('#receive-form [name="quantity"]').fill("1")
        submit_response('#receive-form button[type="submit"]', "/api/inventory/receive", "POST")
        loaded()
        received = next(row for row in api("/inventory?branch_id=1") if row["ingredient_id"] == ingredient["ingredient_id"])
        assert abs(received["quantity"] - after_stock["quantity"] - 1) < .00001
        results["writes"]["restock"] = {"ingredient_id": ingredient["ingredient_id"], "quantity": 1}
        results["checks"].append("Manager delivery raises live stock by the recorded quantity")
        page.screenshot(path=str(output / "03-inventory.png"), full_page=True)

        view("orders")
        page.locator(".manager-form > summary").click()
        edit = page.locator(f'[data-menu-edit="{dish["id"]}"]')
        edit.click()
        page.locator('#menu-form [name="price"]').fill("2.50")
        changed = submit_response('#menu-form button[type="submit"]', f'/api/menu/{dish["id"]}', "PATCH")
        loaded()
        assert changed["price"] == 2.5
        assert api(f'/orders/{order["id"]}')["lines"][0]["unit_price"] == 2.0
        page.locator(".manager-form > summary").click()
        inactive = submit_response(f'[data-menu-toggle="{dish["id"]}"]', f'/api/menu/{dish["id"]}', "DELETE")
        loaded()
        assert inactive["is_active"] is False
        results["checks"].append("Menu update preserves historic receipt prices; dish deactivation succeeds")
        logout()

        login("customer")
        expect(page.locator('[data-view="inventory"]')).to_be_hidden()
        expect(page.locator('[data-view="dashboard"]')).to_be_hidden()
        expect(page.locator("#checkout")).to_have_count(0)
        view("feedback")
        page.locator('#review-form [name="order_id"]').select_option(str(order["id"]))
        page.locator('#review-form [name="rating"]').select_option("2")
        page.locator('#review-form [name="text"]').fill("UI smoke review: checking the real customer feedback workflow.")
        page.locator('#review-form [name="tags"]').fill("slow service")
        review = submit_response('#review-form button[type="submit"]', "/api/reviews", "POST")
        loaded()
        review_id = review.get("id", review.get("_id"))
        results["writes"]["review_id_deleted_at_end"] = review_id
        page.locator(f'[data-review-edit="{review_id}"]').click()
        page.locator('#review-form [name="text"]').fill("UI smoke review edited: purchase-linked feedback is editable.")
        edited = submit_response('#review-form button[type="submit"]', f"/api/reviews/{review_id}", "PATCH")
        loaded()
        assert "edited" in edited["text"]
        profile = api("/profiles/1")
        page.locator('#profile-form [name="dietary"]').fill("vegetarian, less sugar")
        saved = submit_response('#profile-form button[type="submit"]', "/api/profiles/1", "PUT")
        loaded()
        assert saved["dietary_preferences"] == ["vegetarian", "less sugar"]
        # Restore existing preferences through the same UI.
        page.locator('#profile-form [name="dietary"]').fill(", ".join(profile.get("dietary_preferences", [])))
        submit_response('#profile-form button[type="submit"]', "/api/profiles/1", "PUT")
        loaded()
        results["checks"].append("Customer owns order/review/profile actions and cannot see staff navigation")
        page.screenshot(path=str(output / "04-customer-feedback.png"), full_page=True)
        logout()

        login("manager")
        view("feedback")
        reply_form = page.locator(f'.reply-form[data-review="{review_id}"]')
        reply_form.locator('[name="text"]').fill("UI smoke manager reply: thank you for the feedback.")
        replied = submit_response(f'.reply-form[data-review="{review_id}"] button', f"/api/reviews/{review_id}/replies", "POST")
        loaded()
        assert "UI smoke manager reply" in replied["replies"][-1]["text"]
        view("dashboard")
        expect(page.locator("#content")).to_contain_text("Net completed sales")
        expect(page.locator("#content .form-error")).to_have_count(0)
        page.locator("#branch-selector").select_option("")
        page.locator('#dashboard-filters button[type="submit"]').click()
        loaded()
        expect(page.locator("#content .form-error")).to_have_count(0)
        external = api("/analytics/external-feedback")
        assert external["total"] == 1000 and external["positive"] + external["negative"] == 1000
        expect(page.locator("#content")).to_contain_text("UCI Yelp sentence sample")
        expect(page.locator("#content")).to_contain_text("benchmark data")
        page.screenshot(path=str(output / "05-manager-insights.png"), full_page=True)
        page.set_viewport_size({"width": 390, "height": 844})
        page.screenshot(path=str(output / "06-mobile-insights.png"), full_page=True)
        overflow = page.evaluate("""() => ({viewport:innerWidth,document:document.documentElement.scrollWidth, elements:[...document.querySelectorAll("body *")].filter(el=>el.getBoundingClientRect().right>innerWidth+1 && !el.closest(".table-wrap") && !el.closest("nav")).map(el=>({tag:el.tagName,class:el.className,width:el.getBoundingClientRect().width,right:el.getBoundingClientRect().right})).slice(0,12)})""")
        assert overflow["document"] <= overflow["viewport"] + 1, f"Mobile view overflows horizontally: {overflow}"
        page.set_viewport_size({"width": 1440, "height": 1000})
        results["checks"].append("Manager replies, SQL/Mongo analytics, separate 1000-sentence UCI benchmark, responsive layout")
        logout()

        login("customer")
        view("feedback")
        page.once("dialog", lambda dialog: dialog.accept())
        with page.expect_response(lambda r: r.url.endswith(f"/api/reviews/{review_id}") and r.request.method == "DELETE") as deleted:
            page.locator(f'[data-review-delete="{review_id}"]').click()
        assert deleted.value.ok
        loaded()
        expect(page.locator(f'[data-review-delete="{review_id}"]')).to_have_count(0)
        results["checks"].append("Owner confirms deletion; review disappears after successful API deletion")
        logout()
        login("cashier")
        expect(page.locator('[data-view="dashboard"]')).to_be_hidden()
        expect(page.locator("#branch-selector")).to_be_disabled()
        expect(page.locator("#menu-form")).to_have_count(0)
        view("inventory")
        expect(page.locator("#receive-form")).to_have_count(0)
        results["checks"].append("Cashier has assigned-branch access and no manager controls")
        assert not results["js_errors"], results["js_errors"]
        results["status"] = "passed"
        (output / "ui-smoke-results.json").write_text(json.dumps(results, indent=2))
        print(json.dumps(results, indent=2))
        browser.close()


if __name__ == "__main__":
    main()
