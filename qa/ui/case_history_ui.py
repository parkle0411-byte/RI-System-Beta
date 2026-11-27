"""案件 History 分頁（2026-11-27）：在畫面上實際修改已 Announce 的案件，History 只列出真的改過的欄位。"""
import re
import time

from playwright.sync_api import sync_playwright

BASE, PASSWORD = 'http://nginx', 'Ui-Test-Pass-1'
API_TRACKING_SCRIPT = "(() => {\n  const pending = window.__riPendingApi = new Map();\n  const apiUrl = value => {\n    try {\n      const url = new URL(value instanceof Request ? value.url : String(value), location.href);\n      return url.origin === location.origin && url.pathname.startsWith('/api/') ? url.href : null;\n    } catch { return null; }\n  };\n  const nativeFetch = window.fetch.bind(window);\n  window.fetch = (...args) => {\n    const url = apiUrl(args[0]), token = {};\n    if (url) pending.set(token, url);\n    return nativeFetch(...args).then(response => {\n      if (url) {\n        try { response.clone().arrayBuffer().then(() => pending.delete(token), () => pending.delete(token)); }\n        catch { pending.delete(token); }\n      }\n      return response;\n    }, error => { pending.delete(token); throw error; });\n  };\n  const nativeOpen = XMLHttpRequest.prototype.open;\n  const nativeSend = XMLHttpRequest.prototype.send;\n  XMLHttpRequest.prototype.open = function(method, url, ...rest) {\n    this.__riApiUrl = apiUrl(url);\n    return nativeOpen.call(this, method, url, ...rest);\n  };\n  XMLHttpRequest.prototype.send = function(...args) {\n    const token = {};\n    if (this.__riApiUrl) {\n      pending.set(token, this.__riApiUrl);\n      this.addEventListener('loadend', () => pending.delete(token), { once: true });\n    }\n    try { return nativeSend.apply(this, args); }\n    catch (error) { pending.delete(token); throw error; }\n  };\n})();\n"
results, console_errors = [], []


def label_re(text):
    return re.compile(r"^\s*" + re.escape(text) + r"\s*$")


def item(scope, page, label):
    return scope.locator(".el-form-item").filter(has=page.locator(".el-form-item__label", has_text=label_re(label))).first


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


def check(name, ok, detail=''):
    results.append(bool(ok))
    print(('PASS ' if ok else 'FAIL ') + name + ('' if ok else f'   <-- {detail}'), flush=True)


def tabs(page):
    return [t.strip() for t in page.locator('.case-detail-tabs .el-tabs__item').all_inner_texts()]


def open_history(page):
    page.locator('.case-detail-tabs .el-tabs__item', has_text='History').click()
    page.locator('[data-testid="case-history"]').wait_for()
    wait_api_idle(page)
    page.wait_for_timeout(500)
    return page.locator('[data-testid="case-history"]')


def rows(event):
    return [[cell.strip() for cell in row.locator('th, td').all_inner_texts()] for row in event.locator('.history-changes tbody tr').all()]


def edit_and_save(page, change):
    page.locator('.page-header button', has_text='Edit announced case').click()
    page.locator('.case-form').wait_for()
    page.wait_for_timeout(800)
    change(page.locator('.case-form'))
    page.wait_for_timeout(300)
    page.locator('.page-header button', has_text='Save changes').click()
    box = page.locator('.el-message-box').filter(has_text='reason')
    try:
        box.wait_for(timeout=3000)
        box.locator('input, textarea').first.fill('UI history correction')
        box.locator('.el-message-box__btns button', has_text='OK').click()
    except Exception:  # noqa: BLE001  這類案件不要求填理由
        pass
    page.locator('.case-detail-tabs').wait_for(timeout=15000)
    wait_api_idle(page)
    page.wait_for_timeout(800)


