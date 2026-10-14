"""Required AUW draft refs, fixed Howden binding and exact legacy repair through real APIs."""
import copy
import json
import os

from django.conf import settings
from django.contrib.auth import get_user_model
from django.test import Client
from django.utils import timezone
from audit.models import AuditLog, EntitySnapshot
from cases.auw_binding import bind_existing_auw_cases
from cases.draft import normalize_draft
from cases.manual_reference import AUW_FOREIGN_BROKER as HOWDEN, MANUAL_TW_REF_REINSURER as TARGET
from cases.models import Case, ReferenceSequence
from cases.calc.accounting import build_premium_transactions
from masterdata.models import MasterRecord
from personnel.models import Personnel

assert os.environ.get('RI_DISPOSABLE_QA') == 'true'
checks=[]
def check(name, condition):
    assert condition, name
    checks.append(name)
    print('PASS '+name, flush=True)

user=get_user_model().objects.create_user(username='zz.auw.binding', password='AUW-Binding-Password-9!')
person=Personnel.objects.create(name='QA AUW Binding AE',department='admin',role_code='admin',
    auth_user_id=str(user.pk),account_status='active',created_by='qa',updated_by='qa')
for kind,name in [('ae',person.name),('class','QA AUW Binding Class'),('reinsured','QA Binding Cedant'),
                  ('reinsurer',TARGET),('reinsurer','QA Binding Ordinary'),('foreign_broker',HOWDEN)]:
    MasterRecord.objects.get_or_create(entity_type=kind,name=name,defaults={'created_by':'qa','updated_by':'qa'})
client=Client(enforce_csrf_checks=True,HTTP_HOST='localhost',raise_request_exception=False)
def call(method,url,body=None):
    client.get('/api/auth/csrf')
    options={'HTTP_X_CSRFTOKEN':client.cookies['csrftoken'].value}
    if body is not None:options.update(data=json.dumps(body),content_type='application/json')
    return getattr(client,method)(url,**options)
assert call('post','/api/auth/login',{'username':user.username,'password':'AUW-Binding-Password-9!'}).status_code==200
ready=dict(reinsuranceStructure='QS',ae=person.name,currency='TWD',classOfBusiness='QA AUW Binding Class',classCode='ABR',
    newOrRenew='New',typePrefix='Fire',reinsured='QA Binding Cedant',originalInsured='QA Binding Policy',
    policyFrom='2045-01-01',policyTo='2046-01-01',interest='Buildings',situations=[{'address':'QA Road','postcode':'100'}],
    reinsurers=[{'name':TARGET,'foreignBroker':'Other Broker','sharePct':100,'premium':8000,'riCommPct':12.5,'taxPct':1}],
    limitOfLiability=1000000,deductibles='As original',originalConditions='As original',occupation='Office',construction='Concrete',
    sumInsured=[{'category':'Building','amount':1000000}],lossAdvisedDate='2044-12-01',lossRecordYears=5,
    originalPremium=10000,paymentTermsDays=90,riCommPct=17,taxPct=1,manualTwRef='TW45SM010001')
_ref_seq = [0]
def _unique_ref(raw):
    # 2026-10-08 起 AUW 手填 Ref 不可與其他案件重複；同一份範本重複建案時各給一組編號
    if raw.get('manualTwRef') == 'TW45SM010001':
        _ref_seq[0] += 1
        raw = {**raw, 'manualTwRef': 'TW45SM010001-' + str(_ref_seq[0])}
    return raw
def create(raw):
    raw = _unique_ref(raw)
    response=call('post','/api/cases',{'case':raw})
    assert response.status_code==201,response.content
    return Case.objects.get(case_uid=response.json()['case']['caseUid'])
def save(row,raw):
    row.refresh_from_db()
    return call('put','/api/cases',{'caseUid':str(row.case_uid),'rowVersion':row.row_version,'case':raw})
def workflow(row,action,**extra):
    row.refresh_from_db()
    return call('post','/api/case-workflow',{'action':action,'caseUid':str(row.case_uid),'rowVersion':row.row_version,**extra})

for value in [None,'','   ','\u3000\t']:
    before=(Case.objects.count(),EntitySnapshot.objects.count(),list(ReferenceSequence.objects.values()))
    raw=copy.deepcopy(ready)
    if value is None:raw.pop('manualTwRef')
    else:raw['manualTwRef']=value
    response=call('post','/api/cases',{'case':raw})
    check('new AUW draft rejects missing/blank ref '+repr(value),response.status_code==400
        and response.json()['error']=='validation_failed'
        and before==(Case.objects.count(),EntitySnapshot.objects.count(),list(ReferenceSequence.objects.values())))
