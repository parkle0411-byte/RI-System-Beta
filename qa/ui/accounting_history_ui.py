"""Accounting segmented loading (2026-11-13): the page opens on Unreconciled with open accounts at once;
settled legacy history loads in the background and joins All Accounts / Settled/Closed / Brokerage without
clearing a selection; a failed history load shows a warning with Retry. Runs after the Legacy phases."""
import re
from playwright.sync_api import sync_playwright
BASE = "http://nginx"; PASSWORD = "Ui-Test-Pass-1"
checks = []
def check(name, ok):
    assert ok, name
    checks.append(name); print('PASS ' + name, flush=True)
errors = []
HISTORY = re.compile(r".*/api/accounting\?view=list&legacy=history.*")
with sync_playwright() as p:
    b = p.chromium.launch(); page = b.new_page(viewport={"width": 1500, "height": 950}); page.set_default_timeout(60000)
    page.on("console", lambda m: errors.append(m.text) if m.type == "error" and "502" not in m.text and "Failed to load resource" not in m.text else None)
    requests = []
    page.on("request", lambda r: requests.append(r.url) if "/api/accounting" in r.url and r.method == "GET" else None)
    page.goto(BASE + "/login"); page.get_by_label("Username").fill("ui.finance"); page.get_by_label("Password").fill(PASSWORD)
    page.get_by_role("button", name="Sign in").click(); page.wait_for_selector(".app-shell")
    table = page.get_by_test_id("accounting-table")
    rows = lambda: table.locator(".el-table__body tr.el-table__row")
    heading = lambda: page.locator("h2").filter(has_text=re.compile(r"\(\d+\)")).first.inner_text()
    held = []
    page.route(HISTORY, lambda route: held.append(route))
    page.goto(BASE + "/accounting"); rows().first.wait_for()
    check("Accounting opens on Unreconciled Accounts", "Unreconciled Accounts (" in heading()
          and page.get_by_role("tab", name="Unreconciled Accounts", exact=True).get_attribute("aria-selected") == "true")
    check("the first request excludes settled legacy history", any("legacy=open" in u for u in requests) and not any(u.endswith("view=list") for u in requests))
    page.wait_for_function("() => true"); page.wait_for_timeout(500)
    check("settled legacy history is requested separately in the background", len(held) == 1)
    check("open accounts are usable while history is still loading", rows().count() > 0
          and page.get_by_role("button", name="Mark reviewed", exact=True).count() > 0 and "Historically settled" not in table.inner_text())
    check("no loading notice on the Unreconciled tab", page.get_by_test_id("accounting-history-loading").count() == 0)
    box = rows().first.locator(".el-checkbox").first; box.click()
    check("an account can be selected before history arrives", rows().first.locator(".el-checkbox.is-checked").count() == 1)
    page.get_by_role("tab", name="All Accounts", exact=True).click()
    notice = page.get_by_test_id("accounting-history-loading"); notice.wait_for()
    check("All Accounts shows the background-loading notice with the number of transactions", re.search(r"\(\d[\d,]* transactions\)", notice.inner_text()) is not None)
    before = int(re.search(r"\((\d+)\)", heading()).group(1))
    check("All Accounts lists the accounts already loaded, without settled history", before > 0 and "Historically settled" not in table.inner_text())
    page.get_by_role("tab", name="Unreconciled Accounts", exact=True).click(); rows().first.locator(".el-checkbox").first.click()
    for route in held: route.continue_()
    page.unroute(HISTORY)
    page.get_by_role("tab", name="Settled/Closed", exact=True).click()
    page.get_by_text("Historically settled").first.wait_for()
    check("settled history appears in Settled/Closed when the background load finishes",
          page.get_by_test_id("accounting-history-loading").count() == 0 and "Read-only" in table.inner_text())
    page.get_by_role("tab", name="All Accounts", exact=True).click()
    after = int(re.search(r"\((\d+)\)", heading()).group(1))
    check("All Accounts now includes the settled history", after > before and "Historically settled" in table.inner_text())
    # Selection made before the merge survives it.
    page.reload(); held.clear(); page.route(HISTORY, lambda route: held.append(route))
    page.goto(BASE + "/accounting"); rows().first.wait_for(); page.wait_for_timeout(500)
    rows().first.locator(".el-checkbox").first.click()
    for route in held: route.continue_()
    page.unroute(HISTORY); page.wait_for_timeout(1500)
    check("merging history does not clear the current selection", rows().first.locator(".el-checkbox.is-checked").count() == 1)
    # Leaving and returning within the session: history is requested again in the background, page still opens at once.
    n = len([u for u in requests if "legacy=history" in u])
    page.get_by_role("button", name="Refresh", exact=True).click(); page.wait_for_timeout(1500)
    check("Refresh reloads the settled history too", len([u for u in requests if "legacy=history" in u]) == n + 1)
    # Failure of the background request.
    page.route(HISTORY, lambda route: route.fulfill(status=502, content_type="text/html", body="<h1>502</h1>"))
    page.goto(BASE + "/accounting"); rows().first.wait_for()
    check("a failed history load does not disturb the Unreconciled tab", page.get_by_test_id("accounting-history-error").count() == 0
          and page.get_by_test_id("accounting-load-error").count() == 0 and page.get_by_role("button", name="Mark reviewed", exact=True).count() > 0)
    page.get_by_role("tab", name="Settled/Closed", exact=True).click()
    warn = page.get_by_test_id("accounting-history-error"); warn.wait_for()
    check("Settled/Closed explains that settled history could not be loaded", "could not be loaded" in warn.inner_text() and "HTTP 502" in warn.inner_text())
    page.unroute(HISTORY); page.get_by_test_id("accounting-history-retry").click()
    page.get_by_text("Historically settled").first.wait_for()
    check("Retry loads the settled history", page.get_by_test_id("accounting-history-error").count() == 0)
    check("no unexpected JavaScript errors", not errors)
    b.close()
print(f"{len(checks)} passed Accounting background-history UI checks")
