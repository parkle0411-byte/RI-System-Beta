"""Real API checks for pure-AUW identity, reservations and retained evidence rules."""
import copy,json,os,uuid
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
from django.contrib.auth import get_user_model
from django.db import close_old_connections
from django.test import Client
from django.utils import timezone
from cases.models import Case,CaseDocument,ReferenceSequence
from cases.manual_reference import MANUAL_TW_REF_REINSURER as AUW,is_pure_auw_case
from cases.calc.signed_slip import signed_slip_tracking,reminder_due
from cases.auw_reference_conversion import convert_unbooked_pure_auw_reference
from cases.calc.accounting import build_premium_transactions
from cases.calc.payment_terms import build_payment_schedule
from audit.models import EntitySnapshot
from masterdata.models import MasterRecord
from personnel.models import Personnel
assert os.environ.get('RI_DISPOSABLE_QA')=='true'
checks=[]
def check(label,value):
 assert value,label
 checks.append(label);print('PASS '+label,flush=True)
user=get_user_model().objects.create_user(username='zz.auw.identity',password='AUW-Identity-QA-9!')
person=Personnel.objects.create(name='QA AUW Identity AE',department='admin',role_code='admin',auth_user_id=str(user.pk),account_status='active',created_by='qa',updated_by='qa')
for kind,name in [('ae',person.name),('class','QA Identity Class'),('reinsured','QA Identity Cedant'),('reinsurer',AUW),('reinsurer','QA Identity Ordinary'),('foreign_broker','Howden Specialty Limited')]:
 MasterRecord.objects.get_or_create(entity_type=kind,name=name,defaults={'created_by':'qa','updated_by':'qa'})
def call(method,url,body=None,c=None):
 c=c or client;c.get('/api/auth/csrf');kw={'HTTP_X_CSRFTOKEN':c.cookies['csrftoken'].value}
 if body is not None:kw.update(data=json.dumps(body),content_type='application/json')
 return getattr(c,method)(url,**kw)
def login():
 c=Client(enforce_csrf_checks=True,HTTP_HOST='localhost',raise_request_exception=False)
 assert call('post','/api/auth/login',{'username':user.username,'password':'AUW-Identity-QA-9!'},c=c).status_code==200
 return c
client=login()
ready=dict(reinsuranceStructure='QS',ae=person.name,currency='TWD',classOfBusiness='QA Identity Class',classCode='AUID',newOrRenew='New',typePrefix='Fire',reinsured='QA Identity Cedant',originalInsured='QA AUW Identity',policyFrom='2044-05-01',policyTo='2045-05-01',interest='Buildings',situations=[dict(address='QA Road',postcode='100')],reinsurers=[dict(name=AUW,foreignBroker='Howden Specialty Limited',sharePct=100,premium=8000,riCommPct=12.5,taxPct=0,paymentTermsDays=120)],limitOfLiability=1000000,deductibles='As original',originalConditions='As original',occupation='Office',construction='Concrete',sumInsured=[dict(category='Building',amount=1000000)],lossAdvisedDate='2044-04-01',lossRecordYears=5,originalPremium=10000,paymentTermsDays=90,riCommPct=10,taxPct=1,ownerPersonnelId=person.pk,ownerPersonnelName=person.name)
def create(ref=None,raw=None):
 payload=copy.deepcopy(raw or ready)
 if ref is not None:payload['manualTwRef']=ref
 r=call('post','/api/cases',{'case':payload});assert r.status_code==201,r.content
 return Case.objects.get(case_uid=r.json()['case']['caseUid'])
def announce(row,**extra):
 row.refresh_from_db();body={'caseUid':str(row.case_uid),'rowVersion':row.row_version,'confirmed':True,'documentIds':[str(x) for x in CaseDocument.objects.filter(case=row,is_selected=True).values_list('pk',flat=True)],**extra}
 return call('post','/api/case-announce',body)
def edit(row,payload):
 row.refresh_from_db();return call('put','/api/cases',{'caseUid':str(row.case_uid),'rowVersion':row.row_version,'case':payload})
def evidence(row,kind,names=None,selected=True):
 return CaseDocument.objects.create(case=row,kind=kind,reinsurers=names or [],filename=kind+'.pdf',content_type='application/pdf',byte_size=5,sha256='0'*64,storage_key='auw-id-'+str(uuid.uuid4()),is_selected=selected,uploaded_by='qa')
def workflow(row,action,ref):
 row.refresh_from_db();return call('post','/api/case-workflow',dict(caseUid=str(row.case_uid),rowVersion=row.row_version,action=action,manualTwRef=ref))

