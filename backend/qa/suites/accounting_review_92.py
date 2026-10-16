"""Integration regression of the owner's 92 accounting decisions; disposable DB only."""
import copy,json,os
from datetime import datetime,timedelta,timezone as dtz
from unittest.mock import patch
from django.contrib.auth import get_user_model
from django.db import transaction
from django.test import Client,override_settings
from django.utils import timezone
from cases.models import Case
from personnel.models import Personnel
from cases.calc.accounting import build_premium_transactions
from cases.cash_ledger import transaction_details
from audit.models import EntitySnapshot
from fxrates.models import FxRate
assert os.environ.get('RI_DISPOSABLE_QA')=='true'
checks=[]
def check(name,condition,extra=None):
 assert condition,(name,extra)
 checks.append(name);print('PASS '+name,flush=True)
def client(tag,role,dept):
 u=get_user_model().objects.create_user(username='ar92.'+tag,password='Accounting-Review-92!')
 p=Personnel.objects.create(name='AR92 '+tag,department=dept,role_code=role,email=tag+'@company.invalid',auth_user_id=str(u.pk),account_status='active',created_by='qa',updated_by='qa')
 c=Client(HTTP_HOST='localhost');c.force_login(u);return c,p
serial=0
def make(prefix='P',**changes):
 global serial;serial+=1;ref='AR92-'+prefix+str(serial)
 p={'twRef':ref,'currency':'TWD','classOfBusiness':'Property','reinsured':'AR92 Cedant','policyFrom':'2026-01-01','policyTo':'2027-01-01','paymentTermsDays':30,'originalPremium':1000,'riCommPct':0,'taxPct':0,'reinsurers':[{'name':'AR92 RI','sharePct':100,'premium':800,'riCommPct':0,'taxPct':0,'paymentTermsDays':30}],'paymentEntries':[]}
 status=changes.pop('status','closed');parent=changes.pop('parent',None);announced=changes.pop('announced',datetime(2026,1,1,tzinfo=dtz.utc))
 p.update(changes)
 if parent:p.update(parentTwRef=parent.tw_ref,endoEffectiveDate=p.get('endoEffectiveDate','2026-01-01'),endorsementAnnouncedAt=announced.isoformat())
 p['transactions']=build_premium_transactions(p)
 for t in p['transactions']:t.update(postedMonth='2026-01',createdAt='2026-01-01T00:00:00Z')
 return Case.objects.create(tw_ref=ref,status=status,payload=p,currency=p['currency'],parent_case=parent,case_kind='endorsement' if parent else 'original',announced_at=announced,created_by='qa',updated_by='qa')
def details(case):case.refresh_from_db();return transaction_details(case.payload)
def tx(case,leg,index=0):case.refresh_from_db();return [t['txNo'] for t in case.payload['transactions'] if t['legType']==leg][index]
def request(c,action,**body):return c.post('/api/accounting',data=json.dumps({'action':action,**body}),content_type='application/json')
def pay(c,case,leg,value,index=0,date='2026-10-01'):
 no=tx(case,leg,index);return request(c,'record_transaction_payments',paymentDate=date,amount=value,allocations=[{'caseUid':str(case.case_uid),'rowVersion':case.row_version,'txNo':no,'amount':value}])
def settle(c,case,leg,index=0,undo=False,**extra):
 no=tx(case,leg,index);return request(c,'unconfirm_facility_settlement' if undo else 'confirm_facility_settlement',caseUid=str(case.case_uid),rowVersion=case.row_version,txNo=no,note='AR92 checked',**extra)
def offset(c,root,refund,party='cedant'):
 from cases.calc.payment_terms import build_payment_schedule
 from cases.calc.swiss_facility import case_payload
 root.refresh_from_db();refund.refresh_from_db()
 a=next(i for i in build_payment_schedule(case_payload(root))['items'] if i['partyType']==party)
 b=next(i for i in build_payment_schedule(case_payload(refund))['items'] if i['partyType']==party)
 return request(c,'record_premium_offset',originalCaseUid=str(root.case_uid),refundCaseUid=str(refund.case_uid),originalRowVersion=root.row_version,refundRowVersion=refund.row_version,originalKey=a['scheduleKey'],refundKey=b['scheduleKey'],paymentDate='2026-10-01',amount=abs(b['outstanding']))
