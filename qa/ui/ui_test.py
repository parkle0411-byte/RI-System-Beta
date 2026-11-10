"""
畫面測試（無頭 Chromium）。只在用完即丟的測試環境執行（scripts/run_ui_test.sh），資料全是合成的。

  python3 ui_test.py A   外框與各頁面；業務人員：新增草稿 → 補齊 → 文件 → Announce → 通知會計 → 批單
  python3 ui_test.py H   （案件此時是 Announced，另有一張批單 Draft）業務人員：下載 Cover Note／Debit Note／批單的 Word，檢查檔案內容
  python3 ui_test.py R   （執行腳本已跑過兩次提醒排程）業務人員：案件明細的 Reminders 分頁（Suppressed 紀錄、設定錯誤、信件預覽）
  python3 ui_test.py P1  （腳本已打開寄信）登入頁的 Forgot password? → 申請重設連結
  python3 ui_test.py P2  （腳本已從信件取出連結放在 out/reset-link.txt）打開連結 → 設定新密碼 → 用新密碼登入
  python3 ui_test.py B   （執行腳本已把案件設成 Confirmed）管理員：Renewal → Reverse → 修正 Reversed 案件；回收桶；MDM；FX；人員與帳號；Audit
  python3 ui_test.py C   Case Viewer 的權限範圍；強制改密碼
  python3 ui_test.py G   管理員：業績目標（新增、修改、停用、重新啟用）；Dashboard 顯示案件、目標與趨勢
  python3 ui_test.py F   管理員：Production Report 預覽 → 排除一家再保人 → 產生 → 下載 Excel → 關帳（部分確認）；下個月 → 產生 → 關帳（全部確認）→ SOA 出現保費交易
  python3 ui_test.py E   業務人員：Claim 分頁新增理賠、改準備金、記理賠付款（出險日、付款日期必填），SOA 出現理賠交易
  python3 ui_test.py D   （案件此時是 Announced）Finance Staff：Accounting 帳本、記付款、沖銷；管理員：從帳本開啟案件的 SOA 分頁
"""
import re
import time
import sys
from playwright.sync_api import sync_playwright, expect

BASE = "http://nginx"
PASSWORD = "Ui-Test-Pass-1"
PHASE = sys.argv[1] if len(sys.argv) > 1 else "A"
results, console_errors = [], []
API_TRACKING_SCRIPT = "(() => {\n  const pending = window.__riPendingApi = new Map();\n  const apiUrl = value => {\n    try {\n      const url = new URL(value instanceof Request ? value.url : String(value), location.href);\n      return url.origin === location.origin && url.pathname.startsWith('/api/') ? url.href : null;\n    } catch { return null; }\n  };\n  const nativeFetch = window.fetch.bind(window);\n  window.fetch = (...args) => {\n    const url = apiUrl(args[0]), token = {};\n    if (url) pending.set(token, url);\n    return nativeFetch(...args).then(response => {\n      if (url) {\n        try { response.clone().arrayBuffer().then(() => pending.delete(token), () => pending.delete(token)); }\n        catch { pending.delete(token); }\n      }\n      return response;\n    }, error => { pending.delete(token); throw error; });\n  };\n  const nativeOpen = XMLHttpRequest.prototype.open;\n  const nativeSend = XMLHttpRequest.prototype.send;\n  XMLHttpRequest.prototype.open = function(method, url, ...rest) {\n    this.__riApiUrl = apiUrl(url);\n    return nativeOpen.call(this, method, url, ...rest);\n  };\n  XMLHttpRequest.prototype.send = function(...args) {\n    const token = {};\n    if (this.__riApiUrl) {\n      pending.set(token, this.__riApiUrl);\n      this.addEventListener('loadend', () => pending.delete(token), { once: true });\n    }\n    try { return nativeSend.apply(this, args); }\n    catch (error) { pending.delete(token); throw error; }\n  };\n})();\n"
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


def structure_card(page):
    """2026-10-16 起 Reinsurance Type 與 Class 在表單最上方同一張卡片，兩項都選了才顯示後續區塊。"""
    return page.locator('[data-testid="reinsurance-structure-section"]')


def choose_structure_class(page, structure="Quota Share", klass="Property"):
    card = structure_card(page)
    pick(card, page, "Reinsurance Type", structure)
    pick(card, page, "Insurance Type", klass)
    section(page, "Risk Details").wait_for()
    page.wait_for_timeout(300)


def info(page, name):
    """2026-10-16 起 Property 的 Occupation & Construction／Breakdown of Sum Insured／Loss Record／Special Agreement 合併成一張 Information 卡片。
    name：occupation、sumInsured、loss、specialAgreement"""
    return page.locator(f'[data-testid="property-information"] .information-section[data-section="{name}"]')


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


def wait_api_idle(page):
    # Drain application requests before changing identity; ignore preview iframe resources.
    deadline = time.monotonic() + 30
    quiet_since = None
    while time.monotonic() < deadline:
        page.wait_for_timeout(100)
        pending = page.evaluate("Array.from(window.__riPendingApi?.values() || [])")
        if pending:
            quiet_since = None
        elif quiet_since is None:
            quiet_since = time.monotonic()
        elif time.monotonic() - quiet_since >= .6:
            return
    raise TimeoutError("Application requests did not finish before the session transition: " + repr(pending))


def goto(page, url):
    # Full document navigation can discard request completion events from the old
    # page. Drain its API work first, then wait for the new document's startup calls.
    wait_api_idle(page)
    page.goto(url)
    wait_api_idle(page)


def login(page, username):
    goto(page, BASE + "/login")
    page.get_by_label("Username").fill(username)
    page.get_by_label("Password").fill(PASSWORD)
    page.get_by_role("button", name="Sign in").click()
    page.wait_for_selector(".app-shell", timeout=15000)
    wait_api_idle(page)
    console_errors.clear()  # 登入前檢查登入狀態的 401 是預期的


