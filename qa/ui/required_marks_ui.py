"""Red required marks (2026-11-27 owner decision): every field that must be completed shows a red *, either-or pairs
show * on both with one note. Opens new case forms of each type and the FX dialog without saving anything.
The rest of the marks are checked in source by required-marks-work/check_required_marks.py."""
import re
from playwright.sync_api import sync_playwright

BASE, PASSWORD = 'http://nginx', 'Ui-Test-Pass-1'
results = []


def check(name, ok, detail=''):
    results.append(bool(ok))
    print(('PASS ' if ok else 'FAIL ') + name + ('' if ok else f'   <-- {detail}'), flush=True)


def label_re(text):
    return re.compile(r'^\s*' + re.escape(text) + r'\s*$')


def item(scope, page, label):
    return scope.locator('.el-form-item').filter(has=page.locator('.el-form-item__label', has_text=label_re(label))).first


def pick(scope, page, label, option):
    item(scope, page, label).locator('.el-select__wrapper').first.click()
    page.locator('.el-select__popper[aria-hidden="false"] .el-select-dropdown__item').filter(has_text=option).first.click()
    page.keyboard.press('Escape')
    page.wait_for_timeout(300)


def red(rgb):
    m = re.match(r'rgba?\((\d+), (\d+), (\d+)', rgb or '')
    return bool(m) and int(m.group(1)) >= 150 and int(m.group(2)) <= 120 and int(m.group(3)) <= 120


def star(page, scope, label):
    """(required class, '*' drawn before the label, its colour) of one form item."""
    loc = item(scope, page, label)
    if loc.count() == 0:
        return None
    return loc.evaluate("""el => { const lab = el.querySelector(':scope > .el-form-item__label'); const s = getComputedStyle(lab, '::before');
                            return {req: el.classList.contains('is-required'), content: s.content, color: s.color} }""")


def expect_star(page, scope, label, where):
    s = star(page, scope, label)
    check(f'{where}: {label} shows a red *', s and s['req'] and '*' in s['content'] and red(s['color']), s)


def expect_no_star(page, scope, label, where):
    s = star(page, scope, label)
    check(f'{where}: {label} has no * (optional)', s and not s['req'], s)


def heading_star(scope, text):
    h = scope.locator('h3, .el-collapse-item__header').filter(has_text=text).first
    if h.count() == 0:
        return None
    return h.evaluate("el => { const s = el.querySelector('.required-star'); return s ? {text: s.textContent, color: getComputedStyle(s).color} : null }")


def expect_heading_star(scope, text, where):
    s = heading_star(scope, text)
    check(f'{where}: heading "{text}" shows a red *', s and '*' in s['text'] and red(s['color']), s)


def login(page, user):
    page.goto(BASE + '/login')
    page.get_by_label('Username').fill(user)
    page.get_by_label('Password').fill(PASSWORD)
    page.get_by_role('button', name='Sign in').click()
    page.wait_for_selector('.app-shell', timeout=15000)


def new_case(page, structure, klass):
    page.locator('.nav-item', has_text='Account List').click()
    page.wait_for_timeout(700)
    page.get_by_role('button', name='+ New case').click()
    page.locator('.case-form').wait_for()
    card = page.locator('[data-testid="reinsurance-structure-section"]')
    pick(card, page, 'Reinsurance Type', structure)
    pick(card, page, 'Insurance Type', klass)
    page.wait_for_timeout(500)
    return page.locator('.case-form')


with sync_playwright() as p:
    browser = p.chromium.launch()
    page = browser.new_page(viewport={'width': 1440, 'height': 900})
    login(page, 'ui.admin')   # ui.sales gets a new password in phases P1/P2; the administrator may also key in cases

    form = new_case(page, 'Quota Share', 'Property')
    expect_heading_star(form, 'Breakdown of Sum Insured', 'Property QS')
    expect_star(page, form, 'Deductibles', 'Property QS')
    expect_no_star(page, form, 'Express Warranties', 'Property QS')
    check('Property QS: the Sum Insured row hints keep their text', form.locator('input[placeholder="Interest insured *"]').count() >= 1)

    form = new_case(page, 'Quota Share', 'Product Recall')
    for label in ("Reinsured's Retention", 'Express Warranties', 'Conditions Precedent', 'Subjectivities', 'Deductibles', 'Self-Insured Retention'):
        expect_star(page, form, label, 'Product Recall QS')
    check('Product Recall QS: the Deductibles / Self-Insured Retention note is shown',
          form.get_by_text('Enter at least one of the two: Deductibles or Self-Insured Retention.').count() == 1)
    risk = page.get_by_test_id('product-recall-risk')
    expect_heading_star(risk, 'Covered Events', 'Product Recall QS')
    expect_heading_star(risk, 'Covered Loss', 'Product Recall QS')
    check('Product Recall QS: the Covered Loss note is shown', risk.get_by_text('Each selected Covered Loss needs a currency and an amount greater than 0.').count() == 1)

    form = new_case(page, 'Quota Share', 'Stock Throughput')
    for label in ("Reinsured's Retention", 'Express Warranties', 'Conditions Precedent', 'Subjectivities'):
        expect_star(page, form, label, 'STP QS')
    for heading in ('Estimated Turnover', 'HUB List'):
        expect_heading_star(form, heading, 'STP QS')

    form = new_case(page, 'Quota Share', 'Commercial General Liability')
    expect_star(page, form, 'Deductibles', 'CGL QS')
    expect_star(page, form, 'Self-Insured Retention', 'CGL QS')
    check('CGL QS: the Deductibles / Self-Insured Retention note is shown',
          form.get_by_text('Enter at least one of the two: Deductibles or Self-Insured Retention.').count() == 1)
    address = form.locator('.repeat-heading h3').filter(has_text='Principal Address').first
    check('CGL QS: Principal Address stays optional (no *)', address.count() == 1 and address.locator('.required-star').count() == 0)

    page.locator('.nav-item', has_text='Account List').click()
    page.wait_for_timeout(700)
    page.get_by_role('button', name='+ New case').click()
    card = page.locator('[data-testid="reinsurance-structure-section"]')
    pick(card, page, 'Reinsurance Type', 'Facility')
    pick(card, page, 'Insurance Type', 'Personal Accident')
    facility = page.get_by_test_id('facility-placement-form')
    facility.wait_for()
    for label in ('Cedant R/I Comm (%)', 'PPW (days)'):
        expect_star(page, facility, label, 'Facility Placement')
    expect_no_star(page, facility, 'Cedant Tax (%)', 'Facility Placement')

    page.locator('.nav-item', has_text='FX Rates').click()
    page.wait_for_timeout(700)
    page.get_by_role('button', name='+ Set monthly rates').click()
    fx = page.locator('.master-dialog')
    fx.wait_for()
    header = fx.locator('th').filter(has_text='Rate to TWD').first
    s = header.evaluate("el => { const s = el.querySelector('.required-star'); return s ? getComputedStyle(s).color : null }")
    check('FX Rates: the Rate to TWD column shows a red *', red(s), s)
    browser.close()

print(f'{sum(results)} passed required-mark UI checks' if all(results) else f'FAILED {results.count(False)} of {len(results)} required-mark UI checks')
raise SystemExit(0 if all(results) else 1)
