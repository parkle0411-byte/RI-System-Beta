"""Oversea Business: six-field draft, independent cash T3, actual date minus 10."""
import copy,json,os
from datetime import date,timedelta
from django.contrib.auth import get_user_model
from django.test import Client
from django.db import transaction
from cases.models import Case
from cases.draft import normalize_draft,validate_announce_ready
from cases.oversea import dates,refresh_transactions
from cases.calc.totals import case_totals
from cases.calc.accounting import build_premium_transactions
from cases.calc.payment_terms import build_payment_schedule
from cases.cash_ledger import transaction_details
from cases.workflow import reference_prefix
from production.calc import installment_allocations,reinsurer_legs
from production.closing import confirm_case
from production.views import case_source
from dashboard.calc import reinsurer_legs as dashboard_legs
from personnel.models import Personnel
from masterdata.models import MasterRecord
assert os.environ.get('RI_DISPOSABLE_QA')=='true'
from django.core.management import call_command
call_command('makemigrations',check=True,dry_run=True,verbosity=0)
call_command('check',verbosity=0)
checks=[]
def check(name,ok,detail=''):
 assert ok,(name,detail);checks.append(name);print('PASS '+name,flush=True)
def call(c,url,body=None,method='post'):
 return getattr(c,method)(url,json.dumps(body),content_type='application/json') if body is not None else c.get(url)
def account(tag,role):
 u=get_user_model().objects.create_user(username='oversea-'+tag,password='Oversea-Test-9!')
 p=Personnel.objects.create(name='Oversea QA '+tag,department='finance' if role.startswith('accounting') else 'admin' if role=='admin' else 'reinsurance',role_code=role,auth_user_id=str(u.pk),account_status='active',created_by='qa',updated_by='qa')
 c=Client(HTTP_HOST='localhost');c.force_login(u);return c,p
def fixture(**kw):
 p=dict(originalInsured='Oversea QA Insured',originalInsuredCn='海外測試被保險人',policyFrom='2049-01-01',policyTo='2050-01-01',ae='Oversea QA sales',reinsuranceStructure='OVERSEA',classOfBusiness='Fine Art',classCode='FA',currency='TWD',originalPremium=100000,reinsured='Oversea QA Cedant',receiptPaymentDate='2050-01-05',reinsurers=[dict(name='Oversea QA Broker',sharePct=25,brokerageAmount=2500)])
 p.update(kw);return p
def member(case,no):
 case.refresh_from_db();return dict(caseUid=str(case.case_uid),txNo=no,rowVersion=case.row_version)
def get_case(uid):return Case.objects.get(case_uid=uid)
note_storage_keys=[]
def upload_note(client, uid, kind='broker_credit'):
 import base64
 from cases.models import CaseDocument
 response=call(client,'/api/case-documents',dict(caseUid=str(uid),kind=kind,filename=kind+'.pdf',base64=base64.b64encode(b'%PDF-1.4\nForeign RI Broker QA Note\n%%EOF').decode()))
 assert response.status_code==201,response.content[:1200]
 note_storage_keys.append(CaseDocument.objects.get(pk=response.json()['file']['id']).storage_key)
 return response.json()['coverage']['selected']
