"""Immutable preexisting offsets remain visible, affect balances and reverse safely."""
from pathlib import Path
exec(Path('/app/qa/suites/finance_workflow.py').read_text().split('class Done(Exception):')[0])

def legacy_batch(case, targets, net):
 case.refresh_from_db();p=copy.deepcopy(case.payload);details=transaction_details(p);bid=str(uuid.uuid4())
 totals={side:sum(cash+offset for no,cash,offset in targets if details[no]['paymentDirection']==side) for side in ('receivable','payable')}
 for no,cash,offset in targets:
  d=details[no]
  for value,noncash in [(cash,False),(offset,True)]:
   if not value:continue
   p['paymentEntries'].append(dict(id=str(uuid.uuid4()),entryType='payment',transactionNo=no,scheduleKey=d['cashParts'][0]['scheduleKey'],
    partyType=d['partyType'],partyName=d['partyName'],paymentDirection=d['paymentDirection'],currency=p['currency'],amount=value,
    nonCash=noncash,entryKind='finance-offset' if noncash else 'finance-cash',batchId=bid,batchAmount=net,
    batchReceivable=totals['receivable'],batchPayable=totals['payable'],paymentDate='2026-10-01',reference='EXISTING-LEGACY-OFFSET',note='Historical fixture'))
 case.payload=p;case.save();return bid
class Done(Exception):pass
try:
 with transaction.atomic():
  fin=client('cash-history','accounting')
  a=fixture('QA-LEGACY-MIX',party='Legacy Cedant');a1=leg(a,'Leg 1');a2=leg(a,'Leg 2');ci,co=add_claim(a,200)
  review([(a,ci)]);assert register([(a,ci,200,0)],200).status_code==200
  review([(a,a1),(a,co)]);bid=legacy_batch(a,[(a1,800,200),(co,0,200)],800);original=copy.deepcopy(a.payload['paymentEntries'])
  q=fin.get('/api/accounting?view=list').json();bank=next(x for x in q['cashBatches'] if x['batchId']==bid)
  check('preexisting mixed offsets retain gross receipt/payment/net totals',bank['receivableSettled']==1000 and bank['payableSettled']==200 and bank['netCash']==800)
  a.refresh_from_db();d=transaction_details(a.payload)
  check('preexisting offsets still reduce outstanding balances',d[a1]['cashPaid']==800 and d[a1]['nonCashPaid']==200 and d[a1]['outstanding']==0 and d[co]['outstanding']==0)
  check('reading history never rewrites original offsets',a.payload['paymentEntries']==original)
  review([(a,a2)]);r=register([(a,a2,100,0)],-100);check('legacy full collection still releases dependent cash',r.status_code==200,r.content);out=r.json()['batchId']
  check('legacy mixed registration cannot reverse while downstream payment exists',reverse(bid,[a]).json().get('error')=='downstream_payment_locked')
  check('dependent payment can be reversed first',reverse(out,[a]).status_code==200)
  check('legacy mixed registration reverses as a whole after dependencies clear',reverse(bid,[a]).status_code==200)
  a.refresh_from_db();d=transaction_details(a.payload)
  check('legacy cash and offset originals remain unchanged after reversal',a.payload['paymentEntries'][:len(original)]==original)
  check('whole reversal restores each original balance',d[a1]['outstanding']==1000 and d[co]['outstanding']==200)
  q=fin.get('/api/accounting?view=list').json();bank=next(x for x in q['cashBatches'] if x['batchId']==bid)
  check('history marks reversed legacy registration and keeps allocations',bank['status']=='reversed' and len(bank['allocations'])==3)
  z=fixture('QA-LEGACY-PURE',value=200,party='Legacy Pure Cedant');z1=leg(z,'Leg 1');zi,zo=add_claim(z,200)
  review([(z,zi)]);register([(z,zi,200,0)],200);review([(z,z1),(z,zo)]);pure=legacy_batch(z,[(z1,0,200),(zo,0,200)],0)
  q=fin.get('/api/accounting?view=list').json();bank=next(x for x in q['cashBatches'] if x['batchId']==pure)
  check('preexisting pure offset creates no fictional cash',bank['pureOffset'] and bank['netCash']==0 and all(x['cashAmount']==0 for x in bank['allocations']))
  check('preexisting pure offset remains reversible',reverse(pure,[z]).status_code==200)
  z.refresh_from_db()
  from cases.workflow import build_reversed_payload
  try:build_reversed_payload(z.payload);blocked=False
  except ValueError:blocked=True
  check('historical offset still permanently blocks Case Reverse',blocked)
  print(str(len(checks))+' passed preserved legacy offset history checks',flush=True)
  raise Done()
except Done:pass
