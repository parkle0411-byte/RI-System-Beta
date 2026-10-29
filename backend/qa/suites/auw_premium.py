"""AUW editable deductions, fixed zero tax, persistence and posting in disposable QA."""
import copy
import json
import os
import uuid
from datetime import datetime, timezone as dt_timezone
from django.contrib.auth import get_user_model
from django.test import Client
from cases.models import Case, CaseDocument, ReferenceSequence
from cases.draft import normalize_draft, validate_announce_ready
from cases.manual_reference import MANUAL_TW_REF_REINSURER as TARGET
from cases.calc.accounting import calc_legs_for_reinsurer, build_premium_transactions
from cases.calc.payment_terms import build_payment_schedule
from cases.workflow import build_endorsement_payload, build_renewal_payload
from masterdata.models import MasterRecord
from personnel.models import Personnel

assert os.environ.get('RI_DISPOSABLE_QA') == 'true'
checks = []
def check(name, condition):
    assert condition, name
    checks.append(name)
    print('PASS ' + name, flush=True)

user = get_user_model().objects.create_user(username='zz.auw.defaults', password='AUW-Defaults-Password-9!')
person = Personnel.objects.create(name='QA AUW Default AE', department='admin', role_code='admin',
    auth_user_id=str(user.pk), account_status='active', created_by='qa', updated_by='qa')
for kind, name in [('ae', person.name), ('class', 'Property'), ('reinsured', 'QA AUW Cedant'),
                   ('reinsurer', TARGET), ('foreign_broker', 'Howden Specialty Limited')]:
    MasterRecord.objects.get_or_create(entity_type=kind, name=name, defaults={'created_by':'qa', 'updated_by':'qa'})
client = Client(enforce_csrf_checks=True, HTTP_HOST='localhost', raise_request_exception=False)
def call(method, url, body=None):
    client.get('/api/auth/csrf')
    kwargs = {'HTTP_X_CSRFTOKEN': client.cookies['csrftoken'].value}
    if body is not None:
        kwargs.update(data=json.dumps(body), content_type='application/json')
    return getattr(client, method)(url, **kwargs)
assert call('post', '/api/auth/login', {'username':user.username, 'password':'AUW-Defaults-Password-9!'}).status_code == 200
ready = dict(reinsuranceStructure='QS', ae=person.name, currency='TWD', classOfBusiness='Property',
    classCode='ADF', newOrRenew='New', typePrefix='Fire', reinsured='QA AUW Cedant', originalInsured='QA AUW Defaults', originalInsuredCn='合成測試被保險人', reinsuredRetention='Synthetic retention',
    policyFrom='2043-01-01', policyTo='2044-01-01', interest='Buildings', situations=[{'address':'QA Road', 'postcode':'100'}],
    reinsurers=[{'name':TARGET, 'sharePct':100, 'premium':8000, 'riCommPct':12.5, 'taxPct':1,
                 'foreignBroker':'Howden Specialty Limited'}], limitOfLiability=1000000, deductibles='As original',
    basisOfValuation='Replacement Value',originalConditions='As original', occupation='Office', construction='Concrete', constructionSelections=['A2 Class'],
    sumInsured=[{'category':'Building', 'amount':1000000}], lossAdvisedDate='2042-12-01', lossRecordYears=5,
    originalPremium=10000, paymentTermsDays=30, riCommPct=17, taxPct=1, manualTwRef='TW43SM010001')
_ref_seq = [0]
def _unique_ref(raw):
    # 2026-10-08 起 AUW 手填 Ref 不可與其他案件重複；同一份範本重複建案時各給一組編號
    if raw.get('manualTwRef') == 'TW43SM010001':
        _ref_seq[0] += 1
        raw = {**raw, 'manualTwRef': 'TW43SM010001-' + str(_ref_seq[0])}
    return raw
def create(raw):
    raw = _unique_ref(raw)
    response = call('post', '/api/cases', {'case':raw})
    assert response.status_code == 201, response.content
    return Case.objects.get(case_uid=response.json()['case']['caseUid'])
def save(row, raw):
    row.refresh_from_db()
    response = call('put', '/api/cases', {'caseUid':str(row.case_uid), 'rowVersion':row.row_version, 'case':raw})
    row.refresh_from_db()
    return response
