"""V：Reinsurance Staff 對「對象是 Swiss Re Asia／Allianz（Facility）」的帳款（應付與應收）可 Mark reviewed，不能登錄收付款，
只能取消自己的審核；取消時可選只取消這一筆或整批（2026-11-19 業主決定）。先執行 facility_review_seed.py。"""
from playwright.sync_api import sync_playwright, expect
BASE = "http://nginx"; USER, PASSWORD = "ui.facility.rs", "Ui-Facility-Pass-1"   # 由 facility_review_seed.py 建立
SW, SW_T1, ORD, REFUND = 'UIFR-SW-1-R1-T2', 'UIFR-SW-1-R1-T1', 'UIFR-OR-1-R1-T2', 'UIFR-SW-2-R1-T2'
CLAIM_RI, CLAIM_CEDANT = 'UIFR-SW-1-C1-P1-R1-T1', 'UIFR-SW-1-C1-P1-R1-T2'   # 理賠：向 Swiss Re 收／付給 Cedant
AZ = 'UIFR-AZ-1-R1-T2'   # 2026-11-19：Swiss Property 保費 T2 要先收齊 Cedant 才能對帳，審核／取消流程改用 Allianz 應付
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
    tab("Unreconciled Transactions"); expect(row(SW)).to_be_visible()
    mark = lambda no: row(no).get_by_role("button", name="Mark reviewed", exact=True)
    check("應付給 Swiss Re（Facility）的帳款顯示 Mark reviewed", mark(SW).count() == 1)
    check("Cedant 未收齊：Swiss T2 的 Mark reviewed 停用並說明原因", mark(SW).is_disabled() and "Collect the full Cedant installment" in row(SW).inner_text())
    expect(row(AZ)).to_be_visible()
    check("應付給 Allianz（Facility）的帳款可直接 Mark reviewed", mark(AZ).count() == 1 and not mark(AZ).is_disabled())
    check("同一案件的 Cedant 應收沒有 Mark reviewed", mark(SW_T1).count() == 0)
    check("應付給一般再保人的帳款沒有 Mark reviewed", mark(ORD).count() == 0)
    expect(row(REFUND)).to_be_visible()
    check("向 Swiss Re 收回的退保保費（應收）也顯示 Mark reviewed", mark(REFUND).count() == 1)
    expect(row(CLAIM_RI)).to_be_visible()
    check("向 Swiss Re 收的理賠款顯示 Mark reviewed", mark(CLAIM_RI).count() == 1)
    check("付給 Cedant 的理賠款沒有 Mark reviewed", mark(CLAIM_CEDANT).count() == 0)
    check("Reinsurance Staff 看不到 Record receipt / payment", table.get_by_role("button", name="Record receipt / payment", exact=True).count() == 0)
    mark(AZ).click(); dlg = page.locator(".el-dialog:visible"); dlg.locator("input").nth(1).fill("UI facility review")
    dlg.get_by_role("button", name="Mark reviewed", exact=True).click(); updated()
    tab("Reconciled Transactions"); expect(row(AZ)).to_be_visible()
    check("Reconciled：自己審的帳款只有 Cancel review batch，沒有登錄收付款",
          row(AZ).get_by_role("button", name="Cancel review batch", exact=True).count() == 1
          and row(AZ).get_by_role("button", name="Record receipt / payment", exact=True).count() == 0)
    row(AZ).get_by_role("button", name="Cancel review batch", exact=True).click()
    dlg = page.get_by_test_id("cancel-review-dialog"); expect(dlg).to_be_visible()
    check("取消對話框可選「只取消這一筆」或「取消本人在這家的全部」",
          dlg.get_by_test_id("cancel-review-account").is_visible() and "Cancel all my reviews for this counterparty (1 transactions)" in dlg.get_by_test_id("cancel-review-batch").inner_text())
    dlg.get_by_test_id("cancel-review-account").click(); dlg.locator("textarea").first.fill("UI review correction")   # 測試標記直接落在文字框上
    dlg.get_by_role("button", name="Cancel review", exact=True).click(); updated()
    check("取消後帳款離開 Reconciled", row(AZ).count() == 0)
    tab("Unreconciled Transactions"); expect(row(AZ)).to_be_visible()
    check("取消後回到 Unreconciled，可再審核", mark(AZ).count() == 1)
    mark(CLAIM_RI).click(); dlg = page.locator(".el-dialog:visible"); dlg.locator("input").nth(1).fill("UI claim review")
    dlg.get_by_role("button", name="Mark reviewed", exact=True).click(); updated()
    tab("Reconciled Transactions"); expect(row(CLAIM_RI)).to_be_visible()
    check("理賠應收審核後移到 Reconciled，只有 Cancel review batch",
          row(CLAIM_RI).get_by_role("button", name="Cancel review batch", exact=True).count() == 1
          and row(CLAIM_RI).get_by_role("button", name="Record receipt / payment", exact=True).count() == 0)
    check("沒有非預期的 JavaScript 錯誤", not errors, errors)
    b.close()
print(f"{len(checks)} passed Facility account review UI checks")
