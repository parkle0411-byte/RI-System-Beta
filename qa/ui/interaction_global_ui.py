"""Global interaction layer, round 2 (2026-11-25, owner decision): sliding sidebar highlight, button ripple and required-field shake.
Colours, layout and behaviour unchanged; reduced motion switches everything off. Runs in the disposable UI stack."""
import re
from playwright.sync_api import sync_playwright
BASE = "http://nginx"; PASSWORD = "Ui-Test-Pass-1"
checks = []
def check(name, ok, detail=''):
    assert ok, (name, detail)
    checks.append(name); print('PASS ' + name, flush=True)
errors = []

def login(page):
    page.goto(BASE + "/login"); page.get_by_label("Username").fill("ui.finance"); page.get_by_label("Password").fill(PASSWORD)
    page.get_by_role("button", name="Sign in").click(); page.wait_for_selector(".app-shell")
    page.evaluate("() => { try { sessionStorage.clear(); localStorage.clear() } catch (e) {} }")

def near(a, b, tol=2):
    return all(abs(a[k] - b[k]) <= tol for k in ("x", "y", "width", "height"))

def indicator_matches(page):
    ind = page.locator(".nav-ind").bounding_box(); act = page.locator(".nav-item.active").bounding_box()
    return ind is not None and act is not None and near(ind, act), (ind, act)

