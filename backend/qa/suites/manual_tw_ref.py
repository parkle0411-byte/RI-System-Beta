"""Exercise manual reference persistence and conditional announcement through real APIs."""
import copy
import json
import os
import uuid
from django.contrib.auth import get_user_model
from django.test import Client
from django.utils import timezone
from cases.models import Case, CaseDocument, ReferenceSequence
from cases.draft import normalize_draft, validate_announce_ready
from cases.manual_reference import MANUAL_TW_REF_REINSURER as TARGET
from cases.calc.accounting import build_premium_transactions
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

user = get_user_model().objects.create_user(username='zz.manual.ref', password='Manual-Ref-Password-9!')
person = Personnel.objects.create(name='QA Manual Reference AE', department='admin', role_code='admin',
    auth_user_id=str(user.pk), account_status='active', created_by='qa', updated_by='qa')
for kind, name in [('ae', person.name), ('class', 'QA Manual Class'), ('reinsured', 'QA Manual Cedant'),
                   ('reinsurer', TARGET), ('reinsurer', 'QA Ordinary Reinsurer'), ('foreign_broker', 'Howden Specialty Limited')]:
    MasterRecord.objects.create(entity_type=kind, name=name, created_by='qa', updated_by='qa')
client = Client(enforce_csrf_checks=True, HTTP_HOST='localhost', raise_request_exception=False)
def call(method, url, body=None):
    client.get('/api/auth/csrf')
    kwargs = {'HTTP_X_CSRFTOKEN': client.cookies['csrftoken'].value}
    if body is not None:
        kwargs.update(data=json.dumps(body), content_type='application/json')
    return getattr(client, method)(url, **kwargs)
assert call('post', '/api/auth/login', {'username': user.username, 'password': 'Manual-Ref-Password-9!'}).status_code == 200
ready = dict(reinsuranceStructure='QS', ae=person.name, currency='TWD', classOfBusiness='QA Manual Class', classCode='PAR',
    newOrRenew='New', typePrefix='Fire', reinsured='QA Manual Cedant', originalInsured='QA Manual Reference Policy',
    policyFrom='2039-05-01', policyTo='2040-05-01', interest='Buildings', situations=[{'address':'QA Road', 'postcode':'100'}],
    reinsurers=[{'name':TARGET,'foreignBroker':'Howden Specialty Limited','sharePct':100,'premium':8000,'riCommPct':5,'taxPct':1}],
    limitOfLiability=1000000, deductibles='As original', originalConditions='As original', occupation='Office', construction='Concrete',
    sumInsured=[{'category':'Building','amount':1000000}], lossAdvisedDate='2039-04-01', lossRecordYears=5,
    originalPremium=10000, paymentTermsDays=30, riCommPct=10, taxPct=1)
def create(payload):
    response = call('post', '/api/cases', {'case': payload})
    assert response.status_code == 201, response.content
    return Case.objects.get(case_uid=response.json()['case']['caseUid'])
def save(row, payload, version=None):
    row.refresh_from_db()
    return call('put', '/api/cases', {'caseUid':str(row.case_uid), 'rowVersion':version or row.row_version, 'case':payload})
def docs(row):
    for kind in ['offer','signed']:
        CaseDocument.objects.create(case=row,kind=kind,reinsurers=[TARGET,'QA Ordinary Reinsurer'] if kind=='signed' else [],
            filename=kind+'.pdf',content_type='application/pdf',byte_size=5,sha256='0'*64,storage_key='qa-'+str(uuid.uuid4()),
            is_selected=True,uploaded_by='qa')
def announce(row):
    row.refresh_from_db()
    return call('post','/api/case-announce',{'caseUid':str(row.case_uid),'rowVersion':row.row_version,'confirmed':True,
        'documentIds':[str(i) for i in CaseDocument.objects.filter(case=row,is_selected=True).values_list('pk',flat=True)]})
normal_payload = copy.deepcopy(ready)
normal_payload['reinsurers'][0]['name'] = 'QA Ordinary Reinsurer'
normal = create(normal_payload)
check('ordinary draft has no extra reference in stored payload', 'manualTwRef' not in normal.payload)
check('ordinary ready case does not require manual reference', not validate_announce_ready(normal.payload))
count_before = Case.objects.count()
response = call('post', '/api/cases', {'case': ready})
check('target Draft cannot be saved before the manual reference is known', response.status_code==400
    and response.json()['error']=='validation_failed' and Case.objects.count()==count_before)
empty = create({**ready, 'manualTwRef':'LEGACY-REF'})
empty.payload['manualTwRef']=''
empty.save(update_fields=['payload'])
before_seq = list(ReferenceSequence.objects.values())
response = announce(empty)
check('target Announce rejects missing manual reference before allocating auto reference', response.status_code == 400
    and response.json()['error']=='case_not_ready' and {'field':'manualTwRef','label':'TW Ref. (for AUW)'} in response.json()['issues']
    and list(ReferenceSequence.objects.values())==before_seq)
for value in [123, {}, [], 'A'*161, 'ABC\nDEF', 'ABC\x00DEF']:
    response=call('post','/api/cases',{'case':{**ready,'manualTwRef':value}})
    check('invalid manual reference rejected: '+repr(value)[:35],response.status_code==400 and response.json()['error']=='validation_failed')