def logout(page):
    # Leaving the editor flushes delayed draft saves before invalidating its session.
    # Keep console checks intact: no application requests should outlive logout.
    page.locator(".nav-item", has_text="Dashboard").click()
    page.wait_for_url(BASE + "/dashboard")
    wait_api_idle(page)
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
    page.locator(".rdash").wait_for()
    check("admin lands on the first navigation entry (Dashboard)", page.url.endswith("/dashboard") and page.get_by_text("Total Bound YTD").is_visible(), page.url)
    labels = page.locator(".nav-item span:not(.nav-phase)").all_inner_texts()
    check("sidebar shows unified Master Data Management for an admin", labels == ["Dashboard", "Account List", "Legacy Data (Old Register)", "Master Data Management", "Personnel & Accounts", "Production Report", "Accounting", "FX Rates", "Draft Recycle Bin", "System Reference Data", "Audit Log"], labels)
    for label, marker in [("Account List", "All cases"), ("Master Data Management", "Reinsurers ("), ("Personnel & Accounts", "Personnel roster"),
                          ("FX Rates", "Official monthly rates"), ("Draft Recycle Bin", "Retained Drafts"), ("Audit Log", "Audit events"),
                          ("Production Report", "Versioned monthly close"), ("Accounting", "All Accounts (")]:
        nav(page, label)
        check(f"{label} page loads", page.get_by_text(marker).first.is_visible())
    logout(page)

    # ---------------- 業務人員：新增草稿 ----------------
    login(page, "ui.sales")
    labels = page.locator(".nav-item span:not(.nav-phase)").all_inner_texts()
    check("sales sees Dashboard, Account List, MDM, Production, Accounting (read-only, 2026-09-27), FX", labels == ["Dashboard", "Account List", "Legacy Data (Old Register)", "Master Data Management", "Production Report", "Accounting", "FX Rates"], labels)
    nav(page, "Account List")
    page.get_by_role("button", name="+ New case").click()
    page.locator(".case-form").wait_for()
    page.wait_for_timeout(800)
    # 2026-10-16「Reinsurance Type 與 Class 同區塊先選」：一開始只有 Structure 與 Class，兩項都選了才出現其他欄位與 Save draft
    check("new case: header 'Account', only Reinsurance Type and Class shown, Save draft hidden until both are chosen",
          header_title(page) == "Account" and page.locator(".page-header button", has_text="Cancel").is_visible()
          and item(structure_card(page), page, "Reinsurance Type").is_visible() and item(structure_card(page), page, "Insurance Type").is_visible()
          and page.locator(".case-form .el-collapse-item").count() == 0 and item(page, page, "Case Owner").count() == 0
          and page.locator(".page-header button", has_text="Save draft").count() == 0 and page.locator(".form-actions button", has_text="Save draft").count() == 0)
    snap(page, "new-case-structure-class")
    pick(structure_card(page), page, "Reinsurance Type", "Quota Share")
    check("Structure alone does not reveal the rest of the form", page.locator(".case-form .el-collapse-item").count() == 0)
    pick(structure_card(page), page, "Insurance Type", "Property")
    section(page, "Risk Details").wait_for()
    page.wait_for_timeout(500)
    check("after Structure and Class: Risk Details, Save draft in the header, Review & confirm / Save draft at the bottom",
          page.locator(".page-header button", has_text="Save draft").is_visible()
          and page.locator(".form-actions button", has_text="Review & confirm").is_visible() and page.locator(".form-actions button", has_text="Save draft").is_visible())
    titles = [t.strip() for t in page.locator(".case-form .el-collapse-item__header").all_inner_texts()]
    # 2026-10-30 起 Reinsurer Premium 併入 Schedule of Security 的每家再保人卡片，不再是獨立區塊
    want = ["Risk Details", "Schedule of Security", "Terms & Conditions", "Information", "Cedant Premium", "Performance Split", "Reinsurance Conditions"]
    check("Property sections in order, Information merged (2026-10-16), Reinsurer Premium inside Schedule of Security (2026-10-30)",
          [w for t in titles for w in want if t == w or t.startswith(w + " ")] == want
          and not any(t in titles for t in ("Occupation & Construction", "Breakdown of Sum Insured", "Loss Record", "Special Agreement"))
          and not any(t.startswith("Reinsurer Premium") for t in titles), titles)
    owner = selected_label(page, page, "Case Owner")
    check("case owner defaults to the signed-in person", owner == "UI Sales", owner)
    fill(page, page, "Original Insured (EN)", "UI Test Insured Ltd")
    # 2026-10-10 起存檔就要有 Loss Record 的 advised date 與 Past year(s)（2026-10-16 起在 Information 卡片內）
    loss = info(page, "loss")
    date(loss, page, "Loss record advised by broker on", "2026-02-01")
    fill(loss, page, "Past Year(s)", "5")
    page.keyboard.press("Tab")
    # 2026-10-23 草稿自動儲存：人工填寫後離開欄位就自動存檔，按鈕從 Save draft 變成 Save changes
    page.get_by_text("Draft saved automatically").first.wait_for(timeout=10000)
    check("incomplete Draft is saved automatically after leaving a field (2026-10-23)", True)
    check("after the automatic save the buttons read Save changes (no Save draft)",
          page.locator(".page-header button", has_text="Save changes").is_visible() and page.locator(".form-actions button", has_text="Save changes").is_visible()
          and page.locator(".page-header button", has_text="Save draft").count() == 0, page.locator(".page-header button").all_inner_texts())
    page.locator(".page-header button", has_text="Cancel").click()
    page.locator(".case-table").wait_for()
    page.locator(".insured-preview-link", has_text="UI Test Insured Ltd").first.wait_for()
    check("the new Draft is listed", page.locator(".insured-preview-link", has_text="UI Test Insured Ltd").count() == 1)
    snap(page, "list-after-draft")

    # ---------------- 補齊內容 ----------------
    open_case(page, "UI Test Insured Ltd")
    check("case detail: header shows 'Draft · not assigned'", header_title(page) == "Draft · not assigned", header_title(page))
    page.locator(".page-header button", has_text="Edit draft").click()
    page.locator(".case-form").wait_for()
    page.wait_for_timeout(800)
    # 既有案件沿用已存的 Structure 與 Class，直接顯示後續內容（2026-10-16）
    check("editing the Draft: saved Structure and Class kept, details shown directly",
          selected_label(structure_card(page), page, "Reinsurance Type") == "Quota Share"
          and selected_label(structure_card(page), page, "Insurance Type").startswith("Property") and section(page, "Risk Details").is_visible(),
          (selected_label(structure_card(page), page, "Reinsurance Type"), selected_label(structure_card(page), page, "Insurance Type")))
    risk = section(page, "Risk Details")
    pick(risk, page, "Account Executive", "UI AE One")
    pick(risk, page, "Currency", "USD")
    pick(risk, page, "New / Renew", "New")
    item(risk, page, "Type").locator("input, textarea").first.fill("Fire")
    pick(risk, page, "Reinsured", "UI Cedant Insurance")
    fill(risk, page, "Original Insured (CN)", "測試被保險人有限公司")   # 2026-10-23 起 Review／Announce 必填
    date(risk, page, "Effective Date", "2026-03-01")
    date(risk, page, "Expiration Date", "2027-03-01")
    risk.locator(".situation-row input").nth(0).fill("1 Test Road")
    risk.locator(".situation-row input").nth(1).fill("100")
    type_text = item(risk, page, "Type").inner_text()
    check("Type shows the locked structure suffix", "Facultative Reinsurance" in type_text, type_text)

    security = section(page, "Schedule of Security")
    security.get_by_role("button", name="+ Add reinsurer").click()
    cards = security.locator(".repeat-card")
    pick(cards.nth(0), page, "Reinsurer", "UI Re Alpha")
    fill(cards.nth(0), page, "Order Hereon (%)", "60")
    pick(cards.nth(1), page, "Reinsurer", "UI Re Beta (Facility)")
    fill(cards.nth(1), page, "Order Hereon (%)", "40")
    # 2026-10-16 92 項會計規則：每家普通再保人的付款天數要各自填寫，沒有繼承；2026-10-23 起新增的再保人預設 90、可修改
    check("each new reinsurer row has its own Payment Terms (Days), defaulting to 90 (2026-10-23)",
          all(item(cards.nth(i), page, "Payment Terms (Days)").locator("input").first.input_value() == "90" for i in (0, 1)),
          [item(cards.nth(i), page, "Payment Terms (Days)").locator("input").first.input_value() for i in (0, 1)])
    fill(cards.nth(0), page, "Payment Terms (Days)", "45")
    fill(cards.nth(1), page, "Payment Terms (Days)", "60")

    terms = section(page, "Terms & Conditions")
    fill(terms, page, "Limit of Liability", "1000000")
    fill(terms, page, "Deductibles", "10% of loss")
    fill(terms, page, "Original Conditions", "As original")
    occ = info(page, "occupation")
    fill(occ, page, "Occupation", "Office")
    # 2026-10-28 Property Construction 改為複選固定類別（A2／A1／B／C／D Class）
    pick(occ, page, "Construction", "A1 Class")
    sums = info(page, "sumInsured")
    sums.locator(".sum-row input").nth(0).fill("Building")
    sums.locator(".sum-row input").nth(1).fill("1000000")
    loss = info(page, "loss")
    date(loss, page, "Loss record advised by broker on", "2026-02-01")
    fill(loss, page, "Past Year(s)", "5")
    cedant = section(page, "Cedant Premium")
    fill(cedant, page, "100% Premium", "1000")
    fill(cedant, page, "Cedant Collection Days", "30")   # 2026-10-16 起由「Payment Terms (Days)」更名
    fill(cedant, page, "Ceding Commission (%)", "10")
    fill(cedant, page, "Tax (%)", "0")
    rp = section(page, "Schedule of Security").locator(".repeat-card")
    for index, premium in ((0, "600"), (1, "400")):
        box = rp.nth(index).locator(".el-form-item").filter(has=page.locator(".el-form-item__label", has_text=re.compile(r"^\s*Premium \(")))
        box.first.locator("input").first.fill(premium); box.first.locator("input").first.press("Tab")
        fill(rp.nth(index), page, "Deductions (%)", "5")
        fill(rp.nth(index), page, "Tax (%)", "0")
    conditions = section(page, "Reinsurance Conditions").inner_text()
    check("fixed clause of the selected reinsurer is added (LMA5390, Fixed)", "LMA5390" in conditions and "Fixed" in conditions and "LMA3333" in conditions, conditions[:300])
    snap(page, "form-filled")

    # 2026-10-28 Placing Slip 規則：Property QS 的 Basis of Valuation 必填；2026-10-29 起漏填時欄位要變紅框
    page.locator(".form-actions button", has_text="Review & confirm").click()
    check("Review blocked: one required field missing", message(page, "Please complete 1 required field before Review & confirm."))
    basis = item(terms, page, "Basis of Valuation")
    check("the missing Basis of Valuation is outlined in red", "is-required-error" in (basis.get_attribute("class") or ""), basis.get_attribute("class"))
    # Let the existing Draft autosave finish before selecting the missing field.
    # This keeps a slow test server response from replacing the form mid-click.
    page.wait_for_timeout(800)
    wait_api_idle(page)
    pick(terms, page, "Basis of Valuation", "Replacement Value")
    expect(basis).to_contain_text("Replacement Value")
    expect(basis).not_to_have_class(re.compile(r".*\bis-required-error\b.*"))
    check("after choosing it the red outline is gone", "is-required-error" not in (basis.get_attribute("class") or ""))
    page.locator(".form-actions button", has_text="Review & confirm").click()
    try:
        page.locator(".review-dialog .review-heading", has_text="Review case details").wait_for()
    except Exception:
        missing = [x.locator(".el-form-item__label").first.inner_text() for x in page.locator(".is-required-error").all() if x.locator(".el-form-item__label").count()]
        check("Review & confirm: no required field missing", False, (page.locator(".el-message").all_inner_texts()[:2], missing))
        raise
    check("Review & confirm opens the read-only review", page.locator(".review-dialog").filter(has_text="Total order: 100%").count() >= 1)
    snap(page, "review-dialog")
    page.locator(".review-dialog .el-dialog__footer button", has_text="Save changes").click()
    check("saving the edit returns to the case detail", message(page, "Draft updated"))
    page.locator(".case-detail-tabs").wait_for()
    page.wait_for_timeout(500)
    overview = page.locator(".overview-grid").inner_text()
    # 2026-10-23 起草稿自動儲存，每次存檔版本都會增加，所以只確認有版本號
    check("overview: saved version shown and computed amounts (unified ledger rounding: brokerage 406.00)",
          re.search(r"version \d+", overview) is not None and "406.00" in overview and "1,000.00" in overview, overview[:400])
    check("overview: Avg. Rate", "0.100000%" in overview)
    snap(page, "overview")

    # ---------------- 文件與 Announce ----------------
    page.locator(".case-detail-tabs .el-tabs__item", has_text="Documentation").click()
    page.wait_for_timeout(800)
    docs = page.locator(".documents-grid")
    check("documents: not ready before any evidence", "Not ready to Announce" in docs.inner_text())
    check("documents: Cover Note waits for the TW Reference (disabled while Draft)", page.locator(".generated-document-actions button").first.is_disabled())
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
        upload.get_by_role("button", name="Upload Evidence").click()
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
    check("Review & Announce moved out of Documentation", page.get_by_role("button", name="Review & Announce").count() == 0)
    page.locator(".case-detail-tabs .el-tabs__item", has_text="Overview").click()
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

    # ---------------- Claim 分頁（已 Announce：可以新增理賠；實際新增在階段 E） ----------------
    page.locator(".case-detail-tabs .el-tabs__item", has_text="Claim").click()
    page.wait_for_timeout(600)
    check("Claim tab loads: root TW Reference, Add claim form, no claims yet", page.get_by_text("Root TW Reference").is_visible()
          and page.get_by_role("button", name="Add claim").is_visible() and page.get_by_text("No claims recorded").is_visible())

    # ---------------- 批單 ----------------
    page.locator(".case-detail-tabs .el-tabs__item", has_text="Endorsements").click()
    page.wait_for_timeout(800)
    check("endorsement chain lists the announced root", "TWPAR2603001" in page.locator(".workflow-table").inner_text())
    page.get_by_role("button", name="Create endorsement").click()
    confirm_box(page, "Create draft")
    check("endorsement Draft created", message(page, "Endorsement Draft created"))
    page.locator(".endorsement-editor").wait_for()
    check("endorsement form: header 'New endorsement' and risk fields locked", header_title(page) == "New endorsement"
          and page.locator("fieldset.case-fieldset").first.evaluate("el => el.disabled") is True, header_title(page))
    # 2026-10-21：批單沿用原案件的 Cedant 收款天數與各再保人付款天數
    endo_days = (item(section(page, "Cedant Premium"), page, "Cedant Collection Days").locator("input").first.input_value(),
                 [item(c, page, "Payment Terms (Days)").locator("input").first.input_value() for c in section(page, "Schedule of Security").locator(".repeat-card").all()])
    check("endorsement inherits Cedant Collection Days and each reinsurer's Payment Terms (Days) from the source case",
          endo_days == ("30", ["45", "60"]), endo_days)
    security = section(page, "Schedule of Security")
    ref_inputs = security.locator('.el-form-item').filter(has=page.locator('.el-form-item__label', has_text='Reinsurer Ref.')).locator('input')
    if not ref_inputs.first.is_visible(): security.locator('.el-collapse-item__header').click()
    check("endorsement Reinsurer Ref. fields are editable", all(not ref_inputs.nth(i).is_disabled() for i in range(ref_inputs.count())))
    for i in range(ref_inputs.count()):
        ref_inputs.nth(i).fill('UI-ENDO-REF-' + str(i + 1)); ref_inputs.nth(i).press('Tab')
    page.wait_for_timeout(1400); wait_api_idle(page)
    from urllib.parse import urlparse, parse_qs
    uid = parse_qs(urlparse(page.url).query)['draft'][0]
    response = page.context.request.get(BASE + '/api/cases?caseUid=' + uid)
    payload = response.json()['case']['payload']
    check("endorsement reference autosave persists each reinsurer independently", [r['settlementRef'] for r in payload['reinsurers']] == ['UI-ENDO-REF-1', 'UI-ENDO-REF-2'])
    page.reload(); page.locator('.endorsement-editor').wait_for(); page.wait_for_timeout(500)
    security = section(page, "Schedule of Security")
    ref_inputs = security.locator('.el-form-item').filter(has=page.locator('.el-form-item__label', has_text='Reinsurer Ref.')).locator('input')
    if not ref_inputs.first.is_visible(): security.locator('.el-collapse-item__header').click()
    check("endorsement references survive reload", [ref_inputs.nth(i).input_value() for i in range(ref_inputs.count())] == ['UI-ENDO-REF-1', 'UI-ENDO-REF-2'])
    check("editing references retains source reinsurer and share locks", all(item(card, page, label).locator('input').first.is_disabled() for card in security.locator('.repeat-card').all() for label in ['Reinsurer', 'Order Hereon (%)', 'Foreign RI Broker', 'Payment Terms (Days)']))
    snap(page, "endorsement-reference-editable")
    snap(page, "endorsement-form")
    page.locator(".page-header button", has_text="Cancel").click()
    page.locator(".case-table").wait_for()
    check("endorsement Drafts are not top-level rows in the list", page.locator(".case-table .el-table__row").count() == 1)
    logout(page)


