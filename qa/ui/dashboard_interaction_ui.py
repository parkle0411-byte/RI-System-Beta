"""Dashboard interaction layer (2026-11-25, owner decision): colours, layout and data unchanged; interactions added.

Runs in the disposable UI stack with /api/dashboard replaced by a deterministic synthetic response (no seed data needed).
Covers: layout moves (Total Gross Premium on top, Accounting as its own card), count-up ends on the original text, Retention
rating bands, the interactive bar chart (grow-from-bottom, tween, tooltip, pin, range, zoom, cumulative, rank, labels,
target filter, legend, keyboard, replay, year switch, negative month), mix hover and sort, claims expand, Refresh,
and reduced-motion."""
import json, re
from playwright.sync_api import sync_playwright
BASE = "http://nginx"; PASSWORD = "Ui-Test-Pass-1"
checks = []
def check(name, ok, detail=''):
    assert ok, (name, detail)
    checks.append(name); print('PASS ' + name, flush=True)
errors = []

def make(year=2026, retention=91.4, months=10, negative=False):
    labels = [f"{m:02d}" for m in range(1, months + 1)]
    prior = [300000 + 40000 * i for i in range(months)]
    current = [350000 + 30000 * i for i in range(months)]
    if negative: current[3] = -120000
    target = [320000 + 30000 * i for i in range(months)]
    status = ["closed"] * (months - 1) + ["estimated"]
    return {
        "period": {"year": 2026, "currentMonth": "2026-11", "monthNumber": months},
        "metrics": {"ytdCurrent": 482, "ytdPrior": 431, "renewalsMtd": 37, "expectedRenewalsMtd": 41, "newBusinessMtd": 12,
                    "inForcePolicies": 1284, "activeEndorsements": 73, "openQuotes": 56, "retentionRatio": retention,
                    "grossPremiumNtd": 482316540, "outstandingLeg1Ntd": 12480000, "outstandingLeg2Ntd": 9320000,
                    "claimOutstandingByCurrency": [{"currency": "USD", "receivable": 1200, "payable": 800}, {"currency": "EUR", "receivable": 50, "payable": 0}],
                    "missingPostingRates": [], "accountingTotalEstimated": False},
        "brokerage": {"labels": labels, "currentStatus": status, "priorStatus": ["closed"] * months, "current": current, "prior": prior, "target": target, "annualTarget": 6000000},
        "classMix": [{"name": "Property", "amount": 186400000, "pct": 58.0}, {"name": "Commercial General Liability", "amount": 86800000, "pct": 27.0}, {"name": "Product Recall", "amount": 48200000, "pct": 15.0}],
        "reinsurers": [{"name": "Swiss Re", "amount": 84200000, "pct": 60.0}, {"name": "Allianz", "amount": 61500000, "pct": 40.0}],
    }

state = {"retention": 91.4, "negative": False, "calls": 0}
def handler(route):
    url = route.request.url
    m = re.search(r"brokerageYear=(\d+)", url)
    year = int(m.group(1)) if m else 2026
    state["calls"] += 1
    body = make(year=year, retention=state["retention"], months=12 if year != 2026 else 10, negative=state["negative"])
    route.fulfill(status=200, content_type="application/json", body=json.dumps(body))

def login(page):
    page.goto(BASE + "/login"); page.get_by_label("Username").fill("ui.finance"); page.get_by_label("Password").fill(PASSWORD)
    page.get_by_role("button", name="Sign in").click(); page.wait_for_selector(".app-shell")
    page.evaluate("() => { try { sessionStorage.clear(); localStorage.clear() } catch (e) {} }")

