"""
畫面測試（無頭 Chromium）。只在用完即丟的測試環境執行（scripts/run_ui_test.sh），資料全是合成的。

  python3 ui_test.py A   外框與各頁面；業務人員：新增草稿 → 補齊 → 文件 → Announce → 通知會計 → 批單
  python3 ui_test.py B   （執行腳本已把案件設成 Confirmed）管理員：Renewal → Reverse → 修正 Reversed 案件；回收桶；MDM；FX；人員與帳號；Audit
  python3 ui_test.py C   Case Viewer 的權限範圍；強制改密碼
  python3 ui_test.py D   （案件此時是 Announced）Finance Staff：Accounting 帳本、記付款、沖銷；管理員：從帳本開啟案件的 SOA 分頁
"""
import re
import sys
from playwright.sync_api import sync_playwright

BASE = "http://nginx"
PASSWORD = "Ui-Test-Pass-1"
PHASE = sys.argv[1] if len(sys.argv) > 1 else "A"
results, console_errors = [], []
shot = [0]


def check(name, ok, detail=""):
    results.append((name, bool(ok), detail))
    print(("PASS " if ok else "FAIL ") + name + ("" if ok else f"   <-- {detail}"), flush=True)


def snap(page, name):
    shot[0] += 1
    page.screenshot(path=f"out/{PHASE}{shot[0]:02d}-{name}.png", full_page=True)


def label_re(text):
    return re.compile(r"^\s*" + re.escape(text) + r"\s*$")


def item(scope, page, label):
    return scope.locator(".el-form-item").filter(has=page.locator(".el-form-item__label", has_text=label_re(label))).first


def fill(scope, page, label, value):
    field = item(scope, page, label).locator("input, textarea").first
    field.fill(str(value))
    field.press("Tab")


def open_option(page, option):
    """點「目前打開的」下拉選單裡的選項（關閉中的下拉選單也留在 DOM 裡，不能選到它們）。"""
    page.locator('.el-select__popper[aria-hidden="false"] .el-select-dropdown__item').filter(has_text=option).first.click()


def pick(scope, page, label, option):
    item(scope, page, label).locator(".el-select__wrapper").first.click()
    open_option(page, option)
    page.keyboard.press("Escape")
    page.wait_for_timeout(250)


def selected_label(scope, page, label):
    return item(scope, page, label).locator(".el-select__placeholder").first.inner_text().strip()


def date(scope, page, label, value):
    field = item(scope, page, label).locator(".el-date-editor input").first
    field.fill(value)
    field.press("Enter")
    page.keyboard.press("Escape")


def section(page, title):
    return page.locator(".el-collapse-item").filter(has=page.locator(".el-collapse-item__header", has_text=title)).first


def message(page, expect):
    """等待「包含 expect 文字」的提示訊息出現（畫面上可能還留著前一則），回傳是否出現。"""
    try:
        page.locator(".el-message", has_text=expect).last.wait_for(timeout=10000)
        return True
    except Exception:  # noqa: BLE001
        return False


def confirm_box(page, button):
    page.locator(".el-message-box").wait_for(timeout=10000)
    page.locator(".el-message-box__btns button", has_text=button).click()


def login(page, username):
    page.goto(BASE + "/login")
    page.get_by_label("Username").fill(username)
    page.get_by_label("Password").fill(PASSWORD)
    page.get_by_role("button", name="Sign in").click()
    page.wait_for_selector(".app-shell", timeout=15000)
    console_errors.clear()  # 登入前檢查登入狀態的 401 是預期的


def logout(page):
    page.locator(".page-header button", has_text="Log out").click()
    page.wait_for_url(BASE + "/login")


def nav(page, label):
    page.locator(".nav-item", has_text=label).click()
    page.wait_for_timeout(700)


def open_case(page, insured, ref=None):
    nav(page, "Account List")
    rows = page.locator(".case-table .el-table__row")
    if ref:
        rows = rows.filter(has_text=ref)
    rows.locator(".insured-preview-link", has_text=insured).first.click()
    page.locator(".case-preview-dialog").wait_for()
    page.get_by_role("button", name="Open full case").click()
    page.locator(".case-detail-tabs").wait_for()
    page.wait_for_timeout(500)


def header_title(page):
    return page.locator(".page-header h1").inner_text().strip()