def phase_b0(page):
    """已確認的案件還有未完成的批單 Draft：不能續保，畫面要說明原因（2026-10-14）。"""
    login(page, "ui.admin")
    open_case(page, "UI Test Insured Ltd")
    check("open endorsement Draft: no Create renewal button", page.locator(".page-header button", has_text="Create renewal").count() == 0)
    notice = page.locator(".renewal-notice")
    check("the screen explains why renewal is not available", notice.is_visible() and "newer endorsement" in notice.inner_text().lower(), notice.all_inner_texts())
    snap(page, "renewal-notice")
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
    policy_from = item(section(page, "Risk Details"), page, "Effective Date").locator("input").first.input_value()
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
    choose_structure_class(page)   # 2026-10-16 起先選 Structure 與 Class 才出現其他欄位
    fill(page, page, "Original Insured (EN)", "UI Recycle Me")
    loss = info(page, "loss")   # 存檔就需要 Loss Record 的 advised date 與 Past year(s)（Property 的 Information 卡片內）
    date(loss, page, "Loss record advised by broker on", "2026-02-01")
    fill(loss, page, "Past Year(s)", "5")
    page.keyboard.press("Tab")
    page.get_by_text("Draft saved automatically").first.wait_for(timeout=10000)   # 2026-10-23 草稿自動儲存
    check("recycle test draft saved automatically", True)
    page.locator(".page-header button", has_text="Cancel").click()
    page.locator(".case-table").wait_for()
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
    nav(page, "Master Data Management")
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
    check("Case Viewer sees only Dashboard and Account List (no Insured Master, owner 2026-10-29)", labels == ["Dashboard", "Account List"], labels)
    goto(page, f"{BASE}/insured")
    page.wait_for_timeout(1200)
    check("Case Viewer cannot open the Insured Master page directly", "/insured" not in page.url and page.get_by_text("Chinese names, former names and linked policies").count() == 0, page.url)
    nav(page, "Account List")
    check("Case Viewer sees no other people's cases and no + New case", page.locator(".case-table .el-table__row").count() == 0
          and page.get_by_role("button", name="+ New case").count() == 0)
    goto(page, BASE + "/system-status")
    page.wait_for_timeout(800)
    status = page.request.get(BASE + "/health/")
    check("Case Viewer cannot open System status (page redirected, /health/ 403)", "/system-status" not in page.url
          and page.locator(".el-descriptions").count() == 0 and status.status == 403 and message(page, "You do not have permission"), (page.url, status.status))
    logout(page)
    status = page.request.get(BASE + "/health/")
    check("anonymous /health/ -> 401", status.status == 401, status.status)
    page.wait_for_timeout(800)
    check("e-mail not enabled: the login page shows no 'Forgot password?' link", page.get_by_text("Forgot password?").count() == 0)

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