def announce(row):
    for kind in ['offer', 'signed']:
        CaseDocument.objects.create(case=row, kind=kind, reinsurers=[TARGET] if kind=='signed' else [],
            filename=kind+'.pdf', content_type='application/pdf', byte_size=5, sha256='0'*64,
            storage_key='qa-'+str(uuid.uuid4()), is_selected=True, uploaded_by='qa')
    row.refresh_from_db()
    return call('post', '/api/case-announce', {'caseUid':str(row.case_uid), 'rowVersion':row.row_version,
        'confirmed':True, 'documentIds':[str(pk) for pk in CaseDocument.objects.filter(case=row).values_list('pk', flat=True)]})

for rate in [0, 5, 10, 12.5, 100, '7.2500']:
    raw = copy.deepcopy(ready)
    raw['reinsurers'][0].update(riCommPct=rate, taxPct=99)
    row = create(raw)
    stored = row.payload['reinsurers'][0]
    check('POST preserves AUW deductions '+str(rate)+' and enforces zero tax', stored['riCommPct']==float(rate) and stored['taxPct']==0)
    loaded = call('get', '/api/cases?caseUid='+str(row.case_uid)).json()['case']['payload']['reinsurers'][0]
    check('GET retains saved AUW deductions '+str(rate), loaded==stored)
check('Cedant commission and tax stay independent', row.payload['riCommPct']==17 and row.payload['taxPct']==1)
for rate in [None, '']:
    raw = copy.deepcopy(ready)
    raw['reinsurers'][0]['riCommPct'] = rate
    row = create(raw)
    check('explicitly blank AUW deductions remain blank in a draft', row.payload['reinsurers'][0]['riCommPct'] is None)
    check('blank deductions must be completed before Announce', any(issue['field']=='reinsurers.0.riCommPct' for issue in validate_announce_ready(row.payload)))
raw = copy.deepcopy(ready)
del raw['reinsurers'][0]['riCommPct']
check('API does not apply a selection default while saving an omitted rate', create(raw).payload['reinsurers'][0]['riCommPct'] is None)
for rate in [-1, 101, 'invalid', {'invalid':True}]:
    raw = copy.deepcopy(ready)
    raw['reinsurers'][0]['riCommPct'] = rate
    response = call('post', '/api/cases', {'case':raw})
    check('invalid AUW deductions are rejected '+repr(rate), response.status_code==400 and response.json()['error']=='validation_failed')

row = create(ready)
raw = copy.deepcopy(row.payload)
raw['reinsurers'][0].update(riCommPct=7.25, taxPct=5)
check('PUT accepts a changed AUW rate and keeps tax zero', save(row, raw).status_code==200
    and row.payload['reinsurers'][0]['riCommPct']==7.25 and row.payload['reinsurers'][0]['taxPct']==0)
mixed = copy.deepcopy(ready)
mixed['reinsurers'][0]['sharePct'] = 50
mixed['reinsurers'].insert(0, {'name':'QA Ordinary Reinsurer', 'sharePct':50, 'premium':6000, 'riCommPct':13, 'taxPct':3})
row = create(mixed)
normal, auw = row.payload['reinsurers']
check('mixed case preserves independent row deductions and taxes', normal['riCommPct']==13 and normal['taxPct']==3 and auw['riCommPct']==12.5 and auw['taxPct']==0)
variant = copy.deepcopy(ready)
variant['reinsurers'][0]['name'] = '  '+TARGET.lower().replace(' ', '  ')+'  '
value = normalize_draft(variant)['value']['reinsurers'][0]
check('AUW matching tolerates whitespace and case while retaining custom deductions', value['riCommPct']==12.5 and value['taxPct']==0)
for name in [TARGET.replace('0609','0610'), TARGET.replace(' (Facility)',''), 'Other (Facility)']:
    raw = copy.deepcopy(ready)
    raw['reinsurers'][0]['name'] = name
    value = normalize_draft(raw)['value']['reinsurers'][0]
    check('other facility names retain deductions and tax: '+name, value['riCommPct']==12.5 and value['taxPct']==1)