def phase_a(page):
    login(page, "ui.admin")
    check("admin lands on the first navigation entry (Dashboard pending card)", page.url.endswith("/dashboard") and page.locator(".pending-card").is_visible(), page.url)
    labels = page.locator(".nav-item span:not(.nav-phase)").all_inner_texts()
    check("sidebar shows Alpha's navigation for an admin", labels == ["Dashboard", "Account List", "Reinsurance MDM", "Personnel & Accounts", "Production Report", "Accounting", "FX Rates", "Draft Recycle Bin", "Audit Log"], labels)
    for label, marker in [("Account List", "All cases"), ("Reinsurance MDM", "Reinsurers ("), ("Personnel & Accounts", "Personnel roster"),
                          ("FX Rates", "Official monthly rates"), ("Draft Recycle Bin", "Retained Drafts"), ("Audit Log", "Audit events"),
                          ("Production Report", "Queued for migration"), ("Accounting", "Payment schedule (")]:
        nav(page, label)
        check(f"{label} page loads", page.get_by_text(marker).first.is_visible())
    logout(page)

    # ---------------- 業務人員：新增草稿 ----------------
    login(page, "ui.sales")
    labels = page.locator(".nav-item span:not(.nav-phase)").all_inner_texts()
    check("sales sees Dashboard, Account List, MDM, Production, FX", labels == ["Dashboard", "Account List", "Reinsurance MDM", "Production Report", "FX Rates"], labels)
    nav(page, "Account List")
    page.get_by_role("button", name="+ New case").click()
    page.locator(".case-form").wait_for()
    check("new case: header 'Account' with Cancel / Save draft in the header", header_title(page) == "Account"
          and page.locator(".page-header button", has_text="Save draft").is_visible() and page.locator(".page-header button", has_text="Cancel").is_visible())
    page.wait_for_timeout(800)
    owner = selected_label(page, page, "Case owner")
    check("case owner defaults to the signed-in person", owner == "UI Sales", owner)
    fill(page, page, "Original insured (EN)", "UI Test Insured Ltd")
    page.locator(".form-actions button", has_text="Save draft").click()
    check("incomplete Draft can be saved", message(page, "Draft saved"))
    page.locator(".case-table").wait_for()
    check("the new Draft is listed", page.locator(".insured-preview-link", has_text="UI Test Insured Ltd").count() == 1)
    snap(page, "list-after-draft")

    # ---------------- 補齊內容 ----------------
    open_case(page, "UI Test Insured Ltd")
    check("case detail: header shows 'Draft · not assigned'", header_title(page) == "Draft · not assigned", header_title(page))
    page.locator(".page-header button", has_text="Edit draft").click()
    page.locator(".case-form").wait_for()
    page.wait_for_timeout(800)
    risk = section(page, "Risk Details")
    pick(risk, page, "Reinsurance structure", "Quota Share")
    pick(risk, page, "AE", "UI AE One")
    pick(risk, page, "Currency", "USD")
    pick(risk, page, "Class", "Property")
    pick(risk, page, "New / Renew", "New")
    item(risk, page, "Type").locator("input").first.fill("Fire")
    pick(risk, page, "Reinsured", "UI Cedant Insurance")
    date(risk, page, "Effective date", "2026-03-01")
    date(risk, page, "Expiration date", "2027-03-01")
    risk.locator(".situation-row input").nth(0).fill("1 Test Road")
    risk.locator(".situation-row input").nth(1).fill("100")
    type_text = item(risk, page, "Type").inner_text()
    check("Type shows the locked structure suffix", "Facultative Reinsurance" in type_text, type_text)

    security = section(page, "Schedule of Security")
    security.get_by_role("button", name="+ Add reinsurer").click()
    cards = security.locator(".repeat-card")
    pick(cards.nth(0), page, "Reinsurer", "UI Re Alpha")
    fill(cards.nth(0), page, "Order hereon (%)", "60")
    pick(cards.nth(1), page, "Reinsurer", "UI Re Beta (Facility)")
    fill(cards.nth(1), page, "Order hereon (%)", "40")

    terms = section(page, "Terms & Conditions")
    fill(terms, page, "Limit of Liability", "1000000")
    fill(terms, page, "Deductibles", "10% of loss")
    fill(terms, page, "Original Conditions", "As original")
    occ = section(page, "Occupation & Construction")
    fill(occ, page, "Occupation", "Office")
    fill(occ, page, "Construction", "Concrete")
    sums = section(page, "Breakdown of Sum Insured")
    sums.locator(".sum-row input").nth(0).fill("Building")
    sums.locator(".sum-row input").nth(1).fill("1000000")
    loss = section(page, "Loss Record")
    date(loss, page, "Loss record advised by broker on", "2026-02-01")
    fill(loss, page, "Past year(s)", "5")
    cedant = section(page, "Cedant Premium")
    fill(cedant, page, "100% Premium", "1000")
    fill(cedant, page, "Payment terms (days)", "30")
    fill(cedant, page, "Ceding commission (%)", "10")
    fill(cedant, page, "Tax (%)", "0")
    rp = section(page, "Reinsurer Premium").locator(".repeat-card")
    for index, premium in ((0, "600"), (1, "400")):
        fill(rp.nth(index), page, "Premium", premium)
        fill(rp.nth(index), page, "Deductions (%)", "5")
        fill(rp.nth(index), page, "Tax (%)", "0")
    conditions = section(page, "Reinsurance Conditions").inner_text()
    check("fixed clause of the selected reinsurer is added (LMA5390, Fixed)", "LMA5390" in conditions and "Fixed" in conditions and "LMA3333" in conditions, conditions[:300])
    snap(page, "form-filled")

    page.locator(".form-actions button", has_text="Review & confirm").click()
    page.locator(".review-dialog .review-heading", has_text="Review case details").wait_for()
    check("Review & confirm opens the read-only review", page.locator(".review-dialog").filter(has_text="Total order: 100%").count() >= 1)
    snap(page, "review-dialog")
    page.locator(".review-dialog .el-dialog__footer button", has_text="Save changes").click()
    check("saving the edit returns to the case detail", message(page, "Draft updated"))
    page.locator(".case-detail-tabs").wait_for()
    page.wait_for_timeout(500)
    overview = page.locator(".overview-grid").inner_text()
    check("overview: version 2 and computed amounts (unified ledger rounding: brokerage 406.00)",
          "version 2" in overview and "406.00" in overview and "1,000.00" in overview, overview[:400])
    check("overview: Avg. Rate", "0.100000%" in overview)
    snap(page, "overview")

    # ---------------- 文件與 Announce ----------------
    page.locator(".case-detail-tabs .el-tabs__item", has_text="Cover & Debit Note").click()
    page.wait_for_timeout(800)
    docs = page.locator(".documents-grid")
    check("documents: not ready before any evidence", "Not ready to Announce" in docs.inner_text())
    check("documents: generation buttons are disabled on the VM", page.locator(".generated-document-actions button").first.is_disabled())
    upload = page.locator(".document-upload-card")

    def upload_doc(kind_label, reinsurer, filename, content):
        if kind_label != "Offer Slip":
            upload.locator(".el-form-item").first.locator(".el-select__wrapper").click()
            open_option(page, kind_label)
            page.wait_for_timeout(250)
            upload.locator(".el-form-item").nth(1).locator(".el-select__wrapper").click()
            open_option(page, reinsurer)
            page.keyboard.press("Escape")
            page.wait_for_timeout(250)
        upload.locator("input[type=file]").set_input_files({"name": filename, "mimeType": "application/octet-stream", "buffer": content})
        count = page.locator(".document-table .el-table__row").count()
        upload.get_by_role("button", name="Upload evidence").click()
        page.wait_for_function(f"document.querySelectorAll('.document-table .el-table__row').length > {count}", timeout=10000)
        return True

    check("upload Offer Slip (PDF)", upload_doc("Offer Slip", None, "offer.pdf", b"%PDF-1.7\nui test offer\n"))
    check("upload Signed Slip for UI Re Alpha", upload_doc("Reinsurer Signed Slip", "UI Re Alpha", "signed.pdf", b"%PDF-1.7\nui test signed\n"))
    check("upload Confirmation e-mail for the Facility reinsurer", upload_doc("Reinsurer Confirmation E-mail", "UI Re Beta (Facility)", "confirm.eml", b"From: re@example.com\r\nSubject: ok\r\n\r\nConfirmed"))
    page.wait_for_timeout(500)
    check("documents: three files listed and Announce readiness Ready", page.locator(".document-table .el-table__row").count() == 3 and "Documents complete" in docs.inner_text())
    check("signed slip reminder: Facility reinsurer still missing a SIGNED slip; e-mail delivery not enabled",
          "Signed Slip missing" in docs.inner_text() and "automated e-mail delivery is not enabled" in docs.inner_text())
    snap(page, "documents")
    page.get_by_role("button", name="Review & Announce").click()
    dialog = page.locator(".announce-dialog")
    dialog.wait_for()
    announce_btn = dialog.locator(".el-dialog__footer button", has_text="Announce")
    check("Announce is disabled until the attestation is checked", announce_btn.is_disabled())
    dialog.locator(".announce-attestation").click()
    snap(page, "announce-dialog")
    announce_btn.click()
    check("Announce assigns the TW Reference", message(page, "Case Announced · TWPAR2603001"))
    page.wait_for_timeout(500)
    check("header shows the TW Reference", header_title(page) == "TWPAR2603001", header_title(page))

    # ---------------- 通知會計 ----------------
    # 與 Alpha 相同：Announce 之後不會重新載入流程狀態，要重新打開案件才出現「Record notification」
    check("(as Alpha) Record notification appears only after reopening the case", page.get_by_role("button", name="Record notification").count() == 0)
    open_case(page, "UI Test Insured Ltd")
    page.get_by_role("button", name="Record notification").click()
    acc = page.locator(".el-dialog").filter(has_text="Record Accounting notification")
    acc.wait_for()
    pick(acc, page, "Accounting recipient", "UI Finance")
    fill(acc, page, "Note", "Please book the premium.")
    acc.locator(".el-dialog__footer button", has_text="Record notification").click()
    check("accounting notification recorded", message(page, "Accounting notification recorded"))
    page.wait_for_timeout(800)
    check("notification shown on the overview", "UI Finance" in page.locator(".overview-grid").inner_text())

    # ---------------- Claim 分頁（後端尚未移植） ----------------
    page.locator(".case-detail-tabs .el-tabs__item", has_text="Claim").click()
    page.wait_for_timeout(300)
    check("Claim tab falls back to Alpha's 'later milestone' card", page.get_by_text("will be converted from the development site in a later milestone").is_visible())

    # ---------------- 批單 ----------------
    page.locator(".case-detail-tabs .el-tabs__item", has_text="Endorsements").click()
    page.wait_for_timeout(800)
    check("endorsement chain lists the announced root", "TWPAR2603001" in page.locator(".workflow-table").inner_text())
    page.get_by_role("button", name="Create endorsement").click()
    confirm_box(page, "Create draft")
    check("endorsement Draft created", message(page, "Endorsement Draft created"))
    page.locator(".endorsement-editor").wait_for()
    check("endorsement form: header 'New endorsement' and risk fields locked", header_title(page) == "New endorsement"
          and page.locator("fieldset.case-fieldset").evaluate("el => el.disabled") is True, header_title(page))
    snap(page, "endorsement-form")
    page.locator(".page-header button", has_text="Cancel").click()
    page.locator(".case-table").wait_for()
    check("endorsement Drafts are not top-level rows in the list", page.locator(".case-table .el-table__row").count() == 1)
    logout(page)


