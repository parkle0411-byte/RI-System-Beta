"""真實瀏覽器：第一次打開 Accounting、切到 Dashboard、再切回 Accounting 的實際體驗（在壓測環境的網路內執行）。
切換頁面要點選單（不能重新載入網頁），才是使用者實際的操作。"""
import sys
import time

from playwright.sync_api import sync_playwright

BASE = "http://nginx"
results = []


def check(name, ok, detail=""):
    results.append(ok)
    print(("PASS " if ok else "FAIL ") + name + (f"  [{detail}]" if detail and not ok else ""))


with sync_playwright() as p:
    browser = p.chromium.launch()
    page = browser.new_page(viewport={"width": 1600, "height": 900})
    page.set_default_timeout(120_000)
    page.goto(BASE + "/login")
    page.get_by_label("Username").fill("stress.finmgr")
    page.get_by_label("Password").fill("Stress-Load-Test-9!")
    page.get_by_role("button", name="Sign in").click()
    page.wait_for_selector(".app-shell")
    rows = page.locator("[data-testid=accounting-table] .el-table__body tr")
    banner = page.locator("[data-testid=accounting-refreshing]")

    t = time.perf_counter()
    page.goto(BASE + "/accounting")
    rows.first.wait_for(state="attached")
    first = time.perf_counter() - t
    print(f"第一次打開 Accounting：{first:.1f} 秒看到清單")
    check("first visit shows no 'showing earlier list' banner", banner.count() == 0)
    record_buttons = page.get_by_role("button", name="Record payment").count()
    check("first visit: Record payment buttons are available", record_buttons > 0, str(record_buttons))

    page.locator(".nav-item", has_text="Dashboard").click()
    page.wait_for_url("**/dashboard")
    time.sleep(1)
    t = time.perf_counter()
    page.locator(".nav-item", has_text="Accounting").click()
    rows.first.wait_for(state="attached")
    back = time.perf_counter() - t
    print(f"切回 Accounting：{back:.1f} 秒看到清單（先顯示上次的清單）")
    check("returning shows the earlier list within 3 seconds", back < 3, f"{back:.1f}s")
    check("returning shows the 'updating' banner", banner.count() == 1)
    check("while updating, Record payment is not available", page.get_by_role("button", name="Record payment").count() == 0)
    t = time.perf_counter()
    banner.wait_for(state="detached", timeout=120_000)
    done = time.perf_counter() - t
    print(f"背景更新完成：再過 {done:.1f} 秒")
    check("after the update the banner disappears and Record payment is back", page.get_by_role("button", name="Record payment").count() > 0)
    check("after the update the list still has 18,000 rows in total", page.locator("h2", has_text="SoA / Transactions (").first.inner_text() == "SoA / Transactions (18000)")

    # 登出再用別人登入：不能看到上一個人的清單
    page.locator(".page-header button", has_text="Log out").click()
    page.wait_for_url("**/login")
    page.get_by_label("Username").fill("stress.fin1")
    page.get_by_label("Password").fill("Stress-Load-Test-9!")
    page.get_by_role("button", name="Sign in").click()
    page.wait_for_selector(".app-shell")
    page.locator(".nav-item", has_text="Accounting").click()
    time.sleep(1)
    check("after another user signs in, the previous user's list is not shown", banner.count() == 0)
    browser.close()

print(f"\n{sum(results)}/{len(results)} passed")
sys.exit(0 if all(results) else 1)
