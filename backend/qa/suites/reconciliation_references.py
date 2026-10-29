"""Reference-only edits; run solely in the disposable reference QA database."""
import copy,json,os
from unittest.mock import patch
from django.contrib.auth import get_user_model
from django.db import connection,transaction
from django.test import Client,override_settings
from audit.models import AuditLog,EntitySnapshot
from cases.models import Case
from cases.calc.accounting import build_premium_transactions
from cases.cash_ledger import transaction_details
from personnel.models import Personnel
assert os.environ.get('RI_DISPOSABLE_QA')=='true', 'Run only in the disposable QA environment.'
checks=[]
def check(label,value,extra=None):
 assert value,(label,extra) if extra is not None else label
 checks.append(label);print('PASS '+label)
def actor(tag,role='sales',department='reinsurance'):
 user=get_user_model().objects.create_user(username='references.'+tag,password='Ref-QA-only-9!')
 person=Personnel.objects.create(name='References '+tag,department=department,role_code=role,auth_user_id=str(user.pk),account_status='active',created_by='qa',updated_by='qa')
 client=Client(HTTP_HOST='localhost');client.force_login(user);return client,person

def make(ref,status='closed',**over):
 p={'twRef':ref,'currency':'TWD','statementNo':'CEDANT-OLD','originalInsured':'Reference Test Insured','originalInsuredCn':'對帳號碼測試','reinsured':'Ref QA Cedant','classOfBusiness':'Property','classCode':'PAR','reinsuranceStructure':'QS','policyFrom':'2026-01-01','policyTo':'2027-01-01','paymentTermsDays':90,'originalPremium':1000,'riCommPct':10,'taxPct':1,'reinsurers':[{'name':'Ref QA Alpha','sharePct':50,'premium':500,'riCommPct':20,'taxPct':1,'settlementRef':'RI-A-OLD','paymentTermsDays':90},{'name':'Ref QA Beta','sharePct':50,'premium':500,'riCommPct':20,'taxPct':1,'settlementRef':'RI-B-OLD','paymentTermsDays':90}], 'paymentEntries':[], 'facilityAccounting':{'untouched':{'note':'Original reconciliation history'}},'claims':[{'id':'keep-claim','note':'Preserve claim history'}]}
 p.update(over);p['transactions']=build_premium_transactions(p)
 p['transactions'] += [{'txNo':ref+'-C1-T1','source':'claim','claimId':1,'paymentId':1,'legType':'Claim Leg 1','reinsurerIdx':0,'reinsurer':'Ref QA Alpha','amount':50,'createdAt':'2026-10-01T02:00:00Z'},{'txNo':ref+'-C1-T2','source':'claim','claimId':1,'paymentId':1,'legType':'Claim Leg 2','reinsurerIdx':0,'amount':50,'createdAt':'2026-10-01T02:00:00Z'}]
 # 2026-10-16「92 項會計規則」：賠款建立即建帳，到期日＝建帳台灣日期＋15 日；夾具補上建帳時間（createdAt）
 return Case.objects.create(tw_ref=ref,status=status,payload=p,currency='TWD',created_by='qa',updated_by='qa')
def url(case):return '/api/case-reconciliation-references?caseUid='+str(case.case_uid)
def write(client,case,**extra):
 case.refresh_from_db();body={'caseUid':str(case.case_uid),'rowVersion':case.row_version,**extra}
 response=client.post('/api/case-reconciliation-references',data=json.dumps(body),content_type='application/json');case.refresh_from_db();return response
def strip_refs(payload):
 p=copy.deepcopy(payload);p.pop('statementNo',None)
 for row in p.get('reinsurers',[]):row.pop('settlementRef',None)
 return p
