"""Current cash allocation, atomic rejection, permissions and immutable legacy history.

Cross-case remittances and manual settlement are retired. Several independent
T1 can share one genuine receipt within the same case and installment.
"""
import copy,os
from django.db import transaction
from cases.models import Case
from cases.calc.accounting import build_claim_payment_transactions
from audit.models import EntitySnapshot
from qa.current_accounting import client,make,post,pay,nos,details
assert os.environ.get('RI_DISPOSABLE_QA')=='true'
checks=[]
def check(name,ok,extra=None):
 assert ok,(name,extra)
 checks.append(name);print('PASS '+name,flush=True)
def saved(case):
 case.refresh_from_db();return copy.deepcopy((case.payload,case.row_version))
def allocation(case,no,value):
 case.refresh_from_db();return dict(caseUid=str(case.case_uid),rowVersion=case.row_version,txNo=no,amount=value)
def batch(fin,allocations,total=None,**extra):
 return post(fin,'record_transaction_payments',**dict(paymentDate='2026-10-27',amount=total if total is not None else round(sum(a['amount'] for a in allocations),2),allocations=allocations,reference='QA-UNIFIED-BANK',**extra))
class Rollback(Exception):pass
try:
 with transaction.atomic():
  fin,_=client('unified-fin');admin,_=client('unified-admin','admin','admin');read,_=client('unified-read','sales','reinsurance')
  a=make('CURRENT-UNIFIED-A',names=['QA A','QA B'],shares=[60,40]);b=make('CURRENT-UNIFIED-B')
  t1=nos(a,'Leg 1');t2=nos(a,'Leg 2');t3=nos(a,'Leg 3');original=[(t['txNo'],t['amount']) for t in a.payload['transactions']]
  snapshot=saved(a)
  check('outgoing waits for every independent Cedant T1',pay(fin,a,t2[:1]).status_code==409 and saved(a)==snapshot)
  check('partial premium receipt rejected',pay(fin,a,t1[:1],value=200).status_code==400 and saved(a)==snapshot)
  for label,rows,total,error in [
   ('allocation sum',[allocation(a,t1[0],600)],601,'allocation_mismatch'),
   ('duplicate transaction',[allocation(a,t1[0],600)]*2,1200,'duplicate_allocation'),
   ('premium excess',[allocation(a,t1[0],601)],601,'swiss_payment_blocked'),
   ('premium partial',[allocation(a,t1[0],599)],599,'swiss_payment_blocked'),
   ('derived brokerage',[allocation(a,t3[0],120)],120,'transaction_not_payable')]:
   result=batch(fin,rows,total);check(label+' rejected atomically',result.status_code==400 and result.json()['error']==error and saved(a)==snapshot,result.content)
  for value in [True,0,-1,.001,'NaN','Infinity']:
   check('invalid cash amount '+str(value),batch(fin,[allocation(a,t1[0],value)],1).status_code==400 and saved(a)==snapshot)
  check('invalid calendar date rejected',pay(fin,a,t1,paymentDate='2026-02-30').status_code==400)
  check('missing registration explanation rejected',pay(fin,a,t1,reference='',note='').status_code==400)
  check('read-only role cannot register cash',pay(read,a,t1).status_code==403 and saved(a)==snapshot)
  alloc=[allocation(a,t1[0],600),allocation(a,t1[1],400)];alloc[-1]['rowVersion']-=1
  check('one stale allocation blocks whole same-case receipt',batch(fin,alloc).status_code==409 and saved(a)==snapshot)
  snapb=saved(b);result=batch(fin,[allocation(a,t1[0],600),allocation(b,nos(b,'Leg 1')[0],1000)])
  check('same Cedant cannot combine different cases',result.status_code==400 and result.json()['error']=='single_accounting_case' and saved(a)==snapshot and saved(b)==snapb,result.content)
  for over in [dict(currency='USD'),dict(reinsured='Another Cedant')]:
   other=make('CURRENT-OTHER-'+str(len(checks)),**over);before=saved(other)
   r=batch(fin,[allocation(a,t1[0],600),allocation(other,nos(other,'Leg 1')[0],1000)])
   check('currency/counterparty mismatch rejected without writes '+str(over),r.status_code==400 and r.json()['error']=='incompatible_allocations' and saved(a)==snapshot and saved(other)==before,r.content)
  result=pay(fin,a,t1);check('same case same period independent T1 share one actual receipt',result.status_code==200,result.content)
  bid=result.json()['batchId'];d=details(a)
  check('all independent T1 automatically settle',all(d[n]['settlement']=='settled' for n in t1))
  check('T2 and T3 remain independent until outgoing paid',all(d[n]['outstanding'] for n in t2) and all(d[n]['settlement']=='open' for n in t3))
  a.refresh_from_db();entries=copy.deepcopy(a.payload['paymentEntries'])
  check('one real bank batch retains both T1 allocations and external reference',len(entries)==2 and {e['batchId'] for e in entries}=={bid} and sum(e['amount'] for e in entries)==1000 and all(e['reference']=='CURRENT-QA-EXTERNAL' for e in entries))
  check('separate case can reuse external reference without merging records',pay(admin,b,nos(b,'Leg 1')).status_code==200 and Case.objects.get(pk=b.pk).payload['paymentEntries'][0]['batchId']!=bid)
  before=saved(a)
  for role,expected in [(read,403),(fin,409)]:
   result=post(role,'reverse_batch_payment',batchId=bid,cases=[dict(caseUid=str(a.case_uid),rowVersion=a.row_version)],note='QA bank return')
   check('settled receipt reversal preserves history '+str(expected),result.status_code==expected and saved(a)==before,result.content)
  check('first RI payment automatically settles only its own brokerage',pay(fin,a,t2[:1]).status_code==200 and details(a)[t3[0]]['settlement']=='settled' and details(a)[t3[1]]['settlement']=='open')
  check('peer RI remains payable at unchanged original amount',pay(fin,a,t2[1:]).status_code==200 and all(d['settlement']=='settled' for d in details(a).values()))
  a.refresh_from_db();check('T3 creates no fictional bank cash',len(a.payload['paymentEntries'])==4 and all(e['transactionNo'] not in t3 for e in a.payload['paymentEntries']))
  check('automatic settlement retains original obligation amounts and IDs',[(t['txNo'],t['amount']) for t in a.payload['transactions']]==original)
  before=saved(a)
  for action in ['confirm_facility_settlement','unconfirm_facility_settlement']:
   result=post(fin,action,caseUid=str(a.case_uid),rowVersion=a.row_version,txNo=t1[0],note='Retired QA action')
   check(action+' retired without writes',result.status_code==400 and saved(a)==before)
  # A real old partial premium payment permits only the exact remaining balance.
  old=make('CURRENT-OLD-PARTIAL');n=nos(old,'Leg 1')[0]
  legacy=dict(id='historic-partial',entryType='payment',transactionNo=n,scheduleKey='case-effective-date:cedant',amount=200,paymentDate='2026-01-05',reference='IMMUTABLE-OLD-REF')
  old.payload['paymentEntries']=[copy.deepcopy(legacy)];old.save()
  check('old partial payment cannot be topped up by another partial',pay(fin,old,[n],value=300).status_code==400)
  check('old partial payment accepts exact remaining balance',pay(fin,old,[n]).status_code==200 and details(old)[n]['settlement']=='settled')
  old.refresh_from_db();check('old payment record preserved byte for byte',old.payload['paymentEntries'][0]==legacy)
  # Claims remain partial, scoped to a request; cumulative payouts never exceed receipts.
  claim=make('CURRENT-CLAIM');c=dict(id=1);p=dict(id=1,amount=1000,date='2026-10-01',createdAt='2026-10-01T00:00:00Z')
  claim.payload['claims']=[dict(id=1,dateOfLoss='2026-01-01',payments=[p])]
  claim.payload['transactions']=build_claim_payment_transactions(claim.payload,claim.payload,c,p);claim.save()
  ci=nos(claim,'Claim Leg 1')[0];co=nos(claim,'Claim Leg 2')[0]
  check('claim supports partial actual receipt',pay(fin,claim,[ci],value=400).status_code==200)
  check('claim cannot pay more than actual receipts',pay(fin,claim,[co],value=401).status_code==400)
  check('claim payout can use part of actual receipts',pay(fin,claim,[co],value=300).status_code==200)
  claim.refresh_from_db();entry=next(e for e in claim.payload['paymentEntries'] if e['transactionNo']==ci);before=saved(claim)
  result=post(fin,'reverse_batch_payment',batchId=entry['batchId'],cases=[dict(caseUid=str(claim.case_uid),rowVersion=claim.row_version)],note='QA returned receipt')
  check('partial claim reversal cannot violate received-cash cap',result.status_code==409 and saved(claim)==before)
  result=post(fin,'edit_payment',caseUid=str(claim.case_uid),rowVersion=claim.row_version,entryId=entry['id'],amount=299,reason='QA invalid correction')
  check('claim receipt correction cannot fall below paid amount',result.status_code==409 and saved(claim)==before)
  result=post(fin,'edit_payment',caseUid=str(claim.case_uid),rowVersion=claim.row_version,entryId=entry['id'],amount=350,reason='QA supported correction')
  check('unsettled claim cash correction with reason is retained',result.status_code==200,result.content)
  claim.refresh_from_db();check('cash correction stores full before/after business history',claim.payload['paymentEditHistory'][-1]['before']['amount']==400 and claim.payload['paymentEditHistory'][-1]['after']['amount']==350)
  check('remaining claim receipt automatically settles at full amount',pay(fin,claim,[ci]).status_code==200 and details(claim)[ci]['settlement']=='settled')
  check('remaining claim payout automatically settles at full amount',pay(fin,claim,[co]).status_code==200 and details(claim)[co]['settlement']=='settled')
  check('cash writes retain versioned snapshots',EntitySnapshot.objects.filter(entity_type='case',entity_id=str(claim.case_uid),entity_version=claim.row_version).exists())
  raise Rollback()
except Rollback:pass
print(f'{len(checks)}/{len(checks)} current cash allocation checks passed; rolled back')
