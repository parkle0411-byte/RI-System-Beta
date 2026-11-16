"""M: Master Data Reactivate (2026-11-16 owner decision). Runs in the disposable UI stack after mdm_reactivate_seed.py.

Reactivate sends no reason when the record's saved details stay the same. When the server reports that reactivating
would also change the saved details (a Lloyd's syndicate stored before its market details were filled in), the
screen asks for a reason, Cancel leaves the record inactive, and OK reactivates it with that reason."""
from playwright.sync_api import sync_playwright
BASE = "http://nginx"; PASSWORD = "Ui-Test-Pass-1"
checks = []
def check(name, ok, detail=''):
    assert ok, (name, detail)
    checks.append(name); print('PASS ' + name, flush=True)
errors = []
LLOYDS = "Lloyd's Underwriter Syndicate No. 9901 UIR"; PLAIN = "UI Plain Inactive Re"
with sync_playwright() as p:
    b = p.chromium.launch(); page = b.new_context(viewport={"width": 1500, "height": 950}).new_page(); page.set_default_timeout(60000)
    page.on("console", lambda m: errors.append(m.text) if m.type == "error" and "Failed to load resource" not in m.text else None)
    puts = []
    page.on("request", lambda r: puts.append(r.post_data_json) if r.method == "PUT" and "/api/master-data" in r.url else None)
    page.goto(BASE + "/login")
    page.get_by_label("Username").fill("ui.admin"); page.get_by_label("Password").fill(PASSWORD)
    page.get_by_role("button", name="Sign in").click(); page.wait_for_selector(".app-shell")
    page.locator(".nav-item", has_text="Master Data Management").click()
    page.locator(".mdm-tab", has_text="Reinsurers").click()
    page.wait_for_timeout(800)
    row = lambda name: page.locator(".el-table__row", has_text=name).first
    box = page.locator(".el-message-box:visible")
    def done(text):
        try:
            page.locator(".el-message", has_text=text).last.wait_for(timeout=10000); return True
        except Exception:
            return False

    # Plain record: no reason asked, one request.
    before = len(puts)
    row(PLAIN).get_by_role("button", name="Reactivate").click()
    check("a plain inactive reinsurer reactivates without asking for a reason", done("reactivated") and box.count() == 0)
    check("it sent a single request with no reason", len(puts) - before == 1 and puts[-1].get("changeReason") == "" and puts[-1].get("isActive") is True, puts[before:])
    page.wait_for_timeout(500)
    check("the plain reinsurer now offers Deactivate", row(PLAIN).get_by_role("button", name="Deactivate").is_visible())

    # Lloyd's syndicate stored before its market details: the server asks for a reason.
    page.get_by_text("Lloyd's Market (").first.click()   # syndicates are listed in their own collapsible group
    row(LLOYDS).wait_for()
    before = len(puts)
    row(LLOYDS).get_by_role("button", name="Reactivate").click()
    box.wait_for()
    check("the screen asks for a reason when reactivating also changes saved details", "also updates its saved details" in box.inner_text(), box.inner_text())
    box.get_by_role("button", name="Cancel").click()
    page.wait_for_timeout(800)
    check("Cancel sends nothing more and leaves the syndicate inactive", len(puts) - before == 1 and row(LLOYDS).get_by_role("button", name="Reactivate").is_visible(), puts[before:])
    row(LLOYDS).get_by_role("button", name="Reactivate").click()
    box.wait_for()
    box.get_by_role("button", name="OK", exact=True).click()
    check("an empty reason is not accepted", box.get_by_text("Reason is required.").is_visible())
    box.locator("input").fill("UI reactivation reason")
    box.get_by_role("button", name="OK", exact=True).click()
    check("with a reason the syndicate is reactivated", done("reactivated"))
    page.wait_for_timeout(500)
    check("the syndicate now offers Deactivate", row(LLOYDS).get_by_role("button", name="Deactivate").is_visible())
    sent = puts[before:]
    check("the retry carried the reason", [x.get("changeReason") for x in sent][-1] == "UI reactivation reason" and sent[0].get("changeReason") == "", sent)
    check("no unexpected JavaScript errors", not [e for e in errors if "400" not in e], errors)
    b.close()
print(f"{len(checks)} passed Master Data Reactivate UI checks")
