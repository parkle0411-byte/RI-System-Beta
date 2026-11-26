"""Loading skeletons (2026-11-26, owner decision): v-loading spinner masks replaced by page-shaped grey skeleton bars.
Runs in the disposable UI stack. Each page's data request is held back so the loading state stays on screen, then released.
Checks: the skeleton shows inside the page's own block, no Element Plus spinner mask, content is covered, the block is
usable again after load (skeleton removed), reduced motion stops the sweep. Screenshots go to /ui/out/skeleton-*.png."""
import re
from playwright.sync_api import sync_playwright
BASE = "http://nginx"; PASSWORD = "Ui-Test-Pass-1"
checks = []
def check(name, ok, detail=''):
    assert ok, (name, detail)
    checks.append(name); print('PASS ' + name, flush=True)
errors = []
PAGES = [  # (name, path, api regex, container selector, expected skeleton kind rows>=)
    ("Personnel", "/personnel", r"/api/personnel", ".personnel-card"),
    ("Production Report", "/production", r"/api/production-report", ".production-report-card"),
    ("Accounting", "/accounting", r"/api/accounting", "[data-testid=accounting-list]"),
    ("FX Rates", "/fx-rates", r"/api/fx-rates", ".table-card"),
    ("Audit Log", "/audit", r"/api/audit-log", ".table-card"),
    ("Draft Recycle Bin", "/recycle", r"/api/draft-recycle-bin", ".table-card"),
    ("Dashboard", "/dashboard", r"/api/dashboard($|\?)", ".rdash"),
    ("Account List", "/cases", r"/api/cases($|\?)", "[data-testid=account-list-table]"),
]
BARS_JS = """() => [...document.querySelectorAll('.skeleton-mask .sk-bar')].map(b => { const r = b.getBoundingClientRect(); return { x: r.x, y: r.y, w: r.width, h: r.height, row: b.dataset.row ?? null, col: b.dataset.col ?? null } })"""
HEADS_JS = """sel => { const h = document.querySelector(sel); const t = h.matches('.el-table') ? h : [...h.querySelectorAll('.el-table')].find(x => x.getBoundingClientRect().width > 0); if (!t) return null;
  return [...t.querySelectorAll('.el-table__header-wrapper thead tr:last-child th:not(.gutter)')].map(th => { const r = th.getBoundingClientRect(); return { x: r.x, y: r.y, w: r.width, shown: getComputedStyle(th).visibility === 'visible' } }) }"""
ROWS_JS = """sel => { const h = document.querySelector(sel); const t = h.matches('.el-table') ? h : [...h.querySelectorAll('.el-table')].find(x => x.getBoundingClientRect().width > 0); if (!t) return [];
  return [...t.querySelectorAll('.el-table__body-wrapper tbody tr.el-table__row')].slice(0, 3).map(tr => [...tr.children].map(td => { const r = td.getBoundingClientRect(); return { x: r.x, y: r.y, w: r.width, h: r.height } })) }"""
DASH_JS = """() => [...document.querySelectorAll('.rdash .stat-value, .rdash .kpi .val, .rdash .gp-v')].map(e => { const r = e.getBoundingClientRect(); return { x: r.x, y: r.y, h: r.height, gp: e.classList.contains('gp-v') } })"""

def login(page, user):
    page.goto(BASE + "/login"); page.get_by_label("Username").fill(user); page.get_by_label("Password").fill(PASSWORD)
    page.get_by_role("button", name="Sign in").click(); page.wait_for_selector(".app-shell")
    page.evaluate("() => { try { sessionStorage.clear(); localStorage.clear() } catch (e) {} }")