pure=create('TW44SM000001');seq=list(ReferenceSequence.objects.values());r=announce(pure)
check('pure AUW still requires evidence and does not consume a sequence on rejection',r.status_code==400 and r.json()['error']=='documents_not_ready' and list(ReferenceSequence.objects.values())==seq)
evidence(pure,'offer');evidence(pure,'signed',[AUW]);r=announce(pure);pure.refresh_from_db()
check('pure AUW announces after the original evidence requirements are met',r.status_code==200 and CaseDocument.objects.filter(case=pure).count()==2)
check('pure AUW uses manual primary and consumes no automatic sequence',pure.tw_ref=='TW44SM000001' and pure.payload['twRefSource']=='auw_manual' and list(ReferenceSequence.objects.values())==seq)
doc=call('get','/api/case-documents?caseUid='+str(pure.case_uid)).json()
check('document API still tracks AUW evidence',doc['coverage']['ready'] and len(doc['coverage']['required'])==1 and not doc['coverage'].get('documentsExempt'))
tracking=signed_slip_tracking({**pure.payload,'status':'posted'},[],today='2044-08-01')
check('AUW Signed Slip follow-up remains active when its Signed Slip is missing',not tracking['complete'] and tracking['due'] and reminder_due({**pure.payload,'status':'posted'},[],None,'2044-08-01') is not None)
before=Case.objects.count();r=call('post','/api/cases',{'case':{**ready,'manualTwRef':'tw44sm000001'}})
check('case-insensitive duplicate of an announced manual ref is blocked',r.status_code==409 and r.json()['error']=='manual_reference_conflict' and Case.objects.count()==before)
raw=copy.deepcopy(pure.payload);raw['manualTwRef']='TW44SM-RENAMED';r=edit(pure,raw)
check('announced manual primary cannot be silently renumbered',r.status_code==409 and r.json()['error']=='primary_reference_locked')
raw=copy.deepcopy(pure.payload);raw['twRefSource']='system';r=edit(pure,raw);pure.refresh_from_db()
check('client cannot forge reference source',r.status_code==200 and pure.payload['twRefSource']=='auw_manual')
draft=create('TW44SM-DRAFT');r=call('post','/api/cases',{'case':{**ready,'manualTwRef':'TW44SM-DRAFT'}})
check('a draft already reserves its manual ref',r.status_code==409)
other=create('TW44SM-OTHER');before=copy.deepcopy(other.payload);r=edit(other,{**other.payload,'manualTwRef':'TW44SM-DRAFT'});other.refresh_from_db()
check('edit collision is blocked without changing stored payload',r.status_code==409 and other.payload==before)
check('own unchanged reference remains editable in Draft',edit(draft,draft.payload).status_code==200)
recycled=create('TW44SM-RECYCLED');recycled.recycled_at=timezone.now();recycled.recycled_by='qa';recycled.save()
check('recycled references remain reserved for restoration',call('post','/api/cases',{'case':{**ready,'manualTwRef':'TW44SM-RECYCLED'}}).status_code==409)
archive=create('TW44SM-ARCHIVED');archive.is_archived=True;archive.archived_at=timezone.now();archive.archived_by='qa';archive.save()
check('archived references remain reserved',call('post','/api/cases',{'case':{**ready,'manualTwRef':'TW44SM-ARCHIVED'}}).status_code==409)

mixed=copy.deepcopy(ready);mixed['reinsurers']=[{**ready['reinsurers'][0],'sharePct':50},{**ready['reinsurers'][0],'name':'QA Identity Ordinary','sharePct':50,'taxPct':1,'paymentTermsDays':45,'foreignBroker':''}]
mix=create('TW44SM-MIXED',mixed);r=announce(mix)
check('mixed placement still requires AUW and ordinary evidence plus Offer',r.status_code==400 and r.json()['error']=='documents_not_ready' and len(r.json()['coverage']['missing'])==2)
evidence(mix,'offer');r=announce(mix)
check('Offer alone does not waive ordinary reinsurer evidence',r.status_code==400)
evidence(mix,'signed',['QA Identity Ordinary'],selected=False);check('unselected ordinary evidence cannot satisfy mixed placement',announce(mix).status_code==400)
d=CaseDocument.objects.filter(case=mix,kind='signed').get();d.is_selected=True;d.save();r=announce(mix)
check('ordinary-only evidence still leaves AUW missing in a mixed placement',r.status_code==400 and len(r.json()['coverage']['missing'])==1)
evidence(mix,'confirmation',[AUW]);r=announce(mix);mix.refresh_from_db()
check('mixed announces with evidence for every reinsurer and receives automatic primary',r.status_code==200 and mix.tw_ref=='TWAUID4405001' and mix.payload['manualTwRef']=='TW44SM-MIXED' and mix.payload['twRefSource']=='system')
check('mixed document API includes AUW in completed coverage',call('get','/api/case-documents?caseUid='+str(mix.case_uid)).json()['coverage']['missing']==[])
check('mixed Signed Slip follow-up still tracks AUW separately',not signed_slip_tracking({**mix.payload,'status':'posted'},[dict(kind='signed',reinsurers=['QA Identity Ordinary'])],today='2044-08-01')['complete'])
check('manual ref cannot duplicate an existing automatic primary',call('post','/api/cases',{'case':{**ready,'manualTwRef':mix.tw_ref}}).status_code==409)
normal=copy.deepcopy(ready);normal['reinsurers'][0].update(name='QA Identity Ordinary',foreignBroker='',taxPct=1,paymentTermsDays=45)
ordinary=create(raw=normal);check('ordinary placement still needs documents',announce(ordinary).status_code==400)
evidence(ordinary,'offer');evidence(ordinary,'confirmation',['QA Identity Ordinary']);r=announce(ordinary);ordinary.refresh_from_db()
check('ordinary automatic sequence remains continuous after pure AUW',r.status_code==200 and ordinary.tw_ref=='TWAUID4405002')
empty=create('TW44SM-EMPTY');empty.payload['reinsurers'][0]['name']='';empty.save();check('empty named placement cannot use exemption',announce(empty).status_code==400 and not is_pure_auw_case(empty.payload))