def acc_row(page, tx):
    """Accounting 清單裡某一筆交易（交易編號的開頭，例如 TWPAR2603001-R1-T1）。"""
    return page.locator(".table-card .el-table__row").filter(has_text=tx).first


def row_cells(page, tx):
    return acc_row(page, tx).inner_text().replace("\n", " ").replace("\t", " ")


def phase_d(page):
    """Finance-reviewed accounts, full cash, whole reversal and separated Brokerage."""
    login(page, "ui.finance")
    nav(page, "Accounting")
    page.get_by_test_id("accounting-table").locator(".el-table__row").first.wait_for()
    for name in ("All Accounts", "Unreconciled Accounts", "Reconciled Accounts", "Settled/Closed", "Brokerage"):
        check("Accounting tab: " + name, page.get_by_role("tab", name=name, exact=True).is_visible())
    check("no cash T3 in unreconciled accounts", not page.get_by_test_id("accounting-table").locator(".el-table__row").filter(has_text="-T3").count())
    filters = page.locator(".table-card").first
    fill(filters, page, "TW Ref", "nothing-matches")
    check("TW Ref filter finds no unrelated rows", page.get_by_text("No matching accounts. Premium accounts are created at Announce.").is_visible())
    fill(filters, page, "TW Ref", "TWPAR2603001")
    r = acc_row(page, "TWPAR2603001-R1-T1")
    check("unreviewed T1 has review action instead of cash action", r.get_by_role("button", name="Mark reviewed", exact=True).is_visible() and r.get_by_role("button", name="Record receipt / payment", exact=True).count() == 0)
    r.get_by_role("button", name="Mark reviewed", exact=True).click()
    dlg = page.get_by_role("dialog", name="Finance account review", exact=True)
    fill(dlg,page,"Review reference","UI-FINANCE-REVIEW")
    dlg.get_by_role("button",name="Mark reviewed",exact=True).click()
    dlg.wait_for(state="hidden")
    page.get_by_role("tab",name="Reconciled Accounts",exact=True).click()
    r=acc_row(page,"TWPAR2603001-R1-T1")
    check("Finance review moves account into reviewed tab", r.get_by_role("button",name="Record receipt / payment",exact=True).is_visible())
    r.get_by_role("button",name="Record receipt / payment",exact=True).click()
    dlg=page.get_by_role("dialog",name="Record receipts / payments",exact=True)
    fill(dlg,page,"Accounting Dept. Ref.","UI-REMIT-1")
    ar=dlg.locator('.el-table__body-wrapper tbody tr').first
    check('Cash Amount prefills the outstanding balance',float(ar.locator('.el-input-number input').first.input_value().replace(',',''))==540)
    ar.locator('.el-input-number input').first.fill('100');ar.locator('.el-input-number input').first.press('Tab')
    dlg.get_by_role("button",name="Record registrations",exact=True).click()
    expect(ar).to_contain_text('Recorded')
    dlg.get_by_role('button',name='Close',exact=True).click();dlg.wait_for(state='hidden')
    r=acc_row(page,"TWPAR2603001-R1-T1")
    check('partially received premium stays Open', 'Open' in r.inner_text())
    r.get_by_role('button',name='Record receipt / payment',exact=True).click()
    dlg=page.get_by_role('dialog',name='Record receipts / payments',exact=True)
    fill(dlg,page,'Accounting Dept. Ref.','UI-REMIT-REMAINDER')
    check('remaining Cash Amount is prefilled',float(dlg.locator('.el-input-number input').first.input_value().replace(',',''))==440)
    dlg.get_by_role('button',name='Record registrations',exact=True).click()
    expect(dlg.locator('.el-table__body-wrapper tbody tr').first).to_contain_text('Recorded')
    dlg.get_by_role('button',name='Close',exact=True).click();dlg.wait_for(state='hidden')
    page.get_by_role("tab",name="Settled/Closed",exact=True).click()
    bank=acc_row(page,"TWPAR2603001-R1-T1")
    check('Settled/Closed shows fully settled T1', 'Settled' in bank.inner_text())
    bank.get_by_role('button',name='History',exact=True).click()
    hist=page.get_by_role('dialog',name='Account history',exact=True)
    hist.get_by_role('button',name='View registration',exact=True).first.click()
    dlg=page.get_by_role('dialog',name='Receipt / payment registration details',exact=True)
    check('settled registration can be reversed before downstream payment',dlg.get_by_role('button',name='Reverse entire registration',exact=True).is_visible())
    check('direct payment amount edit is removed',page.get_by_role('button',name='Edit amount',exact=True).count()==0)
    dlg.get_by_role('button',name='Reverse entire registration',exact=True).click();box=page.locator('.el-message-box');box.locator('input').fill('UI correction');box.get_by_role('button',name='OK',exact=True).click();box.wait_for(state='hidden')
    check('whole reversal preserves registration with replacement entry',dlg.get_by_role('button',name='Re-register',exact=True).is_visible())
    dlg.get_by_role('button',name='Close',exact=True).click()
    hist.get_by_role('button',name='Close this dialog',exact=True).click()
    page.get_by_role('tab',name='Reconciled Accounts',exact=True).click()
    check('reversed receipt reopens balance and retains Finance review','Open' in row_cells(page,'TWPAR2603001-R1-T1'))
    page.get_by_role('tab',name='Brokerage',exact=True).click()
    check('Brokerage has independent dependency details',page.get_by_role('button',name='Brokerage settlement details',exact=True).count()>0)
    snap(page,'accounting-brokerage')
    nav(page,'Dashboard');held=[];page.route('**/api/accounting?view=list',lambda route:held.append(route));nav(page,'Accounting')
    banner=page.get_by_test_id('accounting-refreshing');banner.wait_for(timeout=8000)
    check('cached list remains read-only during background update',banner.is_visible() and page.get_by_role('button',name='Mark reviewed',exact=True).count()==0)
    for route in held:route.continue_()
    page.unroute('**/api/accounting?view=list');banner.wait_for(state='hidden',timeout=15000)
    logout(page);login(page,'ui.admin');nav(page,'Accounting')
    acc_row(page,'TWPAR2603001-R2-T1').locator('.table-action').first.click();page.locator('.case-detail-tabs').wait_for();page.wait_for_timeout(400)
    check('account identifier opens case SoA', '/cases' in page.url and 'soa' in page.locator('.case-detail-tabs .el-tabs__item.is-active').inner_text().lower())
    logout(page)