class Rollback(Exception):pass
try:
 with transaction.atomic():
  fin,fp=client('finance','accounting','finance');mgr,mp=client('manager','accounting_manager','finance');sales,sp=client('sales','sales','reinsurance');admin,ap=client('admin','admin','admin')
  a=make()
  check('premium partial receipt rejected',pay(fin,a,'Leg 1',200).status_code==400)
  check('full premium receipt accepted',pay(fin,a,'Leg 1',1000).status_code==200)
  check('received is distinct from manual settlement',details(a)[tx(a,'Leg 1')]['settlement']=='pending_confirmation')
  check('manual T1 settlement succeeds',settle(fin,a,'Leg 1').status_code==200)
  a.refresh_from_db();entry=a.payload['paymentEntries'][0]
  check('settled amount editing rejected',request(fin,'edit_payment',caseUid=str(a.case_uid),rowVersion=a.row_version,entryId=entry['id'],amount=900,reason='test').status_code==409)
  check('T1 can cancel before final T3',settle(fin,a,'Leg 1',undo=True).status_code==200)
  a.refresh_from_db();check('ever-settled amount stays locked after cancellation',request(fin,'edit_payment',caseUid=str(a.case_uid),rowVersion=a.row_version,entryId=entry['id'],amount=1000,reason='test').status_code==409)
  check('T1 can be explicitly re-settled',settle(fin,a,'Leg 1').status_code==200)
  check('full T2 payment accepted',pay(fin,a,'Leg 2',800).status_code==200)
  check('T3 blocked before T2 manual settlement',settle(fin,a,'Leg 3').status_code==400)
  check('T2 and T3 settle explicitly',settle(fin,a,'Leg 2').status_code==200 and settle(fin,a,'Leg 3').status_code==200)
  check('final T3 locks all three cancellation paths',all(settle(fin,a,l,undo=True).status_code==409 for l in ['Leg 1','Leg 2','Leg 3']))
  from cases.workflow import build_reversed_payload
  try:build_reversed_payload(a.payload);blocked=False
  except ValueError:blocked=True
  check('any premium cash/settlement history blocks Case Reverse',blocked)
  claimroot=make('CLAIM',reinsurers=[{'name':'R A','sharePct':60,'premium':800,'riCommPct':0,'taxPct':0,'paymentTermsDays':30},{'name':'R B','sharePct':40,'premium':800,'riCommPct':0,'taxPct':0,'paymentTermsDays':30}])
  make('ENDO',parent=claimroot,endoEffectiveDate='2026-07-01',announced=datetime(2026,7,1,tzinfo=dtz.utc),reinsurers=[{'name':'R A','sharePct':50,'premium':800,'riCommPct':0,'taxPct':0,'paymentTermsDays':30},{'name':'R B','sharePct':50,'premium':800,'riCommPct':0,'taxPct':0,'paymentTermsDays':30}])
  def claimwrite(action,**body):
   claimroot.refresh_from_db();return sales.post('/api/claims',data=json.dumps({'action':action,'caseUid':str(claimroot.case_uid),'rowVersion':claimroot.row_version,**body}),content_type='application/json')
  check('claim reserve creation succeeds without accounting entries',claimwrite('create_claim',claim={'dateOfLoss':'2026-03-01','outstandingReserve':1000}).status_code==200)
  old=len(claimroot.payload['transactions']);claimroot.refresh_from_db();check('reserve has no ledger',len(claimroot.payload['transactions'])==old)
  check('record claim creates obligations immediately',claimwrite('record_payment',claimId=1,payment={'date':'2026-01-01','amount':1000}).status_code==200)
  claimroot.refresh_from_db();claims=[t for t in claimroot.payload['transactions'] if t.get('source')=='claim']
  check('claim uses loss-date 60/40 not later 50/50', [t['amount'] for t in claims if t['legType']=='Claim Leg 1']==[600,400])
  expected=(timezone.now().astimezone(__import__('zoneinfo').ZoneInfo('Asia/Taipei')).date()+timedelta(days=15)).isoformat()
  check('claim due is creation Taiwan date +15, ignoring backdated obligation date',all(t['dueDate']==expected for t in claims))
  check('unprocessed claim amount can be corrected',claimwrite('correct_payment',claimId=1,paymentId=1,reason='Correct total',payment={'date':'2026-01-01','amount':900}).status_code==200)
  claimroot.refresh_from_db();check('claim correction keeps before/after history',len(claimroot.payload['claimCorrectionHistory'])==1 and claimroot.payload['claimCorrectionHistory'][0]['before']['amount']==1000)
  check('claim outgoing cannot precede receipts',pay(fin,claimroot,'Claim Leg 2',1).status_code==400)
  check('partial claim receipt accepted',pay(fin,claimroot,'Claim Leg 1',100).status_code==200)
  check('outgoing above received cap rejected',pay(fin,claimroot,'Claim Leg 2',101).status_code==400)
  check('partial outgoing within recorded receipts accepted',pay(fin,claimroot,'Claim Leg 2',40).status_code==200)
  claimroot.refresh_from_db();incoming=next(e for e in claimroot.payload['paymentEntries'] if e.get('transactionNo')==tx(claimroot,'Claim Leg 1'))
  check('receipt edit cannot lower total below already reported outgoing',request(fin,'edit_payment',caseUid=str(claimroot.case_uid),rowVersion=claimroot.row_version,entryId=incoming['id'],amount=30,reason='Correction').status_code==409)
  claimroot.refresh_from_db();check('unsettled receipt amount can be edited with reason',request(fin,'edit_payment',caseUid=str(claimroot.case_uid),rowVersion=claimroot.row_version,entryId=incoming['id'],amount=80,reason='Correction').status_code==200)
  claimroot.refresh_from_db();check('receipt edit history records before/after',claimroot.payload['paymentEditHistory'][-1]['before']['amount']==100 and claimroot.payload['paymentEditHistory'][-1]['after']['amount']==80)
  check('claim source amount is locked once any claim receipt exists',claimwrite('correct_payment',claimId=1,paymentId=1,reason='test',payment={'date':'2026-01-01','amount':800}).status_code==409)
  untouched=make('REVERSE');untouched.payload['transactions']+=copy.deepcopy(claims);untouched.save()
  reversed_payload=build_reversed_payload(untouched.payload)
  check('premium Reverse leaves claim transactions effective',all(not t.get('reversed') for t in reversed_payload['transactions'] if t.get('source')=='claim'))
  untouched.payload=reversed_payload;untouched.status='reversed';untouched.save()
  check('claim cash entry remains usable during premium Reverse',pay(fin,untouched,'Claim Leg 1',10).status_code==200)
  pending=make('PENDING',paymentTermsDays=None,reinsurers=[{'name':'AR92 RI','sharePct':100,'premium':800,'riCommPct':0,'taxPct':0,'paymentTermsDays':None}])
  check('missing premium contract days block receipt',pay(fin,pending,'Leg 1',1000).status_code==400)
  key={'caseUid':str(pending.case_uid),'rowVersion':pending.row_version,'installmentId':'case-effective-date','partyKey':'cedant','days':30,'reason':'Confirmed agreement'}
  check('Finance cannot edit case contract terms',request(fin,'complete_payment_terms',**key).status_code==403)
  check('case staff can complete missing terms without Reverse',request(sales,'complete_payment_terms',**key).status_code==200)
  pending.refresh_from_db();key['rowVersion']=pending.row_version
  check('existing valid contract days remain locked',request(sales,'complete_payment_terms',**key).status_code==409)
  root=make('OFFSET');refund=make('REFUND',parent=root,originalPremium=-200,reinsurers=[{'name':'AR92 RI','sharePct':100,'premium':-160,'riCommPct':0,'taxPct':0,'paymentTermsDays':30}])
  check('ordinary premium manual offset succeeds',offset(fin,root,refund).status_code==200)
  check('manual offset creates no bank receipt and does not auto-settle',details(root)[tx(root,'Leg 1')]['cashPaid']==0 and details(root)[tx(root,'Leg 1')]['outstanding']==800 and details(refund)[tx(refund,'Leg 1')]['settlement']=='pending_confirmation')
  try:build_reversed_payload(root.payload);blocked=False
  except ValueError:blocked=True
  check('offset history blocks Case Reverse',blocked)
  sname='Swiss Re Asia Pte. Ltd., Hong Kong Branch (Facility)'
  swiss=make('SWISS',reinsurers=[{'name':sname,'sharePct':100,'premium':800,'riCommPct':0,'taxPct':0,'paymentTermsDays':90}])
  swissrefund=make('SWISSREF',parent=swiss,endoEffectiveDate='2026-09-01',announced=datetime(2026,9,1,tzinfo=dtz.utc),originalPremium=-200,reinsurers=[{'name':sname,'sharePct':100,'premium':-160,'riCommPct':0,'taxPct':0,'paymentTermsDays':90}])
  check('Swiss cannot offset before collection prerequisites',offset(fin,swiss,swissrefund,'reinsurer').status_code==400 and offset(fin,swiss,swissrefund,'cedant').status_code==400)
  check('Swiss payment waits for Cedant manual settlement',pay(fin,swiss,'Leg 2',800).status_code==400)
  check('Swiss full Cedant receipt and settlement accepted',pay(fin,swiss,'Leg 1',1000).status_code==200 and settle(fin,swiss,'Leg 1').status_code==200)
  check('Swiss still requires statement reference',pay(fin,swiss,'Leg 2',800).status_code==400)
  swiss.refresh_from_db();key={'caseUid':str(swiss.case_uid),'rowVersion':swiss.row_version,'scheduleKey':'case-effective-date:reinsurer:r1'}
  check('Swiss statement ref can be entered after collection',request(fin,'mark_swiss_statement',**key,reference='SWISS-AR92').status_code==200)
  check('Swiss payment accepted after collection and reference',pay(fin,swiss,'Leg 2',800).status_code==200)
  swiss.refresh_from_db();check('bank fees/shortfall endpoint removed',request(fin,'record_swiss_clearance',caseUid=str(swiss.case_uid),rowVersion=swiss.row_version,scheduleKey='case-effective-date:cedant',amount=1,clearingType='bank_fee',note='x').status_code==400)
  check('separate Swiss collected checkbox removed',request(fin,'confirm_swiss_collection',caseUid=str(swiss.case_uid),rowVersion=swiss.row_version,scheduleKey='case-effective-date:cedant').status_code==400)
  # Close a month containing only a zero-income obligation: no Production rows.
  zero=make('ZERO',status='posted',policyFrom='2031-05-01',policyTo='2032-05-01',announced=datetime(2031,5,1,tzinfo=dtz.utc),reinsurers=[{'name':'AR92 RI','sharePct':100,'premium':1000,'riCommPct':0,'taxPct':0,'paymentTermsDays':30}])
  zero.payload['transactions']=[];zero.save()
  prod='/api/production-report'
  view=mgr.get(prod+'?month=2031-05').json();preview=view.get('preview',view)
  check('zero-income preview excludes performance rows but includes accounting rows',not preview['rows'] and len(preview.get('accountingRows',[]))==1,view.keys())
  def prodpost(action,**body):return mgr.post(prod,data=json.dumps({'action':action,'month':'2031-05',**body}),content_type='application/json')
  generated=prodpost('generate',sourceSignature=preview['sourceSignature']);check('zero-income-only report can be generated',generated.status_code==201,generated.content)
  report=generated.json()['report'];closed=prodpost('close',reportUid=report['reportUid'],rowVersion=report['rowVersion'],sourceSignature=report['sourceSignature'])
  check('zero-income-only report close succeeds',closed.status_code==200,closed.content)
  zero.refresh_from_db();check('zero-income close creates T1/T2/T3 and Confirmed',zero.status=='closed' and len(zero.payload['transactions'])==3)
  check('new premium obligations retain actual posting month',all(t['postedMonth']=='2031-05' for t in zero.payload['transactions']))
  # Reminder service is fully mocked: no live or test SMTP is ever contacted.
  from reminders.runner import run_payment
  from reminders.messages import resolve_recipients,finance_emails
  people=[{'name':sp.name,'email':sp.email,'supervisor_email':''},{'name':fp.name,'email':fp.email,'role_code':'accounting'},{'name':mp.name,'email':mp.email,'role_code':'accounting_manager'}]
  recipients=resolve_recipients({'ae':sp.name},people,finance_emails(people))
  check('valid recipients retained when supervisor is missing',sp.email in recipients['recipients'] and fp.email in recipients['recipients'] and recipients['missing'])
  check('Finance Manager not added to financial recipient group',mp.email not in recipients['recipients'])
  mailcase=make('MAIL',policyFrom='2031-05-16',policyTo='2032-05-16',ae=sp.name)
  with patch('reminders.runner._open_cases',return_value=Case.objects.filter(pk=mailcase.pk)),patch('reminders.runner._send',return_value='AR92-MOCK') as sender,patch('reminders.runner.is_reserved_test_email',return_value=False),override_settings(PAYMENT_REMINDER_EMAIL_ENABLED=True):
   first=run_payment('2031-06-08');check('reminder sends seven days before actual contract due',first['sent']==1,first)
   check('same-day reminder deduplicated',run_payment('2031-06-08')['sent']==0)
   check('due-day reminder sends',run_payment('2031-06-15')['sent']==1)
   check('no daily overdue spam',run_payment('2031-06-16')['sent']==0)
   check('weekly overdue reminder sends',run_payment('2031-06-22')['sent']==1)
   check('reminder sender remains mocked',sender.call_count==3)
  check('Finance read-only references stay forbidden',fin.get('/api/case-reconciliation-references?caseUid='+str(a.case_uid)).status_code==403)
  # Every T1 must be explicitly settled; one Swiss checkbox never settles its peers.
  mixed=make('SWISSMIX',reinsurers=[{'name':sname,'sharePct':60,'premium':800,'riCommPct':0,'taxPct':0,'paymentTermsDays':90},{'name':'Other RI','sharePct':40,'premium':800,'riCommPct':0,'taxPct':0,'paymentTermsDays':30}])
  check('both mixed Cedant receipt allocations recorded',pay(fin,mixed,'Leg 1',600,0).status_code==200 and pay(fin,mixed,'Leg 1',400,1).status_code==200)
  check('first mixed T1 manual settlement succeeds',settle(fin,mixed,'Leg 1',0).status_code==200)
  check('one cleared T1 never settles the other or releases Swiss',details(mixed)[tx(mixed,'Leg 1',1)]['settlement']=='pending_confirmation' and pay(fin,mixed,'Leg 2',480,0).status_code==400)
  check('last T1 manual settlement completes whole-period confirmation',settle(fin,mixed,'Leg 1',1).status_code==200)
  from cases.calc.payment_terms import build_payment_schedule
  mixed.refresh_from_db()
  check('whole Cedant confirmation uses manual settlement date',next(i for i in build_payment_schedule(mixed.payload)['items'] if i.get('swissFacility'))['collectionConfirmed'])
  # Dry-run, explicitly signed apply, history protection and idempotent legacy repair.
  from django.core.management import call_command
  from io import StringIO
  from cases.calc.accounting import build_claim_payment_transactions
  legacy=make('LEGACY',reinsurers=[{'name':'Old A','sharePct':60,'premium':800,'riCommPct':0,'taxPct':0,'paymentTermsDays':30},{'name':'Old B','sharePct':40,'premium':800,'riCommPct':0,'taxPct':0,'paymentTermsDays':30}])
  later=make('LEGACYENDO',parent=legacy,endoEffectiveDate='2026-07-01',announced=datetime(2026,7,1,tzinfo=dtz.utc),reinsurers=[{'name':'Old A','sharePct':50,'premium':800,'riCommPct':0,'taxPct':0,'paymentTermsDays':30},{'name':'Old B','sharePct':50,'premium':800,'riCommPct':0,'taxPct':0,'paymentTermsDays':30}])
  before=copy.deepcopy(legacy.payload);claim={'id':1,'dateOfLoss':'2026-03-01','payments':[]};before['claims']=[copy.deepcopy(claim)]
  payment={'id':1,'date':'2026-02-01','amount':1000};claim['payments']=[payment];legacy.payload['claims']=[claim];legacy.payload['transactions'].extend(build_claim_payment_transactions(legacy.payload,later.payload,claim,payment));legacy.row_version=2;legacy.save()
  EntitySnapshot.objects.create(entity_type='case',entity_id=str(legacy.case_uid),entity_version=1,snapshot_reason='claim_created',snapshot_data={'payload':before},created_by='qa',created_at=datetime(2026,4,1,tzinfo=dtz.utc))
  EntitySnapshot.objects.create(entity_type='case',entity_id=str(legacy.case_uid),entity_version=2,snapshot_reason='claim_payment_recorded',snapshot_data={'payload':copy.deepcopy(legacy.payload)},created_by='qa',created_at=datetime(2026,4,2,tzinfo=dtz.utc))
  oldzero=make('OLDZERO',status='posted',policyFrom='2031-05-01',policyTo='2032-05-01',announced=datetime(2031,5,1,tzinfo=dtz.utc),reinsurers=[{'name':'AR92 RI','sharePct':100,'premium':1000,'riCommPct':0,'taxPct':0,'paymentTermsDays':30}]);oldzero.payload['transactions']=[];oldzero.save()
  def preview_repair(**kw):
   out=StringIO();call_command('apply_accounting_review',stdout=out,**kw);return json.loads(out.getvalue())
  v=legacy.row_version;preview=preview_repair();legacy.refresh_from_db();check('legacy dry-run makes no writes',legacy.row_version==v and not preview['applied'])
  old_report=list(__import__('production.models',fromlist=['ProductionReport']).ProductionReport.objects.values('report_uid','rows','row_version','status'))
  protected=copy.deepcopy(a.payload['transactions']);applied=preview_repair(apply=True,expected_signature=preview['signature']);legacy.refresh_from_db();oldzero.refresh_from_db();a.refresh_from_db()
  check('legacy untouched claim ratios corrected to loss-date version',[t['amount'] for t in legacy.payload['transactions'] if t.get('source')=='claim' and t['legType']=='Claim Leg 1']==[600,400])
  check('legacy creation date recovered from payment snapshot, not obligation date',all(t['dueDate']=='2026-04-17' for t in legacy.payload['transactions'] if t.get('source')=='claim'))
  check('legacy correction preserves business history independent of audit',bool(legacy.payload.get('accountingAdjustmentHistory')))
  check('previously handled transaction amounts are preserved',a.payload['transactions']==protected)
  check('legacy zero-income obligations backfill first open month',[t['postedMonth'] for t in oldzero.payload['transactions']]==['2031-06']*3 and oldzero.status=='closed')
  check('legacy repairs never rewrite closed Production reports',list(__import__('production.models',fromlist=['ProductionReport']).ProductionReport.objects.values('report_uid','rows','row_version','status'))==old_report)
  check('legacy repair is idempotent',preview_repair()['changedCases']==0)
  print(str(len(checks))+'/'+str(len(checks))+' accounting review checks passed',flush=True)
  raise Rollback()
except Rollback:pass