class Rollback(Exception):pass
try:
 with transaction.atomic(),override_settings(AUDIT_LOG_PAUSED=False):
  sales,person=actor('sales');admin,_=actor('admin','admin','admin');finance,_=actor('finance','accounting','finance');manager,_=actor('manager','accounting_manager','finance');reader,_=actor('president','president','admin');viewer,_=actor('viewer','viewer','business_1')
  closed=make('REF-QA-CLOSED');posted=make('REF-QA-POSTED','posted')
  before_get=(closed.row_version,AuditLog.objects.count(),EntitySnapshot.objects.count())
  response=sales.get(url(closed));check('writer reads only reference data with no-store',response.status_code==200 and response['Cache-Control']=='no-store, max-age=0' and 'payload' not in response.json()['case'])
  closed.refresh_from_db();check('GET does not change version or history',before_get==(closed.row_version,AuditLog.objects.count(),EntitySnapshot.objects.count()))
  for client,name in [(finance,'finance'),(manager,'finance manager'),(reader,'read-only president'),(viewer,'viewer')]:
   check(name+' cannot read the editor',client.get(url(closed)).status_code==403)
   check(name+' cannot update references',write(client,closed,statementNo='DENIED').status_code==403)
  check('anonymous cannot edit',Client(HTTP_HOST='localhost').get(url(closed)).status_code==401)
  for case in [closed,posted]:
   original=copy.deepcopy(case.payload);old_status=case.status;old_version=case.row_version;ledger_before=transaction_details(original)
   response=write(sales,case,statementNo='000123 / 新號',reinsurers=[{'index':0,'settlementRef':'A-NEW'},{'index':1,'settlementRef':'B-NEW'}]);check(old_status+' accepts both reference changes',response.status_code==200)
   case.refresh_from_db();check(old_status+' preserves complete non-reference payload and status',strip_refs(case.payload)==strip_refs(original) and case.status==old_status and case.row_version==old_version+1)
   check(old_status+' preserves computed cash and settlement',ledger_before==transaction_details(case.payload))
   rows=[r for r in sales.get('/api/accounting').json()['transactionRows'] if r['caseUid']==str(case.case_uid)]
   check(old_status+' Accounting Cedant premium and claim refs update',len(rows)==8 and all(r['reconciliationRef']=='000123 / 新號' for r in rows if r['legType'] in ('Leg 1','Claim Leg 2')))
   check(old_status+' Accounting RI premium and claim refs update',all(r['reconciliationRef']==('A-NEW' if r.get('reinsurerIdx')==0 else 'B-NEW') for r in rows if r['legType'] in ('Leg 2','Claim Leg 1')))
   check(old_status+' Case SoA reads the new reference',sales.get('/api/cases?caseUid='+str(case.case_uid)).json()['case']['payload']['statementNo']=='000123 / 新號')
  # Cash already recorded and manual settlement confirmed must survive reference edits.
  paidcase=make('REF-QA-PAID')
  t1=next(tx['txNo'] for tx in paidcase.payload['transactions'] if tx['legType']=='Leg 1')
  c1=next(tx['txNo'] for tx in paidcase.payload['transactions'] if tx['legType']=='Claim Leg 1')
  def account(body):return finance.post('/api/accounting',data=json.dumps(body),content_type='application/json')
  def pay_amount(value,no=None):
   no=no or t1;paidcase.refresh_from_db();return account({'action':'record_transaction_payments','paymentDate':'2026-10-15','amount':value,'allocations':[{'caseUid':str(paidcase.case_uid),'txNo':no,'rowVersion':paidcase.row_version,'amount':value}], 'note':'QA synthetic registration'})
  # 2026-10-16「92 項會計規則」：保費每次須登錄整筆餘額，只有賠款可部分收付 → 部分收款夾具改用賠款
  check('partial premium payment rejected',pay_amount(100).status_code==400)
  check('partial payment fixture created',pay_amount(20,c1).status_code==200)
  paidcase.refresh_from_db();cash_before=transaction_details(paidcase.payload);raw_before=strip_refs(paidcase.payload)
  check('partial claim fixture recorded',cash_before[c1]['paid']==20 and cash_before[c1]['outstanding']==30,cash_before[c1])
  check('partially paid references update without changing cash',write(sales,paidcase,statementNo='AFTER-PARTIAL').status_code==200 and cash_before==transaction_details(paidcase.payload) and raw_before==strip_refs(paidcase.payload))
  check('remaining payment fixture created',pay_amount(cash_before[t1]['outstanding']).status_code==200)
  paidcase.refresh_from_db();response=account({'action':'confirm_facility_settlement','caseUid':str(paidcase.case_uid),'txNo':t1,'rowVersion':paidcase.row_version,'note':'QA reconciliation complete'})
  check('full receipt auto-settles and manual confirmation is retired',response.status_code==400 and transaction_details(paidcase.payload)[t1]['settlement']=='settled')
  paidcase.refresh_from_db();cash_before=transaction_details(paidcase.payload);raw_before=strip_refs(paidcase.payload)
  check('manually settled references update without reopening settlement',cash_before[t1]['settlement']=='settled' and write(sales,paidcase,statementNo='',reinsurers=[{'index':0,'settlementRef':'AFTER-SETTLED'}]).status_code==200 and cash_before==transaction_details(paidcase.payload) and raw_before==strip_refs(paidcase.payload))
  swiss=make('REF-QA-SCHEDULE','posted',reinsurers=[{'name':'Swiss Re Asia Pte. Ltd., Hong Kong Branch (Facility)','sharePct':100,'premium':1000,'riCommPct':20,'taxPct':1,'settlementRef':'SWISS-OLD'}])
  swiss.payload['transactions']=[];swiss.announced_at=__import__('django.utils.timezone',fromlist=['now']).now();swiss.save()
  check('schedule-only references can update before Production close',write(sales,swiss,statementNo='SWISS-CED',reinsurers=[{'index':0,'settlementRef':'SWISS-RI'}]).status_code==200)
  schedules=[row for row in sales.get('/api/accounting').json()['swissRows'] if row['caseUid']==str(swiss.case_uid)]
  check('schedule-only Accounting uses current refs and names',len(schedules)>=2 and all(row['reconciliationRef']==('SWISS-CED' if row['partyType']=='cedant' else 'SWISS-RI') and row['originalInsured']=='Reference Test Insured' and row['caseStatus']=='posted' for row in schedules))
  snap=EntitySnapshot.objects.filter(entity_id=str(closed.case_uid),snapshot_reason='reconciliation_references_updated').last()
  check('snapshot and audit record the edit',snap is not None and AuditLog.objects.filter(entity_id=str(closed.case_uid),action='update_reconciliation_references').exists())
  check('general Confirmed case editing remains locked',sales.put('/api/cases',data=json.dumps({'caseUid':str(closed.case_uid),'rowVersion':closed.row_version,'case':{**closed.payload,'originalPremium':999999}}),content_type='application/json').status_code==409)
  original=copy.deepcopy(closed.payload)
  check('can clear and reuse references',write(sales,closed,statementNo='',reinsurers=[{'index':0,'settlementRef':''}]).status_code==200 and write(sales,closed,statementNo=posted.payload['statementNo']).status_code==200)
  before=(closed.row_version,EntitySnapshot.objects.count(),AuditLog.objects.count())
  check('identical save is a no-op',write(sales,closed,statementNo=closed.payload['statementNo']).json()['changed'] is False)
  closed.refresh_from_db();check('no-op preserves version and history',before==(closed.row_version,EntitySnapshot.objects.count(),AuditLog.objects.count()))
  cases=[{'statementNo':None},{'statementNo':True},{'statementNo':'a'*161},{'statementNo':'😀'*81},{'originalPremium':5},{'status':'posted'},{'payload':{}},{'reinsurers':[{'index':-1,'settlementRef':'X'}]},{'reinsurers':[{'index':99,'settlementRef':'X'}]},{'reinsurers':[{'index':True,'settlementRef':'X'}]},{'reinsurers':[{'index':0,'settlementRef':'X','name':'OVERRIDE'}]},{'reinsurers':[{'index':0,'settlementRef':'X'},{'index':0,'settlementRef':'Y'}]}]
  for index,data in enumerate(cases):
   before=copy.deepcopy(closed.payload);version=closed.row_version;res=write(sales,closed,**data);closed.refresh_from_db();check('invalid edit '+str(index)+' is atomic',res.status_code==400 and closed.payload==before and closed.row_version==version)
  stale=closed.row_version-1;response=write(sales,closed,rowVersion=stale,statementNo='STALE');check('stale update rejected',response.status_code==409 and response.json()['error']=='version_conflict')
  check('boolean version rejected',write(sales,closed,rowVersion=True,statementNo='BAD').status_code==400)
  version=closed.row_version;before=copy.deepcopy(closed.payload)
  with patch('cases.reference_views.record_snapshot',side_effect=RuntimeError('QA history failure')):
   broken=Client(HTTP_HOST='localhost',raise_request_exception=False);broken.force_login(get_user_model().objects.get(username='references.sales'));response=write(broken,closed,statementNo='ROLLBACK')
  closed.refresh_from_db();check('history failure rolls back the full edit',response.status_code==500 and closed.row_version==version and closed.payload==before)
  with override_settings(AUDIT_LOG_PAUSED=True):
   n_audit=AuditLog.objects.count();n_snap=EntitySnapshot.objects.count();check('audit pause permits reference update',write(sales,closed,statementNo='PAUSED-OK').status_code==200)
   check('audit pause remains respected and snapshot persists',AuditLog.objects.count()==n_audit and EntitySnapshot.objects.count()==n_snap+1)
  for status in ['draft','reversed','archived']:
   case=make('REF-QA-'+status,status);before=copy.deepcopy(case.payload);check(status+' does not use the Announced/Confirmed editor',write(sales,case,statementNo='NO').status_code==409);case.refresh_from_db();check(status+' remains unchanged',case.payload==before)
  for kind in ['archived','recycled']:
   case=make('REF-QA-hidden-'+kind)
   from django.utils import timezone
   if kind=='archived':case.is_archived=True;case.archived_at=timezone.now();case.archived_by='qa'
   else:case.status='draft';case.recycled_at=timezone.now();case.recycled_by='qa'
   case.save();check(kind+' case is not exposed',sales.get(url(case)).status_code==404)
  check('admin uses the same guarded route',write(admin,closed,statementNo='ADMIN-OK').status_code==200)
  raise Rollback()
except Rollback:pass
print(str(len(checks))+'/'+str(len(checks))+' passed; database changes rolled back')