with sync_playwright() as p:
    browser = p.chromium.launch()
    page = browser.new_page(viewport={'width': 1440, 'height': 1000})
    page.add_init_script(API_TRACKING_SCRIPT)
    page.on('console', lambda m: console_errors.append(m.text) if m.type == 'error' else None)
    page.on('pageerror', lambda e: console_errors.append(str(e)))
    try:
        login(page, 'ui.admin')  # ui.sales 的密碼在完整執行時會被忘記密碼階段（P2）改掉
        open_case(page, 'UI History Insured')
        got = tabs(page)
        check('History is the last tab, to the right of Endorsements and Reminders', got[-3:] == ['Endorsements', 'Reminders', 'History'], got)
        panel = open_history(page)
        events = panel.locator('.history-event')
        check('after Announce only: one Announced line without field table',
              events.count() == 1 and 'Announced' in events.first.inner_text() and panel.locator('.history-changes').count() == 0, panel.inner_text())

        def remove_space(form):
            field = item(form, page, 'Occupation').locator('textarea').first
            field.fill('Loc 1: Chemical Factory\nLoc 2: Outdoor Tank')
            field.press('Tab')

        edit_and_save(page, remove_space)
        panel = open_history(page)
        events = panel.locator('.history-event')
        top = events.first
        check('the saved edit is listed first with editor and action',
              events.count() == 2 and 'Case edited' in top.inner_text() and 'UI Admin' in top.inner_text(), panel.inner_text())
        got = rows(top)
        check('saved from the real form: Occupation is the only changed field', len(got) == 1 and got[0][0].startswith('Occupation'), got)
        check('a spacing-only edit says so and shows the removed space',
              'Spacing / line breaks only' in top.inner_text() and top.locator('.history-before').inner_text() == '␣', top.inner_text())
        page.screenshot(path='out/HI01-spacing.png', full_page=True)

        def deductibles(form):
            field = item(form, page, 'Deductibles').locator('textarea, input').first
            field.fill('15% of loss')
            field.press('Tab')

        edit_and_save(page, deductibles)
        panel = open_history(page)
        got = rows(panel.locator('.history-event').first)
        check('second edit: Deductibles only, before and after', len(got) == 1 and got[0] == ['Deductibles', '10%', '15% of loss'], got)
        page.screenshot(path='out/HI02-two-edits.png', full_page=True)
        panel.get_by_role('button', name='Refresh').click()
        wait_api_idle(page)
        check('Refresh keeps the same three events', panel.locator('.history-event').count() == 3, panel.inner_text())

        page.set_viewport_size({'width': 390, 'height': 800})
        page.wait_for_timeout(500)
        wider = panel.evaluate('el => el.scrollWidth - el.clientWidth')
        check('narrow screen: the History panel does not scroll sideways', wider <= 1, wider)
        page.screenshot(path='out/HI03-narrow.png', full_page=True)
        page.set_viewport_size({'width': 1440, 'height': 1000})

        open_case(page, 'UI History Draft')
        panel = open_history(page) if page.locator('.case-detail-tabs .el-tabs__item.is-active', has_text='History').count() == 0 else page.locator('[data-testid="case-history"]')
        check('another case opens with its own history: a draft explains that history starts after Announce',
              'History starts after the case is Announced.' in panel.inner_text() and panel.locator('.history-event').count() == 0, panel.inner_text())
        logout(page)

        login(page, 'ui.finance')
        open_case(page, 'UI History Insured')
        panel = open_history(page)
        check('Finance Staff (read only) sees the same History', panel.locator('.history-event').count() == 3 and '15% of loss' in panel.inner_text(), panel.inner_text())
        check('no browser console errors', not console_errors, console_errors)
    except Exception as exc:  # noqa: BLE001
        page.screenshot(path='out/HI99-failure.png', full_page=True)
        check('History flow completed', False, f'{page.url}: {exc}')
    browser.close()

print(f'\n{sum(results)}/{len(results)} passed')
raise SystemExit(0 if all(results) else 1)
