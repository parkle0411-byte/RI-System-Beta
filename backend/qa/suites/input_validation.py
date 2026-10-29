"""Payment rounding and malformed input regression tests; all writes roll back."""
import copy
import json
from decimal import Decimal
from uuid import uuid4

from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.db import transaction
from django.test import Client, override_settings

from audit.models import AuditLog, EntitySnapshot
from cases.calc.payment_terms import build_payment_schedule
from cases.draft import normalize_draft
from cases.models import Case
from fxrates.models import CURRENCIES, FxRate
from masterdata.models import MasterRecord
from personnel.models import Personnel

checks = []
def check(name, condition, detail=''):
    checks.append((name, bool(condition)))
    print(('PASS ' if condition else 'FAIL ')+name+(' '+str(detail) if not condition else ''),flush=True)

def counts():
    return (MasterRecord.objects.count(), FxRate.objects.count(), EntitySnapshot.objects.count(), AuditLog.objects.count())

with transaction.atomic(), override_settings(AUDIT_LOG_PAUSED=True):
    tag = uuid4().hex[:12]
    user = get_user_model().objects.create_user(username='zz.validation.'+tag,password='Validation-Test-9')
    principal = Personnel.objects.create(name='ZZ Validation '+tag,department='admin',role_code='admin',
        auth_user_id=str(user.pk),account_status='active',created_by='qa',updated_by='qa')
    client = Client(enforce_csrf_checks=True,HTTP_HOST='localhost',raise_request_exception=False)
    client.force_login(user)
    client.get('/api/auth/csrf')
    def call(method,url,body=None,raw=None):
        return getattr(client,method)(url,data=raw if raw is not None else json.dumps(body),content_type='application/json',
            HTTP_X_CSRFTOKEN=client.cookies['csrftoken'].value)

    before = counts()
    before_password = user.password
    before_personnel = (principal.row_version,principal.must_change_password)
    for method,url in [('post','/api/master-data'),('put','/api/master-data'),('post','/api/fx-rates'),
                       ('post','/api/auth/change-password'),('post','/api/auth/login')]:
        for body in [[1],[],None,True,42,'invalid']:
            cache.clear()
            response = call(method,url,body)
            check(f'{method} {url}: non-object {body!r} -> 400 invalid_body',response.status_code==400 and response.json().get('error')=='invalid_body',response.status_code)
        response = call(method,url,raw='{"broken":')
        check(f'{method} {url}: invalid JSON syntax -> 400',response.status_code==400,response.status_code)
    user.refresh_from_db(); principal.refresh_from_db()
    check('bad bodies leave master, FX, snapshots, Audit and password unchanged',counts()==before and user.password==before_password and (principal.row_version,principal.must_change_password)==before_personnel)

    month = '2091-01'
    def rates(usd=30):
        return dict(yearMonth=month,rates=[dict(currency=c,rate=usd if c=='USD' else 1,rowVersion=None) for c in CURRENCIES])
    for bad in [None,[],True,17,'invalid']:
        body = rates(); body['rates'][0] = bad
        response = call('post','/api/fx-rates',body)
        check(f'FX non-object rate item {bad!r} -> 400 invalid_rate_item',response.status_code==400 and response.json().get('error')=='invalid_rate_item',response.status_code)
    for bad in ['NaN','sNaN','Infinity','-Infinity','abc',None,True,{},[],0,-1,1000.01,'0.0000001','1e-1000']:
        response = call('post','/api/fx-rates',rates(bad))
        check(f'FX invalid/non-finite/rounded-zero rate {bad!r} -> 400 invalid_rate',response.status_code==400 and response.json().get('error')=='invalid_rate',response.status_code)
    # Normal JSON exponent can overflow a float without using invalid NaN tokens.
    raw = json.dumps(rates()).replace('"rowVersion": null','"rowVersion": 1e999',1)
    response = call('post','/api/fx-rates',raw=raw)
    check('FX overflowing version -> 400 invalid_version',response.status_code==400 and response.json().get('error')=='invalid_version',response.status_code)
    raw = '{"id":1e999,"rowVersion":1,"entityType":"class","name":"bad"}'
    response = call('put','/api/master-data',raw=raw)
    check('master overflowing id -> 400 version_required',response.status_code==400 and response.json().get('error')=='version_required',response.status_code)
    for bad in [[1],'text',True,7,None]:
        response = call('post','/api/master-data',dict(entityType='reinsurer',name='ZZ Ratings '+tag,payload={'ratings':[bad]}))
        check(f'master non-object rating {bad!r} -> 400',response.status_code==400 and response.json().get('error')=='invalid_fixed_clauses',response.status_code)
    check('all invalid FX/master fields leave no writes',counts()==before)

    # A bad item late in an edit must leave all six existing rates untouched.
    response = call('post','/api/fx-rates',rates('30.1234567'))
    usd = FxRate.objects.filter(year_month=month,currency='USD').first()
    snapshot = EntitySnapshot.objects.filter(entity_type='fx_rate',entity_id=str(usd.pk)).order_by('-id').first() if usd else None
    check('valid FX rounding agrees in response, database and snapshot',response.status_code==200 and usd.rate==Decimal('30.123457') and next(r for r in response.json()['rates'] if r['currency']=='USD')['rate']==30.123457 and snapshot and snapshot.snapshot_data['rate']==30.123457,response.content[:200])
    saved = list(FxRate.objects.filter(year_month=month).order_by('currency').values('id','rate','row_version'))
    current = {r.currency:r.row_version for r in FxRate.objects.filter(year_month=month)}
    body = rates(31)
    for row in body['rates']: row['rowVersion'] = current[row['currency']]
    body['rates'][-1]['rate'] = 'NaN'
    snapshot_count = EntitySnapshot.objects.count()
    response = call('post','/api/fx-rates',body)
    check('late invalid FX edit rejects entire month and preserves versions/snapshots',response.status_code==400 and list(FxRate.objects.filter(year_month=month).order_by('currency').values('id','rate','row_version'))==saved and EntitySnapshot.objects.count()==snapshot_count)
    with transaction.atomic():
        body = rates('0.000001'); body['yearMonth']='2091-02'
        response = call('post','/api/fx-rates',body)
        check('minimum positive six-decimal FX rate is accepted',response.status_code==200 and FxRate.objects.get(year_month='2091-02',currency='USD').rate==Decimal('0.000001'),response.content[:150])
        transaction.set_rollback(True)
    with transaction.atomic():
        body = rates('1000'); body['yearMonth']='2091-03'
        response = call('post','/api/fx-rates',body)
        check('maximum FX rate 1000 is accepted',response.status_code==200,response.content[:150])
        transaction.set_rollback(True)

    # Valid master CRUD and change-password keep working after bad requests.
    response = call('post','/api/master-data',dict(entityType='class',name='ZZ Valid '+tag))
    check('valid master creation still works',response.status_code==201,response.content[:150])
    master = MasterRecord.objects.get(name='ZZ Valid '+tag)
    response = call('put','/api/master-data',dict(id=master.pk,rowVersion=1,entityType='class',name=master.name+' edited'))
    check('valid master update still works',response.status_code==200,response.content[:150])

    helpers = {}
    exec(open('qa/suites/accounting_api.py').read().split('\ntry:\n')[0],helpers)
    payload = normalize_draft(helpers['ready']())['value']
    case = Case.objects.create(tw_ref='ZZ-VALIDATION-'+tag,status='posted',currency='USD',reinsurance_structure='QS',payload=payload,created_by='qa',updated_by='qa')
    item = next(i for i in build_payment_schedule(payload)['items'] if i['partyType']=='cedant' and i['dueDate'])
    def pay(amount,version=None):
        return call('post','/api/accounting',dict(note='QA synthetic registration', action='record_payment',caseUid=str(case.case_uid),scheduleKey=item['scheduleKey'],
            rowVersion=case.row_version if version is None else version,amount=amount,paymentDate='2026-10-06'))
    for amount in [0.001,'0.001',0.004,0.0000001,'NaN','Infinity',0,-1,1e308]:
        with transaction.atomic():
            before_payload = copy.deepcopy(case.payload)
            before_version = case.row_version
            snapshot_count = EntitySnapshot.objects.count()
            response = pay(amount)
            current_case = Case.objects.get(pk=case.pk)
            check(f'payment {amount!r} rejected with no entry/version/snapshot change',response.status_code==400 and response.json().get('error')=='invalid_payment' and current_case.payload==before_payload and current_case.row_version==before_version and EntitySnapshot.objects.count()==snapshot_count,response.status_code)
            transaction.set_rollback(True)
    # 2026-10-16 92 項規則：保費只能逐筆交易、整筆登錄餘額；只有賠款可部分收付。
    # 金額取位（到分）與超付檢查改用一筆賠款應收來測（record_transaction_payments）。
    from cases.calc.accounting import build_premium_transactions
    claim_payload = copy.deepcopy(payload)
    claim_payload['transactions'] = build_premium_transactions({**claim_payload,'twRef':'ZZ-VALIDATION-C-'+tag}) + [
        {'txNo':'ZZ-VAL-C1','source':'claim','claimId':1,'paymentId':1,'legType':'Claim Leg 1','reinsurer':claim_payload['reinsurers'][0]['name'],'reinsurerIdx':0,
         'label':'Claim','amount':250,'settlement':'open','createdAt':'2026-10-01T02:00:00+00:00','dueDate':'2026-10-16'}]
    claim_case = Case.objects.create(tw_ref='ZZ-VALIDATION-C-'+tag,status='closed',currency='USD',reinsurance_structure='QS',payload=claim_payload,created_by='qa',updated_by='qa')
    def pay_claim(amount,version=None):
        claim_case.refresh_from_db()
        return call('post','/api/accounting',dict(note='QA synthetic registration', action='record_transaction_payments',paymentDate='2026-10-06',amount=amount,
            allocations=[dict(caseUid=str(claim_case.case_uid),txNo='ZZ-VAL-C1',rowVersion=claim_case.row_version if version is None else version,amount=amount)]))
    def last_entry():
        return Case.objects.get(pk=claim_case.pk).payload['paymentEntries'][-1]
    for amount,expected in [(0.005,0.01),(0.01,0.01),(12.345,12.35),('100.005',100.01)]:
        with transaction.atomic():
            snapshot_count = EntitySnapshot.objects.count(); version = Case.objects.get(pk=claim_case.pk).row_version
            response = pay_claim(amount)
            check(f'claim payment {amount!r} rounds to {expected} and saves snapshot',response.status_code==200 and abs(last_entry()['amount'])==expected
                  and Case.objects.get(pk=claim_case.pk).row_version==version+1 and EntitySnapshot.objects.count()>snapshot_count,response.content[:150])
            transaction.set_rollback(True)
    with transaction.atomic():
        # Raw balance+0.0049 used to reject even when its stored amount equals balance.
        response = pay_claim(250.0049)
        check('overpayment check uses the rounded amount actually stored',response.status_code==200 and abs(last_entry()['amount'])==250,response.content[:150])
        transaction.set_rollback(True)
    with transaction.atomic():
        response = pay_claim(250.0051)
        check('rounded payment above balance still rejects overpayment',response.status_code==400 and response.json().get('error')=='overpayment',response.content[:150])
        transaction.set_rollback(True)
    response = pay_claim(0.01,version=Case.objects.get(pk=claim_case.pk).row_version+10)
    check('stale payment version still returns 409',response.status_code==409 and response.json().get('error')=='version_conflict',response.content[:150])
    premium_tx = next(t for t in claim_payload['transactions'] if t['legType']=='Leg 1')
    claim_case.refresh_from_db()
    response = call('post','/api/accounting',dict(note='QA synthetic registration', action='record_transaction_payments',paymentDate='2026-10-06',amount=1,
        allocations=[dict(caseUid=str(claim_case.case_uid),txNo=premium_tx['txNo'],rowVersion=claim_case.row_version,amount=1)]))
    check('a partial premium payment is rejected (premiums are recorded in full)',response.status_code==400,response.content[:150])

    response = call('post','/api/auth/change-password',dict(currentPassword='Validation-Test-9',newPassword='New-Validation-Pass-8'))
    user.refresh_from_db()
    check('valid change-password still works',response.status_code==200 and user.check_password('New-Validation-Pass-8'),response.content[:150])
    response = client.get('/api/app-context')
    check('session stays authenticated after password change',response.status_code==200)
    cache.clear()
    response = call('post','/api/auth/login',dict(username=user.username,password='New-Validation-Pass-8'))
    check('valid login still works',response.status_code==200,response.content[:150])
    check('Audit remains paused through validation and normal writes',AuditLog.objects.count()==before[-1])
    transaction.set_rollback(True)

failed = [name for name,ok in checks if not ok]
print(f'{len(checks)-len(failed)}/{len(checks)} passed; database changes rolled back',flush=True)
assert not failed, failed