ordinary=copy.deepcopy(ready)
ordinary.pop('manualTwRef')
ordinary['reinsurers'][0].update(name='QA Binding Ordinary',foreignBroker='Other Broker')
normal=create(ordinary)
check('ordinary Draft still saves without AUW ref and keeps its own broker',
      'manualTwRef' not in normal.payload and normal.payload['reinsurers'][0]['foreignBroker']=='Other Broker')
for broker in ['',None,'Other Broker',{'tamper':True}]:
    raw=copy.deepcopy(ready);raw['reinsurers'][0]['foreignBroker']=broker
    row=create(raw)
    check('server binds AUW to Howden despite client broker '+repr(broker),row.payload['reinsurers'][0]['foreignBroker']==HOWDEN)
check('binding preserves custom deductions and existing AUW tax/terms rules',row.payload['reinsurers'][0]['riCommPct']==12.5
    and row.payload['reinsurers'][0]['taxPct']==0 and row.payload['reinsurers'][0]['paymentTermsDays']==120)
previous=copy.deepcopy(row.payload);version=row.row_version
response=save(row,{**row.payload,'manualTwRef':' '});row.refresh_from_db()
check('editing AUW draft cannot clear ref or modify persisted state',response.status_code==400
    and row.payload==previous and row.row_version==version)
raw=copy.deepcopy(row.payload);raw['reinsurers'][0]['foreignBroker']='Other Broker'
response=save(row,raw);row.refresh_from_db()
check('PUT cannot bypass Howden binding',response.status_code==200 and row.payload['reinsurers'][0]['foreignBroker']==HOWDEN)
raw=copy.deepcopy(ready);raw['manualTwRef']='  000609/TW-45  '
raw['reinsurers'][0]['name']='  '+TARGET.lower().replace(' ','  ')+'  '
row_variant=create(raw)
check('name variants bind Howden and ref remains trimmed text',row_variant.payload['reinsurers'][0]['foreignBroker']==HOWDEN
    and row_variant.payload['manualTwRef']=='000609/TW-45')
mixed=copy.deepcopy(ready)
mixed['reinsurers']=[{**ready['reinsurers'][0],'sharePct':50},{**ordinary['reinsurers'][0],'sharePct':50,'riCommPct':7,'taxPct':3,'paymentTermsDays':45}]
mix=create(mixed)
check('mixed Placement binds only AUW and preserves ordinary financial fields',
      mix.payload['reinsurers'][0]['foreignBroker']==HOWDEN and mix.payload['reinsurers'][1]['foreignBroker']=='Other Broker'
      and mix.payload['reinsurers'][1]['riCommPct']==7 and mix.payload['reinsurers'][1]['taxPct']==3
      and mix.payload['reinsurers'][1]['paymentTermsDays']==45)
raw=copy.deepcopy(mixed);raw.pop('manualTwRef');raw['reinsurers'].reverse()
check('AUW in second or mixed row still requires a case ref',call('post','/api/cases',{'case':raw}).status_code==400)
for name in [TARGET.replace('0609','0610'),TARGET.replace(' (Facility)',''),'Other (Facility)']:
    raw=copy.deepcopy(ready);raw.pop('manualTwRef');raw['reinsurers'][0]['name']=name
    normalized=normalize_draft(raw)
    check('other syndicates and facilities do not trigger binding '+name,not normalized['errors']
          and normalized['value']['reinsurers'][0]['foreignBroker']=='Other Broker')

# Legacy direct Announce must not bypass the broker rule before saving.
legacy=create(ready);legacy.payload['reinsurers'][0]['foreignBroker']='';legacy.save(update_fields=['payload'])
sequence=list(ReferenceSequence.objects.values())
response=call('post','/api/case-announce',{'caseUid':str(legacy.case_uid),'rowVersion':legacy.row_version,'confirmed':True,'documentIds':[]})
check('legacy wrong Howden blocks direct Announce before allocating a TW ref',response.status_code==400
    and response.json()['error']=='case_not_ready'
    and any(issue['field']=='reinsurers.0.foreignBroker' for issue in response.json()['issues'])
    and list(ReferenceSequence.objects.values())==sequence)