def phase_e(page):
    login(page, "ui.sales")
    open_case(page, "UI Test Insured Ltd", ref="TWPAR2603001")
    page.locator(".case-detail-tabs .el-tabs__item", has_text="Claim").click()
    page.get_by_text("Root TW Reference").wait_for()
    # 2026-10-16 92 項會計規則：賠款按出險日適用的保單／批單比例分攤（原本顯示「N reinsurer line(s)」的分攤來源）
    kv = page.locator(".overview-kv").first.inner_text()
    check("Claim tab: root TW Reference and allocation rule (Date of Loss, source kept per obligation) shown", "TWPAR2603001" in kv
          and "effective on the Date of Loss" in kv and "source is retained with each obligation" in kv, kv)
    check("no claims yet", page.get_by_text("No claims recorded").is_visible())
    add = page.locator(".overview-card").filter(has=page.locator("h2", has_text="Add claim"))
    check("VM: Date of Loss marked required, help text updated", item(add, page, "Date of Loss").locator(".is-required, .el-form-item__label").count() >= 1
          and add.get_by_text("Date of Loss is required").is_visible())
    fill(add, page, "Claim / Loss No.", "UI-LOSS-01")
    add.get_by_role("button", name="Add claim").click()
    check("Date of Loss missing -> error from the server", message(page, "Enter the Date of Loss"))
    console_errors.clear()  # 上面故意送出不完整的資料，400 是預期的
    date(add, page, "Date of Loss", "2026-05-01")
    fill(add, page, "Outstanding Reserve", "5000")
    fill(add, page, "Cause of Loss", "UI test fire")
    add.get_by_role("button", name="Add claim").click()
    check("claim added", message(page, "Claim added"))
    page.wait_for_timeout(800)
    card = page.locator(".overview-card").filter(has_text="UI-LOSS-01")
    check("claim card: loss no., date, cause", card.count() == 1 and "2026-05-01 · UI test fire" in card.inner_text(), card.inner_text()[:200] if card.count() else "")
    reserve = card.locator(".el-input-number input").first
    page.wait_for_function("el => !el.disabled", arg=reserve.element_handle(), timeout=10000)
    # Element Plus 的 el-input-number 只在建立時設定 aria-disabled（卡片是在儲存中建立的，會停在 "true"），
    # 實際的 disabled 已是 false：用 force 略過 Playwright 對 aria-disabled 的判斷
    reserve.fill("6000.555", force=True)
    reserve.press("Tab")
    check("reserve updated", message(page, "Outstanding reserve updated"))
    page.wait_for_timeout(600)
    check("reserve shown rounded to cents (VM)", card.locator(".el-input-number input").first.input_value() in ("6000.56", "6,000.56"), card.locator(".el-input-number input").first.input_value())

    card.get_by_role("button", name="Add claim obligation").click()   # 2026-10-08 起理賠只建立應收應付，現金在 Accounting 登錄
    dlg = page.locator(".review-dialog").filter(has_text="Record claim obligation")
    dlg.wait_for()
    fill(dlg, page, "Amount", "1000")
    dlg.get_by_role("button", name="Record obligation").click()
    check("obligation date missing -> error from the server (VM: required)", message(page, "Enter the payment date"))
    console_errors.clear()  # 上面故意送出不完整的資料，400 是預期的
    # 對話框裡不能按 Escape（會關掉整個對話框）：輸入後按 Enter，再點對話框標題收起日期選單
    field = item(dlg, page, "Obligation date").locator(".el-date-editor input").first
    field.fill("2026-07-01")
    field.press("Enter")
    dlg.locator(".review-heading h2").click()
    fill(dlg, page, "Note", "first payment")
    snap(page, "claim-payment")
    dlg.get_by_role("button", name="Record obligation").click()
    check("claim obligation recorded", message(page, "Claim obligations saved; Accounting records receipts and payments separately"))
    page.wait_for_timeout(800)
    card = page.locator(".overview-card").filter(has_text="UI-LOSS-01")
    text = card.inner_text()
    check("obligations table and Cumulative claim obligations show 1,000.00", "1,000.00" in text and "first payment" in text and "2026-07-01" in text, text[:300])
    # 2026-10-16 92 項會計規則：賠款帳款到期日 = 建立帳款的台灣日期 + 15 日，不可修改
    import datetime as dt
    due = (dt.datetime.now(dt.timezone(dt.timedelta(hours=8))).date() + dt.timedelta(days=15)).isoformat()
    row = card.locator(".el-table__row").filter(has_text="first payment").first.inner_text()
    check("claim obligation due date fixed at creation (Taipei) + 15 days", due in row and "Due date (fixed)" in text, (due, row))
    snap(page, "claims")

    page.locator(".case-detail-tabs .el-tabs__item", has_text="SOA").click()
    page.wait_for_timeout(600)
    soa = page.locator(".overview-card").filter(has_text="Statement of Account").first.inner_text()
    check("SOA lists the claim transactions numbered from the TW Ref (VM fix; Alpha: 'undefined-')",
          "TWPAR2603001-C1-P1-R1-T1" in soa and "undefined" not in soa, soa[:400])
    logout(page)


def production_month(page, month_label):
    """月份選擇器（格式 MMM YYYY）：輸入後按 Enter，再按 Preview。"""
    field = page.locator("#production-month")
    field.fill(month_label)
    field.press("Enter")
    page.locator(".production-heading").click()
    page.get_by_role("button", name="Preview").click()
    page.wait_for_timeout(1200)


def month_label(offset=0):
    import datetime as dt
    today = dt.datetime.now(dt.timezone(dt.timedelta(hours=8))).date().replace(day=1)
    y, m = today.year + (today.month - 1 + offset) // 12, (today.month - 1 + offset) % 12 + 1
    return dt.date(y, m, 1).strftime("%b %Y"), f"{y:04d}-{m:02d}"


