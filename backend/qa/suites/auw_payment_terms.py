"""AUW month-end settlement dates, cash matching and reminder dates in disposable QA."""
import calendar
import copy
import json
import os
from datetime import date, timedelta
from django.contrib.auth import get_user_model
from django.test import Client
from cases.models import Case
from cases.draft import normalize_draft
from cases.manual_reference import MANUAL_TW_REF_REINSURER as TARGET
from cases.resolve import payment_terms_signature, same_content
from cases.calc.payment_terms import build_payment_schedule, month_end_date, reminder_kind
from cases.calc.accounting import build_premium_transactions
from personnel.models import Personnel
from reminders.messages import due_kind

assert os.environ.get('RI_DISPOSABLE_QA') == 'true'
checks = []
def check(name, condition):
    assert condition, name
    checks.append(name)
    print('PASS '+name, flush=True)
def ri(payload, index=0, installment=None):
    return next(row for row in build_payment_schedule(payload)['items']
                if row['partyKey']=='r'+str(index+1) and (installment is None or row['installmentId']==installment))
def add(value, days):
    return (date.fromisoformat(value)+timedelta(days=days)).isoformat()

ready = dict(reinsuranceStructure='QS', ae='QA AUW Dates AE', currency='TWD', classOfBusiness='Property',
    classCode='ADP', newOrRenew='New', typePrefix='Fire', reinsured='QA AUW Dates Cedant', originalInsured='QA AUW Dates Policy', originalInsuredCn='合成測試被保險人', reinsuredRetention='Synthetic retention',
    policyFrom='2026-01-01', policyTo='2027-01-01', interest='Buildings', situations=[{'address':'QA Road', 'postcode':'100'}],
    reinsurers=[{'name':TARGET, 'sharePct':100, 'premium':8000, 'riCommPct':12.5, 'taxPct':0,
                 'foreignBroker':'Howden Specialty Limited'}], limitOfLiability=1000000, deductibles='As original',
    originalConditions='As original', occupation='Office', construction='Concrete', constructionSelections=['A2 Class'],
    sumInsured=[{'category':'Building', 'amount':1000000}], lossAdvisedDate='2025-12-01', lossRecordYears=5,
    originalPremium=10000, paymentTermsDays=90, riCommPct=17, taxPct=1, manualTwRef='TW26SM010001')

matrix = 0
for year in [2026, 2027, 2028, 2100, 2400]:
    for month in range(1, 13):
        last = calendar.monthrange(year, month)[1]
        end = date(year, month, last)
        for day in [1, 15, last]:
            raw = copy.deepcopy(ready)
            raw['policyFrom'] = date(year, month, day).isoformat()
            item = ri(raw)
            assert item['sourceBaseDate']==raw['policyFrom'] and item['baseDate']==end.isoformat()
            assert item['contractDueDate']==(end+timedelta(days=120)).isoformat()
            assert item['dueDate']==(end+timedelta(days=110)).isoformat()
            assert item['termsDays']==120 and item['accountingLeadDays']==10
            matrix += 1
check('180 start/middle/end dates agree with independent calendar arithmetic, including leap centuries', matrix==180)
check('January 1 and January 31 share May 31 AUW payment and May 21 accounting dates', all(
    ri({**ready, 'policyFrom':day})['contractDueDate']=='2026-05-31' and ri({**ready, 'policyFrom':day})['dueDate']=='2026-05-21'
    for day in ['2026-01-01', '2026-01-31']))
for raw_date in ['', '2026-02-30', '2026-13-01', 'bad', None]:
    check('invalid AUW source date is pending review '+repr(raw_date), ri({**ready, 'policyFrom':raw_date})['dueDate']=='')
check('leap-February uses February 29', month_end_date('2028-02-01')=='2028-02-29')
for row_terms in [None, 15, 90, 365, 'bad']:
    raw = copy.deepcopy(ready)
    raw['reinsurers'][0]['paymentTermsDays'] = row_terms
    normalized = normalize_draft(raw)
    check('AUW terms are always 120 despite row value '+repr(row_terms), not normalized['errors']
        and normalized['value']['reinsurers'][0]['paymentTermsDays']==120 and ri(raw)['dueDate']=='2026-05-21')