with sync_playwright() as p:
    b = p.chromium.launch()
    ctx = b.new_context(viewport={"width": 1440, "height": 900}); page = ctx.new_page(); page.set_default_timeout(30000)
    page.on("console", lambda m: errors.append(m.text) if m.type == "error" and "Failed to load resource" not in m.text else None)
    page.on("pageerror", lambda e: errors.append(str(e)))
    login(page, "ui.admin")
    for name, path, api, sel in PAGES:
        held = []
        pattern = re.compile(api)
        handler = lambda route, req: held.append(route) if req.method == "GET" and pattern.search(req.url) else route.continue_()
        page.route("**/api/**", handler)
        page.goto(BASE + path)
        host = page.locator(sel).first
        host.wait_for(state="attached")
        page.wait_for_selector(".skeleton-mask", timeout=15000)
        sk = page.locator(".skeleton-mask")
        check(f"{name}: a skeleton shows while its data is loading", sk.count() >= 1)
        check(f"{name}: no Element Plus spinner mask is used", page.locator(".el-loading-mask").count() == 0 and page.locator(".el-loading-spinner").count() == 0)
        box = sk.first.bounding_box(); parent_box = sk.first.evaluate_handle("e => e.parentElement").as_element().bounding_box()
        check(f"{name}: the skeleton covers its block", box and parent_box and abs(box["width"] - parent_box["width"]) <= 4 and abs(box["height"] - parent_box["height"]) <= 4, (box, parent_box))
        check(f"{name}: the skeleton has bars drawn", sk.first.locator(".sk-bar").count() >= 2)
        check(f"{name}: the covered block is marked busy for assistive tech", sk.first.evaluate("e => e.parentElement.getAttribute('aria-busy')") == "true")
        page.wait_for_timeout(500)
        page.screenshot(path=f"/ui/out/skeleton-{name.replace(' ', '-').lower()}.png")
        bars = page.evaluate(BARS_JS)
        is_table = name != "Dashboard"
        heads = page.evaluate(HEADS_JS, sel) if is_table else None
        dash_before = page.evaluate(DASH_JS) if not is_table else None
        if is_table:
            first = [x for x in bars if x["row"] == "0"]
            check(f"{name}: the real table headings stay visible while loading", heads and all(h["shown"] for h in heads), heads)
            check(f"{name}: each skeleton column sits inside its real column heading", first and all(any(h["x"] - 1 <= x["x"] and x["x"] + x["w"] <= h["x"] + h["w"] + 1 for h in heads) for x in first), (first, heads))
        for r in held: r.continue_()
        page.unroute("**/api/**", handler)
        page.wait_for_function("() => !document.querySelector('.skeleton-mask')", timeout=20000)
        check(f"{name}: the skeleton is removed once the data arrived", page.locator(".skeleton-mask").count() == 0 and page.locator(".skeleton-parent[aria-busy]").count() == 0 and page.locator("[aria-busy=true]").count() == 0)
        check(f"{name}: the block is visible and not covered afterwards", host.is_visible())
        page.wait_for_timeout(700)
        if is_table:
            after = page.evaluate(HEADS_JS, sel); rows = page.evaluate(ROWS_JS, sel)
            moved = [(a["x"] - b["x"], a["y"] - b["y"]) for a, b in zip(after, heads)]
            print(f"MEASURE {name}: signed heading dy {round(moved[0][1]) if moved else None}", flush=True)
            print(f"MEASURE {name}: heading shift {max((abs(m[1]) for m in moved), default=0):.0f}px, rows loaded {len(rows)}, row heights {[round(r[0]['h']) for r in rows]}", flush=True)
            if rows:
                bad = []
                for x in first:
                    cell = rows[0][int(x["col"])]; mid = x["y"] + x["h"] / 2
                    if not (cell["x"] - 1 <= x["x"] and x["x"] + x["w"] <= cell["x"] + cell["w"] + 1 and cell["y"] - 8 <= mid <= cell["y"] + cell["h"] + 8): bad.append((x, cell))
                check(f"{name}: the first skeleton row lines up with the first data row (same columns, same place)", not bad, bad[:3])
        else:
            dash_after = page.evaluate(DASH_JS)
            shift = [(round(a["x"] - b["x"]), round(a["y"] - b["y"])) for a, b in zip(dash_after, dash_before)]
            print(f"MEASURE Dashboard: value shift after load {shift}", flush=True)
            page.screenshot(path="/ui/out/skeleton-dashboard-loaded.png")
            check("Dashboard: the skeleton marks every value and the values appear in the same places", len(dash_after) == len(dash_before) and all((abs(sx) <= 4 or v['gp']) and abs(sy) <= 12 for (sx, sy), v in zip(shift, dash_before)), shift)
            check("Dashboard: each value had a skeleton bar on it", all(any(abs(x["x"] - v["x"]) <= 3 and v["y"] - 2 <= x["y"] <= v["y"] + v["h"] for x in bars) for v in dash_before), (dash_before, bars[:6]))
    # reduced motion: the light sweep stops
    rm = b.new_context(viewport={"width": 1440, "height": 900}, reduced_motion="reduce"); rp = rm.new_page(); rp.set_default_timeout(30000)
    login(rp, "ui.admin")
    held = []
    rp.route("**/api/**", lambda route, req: held.append(route) if req.method == "GET" and re.search(r"/api/personnel", req.url) else route.continue_())
    rp.goto(BASE + "/personnel"); rp.wait_for_selector(".skeleton-mask")
    check("reduced motion: the sweep animation is off", rp.evaluate("() => getComputedStyle(document.querySelector('.skeleton-mask'), '::after').animationName") == "none" or rp.evaluate("() => getComputedStyle(document.querySelector('.skeleton-mask'), '::after').display") == "none")
    for r in held: r.continue_()
    rm.close()
    check("no console errors", not errors, errors[:3])
    b.close()
print(f"skeleton: {len(checks)} checks passed")