def phase_b(page):
    login(page, "ui.admin")
    open_case(page, "UI Test Insured Ltd")
    check("Confirmed case: header offers Reverse case and Create renewal", page.locator(".page-header button", has_text="Reverse case").is_visible()
          and page.locator(".page-header button", has_text="Create renewal").is_visible())
    page.locator(".page-header button", has_text="Create renewal").click()
    confirm_box(page, "Create draft")
    check("renewal Draft created", message(page, "Renewal Draft created"))
    page.locator(".case-form").wait_for()
    policy_from = item(section(page, "Risk Details"), page, "Effective date").locator("input").first.input_value()
    check("renewal form: effective date moved one year", policy_from == "2027-03-01", policy_from)
    page.locator(".page-header button", has_text="Cancel").click()
    page.locator(".case-table").wait_for()
    page.wait_for_timeout(500)
    check("list shows the Confirmed case and the renewal Draft", page.locator(".case-table .el-table__row").count() == 2)

    open_case(page, "UI Test Insured Ltd", ref="TWPAR2603001")
    page.locator(".page-header button", has_text="Reverse case").click()
    confirm_box(page, "Reverse case")
    check("case reversed", message(page, "Case reversed"))
    page.wait_for_timeout(800)
    btn = page.locator(".page-header button", has_text="Correct reversed case")
    check("Reversed case offers 'Correct reversed case'", btn.is_visible())
    btn.click()
    page.locator(".case-form").wait_for(timeout=8000)
    check("VM fix: 'Correct reversed case' opens the form (Alpha did nothing)", page.get_by_text("Correct the figures and save.").is_visible())
    page.locator(".page-header button", has_text="Save changes").click()
    confirm_box(page, "Save and move to Announced")
    check("correction saved and moved back to Announced", message(page, "Correction saved"))
    page.wait_for_timeout(800)
    check("detail shows Announced again", "Announced" in page.locator(".page-header p").inner_text(), page.locator(".page-header p").inner_text())

    # ---------------- 回收桶（管理員從預覽丟入，再從回收桶還原） ----------------
    nav(page, "Account List")
    page.get_by_role("button", name="+ New case").click()
    page.locator(".case-form").wait_for()
    fill(page, page, "Original insured (EN)", "UI Recycle Me")
    page.locator(".form-actions button", has_text="Save draft").click()
    message(page, "Draft saved")
    page.locator(".insured-preview-link", has_text="UI Recycle Me").click()
    page.locator(".case-preview-dialog").wait_for()
    page.get_by_role("button", name="Recycle Draft").click()
    confirm_box(page, "Move to recycle bin")
    check("Draft recycled from the preview", message(page, "recycle bin"))
    page.wait_for_timeout(500)
    check("recycled Draft left the list", page.locator(".insured-preview-link", has_text="UI Recycle Me").count() == 0)
    nav(page, "Draft Recycle Bin")
    check("recycle bin lists it with a restore deadline", "UI Recycle Me" in page.locator(".table-card").inner_text())
    snap(page, "recycle-bin")
    page.get_by_role("button", name="Restore").click()
    check("restored", message(page, "Draft restored"))
    nav(page, "Account List")
    check("restored Draft is back in the list", page.locator(".insured-preview-link", has_text="UI Recycle Me").count() == 1)

    # ---------------- MDM（主檔 payload 以 JSON 字串送出，驗證 VM 的相容修正） ----------------
    nav(page, "Reinsurance MDM")
    page.locator(".mdm-tab", has_text="Clauses").click()
    page.get_by_role("button", name="+ Add Clause").click()
    dlg = page.locator(".master-dialog")
    dlg.wait_for()
    fill(dlg, page, "Clause code", "LPO9999")
    fill(dlg, page, "Clause title", "UI Clause Gamma")
    dlg.locator(".el-dialog__footer button", has_text="Add record").click()
    check("clause added", message(page, "Clause added"))
    page.locator(".mdm-tab", has_text="Reinsurers").click()
    page.get_by_role("button", name="+ Add Reinsurer").click()
    dlg.wait_for()
    fill(dlg, page, "Name", "UI Re Gamma")
    fill(dlg, page, "Abbreviation", "URG")
    pick(dlg, page, "Clause", "LPO9999")
    dlg.get_by_role("button", name="+ Add fixed clause").click()
    dlg.locator(".el-dialog__footer button", has_text="Add record").click()
    check("reinsurer with a fixed clause added (payload sent as a JSON string)", message(page, "Reinsurer added"))
    page.wait_for_timeout(500)
    row = page.locator(".el-table__row", has_text="UI Re Gamma")
    check("reinsurer row shows abbreviation and 1 fixed clause", "URG" in row.inner_text() and re.search(r"\b1\b", row.inner_text()) is not None, row.inner_text())
    row.get_by_role("button", name="Deactivate").click()
    check("deactivate", message(page, "deactivated"))
    page.locator(".el-table__row", has_text="UI Re Gamma").get_by_role("button", name="Reactivate").click()
    check("reactivate", message(page, "reactivated"))
    snap(page, "mdm")

    # ---------------- FX ----------------
    nav(page, "FX Rates")
    page.get_by_role("button", name="+ Set monthly rates").click()
    fx = page.locator(".master-dialog")
    fx.wait_for()
    for index, rate in enumerate(["30.5", "33.1", "0.21", "38.9", "3.9", "6.8"]):
        fx.locator(".el-table__row").nth(index).locator("input").fill(rate)
    fx.get_by_role("button", name="Save monthly rates").click()
    check("monthly FX rates saved", message(page, "Monthly FX rates saved"))
    page.wait_for_timeout(500)
    check("six rates listed", page.locator(".table-card .case-table .el-table__row").count() == 6)

    # ---------------- 人員與帳號 ----------------
    nav(page, "Personnel & Accounts")
    page.get_by_role("button", name="+ Add personnel").click()
    pd = page.locator(".master-dialog").filter(has_text="Add personnel")
    pd.wait_for()
    fill(pd, page, "Name", "UI Added Person")
    pd.locator(".el-dialog__footer button", has_text="Add personnel").click()
    check("personnel added", message(page, "Personnel added"))
    partner = page.locator(".el-table__row", has_text="UI Partner")
    partner.get_by_role("button", name="Create account").click()
    ad = page.locator(".master-dialog").filter(has_text="Create login account")
    ad.wait_for()
    fill(ad, page, "Username", "ui.partner")
    ad.locator(".el-dialog__footer button", has_text="Create account").click()
    secret = page.locator(".master-dialog").filter(has_text="Shown once")
    secret.wait_for()
    check("generated password shown once", len(secret.locator("input").nth(1).input_value()) >= 16)
    snap(page, "account-secret")
    secret.get_by_role("button", name="I have noted it — close").click()
    page.wait_for_timeout(500)
    check("account shows Active with 'Password change pending'", "Password change pending" in page.locator(".el-table__row", has_text="UI Partner").inner_text())
    snap(page, "personnel")

    nav(page, "Audit Log")
    page.wait_for_timeout(500)
    text = page.locator(".table-card").inner_text()
    check("Audit Log shows the actions just performed", "announce" in text and "create_account" in text and "recycle_draft" in text)
    logout(page)