reserved=create('TWPF4405001');collision=copy.deepcopy(normal);collision['classCode']='PF';row=create(raw=collision);evidence(row,'offer');evidence(row,'signed',['QA Identity Ordinary']);r=announce(row);row.refresh_from_db()
check('automatic numbering skips a reference reserved by an AUW Draft',r.status_code==200 and row.tw_ref=='TWPF4405002')
long_ref='AUW-'+('X'*156);long=create(long_ref);evidence(long,'offer');evidence(long,'signed',[AUW]);r=announce(long);long.refresh_from_db()
check('160-character AUW primary is stored without truncation',r.status_code==200 and long.tw_ref==long_ref and len(long.tw_ref)==160)
check('pure AUW long reference still does not advance any sequence',ReferenceSequence.objects.get(prefix='TWPF4405').last_value==2)
for source,ref in [(pure,'TW44SM000001'),(pure,'TW44SM-DRAFT')]:
 r=workflow(source,'create_endorsement',ref);check('endorsement rejects reused ref '+ref,r.status_code==409)
r=workflow(pure,'create_endorsement','TW44SM-ENDO');assert r.status_code==201,r.content
endo=Case.objects.get(case_uid=r.json()['case']['caseUid']);p=copy.deepcopy(endo.payload);p.update(endoEffectiveDate='2044-06-01',endoTypes=['premium'],endoText='Additional premium',originalPremium=1000);p['reinsurers'][0]['premium']=800
assert edit(endo,p).status_code==200
seq=list(ReferenceSequence.objects.values());evidence(endo,'offer');evidence(endo,'signed',[AUW]);r=announce(endo);endo.refresh_from_db()
check('pure AUW endorsement has its own manual primary without an E sequence',r.status_code==200 and endo.tw_ref=='TW44SM-ENDO' and list(ReferenceSequence.objects.values())==seq)
check('endorsement retains original parent, Cedant days and one settlement',endo.payload['parentTwRef']==pure.tw_ref and endo.payload['paymentTermsDays']==90 and not endo.payload['installmentEnabled'])
schedule=build_payment_schedule(endo.payload)
check('AUW endorsement schedule retains fixed 120-day month-end rule',not schedule['issues'] and next(x for x in schedule['items'] if x['partyType']=='reinsurer')['paymentRule']=='auw_month_end_120')
r=workflow(long,'create_endorsement','TW44SM-LONG-ENDO');assert r.status_code==201,r.content
child=Case.objects.get(case_uid=r.json()['case']['caseUid']);p=copy.deepcopy(child.payload);p.update(endoEffectiveDate='2044-06-01',endoTypes=['premium'],endoText='Mixed premium',originalPremium=1000);p['reinsurers']=[{**ready['reinsurers'][0],'sharePct':50,'premium':800},{**normal['reinsurers'][0],'sharePct':50,'premium':800}]
# 2026-10-13 Sum Insured 位置規則：由全 Facility 改成混合時，原項目要重新分配到 Location（畫面也會提示）
p['sumInsured']=[{**item,'locationIndex':0} for item in p['sumInsured']]
assert edit(child,p).status_code==200;evidence(child,'offer');evidence(child,'signed',['QA Identity Ordinary',AUW]);r=announce(child);child.refresh_from_db()
check('mixed endorsement of a long manual root gets an automatic E reference without truncation',r.status_code==200 and child.tw_ref==long_ref+'-E01' and child.payload['parentTwRef']==long_ref)
long.status='closed';long.save()
r=workflow(long,'create_renewal','TW45SM-OLD-ROOT')
check('renewal from an older root is blocked while its newer endorsement is active',
      r.status_code==409 and r.json()['error']=='latest_endorsement_required')
