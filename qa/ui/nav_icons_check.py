from playwright.sync_api import sync_playwright

expected = {
    'Dashboard': "M3 16a9 9 0 0 1 18 0",
    'Account List': 'M9 6h11M9 12h11M9 18h11',
    'Legacy Data (Old Register)': "M5 9v10a1 1 0 0 0 1 1h12",
    'Master Data Management': "ellipse cx='12' cy='5'",
    'Personnel & Accounts': "rect x='2' y='4' width='20'",
    'Production Report': 'M7 15l4-4 3 3 6-6',
    'Accounting': "rect x='5' y='2' width='14'",
    'FX Rates': 'M17 2l4 4-4 4',
    'Draft Recycle Bin': 'M9.5 13.5L12 11l2.5 2.5',
    'System Reference Data': 'M4 19.5v-15A2.5',
    'Audit Log': 'M12 2l8 3v6',
}
with sync_playwright() as playwright:
    browser=playwright.chromium.launch(headless=True,args=['--no-sandbox'])
    page=browser.new_page(viewport={'width':1440,'height':1000})
    page.goto('http://nginx/login')
    page.get_by_label('Username').fill('ui.admin')
    page.get_by_label('Password',exact=True).fill('Ui-Test-Pass-1')
    page.get_by_role('button',name='Sign in',exact=True).click()
    page.wait_for_url('**/dashboard')
    for label,fragment in expected.items():
        button=page.locator('.nav-item').filter(has_text=label)
        assert button.count()==1, f'Missing menu item: {label}'
        icon=button.locator('img.nav-icon')
        icon.wait_for(state='visible')
        page.wait_for_function('(img) => img.complete && img.naturalWidth > 0',arg=icon.element_handle())
        source=icon.get_attribute('src') or ''
        assert source.startswith('data:image/svg+xml;') and fragment in source, f'Wrong or missing icon: {label}'
        print('PASS sidebar icon:',label,flush=True)
    page.screenshot(path='/ui/out/nav-icons-restored.png',full_page=True)
    print(f'{len(expected)}/{len(expected)} sidebar icons restored',flush=True)
    browser.close()
