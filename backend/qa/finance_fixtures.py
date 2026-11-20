"""Explicit synthetic Finance review setup for date/math/lifecycle regressions.

Production never auto-reviews accounts. These helpers only prepare QA fixtures;
the finance_workflow suite independently tests every unreviewed and batch guard.
"""
import copy,json,os
from cases.models import Case, FinanceReconciliationBatch
from cases.cash_ledger import transaction_details,cents
assert os.environ.get('RI_DISPOSABLE_QA')=='true'

def post(client,body):
 if 'csrftoken' not in client.cookies:client.get('/api/auth/csrf')
 token=client.cookies.get('csrftoken')
 return client.post('/api/accounting',json.dumps(body),content_type='application/json',**({'HTTP_X_CSRFTOKEN':token.value} if token else {}))

def review_case(case,finance):
 """Mark each synthetic cash account independently so unrelated fixtures stay independent."""
 if not finance or not hasattr(finance,'post') or case.status not in ('posted','closed','reversed'):return
 case.refresh_from_db()
 from cases.finance_workflow import active_reviews
 existing=active_reviews({str(case.case_uid)})
 for no,d in transaction_details(case.payload).items():
  tx=next((t for t in case.payload.get('transactions',[]) if isinstance(t,dict) and t.get('txNo')==no),{})
  if d.get('cashTracking')=='derived' or tx.get('reversed') or tx.get('isReversalEntry') or (str(case.case_uid),no) in existing:continue
  if case.status=='reversed' and tx.get('source')!='claim':continue
  case.refresh_from_db()
  r=post(finance,{'action':'review_accounts','date':'2026-11-03','reference':'QA-FINANCE-FIXTURE',
   'members':[{'caseUid':str(case.case_uid),'txNo':no,'rowVersion':case.row_version}]})
  if r.status_code==409 and r.json().get('error') in PREREQUISITE_ERRORS:continue   # 2026-11-20：對應款收齊後在 cash() 補對帳
  if r.status_code>=400:raise AssertionError(('Synthetic review setup failed',r.status_code,r.content))
 case.refresh_from_db()

PREREQUISITE_ERRORS=('cedant_collection_required','reinsurer_refund_required','reinsurer_claim_required')

def _review_when_ready(client,allocations):
 """2026-11-20 業主決定：所有再保人，審核前要先收齊對應的那筆錢（保費 T2、退給 Cedant、付給 Cedant 的理賠）。
 測試在登錄收付款前才補審核已具備前提的帳款（與實際作業順序相同），並更新同案其他分配列的 rowVersion。"""
 from cases.finance_workflow import review_blocked,review_prerequisite,active_reviews
 for a in allocations:
  try:c=Case.objects.get(case_uid=a.get('caseUid'))
  except (Case.DoesNotExist,ValueError,TypeError):continue
  details=transaction_details(c.payload);d=details.get(a.get('txNo'))
  if not d or not review_prerequisite(c.payload,a['txNo'],d) or (str(c.case_uid),a['txNo']) in active_reviews({str(c.case_uid)}):continue
  if review_blocked(c.payload,a['txNo'],d,details):continue
  r=post(client,{'action':'review_accounts','date':'2026-11-03','reference':'QA-FINANCE-FIXTURE',
   'members':[{'caseUid':str(c.case_uid),'txNo':a['txNo'],'rowVersion':c.row_version}]})
  if r.status_code>=400:raise AssertionError(('Synthetic deferred review failed',r.status_code,r.content))
  c.refresh_from_db()
  for other in allocations:
   if other.get('caseUid')==str(c.case_uid) and 'rowVersion' in other:other['rowVersion']=c.row_version

def cash(client,body):
 """Submit current API format; fixtures must already have been reviewed explicitly."""
 body=copy.deepcopy(body)
 allocations=body.get('allocations')
 if isinstance(allocations,list) and allocations:
  values=[];valid=True
  for a in allocations:
   try:
    c=Case.objects.get(case_uid=a.get('caseUid'));d=transaction_details(c.payload).get(a.get('txNo'),{})
    values.append((a,d))
   except (Case.DoesNotExist,ValueError,TypeError):valid=False;break
  try:
   if valid and values and cents(body.get('amount'))>0 and all(d.get('paymentDirection')=='payable' for a,d in values):
    body['amount']=-body['amount']
  except (ValueError,TypeError):pass
  if valid and body.get('action')=='record_transaction_payments':_review_when_ready(client,allocations)
 return post(client,body)

def prepare_case_correction(case,proposed,finance):
 """Cancel only affected, individually reviewed untreated fixture accounts before Case PUT."""
 if not finance or not hasattr(finance,'post'):return
 from cases.property_original import enabled,transactions
 from cases.finance_corrections import material,base_no
 from cases.finance_workflow import active_reviews
 case.refresh_from_db();old=case.payload
 if not enabled(old):return
 p={**copy.deepcopy(old),**proposed}
 old_live=[t for t in old.get('transactions',[]) if isinstance(t,dict) and t.get('source')!='claim' and not t.get('reversed') and not t.get('isReversalEntry')]
 expected={base_no(t):t for t in transactions(p,'2026-11-03T00:00:00Z',old=old_live)}
 reviewed=active_reviews({str(case.case_uid)})
 for t in old_live:
  if not material(t,expected.get(base_no(t)),old.get('currency'),p.get('currency')):continue
  pair=reviewed.get((str(case.case_uid),t['txNo']))
  if not pair:continue
  b=pair[0];members=[]
  for m in b.members:
   c=Case.objects.get(case_uid=m['caseUid']);members.append({**m,'rowVersion':c.row_version})
  post(finance,{'action':'cancel_review_batch','reviewBatchId':str(b.pk),'reason':'QA approved account correction','members':members})
 case.refresh_from_db()