for name in [TARGET.lower(), '  '+TARGET.replace(' ', '  ')+'  ']:
    raw = copy.deepcopy(ready)
    raw['reinsurers'][0]['name'] = name
    check('AUW date matching tolerates case and whitespace', ri(raw)['contractDueDate']=='2026-05-31')
for name in [TARGET.replace('0609', '0610'), TARGET.replace(' (Facility)', ''), 'Other (Facility)']:
    raw = copy.deepcopy(ready)
    raw['reinsurers'][0]['name'] = name
    # 2026-10-16 92 項規則：普通再保人天數須明確填寫、沒有預設繼承（缺漏即待確認），故此處明確填 90 天
    raw['reinsurers'][0]['paymentTermsDays'] = 90
    item = ri(raw)
    # 2026-10-16：逾期改以實際約定到期日判斷，所有帳款都帶 contractDueDate；此處改驗它是生效日＋90，而非 AUW 月底＋120
    check('unrelated facilities keep date-based terms '+name, item['dueDate']=='2026-03-22'
        and item['baseDate']=='2026-01-01' and item['contractDueDate']=='2026-04-01' and item.get('paymentRule')!='auw_month_end_120')

def cedant(raw):
    return next(row for row in build_payment_schedule(raw)['items'] if row['partyType']=='cedant')
check('AUW case Cedant uses its own 90 days and 15-day accounting lead', cedant(ready)['termsDays']==90
    and cedant(ready)['dueDate']=='2026-03-17')
ordinary = copy.deepcopy(ready)
ordinary['reinsurers'][0].update(name='QA Ordinary Reinsurer', paymentTermsDays=30)
# 2026-10-16 92 項規則（第 33 項）：Cedant 一律用自己填的天數，不再沿用最短再保人天數（取代 10/06 舊案「最短再保期限」算法）
check('unmarked historical cases also use the Cedant own days, not the minimum reinsurer term', cedant(ordinary)['termsDays']==90
    and cedant(ordinary)['dueDate']=='2026-03-17')
new = {**ordinary, 'cedantTermsBasis':'case'}
check('new-case Cedant is independent of a shorter reinsurer term', cedant(new)['termsDays']==90
    and cedant(new)['dueDate']=='2026-03-17' and ri(new)['dueDate']=='2026-01-21')
check('fixed Facility Cedant days ignore obsolete raw exceptions', cedant({**new, 'paymentTermsDays':105})['dueDate']=='2026-04-01')

old = copy.deepcopy(ready)
old['reinsurers'][0]['paymentTermsDays'] = None
value = normalize_draft(old)['value']
check('canonical signatures permit old posted AUW null terms to become fixed 120 without false locks',
    same_content(payment_terms_signature(old), payment_terms_signature(value)))
for premium in [8000, -800]:
    raw = copy.deepcopy(ready)
    raw.update(parentTwRef='TWAUW2601001', endoEffectiveDate='2026-03-15', endorsementAnnouncedAt='2026-03-01T00:00:00+00:00', originalPremium=1000 if premium>0 else -1000)
    raw['reinsurers'][0]['premium'] = premium
    item = ri(raw)
    check('positive and negative endorsements use their March effective month '+str(premium), item['baseDate']=='2026-03-31'
        and item['contractDueDate']=='2026-07-29' and item['dueDate']=='2026-07-19')
    check('endorsement keys and premium signs are preserved '+str(premium), item['scheduleKey']=='case-effective-date:reinsurer:r1'
        and item['amount']==(7000 if premium>0 else -700))
raw['endoEffectiveDate'] = ''
check('missing endorsement effective date does not silently fall back to policy date', ri(raw)['dueDate']=='')

installments = copy.deepcopy(ready)
installments.update(installmentEnabled=True, performanceInstallments=[
    {'id':'I1', 'performanceMonth':'2026-01', 'paymentBaseDate':'2026-01-01', 'premium':4000,
     'paymentTermsDays':15, 'reinsurerPaymentTerms':{'r1':35}},
    {'id':'I2', 'performanceMonth':'2026-02', 'paymentBaseDate':'2026-02-28', 'premium':6000,
     'paymentTermsDays':300, 'reinsurerPaymentTerms':{'r1':400}}])
