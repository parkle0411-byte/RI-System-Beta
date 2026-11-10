"""Accounting load failure (2026-11-10): a server error shows a persistent message with Retry,
never an empty "No matching accounts" list; Retry recovers. Runs in the disposable UI stack."""
import re
from playwright.sync_api import sync_playwright
BASE = "http://nginx"; PASSWORD = "Ui-Test-Pass-1"
checks = []
def check(name, ok):
    assert ok, name
    checks.append(name); print('PASS ' + name, flush=True)
errors = []
with sync_playwright() as p:
    b = p.chromium.launch(); page = b.new_page(viewport={"width": 1440, "height": 900}); page.set_default_timeout(60000)
    page.on("console", lambda m: errors.append(m.text) if m.type == "error" and "502" not in m.text and "Failed to load resource" not in m.text else None)
    page.goto(BASE + "/login"); page.get_by_label("Username").fill("ui.finance"); page.get_by_label("Password").fill(PASSWORD)
    page.get_by_role("button", name="Sign in").click(); page.wait_for_selector(".app-shell")
    page.evaluate("() => { try { sessionStorage.clear(); localStorage.clear() } catch (e) {} }")
    fail = {"on": True}
    def handler(route):
        if fail["on"]:
            route.fulfill(status=502, content_type="text/html", body="<html><body><h1>502 Bad Gateway</h1></body></html>")
        else:
            route.continue_()
    page.route(re.compile(r".*/api/accounting\?view=list.*"), handler)
    page.goto(BASE + "/accounting")
    alert = page.get_by_test_id("accounting-load-error")
    alert.wait_for()
    text = alert.inner_text()
    check("server error shows a persistent Accounting load error", "could not be loaded" in text and "HTTP 502" in text)
    check("first-load failure asks the user to retry", "Please retry" in text)
    check("the table never claims there are no matching accounts", "No matching accounts" not in page.inner_text("[data-testid=accounting-table]")
          and "could not be loaded" in page.inner_text("[data-testid=accounting-table]"))
    page.wait_for_timeout(4000)
    check("the error message stays visible (not a disappearing toast)", alert.is_visible())
    fail["on"] = False
    page.get_by_test_id("accounting-retry").click()
    page.wait_for_function("() => !document.querySelector('[data-testid=accounting-load-error]')")
    check("Retry reloads Accounting and clears the error", not alert.is_visible())
    page.wait_for_function("() => document.querySelectorAll('[data-testid=accounting-table] .el-table__body tr').length > 0", timeout=60000)
    check("accounts are shown after Retry", page.locator("[data-testid=accounting-table] .el-table__body tr").count() > 0)
    # A later refresh failure keeps the loaded list, says so and disables operations.
    fail["on"] = True
    page.get_by_role("button", name="Refresh", exact=True).click()
    alert.wait_for()
    t = alert.inner_text()
    check("refresh failure keeps the earlier list and explains it", "Showing the list loaded at" in t and "disabled" in t
          and page.locator("[data-testid=accounting-table] .el-table__body tr").count() > 0)
    fail["on"] = False
    page.get_by_test_id("accounting-retry").click()
    page.wait_for_function("() => !document.querySelector('[data-testid=accounting-load-error]')")
    check("Retry after a refresh failure recovers", not alert.is_visible())
    check("no unexpected JavaScript errors", not errors)
    b.close()
print(f"{len(checks)} passed Accounting load-error UI checks")