row = create(ready)
check('a custom AUW deduction is Announce-ready', not validate_announce_ready(row.payload))
legs = calc_legs_for_reinsurer(row.payload, row.payload['reinsurers'][0])
check('8000 premium at 12.5% gives 1000 deductions and 7000 payable with zero tax', legs['reinsurerRi']==1000 and legs['reinsurerTax']==0 and legs['leg2']==7000)
schedule = build_payment_schedule(row.payload)
check('payment schedule uses the custom AUW net premium', next(item for item in schedule['items'] if item['partyType']=='reinsurer')['amount']==7000)
response = announce(row)
row.refresh_from_db()
check('real Announce preserves custom deductions and both references', response.status_code==200 and row.status=='posted'
    and row.payload['reinsurers'][0]['riCommPct']==12.5 and row.payload['manualTwRef'].startswith('TW43SM010001') and bool(row.tw_ref))
# Put this isolated fixture in its own production month and exercise real closing.
row.announced_at = datetime(2043, 1, 10, 4, tzinfo=dt_timezone.utc)
row.save(update_fields=['announced_at'])
preview = call('get', '/api/production-report?month=2043-01').json()
response = call('post', '/api/production-report', {'action':'generate', 'month':'2043-01',
    'sourceSignature':preview['sourceSignature']})
assert response.status_code == 201, response.content
report = response.json()['report']
response = call('post', '/api/production-report', {'action':'close', 'month':'2043-01',
    'reportUid':report['reportUid'], 'rowVersion':report['rowVersion'], 'sourceSignature':preview['sourceSignature']})
row.refresh_from_db()
check('Production closing succeeds with the custom AUW rate', response.status_code==200 and row.status=='closed')
check('persisted SoA posting uses 7000 for reinsurer Leg 2', row.payload['transactions'][1]['amount']==7000)
accounting = call('get', '/api/accounting').json()
payments = [item for item in accounting['rows'] if item['caseUid']==str(row.case_uid) and item['partyType']=='reinsurer']
check('Accounting payment row uses the posted custom rate', len(payments)==1 and payments[0]['amount']==7000)
tx = [item for item in accounting['transactionRows'] if item['caseUid']==str(row.case_uid) and item['legType']=='Leg 2']
check('Accounting SoA exposes custom-rate amount', len(tx)==1 and tx[0]['amount']==7000)
for builder in [lambda:build_endorsement_payload(row.payload, row.tw_ref, 0), lambda:build_renewal_payload(row.payload, row.tw_ref)]:
    value = builder()
    check('existing workflow copies preserve the agreed AUW rate', value['reinsurers'][0]['riCommPct']==12.5)

legacy = create(ready)
legacy.payload['reinsurers'][0]['taxPct'] = 1
legacy.save()
issues = validate_announce_ready(legacy.payload)
check('legacy nonzero AUW tax remains blocked, custom deductions are allowed', {issue['field'] for issue in issues}=={'reinsurers.0.taxPct'})
seq_before = list(ReferenceSequence.objects.values())
response = announce(legacy)
check('tax validation still blocks Announce before reference allocation', response.status_code==400
    and response.json()['error']=='case_not_ready' and list(ReferenceSequence.objects.values())==seq_before)
check('saving legacy tax fixes only tax and retains deductions', save(legacy, legacy.payload).status_code==200
    and legacy.payload['reinsurers'][0]['riCommPct']==12.5 and not validate_announce_ready(legacy.payload))
refund = copy.deepcopy(ready)
refund.update(parentTwRef=row.tw_ref, originalPremium=-1000)
refund['reinsurers'][0]['premium'] = -800
result = normalize_draft(refund, allow_negative_premiums=True)
check('return premium retains the manually agreed AUW rate', not result['errors'] and result['value']['reinsurers'][0]['riCommPct']==12.5)
legs = calc_legs_for_reinsurer(result['value'], result['value']['reinsurers'][0])
check('return premium -800 at 12.5% gives -100 deductions and -700 payable', legs['reinsurerRi']==-100 and legs['reinsurerTax']==0 and legs['leg2']==-700)
print(f'{len(checks)}/{len(checks)} AUW premium API checks passed', flush=True)