# This reference test needs the pure AUW root as the current case. Archive its
# mixed-placement child in the disposable fixture before exercising renewal.
Case.objects.filter(pk=child.pk).update(is_archived=True,archived_by='qa',archived_at=timezone.now())
check('renewal rejects a reused AUW ref',workflow(long,'create_renewal','TW44SM-DRAFT').status_code==409)
r=workflow(long,'create_renewal','TW45SM-RENEW');assert r.status_code==201,r.content
renewal=Case.objects.get(case_uid=r.json()['case']['caseUid']);r=edit(renewal,renewal.payload);renewal.refresh_from_db()
check('renewal retains the full 160-character source after saving',r.status_code==200 and renewal.payload['renewedFromTwRef']==long_ref)
seq=list(ReferenceSequence.objects.values());evidence(renewal,'offer');evidence(renewal,'signed',[AUW]);r=announce(renewal);renewal.refresh_from_db()
check('pure AUW renewal keeps evidence requirements and avoids the automatic sequence',r.status_code==200 and renewal.tw_ref=='TW45SM-RENEW' and list(ReferenceSequence.objects.values())==seq)

# Two competing API writers exercise the shared reference reservation guard.
barrier=Barrier(2)
def race():
 close_old_connections();c=login();barrier.wait(timeout=15)
 r=call('post','/api/cases',{'case':{**ready,'manualTwRef':'TW44SM-RACE'}},c=c);close_old_connections();return r.status_code
with ThreadPoolExecutor(max_workers=2) as pool:statuses=list(pool.map(lambda _:race(),range(2)))
check('simultaneous Draft creation permits exactly one reservation',sorted(statuses)==[201,409] and Case.objects.filter(payload__manualTwRef='TW44SM-RACE').count()==1)

legacy=create('TW44SM-LEGACY');legacy.tw_ref='TWOLD4405001';legacy.status='posted';legacy.announced_at=timezone.now();legacy.save()
old=copy.deepcopy(legacy.payload);seq=list(ReferenceSequence.objects.values());count=EntitySnapshot.objects.filter(entity_id=legacy.case_uid).count()
result=convert_unbooked_pure_auw_reference(str(legacy.case_uid),expected_version=legacy.row_version,expected_old_ref=legacy.tw_ref,expected_manual_ref='TW44SM-LEGACY');legacy.refresh_from_db()
check('reviewed unbooked conversion updates only the primary and reference metadata',result['changedCaseCount']==1 and legacy.tw_ref=='TW44SM-LEGACY' and {k:v for k,v in legacy.payload.items() if k not in ['twRefSource','previousTwRefs']}==old)
check('conversion preserves old ref as searchable reserved history and sequence state',legacy.payload['previousTwRefs']==['TWOLD4405001'] and list(ReferenceSequence.objects.values())==seq)
check('conversion records one new snapshot',EntitySnapshot.objects.filter(entity_id=legacy.case_uid).count()==count+1)
result=convert_unbooked_pure_auw_reference(str(legacy.case_uid),expected_version=1,expected_old_ref='TWOLD4405001',expected_manual_ref='TW44SM-LEGACY')
check('repeating conversion is idempotent',result['changedCaseCount']==0)
check('old reference cannot be reassigned to another case',call('post','/api/cases',{'case':{**ready,'manualTwRef':'TWOLD4405001'}}).status_code==409)
booked=create('TW44SM-BOOKED');booked.tw_ref='TWOLD4405002';booked.status='posted';booked.announced_at=timezone.now();booked.payload['transactions']=build_premium_transactions({**booked.payload,'twRef':booked.tw_ref});booked.save()
try:
 convert_unbooked_pure_auw_reference(str(booked.case_uid),expected_version=booked.row_version,expected_old_ref=booked.tw_ref,expected_manual_ref='TW44SM-BOOKED')
 raise AssertionError('Booked case must not be converted')
except ValueError:
 check('booked history blocks the unbooked conversion helper',True)
pure.payload['transactions']=build_premium_transactions({**pure.payload,'twRef':pure.tw_ref});pure.save()
accounting=call('get','/api/accounting').json();tx=[x for x in accounting['transactionRows'] if x['caseUid']==str(pure.case_uid)]
check('Accounting transactions keep manual primary as identity and transaction prefix',len(tx)==3 and all(x['twRef']==pure.tw_ref and x['txNo'].startswith(pure.tw_ref) for x in tx))
check('normalization does not alter editable AUW deduction or fixed tax',pure.payload['reinsurers'][0]['riCommPct']==12.5 and pure.payload['reinsurers'][0]['taxPct']==0)
print(f'{len(checks)}/{len(checks)} AUW primary reference API checks passed',flush=True)
