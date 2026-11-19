"""V：Reinsurance Staff 對「應付給 Swiss Re Asia／Allianz（Facility）」的帳款可 Mark reviewed，不能登錄收付款，
只能取消自己的審核；取消時可選只取消這一筆或整批（2026-11-19 業主決定）。先執行 facility_review_seed.py。"""
from playwright.sync_api import sync_playwright, expect
BASE = "http://nginx"; USER, PASSWORD = "ui.facility.rs", "Ui-Facility-Pass-1"   # 由 facility_review_seed.py 建立
SW, SW_T1, ORD = 'UIFR-SW-1-R1-T2', 'UIFR-SW-1-R1-T1', 'UIFR-OR-1-R1-T2'
checks = []
def check(name, ok, detail=''):
    assert ok, (name, detail)
    checks.append(name); print('PASS ' + name, flush=True)
errors = []
with sync_playwright() as p:
    b = p.chromium.launch(); page = b.new_page(viewport={"width": 1500, "height": 950}); page.set_default_timeout(60000)
    page.on("console", lambda m: errors.append(m.text) if m.type == "error" and "Failed to load resource" not in m.text else None)
    page.goto(BASE + "/login"); page.get_by_label("Username").fill(USER); page.get_by_label("Password").fill(PASSWORD)
    page.get_by_role("button", name="Sign in").click(); page.wait_for_selector(".app-shell")
    page.goto(BASE + "/accounting")
    table = page.get_by_test_id("accounting-table")
    row = lambda no: table.locator("tbody tr").filter(has_text=no)
    def tab(name):
        page.get_by_role("tab", name=name, exact=True).click(); page.wait_for_timeout(500)
    def updated():
        expect(page.get_by_text("Accounting updated").last).to_be_visible(); page.wait_for_timeout(800)
    tab("Unreconciled Accounts"); expect(row(SW)).to_be_visible()
    mark = lambda no: row(no).get_by_role("button", name="Mark reviewed", exact=True)
    check("應付給 Swiss Re（Facility）的帳款顯示 Mark reviewed", mark(SW).count() == 1)
    check("同一案件的 Cedant 應收沒有 Mark reviewed", mark(SW_T1).count() == 0)
    check("應付給一般再保人的帳款沒有 Mark reviewed", mark(ORD).count() == 0)
    check("Reinsurance Staff 看不到 Record receipt / payment", table.get_by_role("button", name="Record receipt / payment", exact=True).count() == 0)
    mark(SW).click(); dlg = page.locator(".el-dialog:visible"); dlg.locator("input").nth(1).fill("UI facility review")
    dlg.get_by_role("button", name="Mark reviewed", exact=True).click(); updated()
    tab("Reconciled Accounts"); expect(row(SW)).to_be_visible()
    check("Reconciled：自己審的帳款只有 Cancel review batch，沒有登錄收付款",
          row(SW).get_by_role("button", name="Cancel review batch", exact=True).count() == 1
          and row(SW).get_by_role("button", name="Record receipt / payment", exact=True).count() == 0)
    row(SW).get_by_role("button", name="Cancel review batch", exact=True).click()
    dlg = page.get_by_test_id("cancel-review-dialog"); expect(dlg).to_be_visible()
    check("取消對話框可選「只取消這一筆」或「取消本人在這家的全部」",
          dlg.get_by_test_id("cancel-review-account").is_visible() and "Cancel all my reviews for this counterparty (1 accounts)" in dlg.get_by_test_id("cancel-review-batch").inner_text())
    dlg.get_by_test_id("cancel-review-account").click(); dlg.locator("textarea").first.fill("UI review correction")   # 測試標記直接落在文字框上
    dlg.get_by_role("button", name="Cancel review", exact=True).click(); updated()
    check("取消後帳款離開 Reconciled", row(SW).count() == 0)
    tab("Unreconciled Accounts"); expect(row(SW)).to_be_visible()
    check("取消後回到 Unreconciled，可再審核", mark(SW).count() == 1)
    check("沒有非預期的 JavaScript 錯誤", not errors, errors)
    b.close()
print(f"{len(checks)} passed Facility payable review UI checks")