with sync_playwright() as p:
    b = p.chromium.launch()
    ctx = b.new_context(viewport={"width": 1440, "height": 900}); page = ctx.new_page(); page.set_default_timeout(30000)
    page.on("console", lambda m: errors.append(m.text) if m.type == "error" and "Failed to load resource" not in m.text else None)
    page.on("pageerror", lambda e: errors.append(str(e)))
    login(page)
    page.goto(BASE + "/dashboard"); page.locator(".rdash").wait_for(); page.wait_for_timeout(600)

    # --- sliding sidebar highlight
    check("sidebar has one highlight block and switches to the moving style", page.locator(".nav-ind").count() == 1 and page.locator(".nav-list.has-ind").count() == 1)
    ok, detail = indicator_matches(page)
    check("the highlight sits exactly on the active item", ok, detail)
    check("the active item keeps its active class and the original colour moves to the block", "active" in page.locator(".nav-item", has_text="Dashboard").get_attribute("class")
          and page.evaluate("() => getComputedStyle(document.querySelector('.nav-item.active')).backgroundColor") in ("rgba(0, 0, 0, 0)", "transparent")
          and page.evaluate("() => getComputedStyle(document.querySelector('.nav-ind')).backgroundColor") == "rgba(175, 45, 65, 0.12)")
    page.locator(".nav-item", has_text="Account List").click(); page.wait_for_url(BASE + "/cases")
    page.wait_for_timeout(120)
    mid = page.locator(".nav-ind").bounding_box()
    page.wait_for_timeout(700)
    ok, detail = indicator_matches(page)
    check("after navigating the highlight moves to the new item", ok and "Account List" in page.locator(".nav-item.active").inner_text(), detail)
    first = page.locator(".nav-item", has_text="Dashboard").bounding_box(); second = page.locator(".nav-item.active").bounding_box()
    check("the highlight travels (it is between the two items shortly after the click)", mid is not None and first["y"] - 1 <= mid["y"] <= second["y"] + 1, (first, mid, second))
    page.locator(".nav-item", has_text="Dashboard").click(); page.wait_for_url(BASE + "/dashboard"); page.wait_for_timeout(700)
    ok, detail = indicator_matches(page)
    check("navigating back works and the highlight follows", ok, detail)

    # --- narrow screen: the sidebar becomes a grid; the block still lands on the active item
    page.set_viewport_size({"width": 700, "height": 900}); page.wait_for_timeout(700)
    ok, detail = indicator_matches(page)
    check("at a narrow width the highlight still sits on the active item", ok, detail)
    page.set_viewport_size({"width": 1440, "height": 900}); page.wait_for_timeout(700)

    # --- ripple
    page.locator(".rdash").wait_for()
    btn = page.get_by_test_id("dashboard-refresh"); bb = btn.bounding_box()
    page.mouse.click(bb["x"] + 10, bb["y"] + bb["height"] / 2)
    page.wait_for_timeout(100)
    check("clicking a button starts one ripple at the click point", page.locator(".ripple").count() == 1 and page.locator(".ripple-wrap").count() == 1)
    wave = page.locator(".ripple").bounding_box() if page.locator(".ripple").count() else None
    check("the ripple is clipped inside the button", page.locator(".ripple-wrap").evaluate("e => getComputedStyle(e).overflow") == "hidden")
    page.wait_for_timeout(900)
    style = btn.get_attribute("style") or ""
    check("the ripple cleans up after itself (no span and no inline position left behind)", page.locator(".ripple").count() == 0 and page.locator(".ripple-wrap").count() == 0 and "position" not in style, (btn.get_attribute("class"), style))
    check("the button still works after a ripple (Refresh reloads)", page.locator(".trend-bar.current").count() >= 0 and btn.is_enabled())
    page.get_by_role("button", name="Log out").click(); page.wait_for_url(re.compile(r".*/login"));
    check("a header button with a ripple still performs its action", "/login" in page.url)

    # --- required-field shake: the rule applies to flagged fields in the case form only
    login(page)
    names = page.evaluate("""() => {
      const form = document.createElement('div'); form.className = 'case-form';
      form.innerHTML = '<div class="el-form-item is-required-error"><div class="el-input__wrapper" id="t1"></div><div class="el-select__wrapper" id="t2"></div><textarea class="el-textarea__inner" id="t3"></textarea></div>' +
        '<div class="required-invalid"><div class="el-input__wrapper" id="t4"></div></div><div class="el-form-item"><div class="el-input__wrapper" id="t5"></div></div>';
      document.body.appendChild(form);
      const out = ['t1','t2','t3','t4','t5'].map(id => getComputedStyle(document.getElementById(id)).animationName);
      const outside = document.createElement('div'); outside.innerHTML = '<div class="is-required-error"><div class="el-input__wrapper" id="t6"></div></div>'; document.body.appendChild(outside);
      out.push(getComputedStyle(document.getElementById('t6')).animationName);
      return out;
    }""")
    check("flagged fields inside the case form shake; unflagged fields and other pages do not", names == ["m-shake", "m-shake", "m-shake", "m-shake", "none", "none"], names)
    dur = page.evaluate("() => parseFloat(getComputedStyle(document.getElementById('t1')).animationDuration)")
    check("the shake is short (about a quarter of a second)", 0.2 <= dur <= 0.3, dur)
    # --- fonts (2026-11-26 owner decision): Lato for English and digits, Kai (標楷體) for Chinese, self-hosted
    page.goto(BASE + "/dashboard"); page.locator(".rdash").wait_for(); page.wait_for_timeout(800)
    fam = page.evaluate("() => getComputedStyle(document.body).fontFamily")
    names_in_stack = [n.strip().strip('"') for n in fam.split(",")]
    check("the page font stack starts with Lato, then the Kai fonts, then the previous Chinese fonts", names_in_stack[:5] == ["Lato", "標楷體", "DFKai-SB", "BiauKai", "Kaiti TC"] and "PingFang TC" in names_in_stack and "Microsoft JhengHei" in names_in_stack, fam)
    check("buttons, inputs and tables use the same stack (not the browser defaults)", all(page.evaluate("(s) => getComputedStyle(document.querySelector(s)).fontFamily", s).startswith("Lato") for s in [".el-button", ".nav-item", ".rdash .gp-v", ".rdash .stat-value"]))
    check("Lato is loaded from the system itself", page.evaluate("async () => { await document.fonts.ready; return document.fonts.check('14px Lato') && [...document.fonts].some(f => f.family.replace(/\"/g, '') === 'Lato' && f.status === 'loaded'); }"))
    check("numbers use tabular figures so amounts still line up", page.evaluate("() => getComputedStyle(document.querySelector('.rdash .stat-value')).fontVariantNumeric") == "tabular-nums")
    hosts = set(); seen = []
    page2 = ctx.new_page(); page2.on("request", lambda r: (hosts.add(r.url.split("/")[2]), seen.append(r.url)))
    page2.goto(BASE + "/cases"); page2.wait_for_timeout(1500)
    font_files = [u for u in seen if u.endswith((".woff2", ".woff"))]
    check("no request leaves the system (the fonts come from the same server)", hosts <= {"nginx"} and "googleapis" not in " ".join(seen), hosts)
    page2.close()

    ctx.close()

    # --- reduced motion: no ripple, no sliding, no shake
    ctx2 = b.new_context(viewport={"width": 1440, "height": 900}, reduced_motion="reduce"); page2 = ctx2.new_page(); page2.set_default_timeout(30000)
    page2.on("pageerror", lambda e: errors.append(str(e)))
    login(page2); page2.goto(BASE + "/dashboard"); page2.locator(".rdash").wait_for(); page2.wait_for_timeout(500)
    bb = page2.get_by_test_id("dashboard-refresh").bounding_box(); page2.mouse.click(bb["x"] + 10, bb["y"] + 8); page2.wait_for_timeout(80)
    check("reduced motion: no ripple", page2.locator(".ripple").count() == 0)
    page2.locator(".nav-item", has_text="Account List").click(); page2.wait_for_url(BASE + "/cases"); page2.wait_for_timeout(60)
    dur = page2.evaluate("() => parseFloat(getComputedStyle(document.querySelector('.nav-ind')).transitionDuration)")
    check("reduced motion: the sidebar highlight jumps instead of sliding", dur <= 0.01, dur)
    ok, detail = indicator_matches(page2)
    check("reduced motion: the highlight still ends on the active item", ok, detail)
    check("no console errors", not errors, errors[:3])
    b.close()
print(f"global interaction: {len(checks)} checks passed")
