"""Manual bank registration with automatic settlement; owner decisions 2026-10-22/24.

Replaces the retired manual-confirmation story while retaining permission,
whole-balance, immutable history, cancellation and bank-return checks.
"""
import copy,os
from django.db import transaction
from cases.accounting_policy import FACILITIES
from cases.calc.payment_terms import build_payment_schedule
from audit.models import AuditLog,EntitySnapshot
from qa.current_accounting import client,make,post,pay,nos,details
assert os.environ.get('RI_DISPOSABLE_QA')=='true'
checks=[]
def check(name,ok,extra=None):
 assert ok,(name,extra)
 checks.append(name);print('PASS '+name,flush=True)
def manual(c,case,no,undo=False):
 case.refresh_from_db()
 return post(c,'unconfirm_facility_settlement' if undo else 'confirm_facility_settlement',caseUid=str(case.case_uid),rowVersion=case.row_version,txNo=no,note='QA reconciliation')
class Rollback(Exception):pass
try:
 with transaction.atomic():
  fin,_=client('manual-finance');read,_=client('manual-read','sales','reinsurance')
  for index,name in enumerate(FACILITIES):
   case=make('CURRENT-MANUAL-'+str(index),names=[name],riPremium=900)
   t1=nos(case,'Leg 1')[0];t2=nos(case,'Leg 2')[0];t3=nos(case,'Leg 3')[0]
   prior=[{'key':'tx:old-preserved-history','confirmed':True,'confirmedAt':'2020-01-01T00:00:00Z','note':'Preserve historical reconciliation'}]
   case.payload['facilityAccounting']={'history':copy.deepcopy(prior)};case.save()
   before=(copy.deepcopy(case.payload),case.row_version)
   check(name+' readonly cannot register bank money',pay(read,case,[t1]).status_code==403)
   check(name+' partial premium receipt rejected',pay(fin,case,[t1],value=400).status_code==400)
   check(name+' reference or explanation is required',pay(fin,case,[t1],reference='').status_code==400)
   case.refresh_from_db();check(name+' refused cash changes neither version nor data',before==(case.payload,case.row_version))
   check(name+' outgoing cannot precede full Cedant receipt',pay(fin,case,[t2]).status_code==409)
   check(name+' Finance records full actual receipt',pay(fin,case,[t1]).status_code==200)
   d=details(case);check(name+' receipt automatically settles and locks T1',d[t1]['settlement']=='settled' and d[t1]['outstanding']==0 and d[t1]['amountEditLocked'] and not d[t1]['canCancelSettlement'])
   check(name+' no separate manual confirmation is available',manual(fin,case,t1).status_code==400)
   check(name+' readonly still cannot invoke confirmation',manual(read,case,t1).status_code==403)
   if name==FACILITIES[-1]:
    check('Swiss still blocks payment without statement reference',pay(fin,case,[t2]).status_code==409)
    case.refresh_from_db();key=next(r['scheduleKey'] for r in build_payment_schedule(case.payload)['items'] if r.get('swissFacility'))
    r=post(fin,'mark_swiss_statement',caseUid=str(case.case_uid),rowVersion=case.row_version,scheduleKey=key,reference='CURRENT-SWISS-STATEMENT')
    check('Swiss statement recorded after full actual receipt',r.status_code==200,r.content)
   check(name+' partial outgoing remains forbidden',pay(fin,case,[t2],value=400).status_code==400)
   check(name+' full actual outgoing is accepted',pay(fin,case,[t2]).status_code==200)
   d=details(case);check(name+' full outgoing and own T3 automatically settle',d[t2]['settlement']=='settled' and d[t3]['settlement']=='settled' and d[t3]['paid']==100 and d[t3]['outstanding']==0)
   case.refresh_from_db();check(name+' derived T3 creates no bank entry',len(case.payload['paymentEntries'])==2 and all(e['transactionNo']!=t3 for e in case.payload['paymentEntries']))
   check(name+' historical reconciliation records are preserved',case.payload['facilityAccounting']['history']==prior)
   saved=copy.deepcopy(case.payload['paymentEntries']);version=case.row_version
   check(name+' settled T1 cannot be manually reopened',manual(fin,case,t1,True).status_code==400)
   case.refresh_from_db();r=post(fin,'reverse_batch_payment',batchId=saved[0]['batchId'],cases=[{'caseUid':str(case.case_uid),'rowVersion':case.row_version}],note='QA bank return')
   check(name+' settled actual receipt cannot be reversed',r.status_code==409 and r.json()['error']=='settled_amount_locked')
   case.refresh_from_db();check(name+' refused reversal retains raw cash and version',case.payload['paymentEntries']==saved and case.row_version==version)
   before=(copy.deepcopy(case.payload),AuditLog.objects.count(),EntitySnapshot.objects.count())
   response=read.get('/api/accounting');case.refresh_from_db()
   check(name+' readonly GET preserves history and amounts',response.status_code==200 and before==(case.payload,AuditLog.objects.count(),EntitySnapshot.objects.count()))
  raise Rollback()
except Rollback:pass
print(f'{len(checks)}/{len(checks)} current Facility cash/settlement checks passed; rolled back')