def phase_c(page):
    login(page, "ui.viewer")
    labels = page.locator(".nav-item span:not(.nav-phase)").all_inner_texts()
    check("Case Viewer sees only Dashboard and Account List", labels == ["Dashboard", "Account List"], labels)
    nav(page, "Account List")
    check("Case Viewer sees no other people's cases and no + New case", page.locator(".case-table .el-table__row").count() == 0
          and page.get_by_role("button", name="+ New case").count() == 0)
    logout(page)

    login(page, "ui.newcomer")
    check("temporary password: forced change dialog, no navigation", page.get_by_text("Change your password first").is_visible() and page.locator(".nav-item").count() == 0)
    snap(page, "forced-password")
    dlg = page.locator(".review-dialog").filter(has_text="Change your password first")
    fill(dlg, page, "Current password", PASSWORD)
    fill(dlg, page, "New password", "Brand-New-Pass-7")
    fill(dlg, page, "Confirm new password", "Brand-New-Pass-7")
    dlg.get_by_role("button", name="Update password").click()
    check("password changed", message(page, "Password updated"))
    page.wait_for_timeout(800)
    check("navigation available after the change", page.locator(".nav-item").count() >= 1)
    logout(page)


def acc_row(page, party):
    return page.locator(".table-card .el-table__row").filter(has_text="TWPAR2603001").filter(has_text=party).first