one, two = ri(installments, installment='I1'), ri(installments, installment='I2')
check('each installment uses its own month-end and ignores terms overrides for AUW', one['dueDate']=='2026-05-21'
    and two['dueDate']==add('2026-02-28', 110) and one['termsDays']==two['termsDays']==120)
check('installment amount allocation and matching keys are preserved', one['amount']==2800 and two['amount']==4200
    and one['scheduleKey']=='I1:reinsurer:r1' and two['scheduleKey']=='I2:reinsurer:r1')
check('screen reminders use the accounting date seven days before and on May 21', reminder_kind(ri(ready), '2026-05-14')=='seven_days_before'
    and reminder_kind(ri(ready), '2026-05-21')=='due_today')
# 2026-10-16 92 項規則（第 83、84 項）：財務提醒信改以實際到期日（AUW 為月底＋120 的 5/31）前 7 日、到期日寄送；畫面仍維持提前 10 日
check('finance e-mail first notice follows Accounting May21, with contract due May31', due_kind(ri(ready),'2026-05-21',{})=='seven_days_before'
    and due_kind(ri(ready),'2026-05-31',{})=='due_today' and due_kind(ri(ready),'2026-05-14',{})=='' and due_kind(ri(ready),'2026-05-24',{})=='')
check('contract payment day does not trigger a duplicate due-today notice', reminder_kind(ri(ready), '2026-05-31')!='due_today')

user = get_user_model().objects.create_user(username='zz.auw.dates', password='AUW-Dates-Password-9!')
person = Personnel.objects.create(name=ready['ae'], department='admin', role_code='admin', auth_user_id=str(user.pk),
    account_status='active', created_by='qa', updated_by='qa')
client = Client(enforce_csrf_checks=True, HTTP_HOST='localhost', raise_request_exception=False)
def call(method, url, body=None):
    client.get('/api/auth/csrf')
    kw = {'HTTP_X_CSRFTOKEN':client.cookies['csrftoken'].value}
    if body is not None:
        kw.update(data=json.dumps(body), content_type='application/json')
    return getattr(client, method)(url, **kw)
assert call('post', '/api/auth/login', {'username':user.username, 'password':'AUW-Dates-Password-9!'}).status_code==200
response = call('post', '/api/cases', {'case':ready})
assert response.status_code==201, response.content
case = Case.objects.get(case_uid=response.json()['case']['caseUid'])
check('POST marks new cases for independent Cedant terms', case.payload['cedantTermsBasis']=='case')
case.status = 'posted'
case.tw_ref = 'TWADP2601001'
case.payload['transactions'] = build_premium_transactions({**case.payload, 'twRef':case.tw_ref})
case.save()
def ledger():
    return next(row for row in call('get', '/api/accounting').json()['rows']
                if row['caseUid']==str(case.case_uid) and row['partyType']=='reinsurer')
before = copy.deepcopy(case.payload)
item = ledger()
case.refresh_from_db()
check('Accounting exposes fixed month-end, internal date and contract date', item['baseDate']=='2026-01-31'
    and item['dueDate']=='2026-05-21' and item['contractDueDate']=='2026-05-31' and item['termsDays']==120)
check('reading recalculated dates does not rewrite existing payload, transactions or entries', case.payload==before)
loaded = call('get', '/api/cases?caseUid='+str(case.case_uid)).json()['case']['payload']
response = call('put', '/api/cases', {'caseUid':str(case.case_uid), 'rowVersion':case.row_version, 'case':loaded})
check('editing a posted AUW case with unchanged terms remains allowed', response.status_code==200)
case.refresh_from_db()
changed = copy.deepcopy(case.payload)
changed['paymentTermsDays'] = 105
response = call('put', '/api/cases', {'caseUid':str(case.case_uid), 'rowVersion':case.row_version, 'case':changed})
case.refresh_from_db();check('posted fixed Cedant terms canonicalize to90', response.status_code==200 and case.payload['paymentTermsDays']==90)
changed = copy.deepcopy(case.payload)
changed.pop('cedantTermsBasis')
response = call('put', '/api/cases', {'caseUid':str(case.case_uid), 'rowVersion':case.row_version, 'case':changed})
# 2026-10-14：伺服器自己保留「新案算法」旗標；漏傳旗標的存檔不會改回舊算法，也不必被擋下
case.refresh_from_db()
check('posted cases cannot silently switch back to the old Cedant rule', response.status_code==200
      and case.payload.get('cedantTermsBasis')=='case')
