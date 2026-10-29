"""Swiss Property: B+90 quarter, actual operation date, full cash and immutable history.

Swiss CGL's separate month-end formula is covered by CGL suites; this suite uses
Property explicitly and never restores retired manual confirmations or offsets.
"""
import copy,os
from datetime import datetime,date,timedelta,timezone
from unittest.mock import patch
from django.db import transaction
from cases.calc.payment_terms import build_payment_schedule,_as_utc
from cases.calc.swiss_facility import SWISS_NAME
from qa.current_accounting import client,make,post,pay,nos,details
assert os.environ.get('RI_DISPOSABLE_QA')=='true'
checks=[]
def check(name,ok,extra=None):
 assert ok,(name,extra)
 checks.append(name);print('PASS '+name,flush=True)
def swiss(case,now=None):return next(r for r in build_payment_schedule(case.payload,now)['items'] if r.get('swissFacility'))
def statement(fin,case,ref='QA-SWISS-STATEMENT'):
 case.refresh_from_db();return post(fin,'mark_swiss_statement',caseUid=str(case.case_uid),rowVersion=case.row_version,scheduleKey=swiss(case)['scheduleKey'],reference=ref)
class Rollback(Exception):pass
try:
 with transaction.atomic():
  fin,_=client('swiss-finance');read,_=client('swiss-read','sales','reinsurance')
  matrix=[('2026-01-01','2026-05-14'),('2026-01-30','2026-05-14'),('2026-01-31','2026-08-14'),('2028-01-31','2028-05-14'),('2026-10-03','2027-02-14')]
  stamp=datetime(2026,4,20,2,tzinfo=timezone.utc)
  for i,(base,expected) in enumerate(matrix):
   case=make('SWISS-CALENDAR-'+str(i),names=[SWISS_NAME],policyFrom=base)
   before=copy.deepcopy(case.payload);items=build_payment_schedule(case.payload,stamp)['items'];cedant=items[0];item=next(r for r in items if r.get('swissFacility'))
   check('original Swiss quarter from Cedant B+90 '+base,item['originalDueDate']==expected,item)
   check('Swiss Cedant actual due and Accounting date '+base,cedant['contractDueDate']==(date.fromisoformat(base)+timedelta(days=90)).isoformat() and cedant['dueDate']==(date.fromisoformat(base)+timedelta(days=80)).isoformat())
   check('reading calendar never rewrites saved history '+base,case.payload==before)
  case=make('SWISS-API-CALENDAR',names=[SWISS_NAME],policyFrom='2026-01-31')
  class Frozen(datetime):
   @classmethod
   def now(cls,tz=None):return stamp if tz else stamp.replace(tzinfo=None)
  with patch('cases.accounting_views.datetime',Frozen):
   rows=fin.get('/api/accounting').json()['swissRows'];mine=[r for r in rows if r['caseUid']==str(case.case_uid)]
   check('API original date uses Aug14 and the complete frozen clock',any(r.get('originalDueDate')=='2026-08-14' and r['dueDate']=='2026-08-14' for r in mine),mine)
  t1=nos(case,'Leg 1');t2=nos(case,'Leg 2');t3=nos(case,'Leg 3')
  check('Swiss payment cannot precede full Cedant cash',pay(fin,case,t2).status_code==409)
  check('statement cannot precede full Cedant settlement',statement(fin,case).status_code==409)
  check('readonly cannot register Swiss cash',pay(read,case,t1).status_code==403)
  check('partial Swiss Cedant cash rejected',pay(fin,case,t1,value=500).status_code==400)
  check('full Swiss Cedant cash recorded',pay(fin,case,t1).status_code==200)
  d=details(case);check('Swiss Cedant automatically settles',all(d[n]['settlement']=='settled' for n in t1))
  check('missing statement still blocks Swiss payment',pay(fin,case,t2).status_code==409)
  check('statement is recorded after automatic collection',statement(fin,case).status_code==200)
  check('partial Swiss payable rejected',pay(fin,case,t2,value=400).status_code==400)
  check('full Swiss payable recorded',pay(fin,case,t2).status_code==200)
  d=details(case);check('Swiss T2 and T3 automatically settle',all(d[n]['settlement']=='settled' for n in t2+t3))
  case.refresh_from_db();before=copy.deepcopy(case.payload);entry=case.payload['paymentEntries'][-1]
  r=post(fin,'reverse_batch_payment',batchId=entry['batchId'],cases=[{'caseUid':str(case.case_uid),'rowVersion':case.row_version}],note='QA returned remittance')
  case.refresh_from_db();check('settled bank remittance cannot be reopened',r.status_code==409 and r.json()['error']=='settled_amount_locked' and case.payload==before)
  check('T3 never fabricates a bank entry',len(case.payload['paymentEntries'])==2)
  for action in ['confirm_swiss_collection','record_swiss_clearance','confirm_facility_settlement','unconfirm_facility_settlement']:
   case.refresh_from_db();r=post(fin,action,caseUid=str(case.case_uid),rowVersion=case.row_version,txNo=t1[0],scheduleKey='case-effective-date:cedant',amount=1,note='QA retired action')
   check('retired Swiss/manual action remains blocked '+action,r.status_code==400)
  # Actual operation date, rather than a backdated bank date, determines lateness.
  late=make('SWISS-LATE-OPERATION',names=[SWISS_NAME]);late_stamp=datetime(2026,5,2,2,tzinfo=timezone.utc)
  with patch('cases.calc.payment_terms._as_utc',side_effect=lambda v=None:late_stamp if v is None else _as_utc(v)),patch('cases.cash_ledger._as_utc',side_effect=lambda v=None:late_stamp if v is None else _as_utc(v)),patch('cases.accounting_views._iso_now',return_value='2026-05-02T02:00:00.000Z'):
   check('backdated bank receipt may be registered',pay(fin,late,nos(late,'Leg 1'),paymentDate='2026-04-30').status_code==200)
   late.refresh_from_db();item=swiss(late,late_stamp)
   check('late operation moves projected quarter but retains original quarter',item['originalDueDate']=='2026-05-14' and item['dueDate']=='2026-08-14',item)
   check('actual operation date is stored separately from bank date',late.payload['paymentEntries'][0]['paymentDate']=='2026-04-30' and late.payload['paymentEntries'][0]['createdAt'].startswith('2026-05-02'))
  # Every RI refund is required, then all independent Cedant T1 must be selected.
  root=make('SWISS-REFUND-ROOT',names=[SWISS_NAME,'QA Other RI'],shares=[60,40])
  refund=make('SWISS-REFUND',names=[SWISS_NAME,'QA Other RI'],shares=[60,40],parent=root,originalPremium=-200,riPremium=-160)
  r1=nos(refund,'Leg 2');c1=nos(refund,'Leg 1')
  check('Cedant refund waits for all RI recoveries',pay(fin,refund,c1).status_code==409)
  check('first RI recovery recorded in full',pay(fin,refund,r1[:1]).status_code==200)
  check('one collected recovery does not release whole Cedant refund',pay(fin,refund,c1).status_code==409)
  check('last RI recovery automatically settles',pay(fin,refund,r1[1:]).status_code==200)
  check('cannot refund just one independent Cedant T1',pay(fin,refund,c1[:1]).status_code==400)
  for party in ['cedant','reinsurer:r1']:
   root.refresh_from_db();refund.refresh_from_db()
   r=post(fin,'record_premium_offset',originalCaseUid=str(root.case_uid),refundCaseUid=str(refund.case_uid),originalRowVersion=root.row_version,refundRowVersion=refund.row_version,originalKey='case-effective-date:'+party,refundKey='case-effective-date:'+party,amount=200,paymentDate='2026-10-27')
   check('Swiss offsets remain unavailable '+party,r.status_code==400 and r.json()['error']=='offset_not_allowed')
  check('whole Cedant refund may be paid early after all actual recoveries',pay(fin,refund,c1).status_code==200)
  check('refund balances automatically settle',all(d['settlement']=='settled' for d in details(refund).values()))
  # Existing returned-bank history keeps its booked period; no new reversal is fabricated.
  historic=make('SWISS-OLD-RETURN',names=[SWISS_NAME]);no=nos(historic,'Leg 2')[0]
  original={'id':'old-paid','entryType':'payment','transactionNo':no,'scheduleKey':'case-effective-date:reinsurer:r1','amount':800,'paymentDate':'2026-05-14','settlementDueDate':'2026-05-14'}
  reversal={**original,'id':'old-bank-return','entryType':'reversal','reversalOf':'old-paid','paymentDate':'2026-05-16'}
  historic.payload['paymentEntries']=[original,reversal];historic.save();before=copy.deepcopy(historic.payload)
  item=swiss(historic,datetime(2026,11,1,tzinfo=timezone.utc));check('old returned remittance retains its original overdue period',item['dueDate']=='2026-05-14' and item['outstanding']==800 and item['status']=='overdue',item)
  fin.get('/api/accounting');historic.refresh_from_db();check('reading preserves both immutable original and bank-return records',historic.payload==before)
  raise Rollback()
except Rollback:pass
print(f'{len(checks)}/{len(checks)} current Swiss Property checks passed; writes rolled back')