def phase_f(page):
    import zipfile
    login(page, "ui.admin")
    nav(page, "Production Report")
    # The fixture policy starts on 2026-03-01; the current rule attributes
    # original-policy performance to inception, not the Announce month.
    label, ym = "Mar 2026", "2026-03"
    next_label, next_ym = "Apr 2026", "2026-04"
    production_month(page, label)
    rows = page.locator(".production-table .el-table__body-wrapper .el-table__row").filter(has_text="TWPAR2603001")
    check(f"{ym} preview lists the case: one row per reinsurer", rows.count() == 2, rows.count())
    check("no missing FX warning (USD saved in phase B)", page.locator(".el-alert", has_text="exchange rate required").count() == 0)
    check("preview has the First Policy No column and shows the case's own number",
          page.locator(".production-table th", has_text="First Policy No").count() >= 1
          and "TWPAR2603001" in rows.first.locator("td").nth(17).inner_text(), rows.first.inner_text()[:300])
    snap(page, "production-preview")

    beta = rows.filter(has_text="UI Re Beta").first
    beta.get_by_role("button", name="Exclude R/I").click()
    box = page.locator(".el-message-box")
    box.wait_for()
    box.locator("input").fill("UI waiting for signed slip")
    box.get_by_role("button", name="Exclude").click()
    check("row deferred to the next month", message(page, f"Item deferred to {next_ym}"))
    page.wait_for_timeout(800)
    deferred = page.locator(".table-card", has=page.locator("h2", has_text="Excluded and deferred items"))
    check("excluded list shows the reinsurer, reason and target month", deferred.count() == 1 and "UI waiting for signed slip" in deferred.inner_text() and next_ym in deferred.inner_text())

    page.get_by_role("button", name="Generate Production Report").click()
    check("V1 generated", message(page, f"Production Report {ym} V1 generated"))
    page.wait_for_timeout(800)
    versions = page.locator(".table-card", has=page.locator("h2", has_text="Report versions"))
    with page.expect_download() as dl:
        versions.get_by_role("button", name="Download XLSX").first.click()
    path = "out/production-v1.xlsx"
    dl.value.save_as(path)
    check("download name Production_Report_<month>_V1.xlsx", dl.value.suggested_filename == f"Production_Report_{ym}_V1.xlsx", dl.value.suggested_filename)
    with zipfile.ZipFile(path) as z:
        sheet = z.read("xl/worksheets/sheet1.xml").decode()
        workbook = z.read("xl/workbook.xml").decode()
    check("xlsx: header row, the included reinsurer, not the deferred one, dates with slashes", "Original Insured" in sheet and "UI Re Alpha" in sheet
          and "UI Re Beta" not in sheet and "2026/03/01" in sheet and f"Production Report {ym}" in workbook, sheet[:200])
    check("xlsx: 18th column First Policy No has its header, the case's own number on the data rows, and the filter covers A:R",
          '<c r="R1"' in sheet and "First Policy No" in sheet and 'autoFilter ref="A1:R' in sheet
          and re.search(r'<c r="R2"[^>]*><is><t>TWPAR2603001</t>', sheet) is not None, sheet[-300:])

    versions.get_by_role("button", name="Close month").click()
    confirm_box(page, "Close month")
    check("month closed; the case is only partly confirmed (0 fully Confirmed)", message(page, f"Production Report {ym} closed · 0 case(s) fully Confirmed"))
    page.wait_for_timeout(800)
    check("closed banner shown, Generate hidden", page.locator(".el-alert", has_text=f"{ym} is closed").count() == 1
          and page.get_by_role("button", name="Generate Production Report").count() == 0)
    snap(page, "production-closed")

    production_month(page, next_label)
    rows = page.locator(".production-table .el-table__body-wrapper .el-table__row").filter(has_text="TWPAR2603001")
    check(f"{next_ym}: the deferred reinsurer appears", rows.count() == 1 and "UI Re Beta" in rows.first.inner_text(), rows.count())
    page.get_by_role("button", name="Generate Production Report").click()
    check("next month V1 generated", message(page, f"Production Report {next_ym} V1 generated"))
    page.wait_for_timeout(800)
    page.locator(".table-card", has=page.locator("h2", has_text="Report versions")).get_by_role("button", name="Close month").click()
    confirm_box(page, "Close month")
    check("next month closed; the case is now fully Confirmed", message(page, f"Production Report {next_ym} closed · 1 case(s) fully Confirmed"))
    page.wait_for_timeout(800)

    open_case(page, "UI Test Insured Ltd", ref="TWPAR2603001")
    check("case header shows Confirmed", "Confirmed" in page.locator(".page-header p").inner_text(), page.locator(".page-header p").inner_text())
    page.locator(".case-detail-tabs .el-tabs__item", has_text="SOA").click()
    page.wait_for_timeout(600)
    soa = page.locator(".overview-card").filter(has_text="Statement of Account").first.inner_text()
    check("SOA lists premium transactions (Leg 1-3) numbered from the TW Ref", "TWPAR2603001-R1-T1" in soa and "TWPAR2603001-R2-T1" in soa, soa[:400])
    snap(page, "soa-after-close")
    logout(page)


def phase_g(page):
    login(page, "ui.admin")
    nav(page, "Personnel & Accounts")
    page.locator(".mdm-tab", has_text="Annual target settings").click()
    page.wait_for_timeout(600)
    check("targets tab: VM text (Dashboard uses targets, Audit recorded)", page.get_by_text("Targets feed the Dashboard brokerage trend").is_visible()
          and page.get_by_text("every change is recorded in the Audit Log").is_visible())
    page.get_by_role("button", name="+ Monthly target").click()
    dlg = page.locator(".master-dialog").filter(has_text="dashboard target")
    dlg.wait_for()
    month_value = item(dlg, page, "Period").locator("input").first.input_value()
    import datetime as dt
    tpe = dt.datetime.now(dt.timezone(dt.timedelta(hours=8)))
    check("monthly target defaults to this month (Taipei)", month_value == tpe.strftime("%b %Y"), month_value)
    check("dialog text: snapshot and Audit Log event", "immutable snapshot and an Audit Log event" in dlg.inner_text())
    fill(dlg, page, "Target amount (TWD)", "500000")
    dlg.get_by_role("button", name="Add target").click()
    check("monthly target added", message(page, "Target added"))
    page.wait_for_timeout(600)
    row = page.locator(".table-card .el-table__row").filter(has_text=tpe.strftime("%Y-%m")).first
    check("target listed: Monthly, 500,000, Active, version 1", "Monthly" in row.inner_text() and "500,000" in row.inner_text() and "Active" in row.inner_text(), row.inner_text())
    row.get_by_role("button", name="Edit").click()
    dlg = page.locator(".master-dialog").filter(has_text="dashboard target")
    dlg.wait_for()
    fill(dlg, page, "Target amount (TWD)", "600000")
    dlg.get_by_role("button", name="Save changes").click()
    check("target updated", message(page, "Target updated"))
    page.wait_for_timeout(600)
    row = page.locator(".table-card .el-table__row").filter(has_text=tpe.strftime("%Y-%m")).first
    check("amount 600,000, version 2", "600,000" in row.inner_text() and "2" in row.locator("td").nth(4).inner_text(), row.inner_text())
    row.get_by_role("button", name="Deactivate").click()
    check("target deactivated", message(page, "Target deactivated"))
    page.wait_for_timeout(600)
    page.locator(".table-card .el-table__row").filter(has_text=tpe.strftime("%Y-%m")).first.get_by_role("button", name="Reactivate").click()
    check("target reactivated", message(page, "Target reactivated"))
    snap(page, "targets")

    nav(page, "Dashboard")
    page.locator(".rdash").wait_for()
    page.wait_for_timeout(1200)
    kpi = page.locator(".kpi", has_text="In-Force Policies").locator(".val").inner_text()
    check("Dashboard: In-Force Policies >= 1 (the Confirmed case from phase F)", kpi.isdigit() and int(kpi) >= 1, kpi)
    check("trend chart drawn with two bar series and target line", page.locator(".trend-svg polyline").count() == 1
          and page.locator(".trend-bar.prior").count() == tpe.month and page.locator(".trend-bar.current").count() == tpe.month
          and page.locator(".trend-point.target").count() == tpe.month)
    check("reinsurer mix lists the case's reinsurers", "UI Re Alpha" in page.locator(".card", has_text="Top Reinsurers").inner_text())
    fill_width = page.locator(".card", has_text="Top Reinsurers").locator(".mix-fill").first.bounding_box()["width"]
    track_width = page.locator(".card", has_text="Top Reinsurers").locator(".mix-track").first.bounding_box()["width"]
    check("VM fix: mix bars are filled (60% bar about 60% of the track)", 0.55 < fill_width / track_width < 0.65, (fill_width, track_width))
    year_select = page.get_by_test_id('dashboard-trend-year')
    year_select.click()
    options = page.locator('.el-select__popper[aria-hidden="false"] .el-select-dropdown__item')
    check('trend selector offers the latest five years', options.all_text_contents() == [str(tpe.year-i) for i in range(5)])
    options.filter(has_text=str(tpe.year-1)).click()
    page.wait_for_timeout(1800)
    check('historical year renders twelve pairs of bars', page.locator('.trend-bar.prior').count() == 12 and page.locator('.trend-bar.current').count() == 12)
    left=page.locator('.trend-bar.prior').first; right=page.locator('.trend-bar.current').first
    check('prior bar lies to the left of current bar', float(left.get_attribute('x')) + float(left.get_attribute('width')) < float(right.get_attribute('x')))
    check('year selection preserves other KPIs', page.locator('.kpi', has_text='In-Force Policies').locator('.val').inner_text() == kpi)
    year_select.click()
    page.locator('.el-select__popper[aria-hidden="false"] .el-select-dropdown__item').filter(has_text=str(tpe.year)).click()
    page.wait_for_timeout(1800)
    check('returning to current year restores current month count', page.locator('.trend-bar.current').count() == tpe.month)
    snap(page, "dashboard")
    goto(page, BASE + "/system-status")
    page.locator(".el-descriptions").wait_for()
    page.wait_for_timeout(800)
    check("System Administrator can open System status (backend and database OK)", page.locator(".el-descriptions .el-tag", has_text="正常").count() == 3,
          page.locator(".el-descriptions").inner_text())
    logout(page)