def phase_d(page):
    login(page, "ui.finance")
    labels = page.locator(".nav-item span:not(.nav-phase)").all_inner_texts()
    check("Finance Staff sees Production Report, Accounting, FX Rates", labels == ["Production Report", "Accounting", "FX Rates"], labels)
    nav(page, "Accounting")
    page.locator(".table-card .el-table__row").first.wait_for()
    rows = page.locator(".table-card .el-table__row").filter(has_text="TWPAR2603001")
    check("ledger lists the Announced case: Cedant + 2 Reinsurers", rows.count() == 3, rows.count())
    ced = acc_row(page, "Cedant")
    check("VM fix: no 'Partial payment' on rows with nothing paid (Alpha shows it on every row)", "Partial payment" not in rows.first.inner_text(), rows.first.inner_text())
    check("cedant row: Record payment button, no case link for Finance", ced.get_by_role("button", name="Record payment").is_visible()
          and ced.locator(".table-action").count() == 0, ced.inner_text())
    snap(page, "accounting-ledger")

    fill(page.locator(".table-card").first, page, "TW Ref", "nothing-matches")
    page.wait_for_timeout(300)
    check("TW Ref filter: no rows", page.get_by_text("No payment schedule rows match these filters.").is_visible())
    fill(page.locator(".table-card").first, page, "TW Ref", "twpar2603")
    page.wait_for_timeout(300)
    pick(page.locator(".table-card").first, page, "Payment party", "Reinsurer")
    check("Payment party = Reinsurer: 2 rows", page.locator(".table-card .el-table__row").filter(has_text="TWPAR2603001").count() == 2)
    item(page.locator(".table-card").first, page, "Payment party").locator(".el-select__wrapper").first.hover()
    item(page.locator(".table-card").first, page, "Payment party").locator(".el-select__clear").first.click()
    page.wait_for_timeout(300)

    outstanding_before = ced.locator("td").nth(6).inner_text()
    ced.get_by_role("button", name="Record payment").click()
    dlg = page.locator(".review-dialog").filter(has_text="Record partial payment")
    dlg.wait_for()
    today = page.evaluate("new Intl.DateTimeFormat('en-CA', { timeZone: 'Asia/Taipei', year: 'numeric', month: '2-digit', day: '2-digit' }).format(new Date())")
    shown = item(dlg, page, "Payment date").locator("input").first.input_value()
    check("payment date defaults to today in Taipei (VM)", shown == today, (shown, today))
    fill(dlg, page, "Amount", "100")
    fill(dlg, page, "Note", "UI partial payment")
    check("dialog shows the outstanding after this entry", "Outstanding after this entry" in dlg.inner_text())
    snap(page, "accounting-payment")
    dlg.get_by_role("button", name="Record payment").click()
    check("payment recorded", message(page, "Payment recorded against the selected installment and party"))
    page.wait_for_timeout(800)
    ced = acc_row(page, "Cedant")
    text = ced.inner_text()
    check("cedant row: Paid 100.00, Partial payment", "100.00" in text and "Partial payment" in text and ced.locator("td").nth(6).inner_text() != outstanding_before, text)

    ced.get_by_role("button", name="Record payment").click()
    dlg = page.locator(".review-dialog").filter(has_text="Record partial payment")
    dlg.wait_for()
    hist = dlg.locator(".repeat-row")
    check("payment history lists the payment with a Reverse button", hist.count() == 1 and "Payment" in hist.first.inner_text() and hist.first.get_by_role("button", name="Reverse").is_visible())
    hist.first.get_by_role("button", name="Reverse").click()
    confirm_box(page, "Create reversal")
    check("reversal created", message(page, "Reversal entry created"))
    page.wait_for_timeout(800)
    ced = acc_row(page, "Cedant")
    check("after reversal: no longer partial, outstanding back to the original", "Partial payment" not in ced.inner_text() and ced.locator("td").nth(6).inner_text() == outstanding_before,
          (ced.inner_text(), outstanding_before))
    ced.get_by_role("button", name="Record payment").click()
    dlg = page.locator(".review-dialog").filter(has_text="Record partial payment")
    dlg.wait_for()
    hist = dlg.locator(".repeat-row")
    check("history keeps the payment and the reversal; the reversed payment has no Reverse button", hist.count() == 2 and "Reversal" in hist.nth(1).inner_text()
          and dlg.get_by_role("button", name="Reverse").count() == 0, dlg.inner_text()[:300])
    snap(page, "accounting-history")
    dlg.get_by_role("button", name="Cancel").click()
    logout(page)

    login(page, "ui.admin")
    nav(page, "Accounting")
    page.locator(".table-card .el-table__row").first.wait_for()
    acc_row(page, "Cedant").locator(".table-action", has_text="TWPAR2603001").click()
    page.locator(".case-detail-tabs").wait_for()
    page.wait_for_timeout(800)
    active = page.locator(".case-detail-tabs .el-tabs__item.is-active").inner_text().strip()
    check("admin: TW Ref in the ledger opens the case on the SOA tab", page.url.endswith("/cases") and "SOA" in active, (page.url, active))
    snap(page, "accounting-open-case")
    logout(page)


with sync_playwright() as p:
    browser = p.chromium.launch()
    page = browser.new_page(viewport={"width": 1440, "height": 1000})
    page.set_default_timeout(15000)
    page.on("console", lambda m: m.type == "error" and console_errors.append(m.text))
    page.on("pageerror", lambda e: console_errors.append("pageerror: " + str(e)))
    try:
        {"A": phase_a, "B": phase_b, "C": phase_c, "D": phase_d}[PHASE](page)
    except Exception as exc:  # noqa: BLE001 - 任何例外都記成失敗並留下截圖
        check(f"phase {PHASE} ran to the end", False, repr(exc)[:400])
        snap(page, "error")
    check(f"phase {PHASE}: no JavaScript errors in the console", not console_errors, console_errors[:5])
    browser.close()

fails = [r for r in results if not r[1]]
print(f"\nphase {PHASE}: {len(results) - len(fails)}/{len(results)} passed")
sys.exit(1 if fails else 0)