# Workflow-created drafts also require the new reference before they exist.
# 續保只能從最新的已確認案件建立（之後加入的規則），所以兩個動作各用一張獨立的原保單
for number, action in enumerate(['create_endorsement','create_renewal'], 1):
    root=create(ready);root.status='closed';root.tw_ref=f'TWABR459900{number}'
    root.payload['transactions']=build_premium_transactions({**root.payload,'twRef':root.tw_ref})
    root.save()
    for value in [None,' ','A'*161,'ABC\nDEF',123]:
        count=Case.objects.count()
        response=workflow(root,action,**({} if value is None else {'manualTwRef':value}))
        check(action+' rejects bad new reference '+repr(value)[:20],response.status_code==400
              and response.json()['error']=='validation_failed' and Case.objects.count()==count)
    response=workflow(root,action,manualTwRef='  NEW-'+action+'  ')
    assert response.status_code==201,response.content
    child=Case.objects.get(case_uid=response.json()['case']['caseUid'])
    check(action+' stores a separate entered ref and fixed Howden',child.payload['manualTwRef']=='NEW-'+action
          and child.payload['reinsurers'][0]['foreignBroker']==HOWDEN and child.tw_ref is None
          and child.payload['reinsurers'][0]['riCommPct']==12.5)
check('workflow drafts do not allocate automatic references',list(ReferenceSequence.objects.values())==sequence)
normal.status='closed';normal.tw_ref='TWABR4501002';normal.save()
response=workflow(normal,'create_renewal')
check('ordinary renewal still creates without an AUW ref',response.status_code==201
      and 'manualTwRef' not in response.json()['case']['payload'])

# Batch repair must be exact, versioned, history preserving and idempotent.
old=create(ready)
old.payload.update(manualTwRef='',transactions=[{'txNo':'OLD-T2','amount':7000,'reinsurer':'Original historical label'}],
    paymentEntries=[{'id':'cash1','scheduleKey':'case-effective-date:reinsurer:r1','amount':123.45,'paymentDate':'2045-03-01'}])
old.payload['reinsurers'][0].update(foreignBroker='',riCommPct=15,taxPct=1)
old.status='posted';old.tw_ref='TWABR4501003';old.save()
retired=create(ready);retired.is_archived=True;retired.archived_at=timezone.now();retired.archived_by='qa';retired.payload['reinsurers'][0]['foreignBroker']='Other Broker';retired.save()
before={str(c.case_uid):copy.deepcopy(c.__dict__) for c in Case.objects.all()}
snapshots=EntitySnapshot.objects.count();audit=AuditLog.objects.count()
result=bind_existing_auw_cases()
check('legacy Howden repair includes existing and archived AUW cases',str(old.case_uid) in result['changedCaseUids']
      and str(retired.case_uid) in result['changedCaseUids'])
for case in Case.objects.all():
    prior=before[str(case.case_uid)]
    if str(case.case_uid) in result['changedCaseUids']:
        restored=copy.deepcopy(case.payload)
        for index,entry in enumerate(restored['reinsurers']):
            previous=prior['payload']['reinsurers'][index]
            if 'foreignBroker' in previous:entry['foreignBroker']=previous['foreignBroker']
            else:entry.pop('foreignBroker',None)
        assert restored==prior['payload']
        assert case.row_version==prior['row_version']+1 and case.status==prior['status'] and case.tw_ref==prior['tw_ref']
    else:
        assert case.payload==prior['payload'] and case.row_version==prior['row_version']
check('batch changes only broker fields and versions; cash, transactions, tax and deductions survive',True)
check('each changed case has an immutable snapshot',EntitySnapshot.objects.count()-snapshots==result['changedCaseCount'])
check('audit follows existing paused/enabled setting',AuditLog.objects.count()-audit==(0 if settings.AUDIT_LOG_PAUSED else result['changedCaseCount']))
check('missing manual refs are reported without inventing numbers',any(item['caseUid']==str(old.case_uid) for item in result['missingManualRefs']))
snapshots=EntitySnapshot.objects.count();audit=AuditLog.objects.count()
repeat=bind_existing_auw_cases()
check('repeat repair changes nothing and writes no duplicate history',repeat['changedCaseCount']==0
      and EntitySnapshot.objects.count()==snapshots and AuditLog.objects.count()==audit)
old.refresh_from_db();version=old.row_version
response=save(old,old.payload);old.refresh_from_db()
check('legacy missing Ref remains blocked on edit until filled',response.status_code==400 and old.row_version==version)
print(f'{len(checks)}/{len(checks)} AUW required reference and Howden API checks passed',flush=True)
