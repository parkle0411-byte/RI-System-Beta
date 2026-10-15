"""真實瀏覽器（無頭 Chromium）打開 Accounting 頁的實際時間（在壓測環境的網路內執行）。

  docker run --rm --network ri-stress_stress --memory 3g -e HOME=/tmp -v qa/stress:/s -w /s ri-ui-playwright:1.56.0 python3 browser_accounting.py [標籤]

量的是使用者看得到的時間：
  下載完成   /api/accounting 回應收完（含 nginx、後端、網路）
  第一列出現 表格第一列出現在畫面上
  可操作     表格畫完，再多等兩個動畫影格仍不卡（主執行緒閒下來）
  篩選回應   在 Reference 欄位輸入文字後，表格更新到只剩符合的列要多久
  DOM 節點、JS 記憶體
"""
import json
import sys
import time

from playwright.sync_api import sync_playwright

BASE = "http://nginx"
LABEL = sys.argv[1] if len(sys.argv) > 1 else "run"
USER, PASSWORD = "stress.finmgr", "Stress-Load-Test-9!"
TIMEOUT = 280_000


def main():
    out = {"label": LABEL}
    with sync_playwright() as p:
        browser = p.chromium.launch(args=["--js-flags=--max-old-space-size=2048"])
        page = browser.new_page(viewport={"width": 1600, "height": 900})
        page.set_default_timeout(TIMEOUT)
        page.goto(BASE + "/login")
        page.get_by_label("Username").fill(USER)
        page.get_by_label("Password").fill(PASSWORD)
        page.get_by_role("button", name="Sign in").click()
        page.wait_for_selector(".app-shell")

        api = {}
        page.on("request", lambda r: api.setdefault("start", time.perf_counter()) if r.url.endswith("/api/accounting") else None)
        page.on("requestfinished", lambda r: api.setdefault("end", time.perf_counter()) if r.url.endswith("/api/accounting") else None)

        t0 = time.perf_counter()
        page.goto(BASE + "/accounting", wait_until="commit")
        try:
            page.wait_for_selector("[data-testid=accounting-table] .el-table__body tr", state="attached")
            out["第一列出現(秒)"] = round(time.perf_counter() - t0, 1)
            # 主執行緒閒下來：連續兩個影格都在 100ms 內完成
            page.evaluate("""() => new Promise(resolve => {
                let last = performance.now(), calm = 0;
                const tick = () => { const now = performance.now(); calm = (now - last < 100) ? calm + 1 : 0; last = now; calm >= 2 ? resolve() : requestAnimationFrame(tick); };
                requestAnimationFrame(tick);
            })""")
            out["可操作(秒)"] = round(time.perf_counter() - t0, 1)
        except Exception as exc:  # noqa: BLE001
            out["錯誤"] = f"{type(exc).__name__}: {str(exc)[:120]}"
            out["已等待(秒)"] = round(time.perf_counter() - t0, 1)
        if "end" in api:
            out["下載完成(秒)"] = round(api["end"] - t0, 1)
        try:
            out["表格列數(DOM)"] = page.locator("[data-testid=accounting-table] .el-table__body tr").count()
            out["DOM 節點數"] = page.evaluate("document.querySelectorAll('*').length")
            out["JS 記憶體(MB)"] = page.evaluate("Math.round(performance.memory.usedJSHeapSize/1048576)")
            out["標題列數"] = page.locator("h2", has_text="SoA / Transactions (").first.inner_text()
        except Exception as exc:  # noqa: BLE001
            out["量測錯誤"] = str(exc)[:100]
        # 篩選回應：輸入 Reference 後，直到表格更新
        try:
            box = page.get_by_label("SoA / Transaction / Reference")
            heading = "() => (Array.from(document.querySelectorAll('h2')).find(h => h.innerText.includes('SoA / Transactions (')) || {}).innerText"
            before = page.evaluate(heading)
            t1 = time.perf_counter()
            box.fill("TWPAR2603")
            page.wait_for_function(f"({heading})() !== {json.dumps(before)}")
            page.evaluate("() => new Promise(r => requestAnimationFrame(() => requestAnimationFrame(r)))")
            out["篩選後更新(秒)"] = round(time.perf_counter() - t1, 1)
            out["篩選後標題"] = page.locator("h2", has_text="SoA / Transactions (").first.inner_text()
        except Exception as exc:  # noqa: BLE001
            out["篩選錯誤"] = str(exc)[:100]
        browser.close()
    print(json.dumps(out, ensure_ascii=False, indent=1))


main()