# 2026-10-08 起「純 AUW」以手填 Ref 當主編號（另見 auw_reference_only）；
# 這裡測的是「自動編號＋另一組手填 Ref」並存，所以用 AUW 與一般再保人混合的案件
row = create({**ready,'manualTwRef':'  000609/TW-ABC-39  ',
              'reinsurers':[{**normal_payload['reinsurers'][0],'sharePct':50},{**ready['reinsurers'][0],'sharePct':50}]})
check('reference saves as trimmed text and preserves leading zeros and punctuation',row.payload['manualTwRef']=='000609/TW-ABC-39')
loaded=call('get','/api/cases?caseUid='+str(row.case_uid)).json()['case']
check('reload returns the saved manual reference and automatic reference is still unassigned',loaded['payload']['manualTwRef']=='000609/TW-ABC-39' and loaded['twRef'] is None)
docs(row)
response=announce(row);row.refresh_from_db()
check('Announce keeps the separate manual reference and assigns normal TW reference',response.status_code==200
    and row.tw_ref=='TWPAR3905001' and row.payload['manualTwRef']=='000609/TW-ABC-39' and row.status=='posted')
listed=next(item for item in call('get','/api/cases').json()['cases'] if item['caseUid']==str(row.case_uid))
check('case list returns both references',listed['twRef']==row.tw_ref and listed['manualTwRef']=='000609/TW-ABC-39')
schedule_before=build_payment_schedule(row.payload)
payload=copy.deepcopy(row.payload);payload['manualTwRef']='000609/TW-EDIT-39'
response=save(row,payload);row.refresh_from_db()
check('Announced case manual reference can be edited without renumbering automatic reference',response.status_code==200
    and row.tw_ref=='TWPAR3905001' and row.payload['manualTwRef']=='000609/TW-EDIT-39')
check('reference edit leaves financial schedule and amount unchanged',build_payment_schedule(row.payload)==schedule_before)
payload=copy.deepcopy(row.payload);payload['manualTwRef']=''
response=save(row,payload)
check('Announced case cannot be saved with required reference missing',response.status_code==400 and response.json()['error']=='validation_failed')
response=save(row,row.payload,version=1)
check('manual reference edit obeys existing optimistic concurrency',response.status_code==409 and response.json()['error']=='version_conflict')
row.refresh_from_db();row.payload['transactions']=build_premium_transactions({**row.payload,'twRef':row.tw_ref});row.save()
accounting=call('get','/api/accounting').json()
payments=[item for item in accounting['rows'] if item['caseUid']==str(row.case_uid)]
tx=[item for item in accounting['transactionRows'] if item['caseUid']==str(row.case_uid)]
check('Accounting payment schedule exposes both references',len(payments)==3 and all(item['manualTwRef']=='000609/TW-EDIT-39' and item['twRef']==row.tw_ref for item in payments))
check('Accounting SoA exposes both references without replacing transaction numbers',len(tx)==6 and all(item['manualTwRef']=='000609/TW-EDIT-39' and item['txNo'].startswith(row.tw_ref) for item in tx))
check('new endorsement and renewal drafts require their own manual reference',build_endorsement_payload(row.payload,row.tw_ref,0)['manualTwRef']==''
    and build_renewal_payload(row.payload,row.tw_ref)['manualTwRef']=='')
mixed=copy.deepcopy(ready);mixed['reinsurers']=[{**normal_payload['reinsurers'][0],'sharePct':50},{**ready['reinsurers'][0],'sharePct':50}]
mixed=create({**mixed, 'manualTwRef':'MIXED-AUW-REF'})
check('target in a mixed reinsurer case also requires manual reference',any(item['field']=='manualTwRef' for item in validate_announce_ready({**mixed.payload,'manualTwRef':''})))
variant=copy.deepcopy(ready);variant['reinsurers'][0]['name']='  '+TARGET.lower().replace(' ', '  ')+'  '
check('target matching tolerates case and repeated whitespace',normalize_draft(variant)['value']['manualTwRef']=='')
for name in [TARGET.replace('0609','0610'),TARGET.replace(' (Facility)',''), 'Other (Facility)']:
    unrelated=copy.deepcopy(ready);unrelated['reinsurers'][0]['name']=name;unrelated['manualTwRef']='SHOULD-NOT-STORE'
    check('other reinsurers do not trigger conditional reference: '+name,'manualTwRef' not in normalize_draft(unrelated)['value'])
response=save(empty,{**normal_payload,'manualTwRef':'OLD-REF'})
empty.refresh_from_db()
check('removing target reinsurer clears saved additional reference',response.status_code==200 and 'manualTwRef' not in empty.payload)
docs(normal)
response=announce(normal);normal.refresh_from_db()
check('ordinary Announce continues the same automatic sequence',response.status_code==200 and normal.tw_ref=='TWPAR3905002')
check('manual field does not reserve or replace the automatic sequence',ReferenceSequence.objects.get(prefix='TWPAR3905').last_value==2)
print(f'{len(checks)}/{len(checks)} manual TW reference API checks passed',flush=True)
