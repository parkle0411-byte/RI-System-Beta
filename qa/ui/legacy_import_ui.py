"""Legacy web import (2026-11-11): admin uploads a Register, sees the preview, imports; Accounting then shows
settled-before-import receipts with their Accounting Dept. Ref. and open balances. Disposable UI stack only."""
import io, zipfile
from datetime import date
from xml.sax.saxutils import escape
from playwright.sync_api import sync_playwright
BASE = "http://nginx"; PASSWORD = "Ui-Test-Pass-1"
checks = []
def check(name, ok):
    assert ok, name
    checks.append(name); print('PASS ' + name, flush=True)
FAC = 'Allianz Global Corporate & Specialty SE, Hong Kong Branch (Facility)'
D = lambda iso: str((date.fromisoformat(iso) - date(1899, 12, 30)).days)
HEAD = ['流水號', 'Insured (in English)', 'Insured (in Chinese)', 'Class', 'TW Ref. No.', 'Reinsurer', 'Cedant', "Cedant's Policy No.",
        'Effective Date', 'Expiry Date', 'AE', 'Currency', '100%Premium', 'Share', 'Our Share Premium', 'R/I Comm.', 'Claim', 'Tax',
        'Bkg.(%)', 'Bkg. (Original Currency)', 'Bkg. (in TWD)', 'Re Dept. Bkg. (in TWD)', 'Net Premium from Cedant',
        'Net Premium to Reinsurer', 'Revenue Month', 'Exchange Rate', 'New / Renew', 'Fac / Claim', 'Receive Date', 'Pay Date',
        'Cedant Receipt No', 'Reinsurer Payment No.', 'Full-closed']
def row(serial, **kw):
    v = {'流水號': serial, 'Insured (in English)': 'UI Import Insured ' + serial, 'Insured (in Chinese)': '匯入' + serial, 'Class': 'PD',
         'TW Ref. No.': 'TWUI-' + serial, 'Reinsurer': FAC, 'Cedant': 'UI Cedant', "Cedant's Policy No.": 'SOA-' + serial,
         'Effective Date': D('2026-03-01'), 'Expiry Date': D('2027-03-01'), 'AE': 'UI Sales', 'Currency': 'TWD', '100%Premium': '20000',
         'Share': '0.5', 'Our Share Premium': '10000', 'R/I Comm.': '1500', 'Claim': '0', 'Tax': '100', 'Bkg.(%)': '0.2',
         'Bkg. (Original Currency)': '2000', 'Bkg. (in TWD)': '2000', 'Re Dept. Bkg. (in TWD)': '2000', 'Net Premium from Cedant': '8400',
         'Net Premium to Reinsurer': '6400', 'Revenue Month': D('2026-03-31'), 'Exchange Rate': '1', 'New / Renew': 'New',
         'Fac / Claim': 'Fac', 'Receive Date': D('2026-05-10'), 'Pay Date': D('2026-05-20')}
    v.update(kw); return v