class Done(Exception):pass
try:
 with transaction.atomic():
  sales,person=account('sales','sales');finance,_=account('finance','accounting');admin,_=account('admin','admin')
  for klass,code in [('Fine Art','FA'),('Terrorism','TR')]:MasterRecord.objects.create(entity_type='class',name=klass,code=code,payload={},created_by='qa',updated_by='qa')
  MasterRecord.objects.create(entity_type='foreign_broker',name='Oversea QA Broker',payload={},created_by='qa',updated_by='qa')
  MasterRecord.objects.create(entity_type='reinsured',name='Oversea QA Cedant',payload={},created_by='qa',updated_by='qa')
  for actual,expected in [('2026-11-05','2026-10-26'),('2027-01-05','2026-12-26'),('2028-03-05','2028-02-24'),('2027-03-05','2027-02-23')]:
   check('calendar date subtraction '+actual,dates({'receiptPaymentDate':actual})['accountingDate']==expected)
  for value in [0,25,2500,9876543,-2500]:
   p=fixture(reinsurers=[dict(name='Oversea QA Broker',sharePct=25,brokerageAmount=value)])
   normalized=normalize_draft(p);check('direct brokerage amount '+str(value),not normalized['errors'] and case_totals(normalized['value'])['brokerage']==value,normalized['errors'])
  for share in [1,25,100]:
   p=fixture(reinsurers=[dict(name='Oversea QA Broker',sharePct=share,brokerageAmount=2500)])
   check('Share never scales direct Brokerage '+str(share),case_totals(p)['brokerage']==2500 and case_totals(p)['cedantPremium']==100000*share/100)
  for klass in ['Fine Art','Terrorism']:
   p=fixture(classOfBusiness=klass);r=normalize_draft(p);check('six-field readiness '+klass,not r['errors'] and not validate_announce_ready(r['value']),r)
  for klass in ['Property','Marine Cargo','Commercial General Liability']:
   check('API rejects unsupported Class '+klass,bool(normalize_draft(fixture(classOfBusiness=klass))['errors']))
  for value in [True,'not-money',{},float('inf')]:
   check('invalid Brokerage rejected '+str(value),bool(normalize_draft(fixture(reinsurers=[dict(name='Oversea QA Broker',sharePct=25,brokerageAmount=value)]))['errors']))
  check('TWD brokerage fractional value rejected',bool(normalize_draft(fixture(reinsurers=[dict(name='Oversea QA Broker',sharePct=25,brokerageAmount=1.1)]))['errors']))
  check('USD brokerage excess precision rejected',bool(normalize_draft(fixture(currency='USD',reinsurers=[dict(name='Oversea QA Broker',sharePct=25,brokerageAmount=1.111)]))['errors']))
  for actual in ['2026-02-30','bad-date']:
   check('invalid actual date rejected '+actual,bool(normalize_draft(fixture(receiptPaymentDate=actual))['errors']))
  for field in ['originalInsured','originalInsuredCn','policyFrom','policyTo','ae']:
   incomplete=fixture(ownerPersonnelId=person.pk,**{field:''})
   normalized=normalize_draft(incomplete);check('incomplete Draft remains savable '+field,not normalized['errors'])
   check('missing field prevents readiness '+field,any(i['field']==field for i in validate_announce_ready(normalized['value'])))
   saved=call(sales,'/api/cases',{'case':incomplete});check('incomplete Draft API saves '+field,saved.status_code==201,saved.content[:800]);missing_case=get_case(saved.json()['case']['caseUid'])
   announced=call(sales,'/api/case-announce',dict(caseUid=str(missing_case.case_uid),rowVersion=missing_case.row_version,confirmed=True,documentIds=[]))
   check('server blocks Announce with missing '+field,announced.status_code==400,announced.content[:800]);missing_case.refresh_from_db()
   check('blocked Announce creates no reference or T3 '+field,missing_case.status=='draft' and not missing_case.tw_ref and not missing_case.payload['transactions'])
  p=fixture(ownerPersonnelId=person.pk,ae=person.name)
  r=call(sales,'/api/cases',{'case':p});check('minimal draft saves without underwriting fields',r.status_code==201,r.content[:1500]);uid=r.json()['case']['caseUid'];case=get_case(uid)
  check('structure stored independently in indexed column',case.reinsurance_structure=='OVERSEA' and str(case.effective_date)=='2049-01-01' and str(case.expiration_date)=='2050-01-01')
  check('draft creates no cash or transactions',case.payload['transactions']==[] and case.payload['paymentEntries']==[])
  check('actual date persists and is not copied into insurance period',case.payload['receiptPaymentDate']=='2050-01-05' and case.payload['policyFrom']=='2049-01-01' and case.payload['policyTo']=='2050-01-01')
  details=fixture(ownerPersonnelId=person.pk,ae=person.name,originalInsured='Oversea Art Museum',originalInsuredCn='海外美術館',policyFrom='2048-02-29',policyFromTime='00:00',policyTo='2049-02-28',policyToTime='12:00')
  r=call(sales,'/api/cases',{'case':details});check('insured names, Policy Period and AE save',r.status_code==201,r.content[:1500]);detail_uid=r.json()['case']['caseUid'];detail_case=get_case(detail_uid)
  check('new details persist independently of actual payment date',all(detail_case.payload[k]==details[k] for k in ['originalInsured','originalInsuredCn','policyFrom','policyFromTime','policyTo','policyToTime','ae','receiptPaymentDate']))
  check('Policy Period populates indexed case dates',str(detail_case.effective_date)=='2048-02-29' and str(detail_case.expiration_date)=='2049-02-28')
  check('Draft does not create an official insured master',not detail_case.insured_master_id and not MasterRecord.objects.filter(entity_type='insured',name='海外美術館').exists())
  r=call(sales,'/api/cases?caseUid='+detail_uid,method='get');check('GET restores all new details',r.status_code==200 and all(r.json()['case']['payload'][k]==details[k] for k in ['originalInsured','originalInsuredCn','policyFrom','policyFromTime','policyTo','policyToTime','ae']))
  r=call(sales,'/api/case-announce',dict(caseUid=detail_uid,rowVersion=detail_case.row_version,confirmed=True,documentIds=upload_note(sales,detail_uid)));check('named Oversea announces with Broker Credit Note and no generated documents',r.status_code==200,r.content[:1500]);detail_case.refresh_from_db()
  check('named Oversea uses shared official insured master',detail_case.insured_master_id and detail_case.insured_master.name=='海外美術館' and detail_case.insured_master.payload.get('insuredAnnouncedAt'))
  check('Effective Date supplies reference month while Accounting Date follows actual receipt',detail_case.tw_ref.startswith('TWFA4802') and len(detail_case.payload['transactions'])==1 and transaction_details(detail_case.payload)[detail_case.payload['transactions'][0]['txNo']]['accountingDate']=='2049-12-26')
  english=normalize_draft(fixture(originalInsured='English Only Museum',originalInsuredCn='',ae=person.name))
  check('English-only Draft saves but cannot Announce',not english['errors'] and english['value']['originalInsured']=='English Only Museum' and any(i['field']=='originalInsuredCn' for i in validate_announce_ready(english['value'])))
  for period in [('2048-02-30','2049-02-28'),('2049-03-01','2049-02-28')]:
   check('invalid Policy Period is rejected '+str(period),bool(normalize_draft(fixture(policyFrom=period[0],policyTo=period[1]))['errors']))
  ready=call(sales,'/api/case-documents?caseUid='+uid,method='get');check('RI Broker note is required for Oversea',ready.status_code==200 and not ready.json()['coverage']['ready'],ready.content[:1200])
  r=call(sales,'/api/case-announce',dict(caseUid=uid,rowVersion=case.row_version,confirmed=True,documentIds=upload_note(sales,uid)));check('Announce record with selected Broker Credit Note',r.status_code==200,r.content[:1500]);case.refresh_from_db();tx=case.payload['transactions']
  check('Announce creates exactly one T3',len(tx)==1 and tx[0]['legType']=='Leg 3' and tx[0]['amount']==2500 and tx[0]['txNo'].endswith('-R1-T3'),tx)
  no=tx[0]['txNo'];check('reference uses class and Effective Date month',case.tw_ref.startswith('TWFA4901'),case.tw_ref)
  check('no zero-value T1/T2 payment schedules',build_payment_schedule(case.payload)['items']==[])
  d=transaction_details(case.payload)[no]
  check('Accounting Date crosses year correctly',d['dueDate']==d['accountingDate']=='2049-12-26' and d['actualPaymentDate']=='2050-01-05',d)
  check('T3 is independent receivable cash account',d['cashTracking']=='cash' and d['canRecord'] and d['paymentDirection']=='receivable' and d['partyName']=='Oversea QA Broker' and not d.get('settlementDependencies'),d)
  check('key-in actual date does not fabricate a Finance receipt',d['paid']==0 and d['outstanding']==2500 and case.payload['paymentEntries']==[])
  r=finance.get('/api/accounting?view=list');row=next(x for x in r.json()['transactionRows'] if x['caseUid']==uid)
  check('Accounting list exposes direct amount and exact dates',row['amount']==2500 and row['accountingDate']=='2049-12-26' and row['actualPaymentDate']=='2050-01-05' and row['overseaBusiness'],row)
  for kind in ['cover','debit','credit','endorsement']:
   r=call(sales,'/api/document-generation-log',dict(caseUid=uid,kind=kind,format='docx'));check('server blocks document generation '+kind,r.status_code==409 and r.json()['error']=='oversea_documents_unavailable',r.content[:800])
  r=call(sales,'/api/claims',dict(caseUid=uid,rowVersion=case.row_version,action='create_claim'));check('API prevents T1/T2 claim creation',r.status_code==409,r.content[:600])
  # Production agrees with list and cash without recomputing premium differences.
  check('Production direct income and actual-date month',reinsurer_legs(case.payload,case.payload['reinsurers'][0])['brokerage']==2500 and installment_allocations(case.payload)[0]['performanceMonth']=='2050-01')
  check('Dashboard income matches direct amount',dashboard_legs(case.payload,case.payload['reinsurers'][0])['brokerage']==2500)
  review=dict(action='review_accounts',date='2050-01-05',reference='Oversea Finance QA',members=[member(case,no)])
  r=call(finance,'/api/accounting',review);check('Finance can review independent T3',r.status_code==200,r.content[:1200])
  changed=copy.deepcopy(case.payload);changed['receiptPaymentDate']='2050-01-06'
  r=call(sales,'/api/cases',dict(caseUid=uid,rowVersion=case.row_version,case=changed,reason='date correction'),method='put');check('reviewed date cannot be silently overwritten',r.status_code==409,r.content[:600])
  with transaction.atomic():
   r=call(finance,'/api/accounting',dict(action='record_transaction_payments',paymentDate='2050-01-04',reference='Wrong date',amount=2500,allocations=[{**member(case,no),'cashAmount':2500,'offsetAmount':0}]))
   check('Finance receipt may use a different actual date',r.status_code==200,r.content[:800])
   transaction.set_rollback(True)
  case.refresh_from_db()
  r=call(finance,'/api/accounting',dict(action='record_transaction_payments',paymentDate='2050-01-05',reference='Actual receipt',amount=2500,allocations=[{**member(case,no),'cashAmount':2500,'offsetAmount':0}]))
  check('Finance records T3 without T1/T2 prerequisites',r.status_code==200,r.content[:1800]);case.refresh_from_db();d=transaction_details(case.payload)[no]
  check('actual cash settles direct T3 and retains Accounting Date',d['settlement']=='settled' and d['paid']==2500 and d['outstanding']==0 and d['accountingDate']=='2049-12-26',d)
  # Closing Production recognizes existing T3 without duplication.
  source=case_source(case);key=f'{case.pk}:FULL:R0';closed=confirm_case(source,[{'reinsurerKey':key}],'2050-01')
  check('Production close never duplicates announced T3',len(closed['payload']['transactions'])==1 and closed['payload']['transactions'][0]['txNo']==no,closed)
  check('production confirmation keeps actual cash',closed['payload']['paymentEntries']==case.payload['paymentEntries'])
  neg=normalize_draft(fixture(reinsurers=[dict(name='Oversea QA Broker',sharePct=25,brokerageAmount=-750)]))['value'];refresh_transactions(neg,'QA-NEG','2050-01-01T00:00:00Z');d=transaction_details(neg)['QA-NEG-R1-T3'];check('negative direct Brokerage is payable T3 only',d['paymentDirection']=='payable' and d['amount']==-750 and len(neg['transactions'])==1,d)
  print(str(len(checks))+' passed Oversea Business checks',flush=True)
  raise Done()
except Done:pass

from cases import storage
for key in note_storage_keys:storage.delete(key)