def phase_h(page):
    import io
    import zipfile
    login(page, "ui.sales")
    open_case(page, "UI Test Insured Ltd", ref="TWPAR2603001")
    page.locator(".case-detail-tabs .el-tabs__item", has_text="Documentation").click()
    page.wait_for_timeout(800)
    cards = page.locator(".generated-document-card")
    check("Announced case: Cover Note and Debit Note cards", cards.count() == 2 and "Cover Note" in cards.nth(0).inner_text() and "Debit Note" in cards.nth(1).inner_text())

    def download(card, button, expect_message):
        try:
            with page.expect_download(timeout=20000) as info:
                page.locator(".generated-document-card").filter(has_text=card).get_by_role("button", name=button).click()
        except Exception:  # noqa: BLE001 - 沒有下載時，把畫面上的提示一起報出來（多半是產生前的必填檢查）
            shown = page.locator(".el-message").all_inner_texts()
            raise AssertionError(f"{card}: no download; messages on screen: {shown}")
        d = info.value
        path = f"out/{d.suggested_filename}"
        d.save_as(path)
        ok = message(page, expect_message) if expect_message else True
        return d.suggested_filename, open(path, "rb").read(), ok

    def docx_text(data):
        with zipfile.ZipFile(io.BytesIO(data)) as z:
            xml = z.read("word/document.xml").decode("utf-8")
        return re.sub(r"<[^>]+>", "", xml)

    # 2026-10-27 一般 Property QS：Word 先存進 Case Documents 才下載；檔名 類型_Ref_Original Insured_台灣生成日期
    stamp = r"_UI Test Insured Ltd_\d{4}-\d{2}-\d{2}\.docx"
    # Placing Slip 規則（2026-10-28）下的 Cover Note 不另跳成功訊息，改看 Generated documents 清單
    name, data, ok = download("Cover Note", "Download Word (.docx)", None)
    text = docx_text(data)
    check("Cover Note Word: file name, saved to Case Documents (2026-10-27)", re.fullmatch("CoverNote_TWPAR2603001" + stamp, name) is not None and ok, name)
    check("Cover Note Word: contains the TW Reference and the insured", "TWPAR2603001" in text and "UI Test Insured Ltd" in text, text[:300])
    name, data, ok = download("Debit Note", "Download Word (.docx)", "Debit Note Word saved to Case Documents and downloaded.")
    text = docx_text(data)
    check("Debit Note Word: file name, TW Reference, saved to Case Documents", re.fullmatch("DebitNote_TWPAR2603001" + stamp, name) is not None and "TWPAR2603001" in text and ok, name)
    page.wait_for_timeout(800)
    generated = page.locator(".documents-grid").inner_text()
    check("both Word files are listed in Case Documents", "CoverNote_TWPAR2603001" in generated and "DebitNote_TWPAR2603001" in generated, generated[:300])
    check("PDF download buttons retired", cards.get_by_role("button", name="Download PDF").count() == 0)
    snap(page, "documents-generated")

    # 批單 Draft（階段 A 建立）：只有 Endorsement Word
    # 批單不在案件列表裡：從根案件的流程（case-workflow）取批單鏈
    chain = page.evaluate("""async () => {
      const list = await (await fetch('/api/cases', {cache: 'no-store'})).json()
      const root = (list.cases || []).find((r) => r.twRef === 'TWPAR2603001')
      const wf = await (await fetch('/api/case-workflow?caseUid=' + root.caseUid, {cache: 'no-store'})).json()
      return wf.workflow.chain
    }""")
    endo = next((r for r in chain if r.get("caseKind") == "endorsement" and r.get("status") == "draft"), None)
    check("endorsement Draft found through the workflow API", endo is not None, [(r.get("caseKind"), r.get("status")) for r in chain])
    if endo:
        goto(page, f"{BASE}/cases?case={endo['caseUid']}")
        page.locator(".case-detail-tabs").wait_for()
        page.locator(".case-detail-tabs .el-tabs__item", has_text="Documentation").click()
        page.wait_for_timeout(800)
        cards = page.locator(".generated-document-card")
        # 2026-10-29：批單 Debit／Credit Note 只在 Announce 之後出現，Draft 只有 Endorsement 卡片
        check("endorsement Draft: only the Endorsement card, no Debit/Credit Note yet", cards.count() == 1 and "Endorsement" in cards.first.inner_text()
              and cards.first.get_by_role("button").count() == 1 and page.locator("[data-testid=endorsement-note-card]").count() == 0)
        # 2026-10-28：正式 Endorsement Word 要成功 Announce 之後才能下載
        cards.first.get_by_role("button", name="Download Word (.docx)").click()
        check("endorsement Draft: Endorsement Word waits for Announce", message(page, "The formal Endorsement is available after successful Announce."))
    logout(page)


def phase_r(page):
    login(page, "ui.sales")
    open_case(page, "UI Test Insured Ltd", ref="TWPAR2603001")
    page.locator(".case-detail-tabs .el-tabs__item", has_text="Reminders").click()
    page.wait_for_timeout(1200)
    body = page.locator(".overview-stack").first.inner_text()
    check("Reminders tab: e-mail not enabled notice", "Reminder e-mail is not enabled on the VM" in body)
    slip = page.locator(".overview-card").filter(has=page.locator("h2", has_text="Signed Slip reminders"))
    rows = slip.locator(".el-table__row")
    check("Signed Slip: one Suppressed reminder for the missing Facility reinsurer, to AE and supervisor",
          rows.count() == 1 and "Suppressed (not sent)" in rows.first.inner_text() and "UI Re Beta (Facility)" in rows.first.inner_text()
          and "ui.ae@tw-insure.com" in rows.first.inner_text() and "ui.boss@tw-insure.com" in rows.first.inner_text(), rows.first.inner_text() if rows.count() else "")
    errors = page.locator(".overview-card").filter(has=page.locator("h2", has_text="Configuration errors")).locator(".el-table__row")
    check("Configuration errors: the first run (AE had no Personnel record) is listed",
          errors.count() >= 1 and "Account Executive does not match one active Personnel record." in errors.first.inner_text(), errors.count())
    # 2026-10-16 92 項會計規則：財務提醒改用「正式帳款」的實際到期日，帳款要到 Production 關帳（階段 F）才建立；
    # 此時案件還沒有正式帳款，所以不會有付款提醒（原本依付款排程提醒、檢查 Finance 收件人的項目改為此檢查）
    pay_card = page.locator(".overview-card").filter(has=page.locator("h2", has_text="Payment reminders"))
    check("Payment: no reminders before formal accounting entries exist (created at Production close); recipients rule shows AE, supervisor and Finance",
          pay_card.locator(".el-table__row").count() == 0 and "No payment reminders for this case." in pay_card.inner_text()
          and "Account Executive's supervisor and Finance" in pay_card.inner_text(), pay_card.inner_text()[:300])
    rows.first.get_by_role("button", name="Preview").click()
    dlg = page.locator(".el-dialog").filter(has_text="Reminder preview")
    dlg.wait_for()
    check("preview: subject with the TW Reference", "[Signed Slip 逾期警示] TWPAR2603001" in dlg.inner_text(), dlg.inner_text()[:200])
    frame = dlg.locator("iframe.reminder-preview-frame")
    srcdoc = frame.get_attribute("srcdoc") or ""
    check("preview: e-mail HTML in a sandboxed frame, link to the VM", frame.get_attribute("sandbox") == "" and "開啟 Reinsurance Department System" in srcdoc
          and "<li>UI Re Beta (Facility)</li>" in srcdoc, srcdoc[:200])
    snap(page, "reminders")
    page.keyboard.press("Escape")
    logout(page)


def phase_p1(page):
    goto(page, BASE + "/login")
    page.get_by_text("Forgot password?").wait_for(timeout=10000)
    wait_api_idle(page)
    console_errors.clear()  # 登入前檢查登入狀態的 401 是預期的（同 login()）
    check("e-mail enabled: 'Forgot password?' is shown on the login page", page.get_by_text("Forgot password?").is_visible())
    page.get_by_text("Forgot password?").click()
    page.wait_for_url(BASE + "/forgot-password")
    page.get_by_label("Username or e-mail").fill("UI.Sales")
    page.get_by_role("button", name="Send reset link").click()
    check("request: generic confirmation shown", message_text(page, "If the account exists and has an e-mail address"))
    snap(page, "forgot-password")


