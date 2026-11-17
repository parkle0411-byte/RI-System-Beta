"""U: account lifecycle from the Personnel page (2026-11-17: the four account addresses became one, POST
/api/personnel-accounts with action). Reset password, disable and re-enable an account through the screen and
confirm each request uses the single address with its action. Runs after personnel_accounts_seed.py."""
import json
from playwright.sync_api import sync_playwright
BASE = "http://nginx"; PASSWORD = "Ui-Test-Pass-1"
checks = []
def check(name, ok, detail=''):
    assert ok, (name, detail)
    checks.append(name); print('PASS ' + name, flush=True)
errors = []
with sync_playwright() as p:
    b = p.chromium.launch(); page = b.new_page(viewport={"width": 1500, "height": 950}); page.set_default_timeout(60000)
    page.on("console", lambda m: errors.append(m.text) if m.type == "error" and "Failed to load resource" not in m.text else None)
    sent = []
    page.on("request", lambda r: sent.append((r.url, r.post_data_json)) if "/api/personnel-accounts" in r.url and r.method == "POST" else None)
    page.goto(BASE + "/login"); page.get_by_label("Username").fill("ui.admin"); page.get_by_label("Password").fill(PASSWORD)
    page.get_by_role("button", name="Sign in").click(); page.wait_for_selector(".app-shell")
    page.locator(".nav-item", has_text="Personnel & Accounts").click(); page.wait_for_timeout(800)
    row = lambda: page.locator(".el-table__row", has_text="UI Account Lifecycle").first
    box = page.locator(".el-message-box:visible")
    def done(text):
        try:
            page.locator(".el-message", has_text=text).last.wait_for(timeout=10000); return True
        except Exception:
            return False

    row().get_by_role("button", name="Reset password").click()
    box.get_by_role("button", name="Reset", exact=True).click()
    secret = page.locator(".master-dialog").filter(has_text="Shown once"); secret.wait_for()
    check("Reset password shows a new one-time password", "Password reset" in secret.inner_text() and len(secret.locator("input").nth(1).input_value()) >= 16)
    check("it used the single address with action reset_password", sent[-1][0].endswith("/api/personnel-accounts") and sent[-1][1].get("action") == "reset_password", sent[-1])
    secret.get_by_role("button", name="I have noted it — close").click(); page.wait_for_timeout(500)

    row().get_by_role("button", name="Disable account").click()
    box.get_by_role("button", name="Disable account", exact=True).click()
    check("Disable account works", done("Account disabled"))
    check("it used the single address with action disable", sent[-1][0].endswith("/api/personnel-accounts") and sent[-1][1].get("action") == "disable", sent[-1])
    page.wait_for_timeout(500)
    check("the row now offers Re-enable account", row().get_by_role("button", name="Re-enable account").is_visible())

    row().get_by_role("button", name="Re-enable account").click()
    box.get_by_role("button", name="Re-enable", exact=True).click()
    check("Re-enable account works", done("Account re-enabled"))
    check("it used the single address with action enable", sent[-1][0].endswith("/api/personnel-accounts") and sent[-1][1].get("action") == "enable", sent[-1])
    page.wait_for_timeout(500)
    check("the row offers Disable account again", row().get_by_role("button", name="Disable account").is_visible())
    check("no request went to a retired sub-address", all(url.split("?")[0].endswith("/api/personnel-accounts") for url, _ in sent), [u for u, _ in sent])
    check("no unexpected JavaScript errors", not errors, errors)
    b.close()
print(f"{len(checks)} passed Personnel account lifecycle UI checks")
