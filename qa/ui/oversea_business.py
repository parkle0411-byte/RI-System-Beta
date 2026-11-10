import re,json
from pathlib import Path
from playwright.sync_api import sync_playwright,expect
checks=[]
def check(name,condition=True):
 assert condition,name;checks.append(name);print('PASS '+name,flush=True)
def field(page,label):return page.locator('.el-form-item').filter(has=page.locator('.el-form-item__label').filter(has_text=re.compile('^'+re.escape(label)+'$'))).first
def select(page,label,value):
 field(page,label).locator('.el-select__wrapper').first.click()
 page.locator('.el-select__popper[aria-hidden="false"] .el-select-dropdown__item').filter(has_text=re.compile('^'+re.escape(value)+r'(?: ·.*)?$')).first.click();page.keyboard.press('Escape');page.wait_for_timeout(250)
def fill(page,label,value):
 f=field(page,label).locator('input').last;f.fill(str(value));f.press('Tab')
def waitapi(page):
 page.wait_for_timeout(400)
def request(page,path,body=None,method='POST'):
 return page.evaluate('''async ({path,body,method})=>{const csrf=document.cookie.split('; ').find(x=>x.startsWith('csrftoken='))?.split('=')[1];const r=await fetch(path,{method,headers:{'Content-Type':'application/json','X-CSRFToken':csrf},body:body==null?undefined:JSON.stringify(body)});return {status:r.status,body:await r.json()}}''',dict(path=path,body=body,method=method))
def upload_broker_note(page, kind='Credit Note', filename='foreign-broker-credit.pdf'):
 panel=page.locator('[data-testid="oversea-broker-evidence"]:visible').last
 panel.locator('.el-select__wrapper').click()
 options=page.locator('.el-select__popper[aria-hidden="false"] .el-select-dropdown__item').all_text_contents()
 endorsement='for this endorsement' in panel.inner_text()
 check('endorsement offers Credit Note and Debit Note' if endorsement else 'Original offers Credit Note only',set(options)=={'Credit Note','Debit Note'} if endorsement else options==['Credit Note'])
 page.locator('.el-select__popper[aria-hidden="false"] .el-select-dropdown__item').filter(has_text=re.compile('^'+re.escape(kind)+'$')).click()
 panel.locator('input[type=file]').set_input_files(dict(name=filename,mimeType='application/pdf',buffer=b'%PDF-1.4\nForeign Broker QA Note\n%%EOF'))
 with page.expect_response(lambda r:'/api/case-documents' in r.url and r.request.method=='POST') as uploaded:panel.get_by_role('button',name='Upload Broker Note',exact=True).click()
 assert uploaded.value.status==201,uploaded.value.text()
 expect(panel).to_contain_text('RI Broker note selected')
 return uploaded.value.json()['file']['id']
