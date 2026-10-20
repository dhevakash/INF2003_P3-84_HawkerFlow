"""Read-only browser/axe/viewport audit; preserves before/after raw evidence.

Fetch pinned axe-core to evidence/redesign/tools/axe.min.js before running.
No business records are created, changed or deleted by this audit.
"""
import argparse
import json
from pathlib import Path
from datetime import datetime, timezone
from playwright.sync_api import sync_playwright, expect

WIDTHS = [320, 375, 768, 1024, 1440, 1920]
METRICS = """() => {
  window.auditVitals={lcp:0,cls:0,events:[]};
  try { new PerformanceObserver(l=>{for(const e of l.getEntries()) window.auditVitals.lcp=e.startTime;}).observe({type:'largest-contentful-paint',buffered:true}); } catch {}
  try { new PerformanceObserver(l=>{for(const e of l.getEntries()) if(!e.hadRecentInput)window.auditVitals.cls+=e.value;}).observe({type:'layout-shift',buffered:true}); } catch {}
  try { new PerformanceObserver(l=>{for(const e of l.getEntries())if(e.interactionId)window.auditVitals.events.push({id:e.interactionId,duration:e.duration,name:e.name});}).observe({type:'event',buffered:true,durationThreshold:16}); } catch {}
}"""


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--phase", choices=["before", "after"], required=True)
    parser.add_argument("--base-url", default="http://127.0.0.1:8000")
    parser.add_argument("--strict", action="store_true")
    args = parser.parse_args()
    out = Path("evidence/redesign") / args.phase
    out.mkdir(parents=True, exist_ok=True)
    axe = Path("evidence/redesign/tools/axe.min.js").read_text(encoding="utf-8")
    core_script = Path("evidence/redesign/tools/web-vitals.iife.js").read_text(encoding="utf-8") + """
    for(const name of ['LCP','INP','CLS']) webVitals['on'+name](metric=>window.captureVital({name:metric.name,value:metric.value}),{reportAllChanges:true});
    """
    results = {"phase": args.phase, "base_url": args.base_url, "recorded_utc": datetime.now(timezone.utc).isoformat(),
               "widths": WIDTHS, "scenes": [], "js_errors": [], "performance_lab": []}
    with sync_playwright() as pw:
        browser = pw.chromium.launch()
        context = browser.new_context(base_url=args.base_url, viewport={"width":1440,"height":1000})
        context.add_init_script("("+METRICS+")()")
        page = context.new_page()
        page.on("pageerror", lambda e: results["js_errors"].append(str(e)))

        def loaded():
            page.wait_for_function("""() => !document.querySelector('#content > .loading') && document.querySelector('#content')?.getAttribute('aria-busy')!=='true'""", timeout=15000)
            expect(page.locator("#page-error")).to_be_hidden()

        def scene(name):
            record = {"name": name, "viewports": []}
            for width in WIDTHS:
                page.set_viewport_size({"width":width,"height":1000 if width>=768 else 844})
                dimensions = page.evaluate("""() => {
                  const visible=e=>{const r=e.getBoundingClientRect();const s=getComputedStyle(e);return r.width>0&&r.height>0&&s.visibility!=='hidden'&&s.display!=='none';};
                  const nav=[...document.querySelectorAll('.nav-item')].filter(visible).map(e=>{const r=e.getBoundingClientRect();return {text:e.textContent.trim(),height:r.height,width:r.width,right:r.right,withinViewport:r.right<=innerWidth+1&&r.left>=0};});
                  const small=[...document.querySelectorAll('button,input,select,summary')].filter(visible).map(e=>{const r=e.getBoundingClientRect();return {text:(e.textContent||e.name||e.id).trim().slice(0,60),height:r.height,width:r.width};}).filter(e=>e.height<24||e.width<24);
                  return {viewport:innerWidth,documentWidth:document.documentElement.scrollWidth,nav,targetsBelow24px:small,bodyFont:getComputedStyle(document.body).fontSize};
                }""")
                record["viewports"].append(dimensions)
                if width in (375,1440):
                    page.screenshot(path=str(out/f"{name}-{width}.png"),full_page=True)
            page.set_viewport_size({"width":1440,"height":1000})
            page.evaluate(axe)
            report = page.evaluate("""async()=>{const r=await axe.run(document,{runOnly:{type:'tag',values:['wcag2a','wcag2aa','wcag21aa','wcag22aa','best-practice']}});return {violations:r.violations.map(v=>({id:v.id,impact:v.impact,description:v.description,helpUrl:v.helpUrl,nodes:v.nodes.map(n=>({target:n.target,failureSummary:n.failureSummary}))})),incomplete:r.incomplete.map(v=>({id:v.id,nodes:v.nodes.length})),passes:r.passes.length};}""")
            record["axe"] = report
            if args.phase=="after":
                page.set_viewport_size({"width":375,"height":844})
                record["axe_mobile"] = page.evaluate("""async()=>{const r=await axe.run(document,{runOnly:{type:'tag',values:['wcag2a','wcag2aa','wcag21aa','wcag22aa','best-practice']}});return {violations:r.violations.map(v=>({id:v.id,impact:v.impact,nodes:v.nodes.map(n=>({target:n.target,failureSummary:n.failureSummary}))})),incomplete:r.incomplete.map(v=>({id:v.id,nodes:v.nodes.length})),passes:r.passes.length};}""")
                page.set_viewport_size({"width":1440,"height":1000})
            record["vitals_observed"] = page.evaluate("window.auditVitals")
            results["scenes"].append(record)
            print(name, "axe violations:", len(report["violations"]), "viewport overflow:",sum(r["documentWidth"]>r["viewport"]+1 for r in record["viewports"]))
            (out/"audit.json").write_text(json.dumps(results,indent=2)+"\n",encoding="utf-8")

        def login(role):
            page.locator(f'[data-demo="{role}"]').click()
            page.locator('#login-form button[type="submit"]').click()
            expect(page.locator("#workspace")).to_be_visible(timeout=15000)
            loaded()

        def view(name):
            page.locator(f'[data-view="{name}"]').click()
            loaded()

        page.goto("/")
        scene("login")
        login("manager")
        scene("manager-orders")
        view("inventory")
        scene("manager-inventory")
        view("feedback")
        scene("manager-feedback")
        view("dashboard")
        page.locator("#demo-analysis").click()
        loaded()
        scene("manager-sales")
        for tab in ("forecast", "waste", "loyalty", "feedback"):
            page.locator(f'[data-insight-tab="{tab}"]').click()
            loaded()
            scene("manager-"+("reviews" if tab=="feedback" else tab))
        page.locator("#logout").click()
        login("customer")
        scene("customer-orders")
        view("feedback")
        scene("customer-feedback")
        page.locator("#logout").click()
        login("cashier")
        scene("cashier-orders")
        view("inventory")
        scene("cashier-inventory")
        if args.phase=="after":
            page.goto("/about")
            scene("about")

        # Five fresh local desktop runs: lab evidence, not field CWV at p75.
        for index in range(5):
            lab = browser.new_context(base_url=args.base_url,viewport={"width":1440,"height":1000})
            lab.add_init_script("("+METRICS+")()")
            measured={}
            lab.expose_binding("captureVital",lambda source,metric:measured.update({metric["name"]:metric["value"]}))
            lab.add_init_script(core_script)
            lp=lab.new_page()
            lp.goto("/")
            lp.locator('[data-demo="manager"]').click()
            lp.locator('#login-form button[type="submit"]').click()
            expect(lp.locator("#workspace")).to_be_visible(timeout=15000)
            lp.wait_for_function("() => !document.querySelector('#content > .loading') && document.querySelector('#content')?.getAttribute('aria-busy')!=='true'")
            lp.locator('[data-view="inventory"]').click()
            lp.wait_for_function("() => !document.querySelector('#content > .loading') && document.querySelector('#content')?.getAttribute('aria-busy')!=='true'")
            sample=lp.evaluate("""()=>({vitals:window.auditVitals,resources:performance.getEntriesByType('resource').filter(e=>['script','link'].includes(e.initiatorType)).map(e=>({name:e.name.split('/').pop(),transferSize:e.transferSize,encodedBodySize:e.encodedBodySize,duration:e.duration})),navigation:performance.getEntriesByType('navigation').map(e=>({domContentLoaded:e.domContentLoadedEventEnd,load:e.loadEventEnd}))})""")
            lp.goto("about:blank")
            sample["web_vitals_4_2_4"]=dict(measured)
            results["performance_lab"].append(sample)
            lab.close()
        results["summary"] = {"scenes":len(results["scenes"]),"responsive_cases":len(results["scenes"])*len(WIDTHS),
            "axe_rule_violations":sum(len(s["axe"]["violations"]) for s in results["scenes"]),
            "axe_mobile_rule_violations":sum(len(s.get("axe_mobile",{}).get("violations",[])) for s in results["scenes"]),
            "overflow_cases":sum(v["documentWidth"]>v["viewport"]+1 for s in results["scenes"] for v in s["viewports"]),
            "offscreen_nav_cases":sum(any(not n["withinViewport"] for n in v["nav"]) for s in results["scenes"] for v in s["viewports"])}
        (out/"audit.json").write_text(json.dumps(results,indent=2)+"\n",encoding="utf-8")
        print(json.dumps(results["summary"],indent=2))
        browser.close()
        if args.strict:
            assert not results["js_errors"],results["js_errors"]
            assert results["summary"]["axe_rule_violations"]==0
            assert results["summary"]["axe_mobile_rule_violations"]==0
            assert results["summary"]["overflow_cases"]==0
            assert results["summary"]["offscreen_nav_cases"]==0


if __name__=="__main__":
    main()