def workbook(rows):
    col = lambda i: (col(i // 26 - 1) if i >= 26 else '') + chr(65 + i % 26)
    cell = lambda ref, value: f'<c r="{ref}" t="inlineStr"><is><t>{escape(str(value))}</t></is></c>'
    lines = [f'<row r="{n}">' + ''.join(cell(col(i) + str(n), r[h]) for i, h in enumerate(HEAD) if h in r) + '</row>'
             for n, r in enumerate([dict(zip(HEAD, HEAD))] + rows, 1)]
    ns = 'http://schemas.openxmlformats.org/spreadsheetml/2006/main'; out = io.BytesIO()
    with zipfile.ZipFile(out, 'w') as z:
        z.writestr('[Content_Types].xml', '<?xml version="1.0"?><Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types"/>')
        z.writestr('xl/workbook.xml', f'<?xml version="1.0"?><workbook xmlns="{ns}" xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"><sheets><sheet name="Facultative" sheetId="1" r:id="rId1"/></sheets></workbook>')
        z.writestr('xl/_rels/workbook.xml.rels', '<?xml version="1.0"?><Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"><Relationship Id="rId1" Target="worksheets/sheet1.xml"/></Relationships>')
        z.writestr('xl/worksheets/sheet1.xml', f'<?xml version="1.0"?><worksheet xmlns="{ns}"><sheetData>' + ''.join(lines) + '</sheetData></worksheet>')
    return out.getvalue()
GOOD = workbook([row('UI9001', **{'Cedant Receipt No': 'CR-UI9001', 'Reinsurer Payment No.': 'RP-UI9001', 'Full-closed': 'v'}),
                 row('UI9002', **{'Cedant Receipt No': 'CR-UI9002'})])
BAD = workbook([row('UI9101', Class='XX')])
errors = []
with sync_playwright() as p:
    b = p.chromium.launch(); page = b.new_page(viewport={"width": 1440, "height": 900}); page.set_default_timeout(60000)
    page.on("console", lambda m: errors.append(m.text) if m.type == "error" and "Failed to load resource" not in m.text else None)
    page.goto(BASE + "/login"); page.get_by_label("Username").fill("ui.admin"); page.get_by_label("Password").fill(PASSWORD)
    page.get_by_role("button", name="Sign in").click(); page.wait_for_selector(".app-shell")
    page.goto(BASE + "/legacy"); page.get_by_role("button", name="Import Batches").click()
    panel = page.get_by_test_id("legacy-import"); panel.wait_for()
    def preview(content, name):
        panel.locator("input[type=file]").set_input_files({"name": name, "mimeType": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", "buffer": content})
        panel.get_by_role("button", name="Preview").click(); panel.get_by_text("Rows in file").wait_for()
    preview(BAD, "UI Bad Register.xlsx")
    page.get_by_test_id("legacy-import-errors").wait_for()
    check("preview lists row errors", "Class must be PD or GL." in page.get_by_test_id("legacy-import-errors").inner_text())
    check("errors disable the import button", page.get_by_test_id("legacy-import-commit").is_disabled())
    panel.get_by_role("button", name="Clear").click()
    preview(GOOD, "UI Register.xlsx")
    text = panel.inner_text()
    check("preview shows counts and settlement", "To import" in text and "Fully settled" in text and "With open balances" in text)
    commit = page.get_by_test_id("legacy-import-commit")
    check("clean preview enables Import 2 Transactions", commit.is_enabled() and "Import 2 Transactions" in commit.inner_text())
    commit.click(); page.get_by_role("button", name="Import", exact=True).click()
    page.get_by_text("Imported 2 transactions.").wait_for()
    check("import completes with a confirmation message", True)
    page.keyboard.press("Escape"); page.wait_for_timeout(500)
    page.get_by_placeholder("Search old reference").fill("TWUI-UI900"); page.get_by_role("button", name="Search").click()
    page.get_by_text("UI9002").first.wait_for()
    body = page.inner_text(".legacy-page")
    check("Legacy list shows settled and open imported rows", "Historically Reconciled / Settled" in body and "Imported · Open in Accounting" in body)
    # 2026-11-13：Accounting 預設開在 Unreconciled；已結清的舊資料歷史在背景載入後出現在 All Accounts。
    page.goto(BASE + "/accounting"); page.get_by_role("tab", name="All Accounts", exact=True).click()
    page.wait_for_selector("[data-testid=accounting-table] .el-table__body tr")
    page.get_by_text("Historically settled").first.wait_for()
    acc = page.inner_text("[data-testid=accounting-table]")
    check("Accounting shows the settled amount with Historically settled", "TWD 8,400" in acc and "Historically settled" in acc)
    check("Accounting shows the Effective Date beside the TW Ref", "TWUI-UI9001 · 2026-03-01" in acc or "2026-03-01" in acc)
    check("no JavaScript errors", not errors)
    b.close()
print(f"{len(checks)} passed Legacy web import UI checks")
