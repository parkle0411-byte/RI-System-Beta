"""Accounting 分頁的功能檢查（真實瀏覽器，1 萬件案件／1.8 萬列資料；在壓測環境的網路內執行）。

  docker run --rm --network ri-stress_stress --memory 3g --shm-size 1g -e HOME=/tmp -v qa/stress:/s:ro -w /s ri-ui-playwright:1.56.0 python3 browser_paging.py
"""
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
    page.goto(BASE + "/accounting")
    rows = page.locator("[data-testid=accounting-table] .el-table__body tr")
    rows.first.wait_for(state="attached")
    heading = lambda: page.locator("h2", has_text="SoA / Transactions (").first.inner_text()
    first_row = lambda: rows.first.inner_text()

    check("title shows the full filtered total", heading() == "SoA / Transactions (18000)", heading())
    check("first page renders 100 rows, not 18,000", rows.count() == 100, str(rows.count()))
    pagination = page.locator("[data-testid=accounting-pagination]")
    check("pagination shows the total", "18000" in pagination.inner_text(), pagination.inner_text()[:60])
    page1_first = first_row()

    pagination.locator(".el-pager li", has_text="2").first.click()
    page.wait_for_function("(a) => document.querySelector('[data-testid=accounting-table] .el-table__body tr').innerText !== a", arg=page1_first)
    check("page 2 shows different rows (100)", rows.count() == 100 and first_row() != page1_first)
    page2_first = first_row()

    # 勾選一列（可勾的第一列），換頁後仍保留
    box = page.locator("[data-testid=accounting-table] .el-table__body .el-checkbox:not(.is-disabled)").first
    selectable = box.count() > 0
    if selectable:
        box.click()
        record = page.get_by_role("button", name="Record selected (1)")
        check("selecting a row enables Record selected (1)", record.count() == 1)
        pagination.locator(".el-pager li", has_text="3").first.click()
        page.wait_for_function("(a) => document.querySelector('[data-testid=accounting-table] .el-table__body tr').innerText !== a", arg=page2_first)
        check("selection is kept after changing page", page.get_by_role("button", name="Record selected (1)").count() == 1)
        pagination.locator(".el-pager li", has_text="2").first.click()
        page.wait_for_function("(a) => document.querySelector('[data-testid=accounting-table] .el-table__body tr').innerText === a", arg=page2_first)
        check("the selected row is still checked when its page is shown again",
              page.locator("[data-testid=accounting-table] .el-table__body .el-checkbox.is-checked").count() == 1)
    else:
        check("a selectable row exists on page 2", False)

    # 換頁大小
    pagination.locator(".el-select").click()
    page.locator(".el-select-dropdown__item", has_text="50/page").click()
    page.wait_for_function("document.querySelectorAll('[data-testid=accounting-table] .el-table__body tr').length === 50")
    check("page size 50 shows 50 rows", rows.count() == 50)

    # 篩選：回到第 1 頁，標題是符合的總數
    pagination.locator(".el-pager li", has_text="4").first.click()
    page.get_by_label("SoA / Transaction / Reference").fill("TWPAR2603")
    page.wait_for_function("(document.querySelector('h2:nth-of-type(1)') && Array.from(document.querySelectorAll('h2')).some(h => h.innerText.match(/SoA \\/ Transactions \\(\\d+\\)/) && !h.innerText.includes('18000')))")
    time.sleep(0.5)
    total = int(heading().split("(")[1].rstrip(")"))
    check("filter updates the total", 0 < total < 18000, heading())
    current = pagination.locator(".el-pager li.is-active").inner_text() if pagination.count() else "1"
    check("filter returns to page 1", current.strip() == "1", current)
    check("filtered page shows min(total, page size) rows", rows.count() == min(total, 50), f"{rows.count()} / {total}")

    # 很窄的篩選：不到一頁就不顯示分頁，列全部顯示
    page.get_by_label("SoA / Transaction / Reference").fill("TWPAR2603001")
    page.wait_for_function("(document.querySelectorAll('[data-testid=accounting-table] .el-table__body tr').length) <= 50")
    time.sleep(0.5)
    narrow = int(heading().split("(")[1].rstrip(")"))
    check("narrow filter: all rows shown and no pagination bar", rows.count() == narrow and (narrow == 0 or narrow <= 50) and page.locator("[data-testid=accounting-pagination]").count() == 0,
          f"{rows.count()} rows / total {narrow}")

    # 清除篩選回到全部
    page.get_by_label("SoA / Transaction / Reference").fill("")
    page.wait_for_function("Array.from(document.querySelectorAll('h2')).some(h => h.innerText.includes('(18000)'))")
    check("clearing the filter restores all 18,000 (paged)", heading() == "SoA / Transactions (18000)" and rows.count() == 50)
    browser.close()

print(f"\n{sum(results)}/{len(results)} passed")
sys.exit(0 if all(results) else 1)
