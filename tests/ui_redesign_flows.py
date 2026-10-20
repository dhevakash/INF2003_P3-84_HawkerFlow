"""Read-only interaction, keyboard, failure-state and session checks."""
import json
from pathlib import Path
from playwright.sync_api import sync_playwright, expect


def main():
    out=Path("evidence/redesign/flows")
    out.mkdir(parents=True,exist_ok=True)
    results={"checks":[],"page_errors":[]}
    with sync_playwright() as pw:
        browser=pw.chromium.launch()
        context=browser.new_context(base_url="http://127.0.0.1:8000",viewport={"width":1440,"height":1000},reduced_motion="reduce")
        page=context.new_page()
        page.on("pageerror",lambda error:results["page_errors"].append(str(error)))
        page.goto("/")
        page.keyboard.press("Tab")
        expect(page.locator("#skip-link")).to_be_focused()
        page.keyboard.press("Enter")
        expect(page.locator("#login-form")).to_be_focused()
        results["checks"].append("Keyboard skip link reaches the visible sign-in form")
        page.locator('[data-demo="manager"]').click()
        page.locator("#login-password").press("Enter")
        expect(page.locator("#workspace")).to_be_visible(timeout=15000)

        def loaded():
            page.wait_for_function("()=>!document.querySelector('#content > .loading') && document.querySelector('#content')?.getAttribute('aria-busy')!=='true'",timeout=15000)
            expect(page.locator("#page-error")).to_be_hidden()

        loaded()
        expect(page.locator("#view-title")).to_be_focused()
        results["checks"].append("Sign-in works with Enter and places focus on the workspace heading")
        page.locator("#menu-search").fill("chicken")
        shown=page.locator("[data-add]:visible")
        assert shown.count()>0
        assert all("chicken" in text.lower() for text in shown.all_text_contents())
        page.locator("#menu-search").fill("no-matching-demo-dish")
        expect(page.locator("#menu-no-results")).to_be_visible()
        page.locator("#menu-search").fill("")
        page.locator("#menu-category").select_option(label="Drinks")
        assert all("Drinks" in text for text in shown.all_text_contents())
        page.locator("#menu-category").select_option("")
        results["checks"].append("Dish text/category search and no-results recovery")
        page.locator('[data-open-insight="forecast"]').click()
        loaded()
        expect(page.locator('[role="tab"][aria-selected="true"]')).to_have_attribute("data-insight-tab","forecast")
        page.locator('[data-insight-tab="forecast"]').focus()
        page.keyboard.press("ArrowRight")
        expect(page.locator('[data-insight-tab="waste"]')).to_be_focused()
        expect(page.locator('[data-insight-tab="forecast"]')).to_have_attribute("aria-selected","true")
        page.keyboard.press("Space")
        loaded()
        expect(page.locator('[data-insight-tab="waste"]')).to_have_attribute("aria-selected","true")
        expect(page.locator('[data-insight-tab="waste"]')).to_be_focused()
        page.keyboard.press("Home")
        expect(page.locator('[data-insight-tab="sales"]')).to_be_focused()
        page.keyboard.press("End")
        expect(page.locator('[data-insight-tab="feedback"]')).to_be_focused()
        results["checks"].append("Manager shortcuts plus manual Arrow/Space/Home/End tab navigation retain focus")
        page.locator('[data-view="inventory"]').click()
        loaded()
        page.locator("#inventory-search").fill("chicken")
        expect(page.locator("[data-stock-name]:visible")).to_have_count(1)
        page.locator("#inventory-search").fill("no-matching-ingredient")
        expect(page.locator("#inventory-no-results")).to_be_visible()
        page.locator("#inventory-search").fill("")
        page.locator("#inventory-low-only").check()
        assert all(row=="true" for row in page.locator("[data-stock-name]:visible").evaluate_all("els=>els.map(e=>e.dataset.stockLow)"))
        page.locator("#inventory-low-only").uncheck()
        results["checks"].append("Ingredient search and usable low-stock filtering")

        # Explicit HTTP fault injection, not a claim about a real service outage.
        page.route("**/api/inventory?*",lambda route:route.fulfill(status=503,content_type="application/json",body='{"detail":"Explicit UI audit failure"}'))
        page.locator('[data-view="inventory"]').click()
        expect(page.locator("#retry-view")).to_be_visible(timeout=15000)
        expect(page.locator("#page-error")).to_contain_text("Explicit UI audit failure")
        page.unroute("**/api/inventory?*")
        page.locator("#retry-view").click()
        loaded()
        expect(page.locator("#inventory-search")).to_be_visible()
        results["checks"].append("Injected read failure shows error and retry recovers without a business write")

        page.locator('[data-view="orders"]').click()
        loaded()
        page.locator(".manager-form > summary").click()
        page.route("**/api/menu/*/recipe",lambda route:route.fulfill(status=503,content_type="application/json",body='{"detail":"Explicit recipe-load failure"}'))
        options=page.locator("#recipe-dish option").all_text_contents()
        page.locator("#recipe-dish").select_option(index=1)
        expect(page.locator("#retry-recipe")).to_be_visible(timeout=15000)
        expect(page.locator('#recipe-form button[type="submit"]')).to_be_disabled()
        page.unroute("**/api/menu/*/recipe")
        page.locator("#retry-recipe").click()
        expect(page.locator('#recipe-form button[type="submit"]')).to_be_enabled(timeout=15000)
        results["checks"].append("Recipe load failure disables saving and its retry reloads safely")

        page.evaluate("sessionStorage.setItem('unrelated-session-key','keep')")
        page.locator("#logout").click()
        expect(page.locator("#login-email")).to_be_focused()
        assert page.evaluate("sessionStorage.getItem('hf_token')")==None
        assert page.evaluate("sessionStorage.getItem('unrelated-session-key')")=="keep"
        page.reload()
        expect(page.locator("#login-screen")).to_be_visible()
        results["checks"].append("Sign-out clears app session, preserves unrelated storage and survives refresh")
        assert not results["page_errors"],results["page_errors"]
        results["status"]="passed"
        (out/"results.json").write_text(json.dumps(results,indent=2)+"\n",encoding="utf-8")
        print(json.dumps(results,indent=2))
        browser.close()


if __name__=="__main__":
    main()
