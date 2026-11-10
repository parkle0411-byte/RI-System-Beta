"""Removed API contracts fail safely; immutable legacy records remain readable."""
from pathlib import Path
exec(Path('/app/qa/suites/finance_workflow.py').read_text().split('class Done(Exception):')[0])
from cases.finance_workflow import active_reviews
from django.test import override_settings
from audit.models import AuditLog
class Done(Exception):pass
try:
 with transaction.atomic():
  fin=client('retired-fin','accounting');sales=client('retired-sales','sales')
  a=fixture('QA-RETIRED');no=leg(a,'Leg 1');snapshot=(copy.deepcopy(a.payload),a.row_version,EntitySnapshot.objects.count(),AuditLog.objects.count())
  retired=['record_payment','reverse_payment','record_allianz_claim_followup','record_great_american_claim_followup','record_qbe_claim_followup','edit_payment','confirm_facility_settlement','unconfirm_facility_settlement',
   'confirm_swiss_collection','unconfirm_swiss_collection','record_swiss_clearance','record_swiss_offset','record_premium_offset']
  for action in retired:
   r=api(fin,{'action':action,'caseUid':str(a.case_uid),'rowVersion':a.row_version,'amount':1,'note':'QA forbidden legacy action'})
   check('retired action rejected: '+action,r.status_code==410 and r.json()['error']=='retired_accounting_action',r.content)
   check('readonly cannot invoke retired action: '+action,api(sales,{'action':action}).status_code==403)
  a.refresh_from_db();check('retired operations preserve raw accounts, versions and snapshots',snapshot==(a.payload,a.row_version,EntitySnapshot.objects.count(),AuditLog.objects.count()))
  for bad in (None,{},'bad',[],[None],[{'caseUid':'bad','txNo':'x','rowVersion':1}]):
   r=api(fin,{'action':'review_accounts','date':'2026-11-03','reference':'QA','members':bad})
   check('invalid review members rejected without server error '+repr(bad),400<=r.status_code<500,r.content)
  for bad in (None,'not-a-uuid',42,{},[]):
   r=api(fin,{'action':'cancel_review_batch','reviewBatchId':bad,'reason':'QA','members':[]})
   check('invalid cancel batch rejected without server error '+repr(bad),400<=r.status_code<500,r.content)
  review([(a,no)]);a.refresh_from_db();snapshot=(copy.deepcopy(a.payload),a.row_version,EntitySnapshot.objects.count())
  for cash_value in (True,-1,'NaN','Infinity',1e308):
   r=register([(a,no,cash_value,0)],1000)
   a.refresh_from_db();check('invalid cash allocation immutable '+repr(cash_value),400<=r.status_code<500 and snapshot==(a.payload,a.row_version,EntitySnapshot.objects.count()),r.content)
  stale=member(a,no);stale['rowVersion']-=1
  r=api(fin,{'action':'record_transaction_payments','paymentDate':'2026-11-03','reference':'QA','amount':1000,'allocations':[{**stale,'cashAmount':1000,'offsetAmount':0}]})
  check('stale reviewed allocation rejected before writes',r.status_code==409 and r.json()['error']=='version_conflict',r.content)
  with override_settings(AUDIT_LOG_PAUSED=True):
   prior=AuditLog.objects.count();r=register([(a,no,1000,0)],1000);check('Finance receipt persists without enabling paused Audit',r.status_code==200 and AuditLog.objects.count()==prior,r.content)
  a.refresh_from_db();before=copy.deepcopy(a.payload);r=fin.get('/api/accounting?view=list');a.refresh_from_db()
  check('GET does not rewrite cash, offsets, amounts or history',r.status_code==200 and a.payload==before)
  check('new review metadata can be read independently of settlement',any(x['txNo']==no and x['financeReviewed'] and x['settlement']=='settled' for x in r.json()['transactionRows']))
  print(str(len(checks))+' passed retired-action and immutable-history checks',flush=True)
  raise Done()
except Done:pass