with sync_playwright() as p:
    b = p.chromium.launch()
    ctx = b.new_context(viewport={"width": 1440, "height": 1000}); page = ctx.new_page(); page.set_default_timeout(30000)
    page.on("console", lambda m: errors.append(m.text) if m.type == "error" and "Failed to load resource" not in m.text else None)
    page.on("pageerror", lambda e: errors.append(str(e)))
    login(page)
    page.route(re.compile(r".*/api/dashboard.*"), handler)
    page.goto(BASE + "/dashboard"); page.locator(".rdash").wait_for()

    # --- grow from the bottom: sample right after load and again when settled
    page.wait_for_selector(".trend-bar.current")
    page.wait_for_timeout(120)
    early = page.evaluate("() => [...document.querySelectorAll('.trend-bar.current')].slice(5,8).map(e => e.getBoundingClientRect().height)")
    page.wait_for_timeout(2200)
    late = page.evaluate("() => [...document.querySelectorAll('.trend-bar.current')].slice(5,8).map(e => e.getBoundingClientRect().height)")
    check("bars grow from the bottom (shorter right after load than when settled)", all(e < l * 0.8 for e, l in zip(early, late)) and all(l > 20 for l in late), (early, late))

    # --- layout: Total Gross Premium on top, Accounting is its own card, four KPIs
    gp = page.get_by_test_id("dashboard-gross-premium").bounding_box(); stat = page.locator(".row3").bounding_box()
    check("Total Gross Premium sits above the three stat cards", gp["y"] + gp["height"] <= stat["y"] + 2, (gp, stat))
    check("Total Gross Premium is no longer a KPI cell", page.locator(".kpi", has_text="Total Gross Premium").count() == 0 and page.locator(".kpi").count() == 4)
    acc = page.get_by_test_id("dashboard-accounting")
    check("Accounting is its own card (not inside the KPI grid)", acc.count() == 1 and acc.locator("xpath=ancestor::*[contains(@class,'kpi-grid')]").count() == 0 and "Accounting · Receivable / Payable" in acc.inner_text())
    check("Gross premium keeps its original format", "TWD 482,316,540.00" in page.get_by_test_id("dashboard-gross-premium").inner_text().replace("\n", " "), page.get_by_test_id("dashboard-gross-premium").inner_text())
    check("count-up ends on the original text (no thousands separator on counts)", page.locator(".kpi", has_text="In-Force Policies").locator(".val").inner_text() == "1284"
          and page.locator(".stat-value").first.inner_text() == "482")
    check("Accounting totals keep the original format", "TWD 12,480,000 / 9,320,000" in acc.inner_text().replace("\n", " "), acc.inner_text())
    check("retention shows 91.4% with an Excellent rating", page.locator(".kpi", has_text="Renewal Retention Ratio").inner_text().replace("\n", " ").startswith("Renewal Retention Ratio 91.4%") and page.locator(".rate").inner_text().startswith("Excellent"), page.locator(".kpi", has_text="Renewal Retention").inner_text())
    page.locator(".rate").hover(); page.wait_for_timeout(300)
    check("hovering the rating lists the seven levels and marks the current one", page.locator(".rate-pop .rp-row").count() == 7 and page.locator(".rate-pop .rp-row.on").inner_text().startswith("Excellent") and page.locator(".rate-pop").is_visible())
    page.mouse.move(5, 5)

    # --- claims by original currency expand
    check("claims list is collapsed at first", not page.locator(".acc-claims.open").count())
    page.get_by_role("button", name="Claims by original currency").click(); page.wait_for_timeout(350)
    txt = acc.inner_text()
    check("claims list expands with the original-currency rows", page.locator(".acc-claims.open").count() == 1 and "USD 1,200 / 800" in txt and "EUR 50 / 0" in txt, txt)

    # --- original structure the older tests rely on
    n = 10
    check("chart keeps one polyline and one pair of bars and one target point per month", page.locator(".trend-svg polyline").count() == 1 and page.locator(".trend-bar.prior").count() == n
          and page.locator(".trend-bar.current").count() == n and page.locator(".trend-point.target").count() == n)
    left = page.locator(".trend-bar.prior").first; right = page.locator(".trend-bar.current").first
    check("prior bar lies to the left of current bar", float(left.get_attribute("x")) + float(left.get_attribute("width")) < float(right.get_attribute("x")))
    check("last month is marked as an estimate", page.locator(".trend-bar.current.est").count() == 1)

    # --- tooltip, pin, range, zoom
    box = page.locator(".trend-svg").bounding_box()
    slot = lambda i, total=n: box["x"] + (66 + (i + .5) * (824 / total)) * box["width"] / 900
    cy = box["y"] + box["height"] * .5
    page.mouse.move(slot(4), cy); page.wait_for_timeout(250)
    tip = page.locator(".ctip.on").inner_text()
    check("hover shows a tooltip with month, both years and the target", "May" in tip and "2025" in tip and "2026" in tip and "Target" in tip, tip)
    page.mouse.click(slot(4), cy); page.wait_for_timeout(250)
    check("click pins the month and shows its summary", "May 2026" in page.locator(".cdetail").inner_text() and "of target" in page.locator(".cdetail").inner_text(), page.locator(".cdetail").inner_text())
    page.mouse.click(slot(4), cy); page.wait_for_timeout(250)
    check("clicking the same month again unpins it", "Hover for values" in page.locator(".cdetail").inner_text())
    page.mouse.move(slot(1), cy); page.mouse.down(); page.mouse.move(slot(5), cy, steps=6); page.mouse.up(); page.wait_for_timeout(250)
    summary = page.locator(".cdetail").inner_text()
    check("dragging across months totals the range", "Feb–Jun" in summary and "Total" in summary and "Avg" in summary and "vs 2025" in summary, summary)
    page.get_by_role("button", name="Zoom in").click(); page.wait_for_timeout(700)
    check("zoom keeps only the chosen months and shows a way back", page.locator(".trend-bar.current").count() == 5 and page.get_by_role("button", name=re.compile("^Zoom Feb–Jun")).count() == 1)
    page.get_by_role("button", name=re.compile("^Zoom Feb–Jun")).click(); page.wait_for_timeout(500)
    check("leaving zoom restores all months", page.locator(".trend-bar.current").count() == n)

    # --- controls
    def heights(sel): return page.evaluate("(s) => [...document.querySelectorAll(s)].map(e => Math.round(e.getBoundingClientRect().height))", sel)
    before = heights(".trend-bar.current")
    page.get_by_role("button", name="Cumulative").click(); page.wait_for_timeout(900)
    after = heights(".trend-bar.current")
    check("Cumulative accumulates month by month (last bar taller than monthly)", after[-1] > before[-1] and after[-1] > after[0] * 3, (before, after))
    page.get_by_role("button", name="Monthly").click(); page.wait_for_timeout(900)
    page.get_by_role("button", name="Rank").click(); page.wait_for_timeout(900)
    first = page.locator(".trend-month").first.text_content()
    check("Rank puts the largest month first", first == "10", first)
    check("Rank hides the connecting target line", page.evaluate("() => getComputedStyle(document.querySelector('.trend-line.target')).opacity") == "0")
    page.get_by_role("button", name="Time").click(); page.wait_for_timeout(700)
    check("Time restores calendar order", page.locator(".trend-month").first.text_content() == "01")
    page.get_by_role("button", name="Values", exact=True).click(); page.wait_for_timeout(300)
    check("Values labels appear above the current bars", page.locator(".vlab").count() == n)
    page.get_by_role("button", name="YoY %").click(); page.wait_for_timeout(300)
    check("YoY labels show a signed percentage", re.match(r"^[+−]\d+%$", page.locator(".vlab").first.text_content()) is not None, page.locator(".vlab").first.text_content())
    page.get_by_role("button", name="No labels").click(); page.wait_for_timeout(200)
    check("labels can be turned off", page.locator(".vlab").count() == 0)
    page.get_by_role("button", name="Below target").click(); page.wait_for_timeout(500)
    dim_below = page.locator(".trend-chart .col.dim").count()
    page.get_by_role("button", name="At/above target").click(); page.wait_for_timeout(500)
    dim_above = page.locator(".trend-chart .col.dim").count()
    check("target filter dims the other group (every month is above target here)", dim_below == n and dim_above == 0, (dim_below, dim_above))
    page.get_by_role("button", name="All", exact=True).click(); page.wait_for_timeout(400)
    page.get_by_role("checkbox", name="Target").uncheck(); page.wait_for_timeout(300)
    check("Target can be hidden", page.evaluate("() => getComputedStyle(document.querySelector('.trend-point.target')).opacity") == "0")
    page.get_by_role("checkbox", name="Target").check()
    page.get_by_role("button", name=re.compile("^Prior year")).click(); page.wait_for_timeout(300)
    check("legend hides the prior-year bars", page.evaluate("() => getComputedStyle(document.querySelector('.trend-bar.prior')).opacity") == "0")
    page.get_by_role("button", name=re.compile("^Prior year")).click()

    # --- keyboard
    page.locator(".trend-chart").focus(); page.keyboard.press("ArrowRight"); page.wait_for_timeout(200)
    check("ArrowRight pins the first month", "Jan 2026" in page.locator(".cdetail").inner_text(), page.locator(".cdetail").inner_text())
    page.keyboard.press("ArrowRight"); page.wait_for_timeout(200)
    check("ArrowRight again moves to the next month", "Feb 2026" in page.locator(".cdetail").inner_text())
    page.keyboard.press("Escape"); page.wait_for_timeout(200)
    check("Escape clears the pin", "Hover for values" in page.locator(".cdetail").inner_text())

    # --- replay
    page.get_by_role("button", name="Replay").click(); page.wait_for_timeout(450)
    mid = page.locator(".trend-bar.current").count()
    page.wait_for_timeout(2600)
    check("Replay rebuilds the chart month by month", 0 <= mid < n and page.locator(".trend-bar.current").count() == n, mid)

    # --- year switch keeps everything working
    page.get_by_test_id("dashboard-trend-year").click()
    page.locator('.el-select__popper[aria-hidden="false"] .el-select-dropdown__item').filter(has_text="2025").click(); page.wait_for_timeout(1500)
    check("year selection renders twelve pairs of bars and keeps KPIs", page.locator(".trend-bar.current").count() == 12 and page.locator(".kpi", has_text="In-Force Policies").locator(".val").inner_text() == "1284")
    page.get_by_test_id("dashboard-trend-year").click()
    page.locator('.el-select__popper[aria-hidden="false"] .el-select-dropdown__item').filter(has_text="2026").click(); page.wait_for_timeout(1500)

    # --- mix hover and sort
    mix = page.locator(".card", has_text="Mix by Class of Business")
    names = lambda: [e.inner_text() for e in mix.locator(".mix-row > span:first-child").all()]
    check("mix rows start in share order", names()[0] == "Property", names())
    mix.get_by_role("button", name="A–Z").click(); page.wait_for_timeout(600)
    check("A–Z sorts the classes by name", names() == sorted(names()), names())
    mix.get_by_role("button", name="Share").click(); page.wait_for_timeout(600)
    check("Share restores the share order", names()[0] == "Property")
    tip = mix.locator(".mix-row").first.get_attribute("data-tip")
    check("each row carries its amount and share for the hover tip", tip.startswith("TWD ") and "58.0%" in tip, tip)
    fill = mix.locator(".mix-fill").first.bounding_box()["width"]; track = mix.locator(".mix-track").first.bounding_box()["width"]
    check("mix bars are still filled to their share (58% bar about 58% of the track)", 0.53 < fill / track < 0.63, (fill, track))

    # --- Refresh
    calls = state["calls"]
    page.get_by_test_id("dashboard-refresh").click(); page.wait_for_timeout(1500)
    check("Refresh asks the server again and rebuilds the chart", state["calls"] > calls and page.locator(".trend-bar.current").count() == n and "just now" in page.locator(".upd").inner_text())

    # --- retention rating bands (reload with each value)
    bands = [(100, "Excellent"), (91, "Excellent"), (90.5, "Very Good"), (81, "Very Good"), (80.9, "Good"), (71, "Good"), (70.5, "Satisfactory"), (61, "Satisfactory"), (60.5, "Average"),
             (41, "Average"), (40.5, "Below Average"), (21, "Below Average"), (20.5, "Unsatisfactory"), (0, "Unsatisfactory")]
    wrong = []
    for value, name in bands:
        state["retention"] = value; page.reload(); page.locator(".rdash").wait_for(); page.wait_for_selector(".rate")
        got = page.locator(".rate").inner_text().split("\n")[0]
        if got != name: wrong.append((value, got, name))
    check("rating bands match the owner's table at every boundary", not wrong, wrong)
    state["retention"] = None; page.reload(); page.locator(".rdash").wait_for(); page.wait_for_timeout(900)
    check("no rating when the ratio is N/A", page.locator(".rate").count() == 0 and "N/A" in page.locator(".kpi", has_text="Renewal Retention Ratio").inner_text())
    state["retention"] = 91.4

    # --- negative month draws below the zero line
    state["negative"] = True; page.reload(); page.locator(".rdash").wait_for(); page.wait_for_selector(".trend-bar.current"); page.wait_for_timeout(1600)
    neg = page.locator(".trend-bar.current").nth(3)
    zero = page.locator(".trend-zero").bounding_box(); nb = neg.bounding_box()
    check("a negative month is drawn below the zero line", "neg" in neg.get_attribute("class") and nb["y"] >= zero["y"] - 1 and nb["height"] > 5, (zero, nb))
    state["negative"] = False

    # --- navigation away and back works
    page.locator(".nav-item", has_text="Account List").click(); page.wait_for_url(BASE + "/cases"); page.locator(".nav-item", has_text="Dashboard").click(); page.wait_for_url(BASE + "/dashboard")
    page.locator(".rdash").wait_for(); page.wait_for_selector(".trend-bar.current")
    check("leaving and returning to Dashboard works", page.locator(".trend-bar.current").count() == n)
    page.screenshot(path="out/dashboard_interaction.png", full_page=True)

    # --- reduced motion: no growth animation, count-up shows the result immediately
    ctx2 = b.new_context(viewport={"width": 1440, "height": 1000}, reduced_motion="reduce"); page2 = ctx2.new_page(); page2.set_default_timeout(30000)
    page2.on("pageerror", lambda e: errors.append(str(e)))
    login(page2); page2.route(re.compile(r".*/api/dashboard.*"), handler)
    page2.goto(BASE + "/dashboard"); page2.wait_for_selector(".trend-bar.current"); page2.wait_for_timeout(250)
    h1 = page2.evaluate("() => [...document.querySelectorAll('.trend-bar.current')].slice(5,8).map(e => Math.round(e.getBoundingClientRect().height))")
    page2.wait_for_timeout(1200)
    h2 = page2.evaluate("() => [...document.querySelectorAll('.trend-bar.current')].slice(5,8).map(e => Math.round(e.getBoundingClientRect().height))")
    check("reduced motion: bars are at full height straight away", h1 == h2 and all(h > 20 for h in h2), (h1, h2))
    check("reduced motion: numbers show the result without counting", page2.locator(".kpi", has_text="In-Force Policies").locator(".val").inner_text() == "1284")
    check("no console errors", not errors, errors[:3])
    b.close()
print(f"dashboard interaction: {len(checks)} checks passed")
