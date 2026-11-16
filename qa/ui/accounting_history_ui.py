"""Y: Accounting server paging (2026-11-17 owner decision; replaces the 2026-11-13 background history merge).

Accounting opens on Unreconciled with the open accounts only; settled legacy history is never downloaded as a whole.
All Accounts / Settled/Closed / Brokerage ask the server for one page of 100 rows (history included); filters are
applied by the server (text after a pause), the dropdowns include history-only names, registrations of a history
row open from its history, and a failed page shows an error with Retry. Runs after accounting_paging_seed.py."""
import json, re
from urllib.parse import parse_qs, urlparse
from playwright.sync_api import sync_playwright
BASE = "http://nginx"; PASSWORD = "Ui-Test-Pass-1"
checks = []
def check(name, ok, detail=''):
    assert ok, (name, detail)
    checks.append(name); print('PASS ' + name, flush=True)
errors = []
PAGE = re.compile(r".*/api/accounting\?view=page.*")
with sync_playwright() as p:
    b = p.chromium.launch(); page = b.new_page(viewport={"width": 1500, "height": 950}); page.set_default_timeout(60000)
    page.on("console", lambda m: errors.append(m.text) if m.type == "error" and "502" not in m.text and "Failed to load resource" not in m.text else None)
    requests, pages = [], []
    page.on("request", lambda r: requests.append(r.url) if "/api/accounting" in r.url and r.method == "GET" else None)
    def remember(response):
        if "/api/accounting?view=page" in response.url and response.ok:
            try: pages.append((parse_qs(urlparse(response.url).query), response.json()))
            except Exception: pass
    page.on("response", remember)
    page.goto(BASE + "/login"); page.get_by_label("Username").fill("ui.finance"); page.get_by_label("Password").fill(PASSWORD)
    page.get_by_role("button", name="Sign in").click(); page.wait_for_selector(".app-shell")
    table = page.get_by_test_id("accounting-table")
    rows = lambda: table.locator(".el-table__body tr.el-table__row")
    heading = lambda: page.locator("h2").filter(has_text=re.compile(r"\(\d+\)")).first.inner_text()
    count = lambda: int(re.search(r"\((\d+)\)", heading()).group(1))
    def settle():
        page.wait_for_timeout(400)
        page.wait_for_function("() => !document.querySelector('[data-testid=accounting-list] .el-loading-mask')")
    def tab(name):
        n = len(pages); page.get_by_role("tab", name=name, exact=True).click()
        page.wait_for_function(f"() => true"); page.wait_for_timeout(200)
        for _ in range(100):
            if len(pages) > n: break
            page.wait_for_timeout(100)
        settle()

    page.goto(BASE + "/accounting"); rows().first.wait_for(); page.wait_for_timeout(800)
    check("Accounting opens on Unreconciled Accounts", "Unreconciled Accounts (" in heading()
          and page.get_by_role("tab", name="Unreconciled Accounts", exact=True).get_attribute("aria-selected") == "true")
    check("opening loads the open accounts and the dropdown names only", any("legacy=open" in u for u in requests) and any("view=options" in u for u in requests)
          and not any("legacy=history" in u for u in requests) and not any("view=page" in u for u in requests), requests)
    check("no history is listed or downloaded on Unreconciled", "Historically settled" not in table.inner_text() and page.get_by_role("button", name="Mark reviewed", exact=True).count() > 0)
    rows().first.locator(".el-checkbox").first.click()
    check("Unreconciled selection works as before", rows().first.locator(".el-checkbox.is-checked").count() == 1)
    unreconciled = count()

    tab("All Accounts")
    query, body = pages[-1]
    check("All Accounts asks the server for page 1", query.get("tab") == ["all"] and query.get("page") == ["1"], query)
    check("the heading shows the server's total over the whole system", count() == body["total"] and body["total"] > 100, (count(), body["total"]))
    check("one page holds 100 rows", rows().count() == 100 and len(body["rows"]) == 100)
    pager = page.get_by_test_id("accounting-server-pagination")
    check("the pager shows the total and the fixed page size, without a page-size menu", "100 rows per page" in pager.inner_text()
          and str(body["total"]) in pager.inner_text() and pager.locator(".el-pagination__sizes").count() == 0, pager.inner_text())
    first = rows().first.inner_text()
    n = len(pages); pager.locator(".el-pager li", has_text=re.compile(r"^2$")).click(); settle()
    check("page 2 is a new server request with other rows", len(pages) > n and pages[-1][0].get("page") == ["2"] and rows().first.inner_text() != first)

    tab("Settled/Closed")
    query, body = pages[-1]
    check("Settled/Closed asks for settled accounts", query.get("tab") == ["settled"] and query.get("settlement") == ["settled"] and query.get("page") == ["1"], query)
    check("Settled/Closed lists settled legacy history from the server", "Historically settled" in table.inner_text() and count() == body["total"] and body["total"] >= 320)

    # Text filter: one request after typing stops.
    n = len(pages)
    box = page.locator(".el-form-item", has_text="TW Ref").locator("input").first
    box.press_sequentially("UI-HIST-REF-15", delay=40); page.wait_for_timeout(1200); settle()
    typed = [q for q, _ in pages[n:]]
    check("typing sends one request after the pause, not one per key", len(typed) == 1 and typed[0].get("reference") == ["UI-HIST-REF-15"], typed)
    check("the filtered list shows the server's total and only matching references", 0 < count() == pages[-1][1]["total"] <= 40
          and all("UI-HIST-REF-15" in rows().nth(i).inner_text() for i in range(rows().count())), (count(), pages[-1][1]["total"]))
    box.fill(""); page.wait_for_timeout(1200); settle()

    # History-only cedant in the dropdown.
    cedant = page.locator(".el-form-item", has_text="Cedant").locator(".el-select").first
    cedant.click(); page.keyboard.type("UI History Only", delay=30)
    option = page.locator(".el-select-dropdown__item:visible", has_text="UI History Only Cedant")
    try: option.first.wait_for(timeout=10000)
    except Exception: pass
    check("the Cedant dropdown includes a name that exists only in the settled history", option.count() == 1)
    n = len(pages); option.click(); settle()
    check("choosing it filters on the server", pages[-1][0].get("cedant") == ["UI History Only Cedant"] and count() == 160, (pages[-1][0], count()))
    check("every listed row belongs to that cedant", all("UI History Only Cedant" in rows().nth(i).inner_text() for i in range(rows().count())))

    # History of a history row opens its imported receipt.
    rows().first.get_by_role("button", name="History", exact=True).click()
    dialog = page.locator(".el-dialog:visible").filter(has_text="Account history")
    check("the history of a settled legacy account lists its imported receipt (read-only, as before)", "UI-REC-" in dialog.inner_text()
          and dialog.get_by_role("button", name="View registration").count() == 0)
    page.keyboard.press("Escape"); page.wait_for_timeout(400)

    tab("Brokerage")
    check("Brokerage asks the server too", pages[-1][0].get("tab") == ["brokerage"])

    # Refresh reloads the page and the dropdown names.
    tab("Settled/Closed")
    n_page, n_opt = len([u for u in requests if "view=page" in u]), len([u for u in requests if "view=options" in u])
    page.get_by_role("button", name="Refresh", exact=True).click(); page.wait_for_timeout(1500); settle()
    check("Refresh reloads the current page and the dropdown names", len([u for u in requests if "view=page" in u]) > n_page
          and len([u for u in requests if "view=options" in u]) == n_opt + 1)

    # A failed page shows an error with Retry; the open tabs are not affected.
    page.route(PAGE, lambda route: route.fulfill(status=502, content_type="text/html", body="<h1>502</h1>"))
    n = len(requests); page.locator(".el-form-item", has_text="Currency").locator(".el-select").first.click()
    page.locator(".el-select-dropdown__item:visible", has_text="TWD").first.click(); page.wait_for_timeout(1000)
    error = page.get_by_test_id("accounting-page-error"); error.wait_for()
    check("a failed page explains the error", "could not be loaded" in error.inner_text() and "HTTP 502" in error.inner_text())
    page.unroute(PAGE); page.get_by_test_id("accounting-page-retry").click(); settle()
    check("Retry loads the page", page.get_by_test_id("accounting-page-error").count() == 0 and pages[-1][0].get("currency") == ["TWD"] and rows().count() > 0)
    currency = page.locator(".el-form-item", has_text="Currency").locator(".el-select").first
    currency.hover(); currency.locator(".el-select__clear").first.click(); page.wait_for_timeout(800); settle()
    check("clearing the filter asks the server again", "currency" not in pages[-1][0])
    cedant.hover(); cedant.locator(".el-select__clear").first.click(); page.wait_for_timeout(800); settle()

    n = len([u for u in requests if "view=page" in u])
    page.get_by_role("tab", name="Unreconciled Accounts", exact=True).click(); page.wait_for_timeout(800)
    check("back on Unreconciled the list is the browser's again, with no page request", count() == unreconciled
          and len([u for u in requests if "view=page" in u]) == n and page.get_by_role("button", name="Mark reviewed", exact=True).count() > 0,
          (count(), unreconciled, len([u for u in requests if "view=page" in u]), n))
    check("no unexpected JavaScript errors", not errors, errors)
    b.close()
print(f"{len(checks)} passed Accounting server-paging UI checks")