def post(action, **kw):
    case.refresh_from_db()
    return call('post', '/api/accounting', {'action':action, 'caseUid':str(case.case_uid), 'rowVersion':case.row_version, **kw})
def pay(key, amount):
    return post('record_payment', note='QA synthetic registration', scheduleKey=key, paymentDate='2026-05-31', amount=amount)
cedant_row = next(row for row in call('get', '/api/accounting').json()['rows']
                  if row['caseUid']==str(case.case_uid) and row['partyType']=='cedant')
# 2026-10-20 四類統一：AUW 付款前須先登錄整期 Cedant 全額收款並逐筆人工銷帳
response = pay(item['scheduleKey'], 7000)
check('AUW payment is blocked before the whole Cedant installment is received and settled', response.status_code==409 and ledger()['paid']==0)
check('Cedant receipt is recorded in full', pay(cedant_row['scheduleKey'], cedant_row['amount']).status_code==200)
check('full Cedant receipt automatically releases AUW payment',ledger()['paymentAllowed'])
case.refresh_from_db()
t1 = next(t['txNo'] for t in case.payload['transactions'] if str(t.get('legType','')).startswith('Leg 1'))
response = post('confirm_facility_settlement', txNo=t1, note='QA AUW Cedant write-off')
check('Cedant T1 auto-settles and manual confirmation is retired',response.status_code==400)
# 2026-10-16 92 項規則（第 52 項）：保費每次須登錄整筆餘額，不得部分付款（取代舊的 2500＋4500 分次付款）
response = pay(item['scheduleKey'], 2500)
check('partial AUW premium payment is rejected', response.status_code==400 and ledger()['paid']==0)
check('full cash entry matches the same AUW schedule', pay(item['scheduleKey'], 7000).status_code==200)
paid = ledger()
# 2026-10-20 四類統一：付款過原到期日（5/31）後，即使已登錄全額付款，未經人工確認仍顯示逾期；原期限不重算
check('fully paid AUW automatically settles, stops overdue and keeps original dates', paid['paid']==7000 and paid['outstanding']==0
    and paid['settlement']=='settled' and paid['paymentStatus']=='settled' and paid['contractDueDate']=='2026-05-31' and paid['dueDate']=='2026-05-21')
case.refresh_from_db()
entry = next(e for e in case.payload['paymentEntries'] if e.get('scheduleKey')==item['scheduleKey'])
# 2026-10-16 92 項規則：保費收付改為逐筆交易登錄（record_payment 轉為單筆匯款批次），更正須整筆沖回該匯款
response = call('post', '/api/accounting', {'action':'reverse_payment', 'caseUid':str(case.case_uid),
    'rowVersion':case.row_version, 'entryId':entry['id'], 'paymentDate':'2026-06-01'})
check('single-entry reversal cannot split a remittance', response.status_code==400 and response.json()['error']=='batch_reverse_required')
response = call('post', '/api/accounting', {'action':'reverse_batch_payment', 'batchId':entry['batchId'], 'paymentDate':'2026-06-01',
    'cases':[{'caseUid':str(case.case_uid), 'rowVersion':case.row_version}], 'note':'QA reversal'})
partial = ledger()
check('settled cash cannot be reversed or change its contractual date', response.status_code==409 and response.json()['error']=='settled_amount_locked'
    and partial['paid']==7000 and partial['outstanding']==0 and partial['contractDueDate']=='2026-05-31')
case.refresh_from_db()
check('rejected reversal creates no new cash entry', [e.get('entryType') for e in case.payload['paymentEntries'] if e.get('scheduleKey')==item['scheduleKey']]==['payment'])
case.refresh_from_db()
check('payment and reversal operations preserve the original SoA transactions', [(x['txNo'],x['amount']) for x in case.payload['transactions']]==[(x['txNo'],x['amount']) for x in before['transactions']])
print(f'{len(checks)}/{len(checks)} AUW payment terms checks passed', flush=True)
