import re
from playwright.sync_api import sync_playwright, expect

def field(page, label):
    return page.locator('.el-form-item').filter(has=page.locator('.el-form-item__label').filter(has_text=re.compile('^'+re.escape(label)+'$'))).first

def select(page, label, value):
    field(page,label).locator('.el-select__wrapper').first.click()
    page.locator('.el-select__popper[aria-hidden="false"] .el-select-dropdown__item').filter(has_text=re.compile('^'+re.escape(value)+r'(?: ·.*)?$')).first.click()
    page.keyboard.press('Escape')

with sync_playwright() as p:
    browser=p.chromium.launch(headless=True,args=['--no-sandbox'])
    page=browser.new_page(viewport={'width':1440,'height':1100}); errors=[]
    page.on('pageerror', lambda e: errors.append(str(e)))
    page.goto('http://nginx/login'); page.get_by_label('Username').fill('ui.admin'); page.get_by_label('Password',exact=True).fill('Ui-Test-Pass-1')
    page.get_by_role('button',name='Sign in',exact=True).click();page.wait_for_url('**/dashboard')
    page.goto('http://nginx/cases');page.get_by_role('button',name='+ New case',exact=True).click()
    select(page,'Reinsurance Type','Quota Share');select(page,'Insurance Type','Stock Throughput')
    expect(page.get_by_test_id('case-section-information')).to_be_visible()
    expect(page.get_by_test_id('case-section-information').get_by_text('Information',exact=True)).to_be_visible()
    expect(field(page,'Conveyance')).to_be_visible();expect(field(page,'Voyage')).to_be_visible()
    expect(field(page,'Limit of Liability').locator('textarea')).to_be_visible()
    expect(page.locator('h3').filter(has_text='HUB List')).to_be_visible(); expect(page.locator('h3').filter(has_text='Estimated Turnover')).to_be_visible()
    assert not field(page,'Aggregate Limit (Policy Limit)').count()
    field(page,'Original Insured (EN)').locator('input').last.fill('STP Smoke Insured')
    field(page,'Conveyance').locator('textarea').fill('Sea and air')
    field(page,'Voyage').locator('textarea').fill('Worldwide')
    field(page,'Limit of Liability').locator('textarea').fill('USD 1,000,000 any one event')
    page.get_by_placeholder('Location name *').fill('Test hub')
    page.get_by_placeholder('Full address *').fill('Taipei address')
    page.get_by_placeholder('Full address *').press('Tab')
    page.get_by_text('Draft saved automatically').first.wait_for(timeout=20000)
    page.screenshot(path='/ui/out/stp-keyin.png',full_page=True)
    page.wait_for_function("""async () => {
      const listing = await fetch('/api/cases').then(r=>r.json());
      const row = listing.cases.find(c => c.originalInsured === 'STP Smoke Insured');
      if (!row) return false;
      const response=await fetch('/api/cases?caseUid='+encodeURIComponent(row.caseUid)).then(r=>r.json());
      const raw=response.case.payload.draftInput || response.case.payload;
      return raw.conveyance === 'Sea and air' && raw.voyage === 'Worldwide' && raw.limitOfLiability === 'USD 1,000,000 any one event' && raw.stpHubs?.[0]?.name === 'Test hub' && raw.stpHubs?.[0]?.address === 'Taipei address';
    }""",timeout=30000)
    saved_case=page.evaluate("""async () => { const listing=await fetch('/api/cases').then(r=>r.json()); const row=listing.cases.find(c=>c.originalInsured==='STP Smoke Insured'); return (await fetch('/api/cases?caseUid='+encodeURIComponent(row.caseUid)).then(r=>r.json())).case }""")
    raw=saved_case['payload'].get('draftInput',saved_case['payload'])
    raw.update({'classOfBusiness':'Stock Throughput','classCode':'ST','reinsuranceStructure':'QS','currency':'USD','newOrRenew':'New',
        'typePrefix':'Stock Throughput','originalInsured':'STP Smoke Insured','originalInsuredCn':'測試被保險人','reinsured':'UI Cedant Insurance',
        'policyFrom':'2026-01-01','policyTo':'2027-01-01','ae':'UI AE One','interest':'Stock','situations':[{'address':'Taipei','postcode':'100'}],
        'originalPremium':1000,'riCommPct':0,'taxPct':1,'paymentTermsDays':90,
        'reinsurers':[{'name':'UI Re Alpha','sharePct':20,'premium':1000,'riCommPct':10,'taxPct':0,'paymentTermsDays':90}],
        'deductibles':'USD 1,000','originalConditions':'Condition A','reinsuredRetention':'Waived',
        'expressWarranties':'None','conditionsPrecedent':'None','subjectivities':'None','lossAdvisedDate':'2026-01-01','lossRecordYears':5,
        'stpTurnoverMode':'combined','stpTurnover':[{'company':'','currency':'USD','amount':123}],
        'stpHubs':[{'name':'Test hub','address':'Taipei address','currency':'USD','amount':500}]})
    updated=page.evaluate('''async ({uid,version,data}) => { const token=document.cookie.split('; ').find(s=>s.startsWith('csrftoken='))?.split('=')[1]; const r=await fetch('/api/cases',{method:'PUT',headers:{'Content-Type':'application/json','X-CSRFToken':token},body:JSON.stringify({caseUid:uid,rowVersion:version,case:data,incompleteDraft:true})});return {status:r.status,body:await r.json()} }''',{'uid':saved_case['caseUid'],'version':saved_case['rowVersion'],'data':raw})
    assert updated['status']==200,updated
    page.goto('http://nginx/cases?draft='+saved_case['caseUid'])
    expect(field(page,'Limit of Liability').locator('textarea')).to_have_value('USD 1,000,000 any one event')
    page.get_by_role('button',name='Review & confirm',exact=True).click()
    dialog=page.locator('.review-dialog:visible').last
    expect(dialog.get_by_role('heading',name='Information',exact=True)).to_be_visible(timeout=15000)
    expect(dialog.get_by_text('Test hub',exact=True)).to_be_visible()
    expect(dialog.get_by_text('Worldwide',exact=True)).to_be_visible()
    assert dialog.get_by_text('Total sum insured:',exact=False).count()==0
    page.screenshot(path='/ui/out/stp-review.png',full_page=True)
    assert not errors,errors
    print('STP UI key-in smoke passed', flush=True)
    browser.close()
