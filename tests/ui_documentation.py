"""Verify the served documentation, CSP and demo-information links in Chromium."""
import json
from pathlib import Path
from playwright.sync_api import expect, sync_playwright


def main():
    record={"routes":[],"console_errors":[],"page_errors":[]}
    with sync_playwright() as pw:
        browser=pw.chromium.launch()
        page=browser.new_page(base_url="http://127.0.0.1:8000")
        page.on("pageerror",lambda error:record["page_errors"].append(str(error)))
        page.on("console",lambda message:record["console_errors"].append(message.text) if message.type=="error" else None)
        for path,selector,text in [
            ("/docs",".swagger-ui .info .title","HawkerFlow"),
            ("/redoc","redoc h1","HawkerFlow"),
            ("/about","h1","Demo information & privacy"),
        ]:
            response=page.goto(path)
            assert response.status==200
            expect(page.locator(selector)).to_contain_text(text,timeout=30000)
            record["routes"].append({"path":path,"status":response.status,"visible":True})
        assert not record["console_errors"],record["console_errors"]
        assert not record["page_errors"],record["page_errors"]
        record["status"]="passed"
        Path("evidence/redesign/documentation.json").write_text(json.dumps(record,indent=2)+"\n",encoding="utf-8")
        print(json.dumps(record,indent=2))
        browser.close()


if __name__=="__main__":
    main()