def message_text(page, text):
    try:
        page.get_by_text(text).first.wait_for(timeout=10000)
        return True
    except Exception:  # noqa: BLE001
        return False


def phase_p2(page):
    link = open("out/reset-link.txt").read().strip()
    check("reset link taken from the e-mail", link.startswith(BASE + "/reset-password?uid="), link[:80])
    goto(page, link)
    page.get_by_label("New password", exact=True).fill("short")
    page.get_by_label("Confirm new password").fill("short")
    page.get_by_role("button", name="Set new password").click()
    check("weak password is refused before sending", message_text(page, "too short"))
    page.get_by_label("New password", exact=True).fill("Ui-Test-Pass-9")
    page.get_by_label("Confirm new password").fill("Ui-Test-Pass-9")
    page.get_by_role("button", name="Set new password").click()
    check("new password set", message_text(page, "Your password has been reset"))
    snap(page, "reset-password")
    goto(page, BASE + "/login")
    page.get_by_label("Username").fill("ui.sales")
    page.get_by_label("Password").fill("Ui-Test-Pass-9")
    page.get_by_role("button", name="Sign in").click()
    page.wait_for_selector(".app-shell", timeout=15000)
    check("sign in with the new password", page.locator(".app-shell").is_visible())
    console_errors.clear()
    logout(page)
    goto(page, link)
    page.get_by_label("New password", exact=True).fill("Ui-Test-Pass-8")
    page.get_by_label("Confirm new password").fill("Ui-Test-Pass-8")
    page.get_by_role("button", name="Set new password").click()
    check("the same link cannot be used again", message_text(page, "invalid or has expired"))
    console_errors.clear()   # 400 回應在 console 會有一行網路錯誤，屬預期


def phase_k(page):
    """VM 才有（2026-09-29）：Fixed Clause 依 Class。MDM 設定 Class 條款與再保人條款的適用 Class，案件表單依 Class 帶入。"""
    login(page, "ui.admin")
    nav(page, "Master Data Management")
    dlg = page.locator(".master-dialog")
    page.locator(".mdm-tab", has_text="Classes").click()
    page.get_by_role("button", name="+ Add Class").click()
    dlg.wait_for()
    fill(dlg, page, "Code", "UMC")
    fill(dlg, page, "Name", "UI Marine Cargo")
    pick(dlg, page, "Clause", "NMA2918")
    dlg.get_by_role("button", name="+ Add fixed clause").click()
    dlg.locator(".el-dialog__footer button", has_text="Add record").click()
    check("class with its own fixed clause added", message(page, "Class added"))
    page.wait_for_timeout(500)
    row = page.locator(".el-table__row", has_text="UI Marine Cargo")
    check("class row shows 1 fixed clause", re.search(r"\b1\b", row.inner_text()) is not None, row.inner_text())

    # QS key-in currently permits Property/CGL only. Keep Marine MDM coverage,
    # and create the permitted CGL fixture for the case class-switch assertion.
    page.get_by_role("button", name="+ Add Class").click()
    dlg.wait_for()
    fill(dlg, page, "Code", "GL")
    fill(dlg, page, "Name", "Commercial General Liability")
    pick(dlg, page, "Clause", "NMA2918")
    dlg.get_by_role("button", name="+ Add fixed clause").click()
    dlg.locator(".el-dialog__footer button", has_text="Add record").click()
    check("permitted CGL class carries the fixed clause for the case-switch check", message(page, "Class added"))
    page.wait_for_timeout(500)
    page.locator(".mdm-tab", has_text="Reinsurers").click()
    page.locator(".el-table__row", has_text="UI Re Alpha").get_by_role("button", name="Edit").click()
    dlg.wait_for()
    old_scope = dlg.get_by_label("Applies to LMA5390").locator("xpath=ancestor::div[contains(concat(' ', normalize-space(@class), ' '), ' el-select ')][1]").inner_text()
    check("existing clause without class scope shows All classes", "All classes" in old_scope, old_scope)
    pick(dlg, page, "Clause", "LPO9999")
    dlg.get_by_role("button", name="+ Add fixed clause").click()
    new_scope = dlg.get_by_label("Applies to LPO9999").locator("xpath=ancestor::div[contains(concat(' ', normalize-space(@class), ' '), ' el-select ')][1]").inner_text()
    check("a newly added reinsurer clause defaults to Property", "Property" in new_scope and "All classes" not in new_scope, new_scope)
    snap(page, "mdm-reinsurer-applies-to")
    dlg.locator(".el-dialog__footer button", has_text="Save changes").click()
    check("reinsurer saved with a class-scoped clause", message(page, "Reinsurer updated"))
    page.wait_for_timeout(500)
    page.locator(".mdm-tab", has_text="Clauses").click()
    page.wait_for_timeout(300)
    used = page.locator(".el-table__row", has_text="LPO9999").inner_text()
    check("Clauses tab: Used by shows the reinsurer with its class scope", "URA (Property)" in used, used)
    used = page.locator(".el-table__row", has_text="NMA2918").inner_text()
    check("Clauses tab: Used by shows the class", "Class: UI Marine Cargo" in used, used)
    snap(page, "mdm-class-clauses")
    logout(page)

    login(page, "ui.sales")
    nav(page, "Account List")
    page.get_by_role("button", name="+ New case").click()
    page.locator(".case-form").wait_for()
    page.wait_for_timeout(800)
    # 2026-10-16 起 Class 在最上方的 Structure 卡片（與 Reinsurance Type 一起先選）
    top = structure_card(page)
    security = section(page, "Schedule of Security")
    def conditions():
        page.wait_for_timeout(300)
        return section(page, "Reinsurance Conditions").inner_text()
    choose_structure_class(page, "Quota Share", "Property")
    pick(security.locator(".repeat-card").nth(0), page, "Reinsurer", "UI Re Alpha")
    section(page, "Reinsurance Conditions").get_by_text("LPO9999", exact=True).wait_for()
    text = conditions()
    check("Property case: all-class and Property-only reinsurer clauses, no Marine class clause",
          all(c in text for c in ("LMA3333", "INTERMEDIARY", "LMA5390", "LPO9999")) and "NMA2918" not in text, text[:400])
    pick(top, page, "Insurance Type", "Commercial General Liability")
    section(page, "Reinsurance Conditions").get_by_text("NMA2918", exact=True).wait_for()
    text = conditions()
    check("changing Class re-applies clauses: CGL class clause in, Property-only clause out",
          all(c in text for c in ("LMA3333", "LMA5390", "NMA2918")) and "LPO9999" not in text, text[:400])
    pick(security.locator(".repeat-card").nth(0), page, "Reinsurer", "UI Re Beta (Facility)")
    text = conditions()
    check("all-Facility case still gets the class clause", "NMA2918" in text and "LMA5390" not in text and "LMA3333" in text, text[:400])
    snap(page, "case-class-clauses")
    logout(page)


exec(open('legacy_entry_ui.py').read())

with sync_playwright() as p:
    browser = p.chromium.launch()
    page = browser.new_page(viewport={"width": 1440, "height": 1000}, accept_downloads=True)
    page.set_default_timeout(15000)
    page.add_init_script(API_TRACKING_SCRIPT)
    page.on("console", lambda m: m.type == "error" and console_errors.append(m.text))
    page.on("pageerror", lambda e: console_errors.append("pageerror: " + str(e)))
    try:
        {"L": phase_l, "A": phase_a, "H": phase_h, "R": phase_r, "P1": phase_p1, "P2": phase_p2, "B0": phase_b0, "B": phase_b, "K": phase_k, "C": phase_c, "D": phase_d, "E": phase_e, "F": phase_f, "G": phase_g}[PHASE](page)
    except Exception as exc:  # noqa: BLE001 - 任何例外都記成失敗並留下截圖
        check(f"phase {PHASE} ran to the end", False, repr(exc)[:400])
        snap(page, "error")
    check(f"phase {PHASE}: no JavaScript errors in the console", not console_errors, console_errors[:5])
    browser.close()

fails = [r for r in results if not r[1]]
print(f"\nphase {PHASE}: {len(results) - len(fails)}/{len(results)} passed")
sys.exit(1 if fails else 0)
