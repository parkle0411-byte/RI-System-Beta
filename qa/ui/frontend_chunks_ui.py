"""Front-end code splitting and Word-generator caching (2026-11-13). Runs in the disposable UI stack.

Pages load on demand from their own files; a page file that no longer exists after a deployment makes the
app reload the target page once instead of leaving a dead link; the Word generator scripts are cacheable
with revalidation, the SPA HTML stays no-store and hashed assets stay immutable."""
import re
from playwright.sync_api import sync_playwright
BASE = "http://nginx"; PASSWORD = "Ui-Test-Pass-1"
checks = []
def check(name, ok):
    assert ok, name
    checks.append(name); print('PASS ' + name, flush=True)
errors = []
with sync_playwright() as p:
    b = p.chromium.launch(); ctx = b.new_context(viewport={"width": 1500, "height": 950}); page = ctx.new_page(); page.set_default_timeout(60000)
    page.on("console", lambda m: errors.append(m.text) if m.type == "error" and "404" not in m.text and "Failed to load resource" not in m.text
            and "dynamically imported module" not in m.text else None)
    assets = []
    page.on("response", lambda r: assets.append((r.url, r.status, r.headers.get("cache-control", ""))) if "/assets/" in r.url or "/alpha-documents/" in r.url else None)
    page.goto(BASE + "/login")
    names = lambda: [u.rsplit("/", 1)[-1] for u, s, c in assets if s == 200]
    check("the login page loads the shared vendor file and the small main file, not every page",
          any(n.startswith("vendor-") and n.endswith(".js") for n in names()) and any(n.startswith("index-") and n.endswith(".js") for n in names())
          and not any(n.startswith(("CaseWorkspace-", "Accounting-", "Production-")) for n in names()))
    check("hashed assets are immutable", all("immutable" in c for u, s, c in assets if "/assets/" in u and s == 200))
    page.get_by_label("Username").fill("ui.admin"); page.get_by_label("Password").fill(PASSWORD)
    page.get_by_role("button", name="Sign in").click(); page.wait_for_selector(".app-shell")
    def nav(label):
        page.locator(".app-sidebar, aside").first.get_by_text(label, exact=True).first.click()
    for label, marker, chunk in (("Production Report", "Versioned monthly close", "Production-"), ("FX Rates", "Official monthly rates", "FxRates-"),
                                 ("Accounting", "Unreconciled Accounts (", "Accounting-")):
        before = len(assets); nav(label); page.get_by_text(marker).first.wait_for()
        check(f"{label} loads its own page file on first visit", any(n.startswith(chunk) for n in [u.rsplit('/', 1)[-1] for u, s, c in assets[before:] if s == 200]))
    before = len(assets); nav("Production Report"); page.get_by_text("Versioned monthly close").first.wait_for()
    check("a page already visited is not downloaded again", not any("/assets/Production-" in u for u, s, c in assets[before:]))

    # A page file that disappeared after a deployment: the app reloads the target page once and recovers.
    failed = {"n": 0}
    def gone(route):
        if failed["n"] == 0:
            failed["n"] += 1; route.fulfill(status=404, content_type="text/html", body="<h1>404</h1>")
        else:
            route.continue_()
    page2 = ctx.new_page(); page2.set_default_timeout(60000)
    page2.goto(BASE + "/dashboard"); page2.wait_for_selector(".app-shell")
    page2.route(re.compile(r".*/assets/MasterData-.*\.js"), gone)
    page2.locator(".app-sidebar, aside").first.get_by_text("Master Data Management", exact=True).first.click()
    page2.get_by_text("Reinsurers (").first.wait_for()
    check("a missing page file triggers one reload and the page then opens", failed["n"] == 1 and page2.url.endswith("/mdm"))
    page2.close()

    # Word generator scripts: cacheable with revalidation; SPA HTML stays no-store.
    r = ctx.request.get(BASE + "/alpha-documents/vm-docx-generator.js"); etag = r.headers.get("etag", "")
    check("Word generator scripts are cacheable with revalidation", r.status == 200 and r.headers.get("cache-control") == "no-cache" and bool(etag))
    r2 = ctx.request.get(BASE + "/alpha-documents/vm-docx-generator.js", headers={"If-None-Match": etag})
    check("an unchanged Word generator script is not downloaded again (304)", r2.status == 304)
    r3 = ctx.request.get(BASE + "/alpha-documents/docx-templates.js")
    check("Word templates use the same rule", r3.status == 200 and r3.headers.get("cache-control") == "no-cache")
    for path in ("/", "/login", "/cases"):
        check(f"SPA HTML {path} stays no-store", ctx.request.get(BASE + path).headers.get("cache-control") == "no-store")
    check("no unexpected JavaScript errors", not errors)
    b.close()
print(f"{len(checks)} passed front-end loading UI checks")