with sync_playwright() as pw:
 browser=pw.chromium.launch(headless=True,args=['--no-sandbox']);context=browser.new_context(viewport={'width':1440,'height':1100});page=context.new_page();errors=[];page.on('pageerror',lambda e:errors.append(str(e)))
 page.goto('http://nginx/login');page.get_by_label('Username').fill('ui.admin');page.get_by_label('Password',exact=True).fill('Ui-Test-Pass-1');page.get_by_role('button',name='Sign in',exact=True).click();page.wait_for_url('**/dashboard')
 page.goto('http://nginx/cases');page.get_by_role('button',name='+ New case',exact=True).click()
 select(page,'Reinsurance Type','Oversea Business');field(page,'Insurance Type').locator('.el-select__wrapper').click();page.wait_for_timeout(300);opts=page.locator('.el-select__popper[aria-hidden="false"] .el-select-dropdown__item').all_text_contents();print('Class options: '+repr(opts),flush=True);check('only Fine Art and Terrorism offered',len(opts)==2 and any('Fine Art' in x for x in opts) and any('Terrorism' in x for x in opts));page.keyboard.press('Escape');select(page,'Insurance Type','Fine Art')
 form=page.get_by_test_id('oversea-business-form');expect(form).to_be_visible();labels=form.locator('.el-form-item__label').all_text_contents();check('insured, AE and Policy Period fields precede financial inputs',labels==['Insured (EN)','Insured (CN)','Account Executive','Policy Period','100% Premium','Share (%)','Brokerage','Reinsurance Broker','Cedant','Receipt / Payment Date']);check('no generic underwriting fields',page.locator('.case-form').get_by_text('Risk Details',exact=True).count()==0)
 check('all Oversea input groups marked required',form.locator('.el-form-item.is-required').count()==10)
 check('AE defaults to signed-in user',field(page,'Account Executive').inner_text().find('UI Admin')>=0)
 fill(page,'Insured (EN)','Yageo Group');fill(page,'Insured (CN)','海外美術館');select(page,'Account Executive','Oversea UI AE')
 f=page.get_by_label('Policy effective date',exact=True);f.fill('2048-02-29');f.press('Enter');page.keyboard.press('Escape');expect(page.get_by_label('Policy expiration date',exact=True)).to_have_value('2049-02-28');check('Policy Period defaults one year with leap-day handling')
 field(page,'Policy Period').locator('.el-select__wrapper').first.click();page.locator('.el-select__popper[aria-hidden="false"] .el-select-dropdown__item').filter(has_text=re.compile('^00:00$')).click();page.keyboard.press('Escape');expect(field(page,'Policy Period')).to_contain_text('00:00');check('Policy time can be selected')
 fill(page,'100% Premium','100000');fill(page,'Share (%)','25');fill(page,'Brokerage','2500.25');select(page,'Reinsurance Broker','Oversea UI Broker');select(page,'Cedant','Oversea UI Cedant');f=field(page,'Receipt / Payment Date').locator('input');f.fill('2050-01-05');f.press('Enter');page.keyboard.press('Escape');expect(page.get_by_test_id('oversea-t3')).to_contain_text('2,500.25');check('Brokerage above 100 accepted as direct amount')
 page.screenshot(path='out/oversea-details-desktop.png',full_page=True)
 with page.expect_response(lambda response: response.url.endswith('/api/cases') and response.request.method=='POST') as saved:
  page.get_by_role('button',name='Save draft',exact=True).last.click()
 response=saved.value;check('minimal draft API saves',response.status==201);uid=response.json()['case']['caseUid'];saved_case=request(page,'/api/cases?caseUid='+uid,None,'GET')['body']['case'];check('API preserves details and adjusted AE',all(saved_case['payload'][k]==v for k,v in {'originalInsured':'Yageo Group','originalInsuredCn':'海外美術館','ae':'Oversea UI AE','policyFrom':'2048-02-29','policyTo':'2049-02-28','policyFromTime':'00:00','policyToTime':'00:00'}.items()))
 page.goto('http://nginx/cases');expect(page.locator('.case-table').get_by_role('button',name='Yageo Group',exact=True)).to_be_visible();check('Account List displays saved Insured (EN)')
 page.screenshot(path='out/oversea-account-name-list.png',full_page=True)
 page.goto('http://nginx/cases?case='+uid)
 expect(page.locator('.page-header p')).to_contain_text('Yageo Group');check('Account detail header displays saved Insured (EN)')
 page.screenshot(path='out/oversea-account-name-header.png',full_page=True)
 expect(page.locator('[data-testid=oversea-business-summary]:visible').first).to_be_visible();check('saved minimal case summary');expect(page.locator('[data-testid=oversea-business-summary]:visible').first).to_contain_text('2049-12-26');check('Accounting Date is actual date minus ten days across year')
 page.goto('http://nginx/cases?case='+uid);expect(page.locator('[data-testid=oversea-business-summary]:visible').first).to_contain_text('2,500.25');check('amount and date survive reopening')
 summary=page.locator('[data-testid=oversea-business-summary]:visible').first
 for value in ['Yageo Group','海外美術館','Oversea UI AE','2048-02-29 00:00','2049-02-28 00:00']:expect(summary).to_contain_text(value)
 check('saved summary restores insured, Policy Period and AE')
 expect(page.get_by_test_id('oversea-broker-evidence')).to_contain_text('Announce is blocked')
 check('Original shows required-note blocker before upload')
 page.get_by_role('button',name='Edit draft',exact=True).click()
 page.get_by_role('button',name='Review & confirm',exact=True).click()
 review=page.locator('.review-dialog:visible')
 expect(review.get_by_test_id('oversea-broker-evidence')).to_be_visible()
 expect(review.get_by_role('button',name='Announce',exact=True)).to_be_disabled()
 expect(review.locator('.announce-attestation')).to_have_class(re.compile('is-disabled'))
 check('form review blocks Announce and confirmation until note upload')
 page.screenshot(path='out/oversea-credit-note-required.png',full_page=True)
 review.get_by_role('button',name='Back to edit',exact=True).click()
 page.goto('http://nginx/cases?case='+uid)
 upload_broker_note(page)
 page.get_by_role('button',name='Review & Announce',exact=True).click();dialog=page.locator('.announce-dialog');expect(dialog.get_by_test_id('oversea-business-summary')).to_be_visible();check('Announce uses minimal summary')
 note=dialog.locator('.broker-note-row .el-checkbox')
 with page.expect_response(lambda r:'/api/case-documents' in r.url and r.request.method=='PUT'):note.click()
 expect(dialog.get_by_role('button',name='Announce',exact=True)).to_be_disabled()
 expect(dialog.locator('.announce-attestation')).to_have_class(re.compile('is-disabled'))
 check('deselecting note blocks final Announce and attestation')
 with page.expect_response(lambda r:'/api/case-documents' in r.url and r.request.method=='PUT'):note.click()
 expect(dialog.locator('.announce-attestation')).not_to_have_class(re.compile('is-disabled'))
 check('reselecting requires a fresh final confirmation')
 page.screenshot(path='out/oversea-credit-note-review.png',full_page=True)
 dialog.locator('.announce-attestation').click();dialog.get_by_role('button',name='Announce',exact=True).click();expect(page.locator('[data-testid=oversea-business-summary]:visible').first).to_be_visible();waitapi(page)
 result=request(page,'/api/cases?caseUid='+uid,None,'GET');case=result['body']['case'];tx=case['payload']['transactions'];check('Announce creates T3 only',len(tx)==1 and tx[0]['amount']==2500.25 and tx[0]['legType']=='Leg 3')
 check('Oversea reference follows Effective Date rather than receipt date',case['twRef'].startswith('TWFA4802'))
 page.get_by_role('tab',name='Documentation',exact=True).click();expect(page.get_by_role('heading',name='Generated documents',exact=True)).to_have_count(0);check('document generation section absent')
 page.goto('http://nginx/accounting');page.get_by_role('tab',name='Unreconciled Accounts',exact=True).click();row=page.get_by_test_id('accounting-table').locator('tbody tr').filter(has_text=tx[0]['txNo']);expect(row).to_be_visible();expect(row).to_contain_text('2049-12-26');expect(row).to_contain_text('2050-01-05');expect(row).to_contain_text('Oversea UI Broker');check('Accounting shows exact dates and broker on independent T3');page.screenshot(path='out/oversea-accounting-desktop.png',full_page=True)
 row.get_by_role('button',name='Mark reviewed',exact=True).click();dlg=page.locator('.el-dialog:visible');dlg.locator('input').nth(1).fill('Oversea UI review');dlg.get_by_role('button',name=re.compile('Save|Confirm|Mark reviewed')).last.click();waitapi(page)
 # API coverage verifies registration atomically; browser verifies the visible list and prefilling.
 page.get_by_role('tab',name='Reconciled Accounts',exact=True).click();row=page.get_by_test_id('accounting-table').locator('tbody tr').filter(has_text=tx[0]['txNo']);expect(row).to_be_visible();row.get_by_role('button',name='Record receipt / payment',exact=True).click();dlg=page.locator('.el-dialog:visible');check('receipt dialog allows its own actual date and prefills Cash Amount',bool(dlg.locator('input').first.input_value()) and float(dlg.locator('.el-input-number input').first.input_value().replace(',',''))==2500.25);page.keyboard.press('Escape')
 page.set_viewport_size({'width':390,'height':844});page.goto('http://nginx/cases');page.get_by_role('button',name='+ New case',exact=True).click();select(page,'Reinsurance Type','Oversea Business');select(page,'Insurance Type','Terrorism');expect(page.get_by_test_id('oversea-business-form')).to_be_visible();check('mobile Terrorism minimal form');page.screenshot(path='out/oversea-details-mobile.png',full_page=True)
 check('no browser runtime errors',not errors)
 Path('out/oversea-ui.json').write_text(json.dumps({'passed':True,'checks':checks,'consoleErrors':errors},indent=2));print(str(len(checks))+' passed Oversea UI checks');browser.close()

exec(Path('/ui/oversea_workflows.py').read_text())
