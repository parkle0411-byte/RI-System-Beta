"""Real API cash-only submissions: currency/direction isolation and safe retries."""
from pathlib import Path
exec(Path('/app/qa/suites/finance_workflow.py').read_text().split('class Done(Exception):')[0])
from cases.oversea import refresh_transactions as oversea_transactions
from production.calc import installment_allocations
from cases.finance_workflow import review_batches

def cash_request(targets,submission=None,**over):
 body={'action':'record_transaction_payments','cashSubmissionId':submission or str(uuid.uuid4()),'paymentDate':'2026-11-06','reference':'CASH-V2','note':'',
 'allocations':[{**member(c,no),'cashItemId':str(uuid.uuid4()),'cashAmount':value} for c,no,value in targets]}
 body.update(over);return body

def cancel_group(bid):
 group=next(b for b in fin.get('/api/accounting?view=list').json()['reviewBatches'] if b['id']==bid)
 return api(fin,{'action':'cancel_review_batch','reviewBatchId':bid,'reason':'QA group cancellation','members':group['members']})
def unchanged(c):
 c.refresh_from_db();return copy.deepcopy(c.payload)
class Done(Exception):pass
try:
 with transaction.atomic():
  fin=client('cash-v2','accounting');sales=client('cash-v2-sales','sales')
  a=fixture('QA-CASH-A');b=fixture('QA-CASH-B');c=fixture('QA-CASH-C',currency='TWD')
  a1=leg(a,'Leg 1');c1=leg(c,'Leg 1');bi,bo=add_claim(b,200)
  check('claim prerequisite receipt setup',review([(b,bi)]).status_code==200 and register([(b,bi,200,0)],200).status_code==200)
  r=review([(a,a1),(b,bo),(c,c1)]);check('same counterparty can review currencies and directions in one operation',r.status_code==200,r.content);bid=r.json()['reviewBatchId']
  groups=fin.get('/api/accounting?view=list').json()['reviewBatches'];g=next(g for g in groups if g['id']==bid)
  check('logical review exposes all currencies without adding unlike amounts',set(g['currencies'])=={'USD','TWD'} and g['currency']=='' and len(g['members'])==3)
  body=cash_request([(a,a1,600),(b,bo,50),(c,c1,800)])
  r=api(fin,body);check('multi-currency opposite-direction actual cash accepted',r.status_code==200 and r.json()['succeeded']==3 and r.json()['failed']==0,r.content);res=r.json()['results']
  check('each currency and direction has independent registration',len({x['batchId'] for x in res})==3)
  a.refresh_from_db();c.refresh_from_db();check('premium partial receipts preserve remaining balance',transaction_details(a.payload)[a1]['outstanding']==400 and transaction_details(c.payload)[c1]['outstanding']==200)
  check('partial cash details advertise partial receipts and no new offsets',transaction_details(a.payload)[a1]['fullPaymentRequired'] is False and all(not e['nonCash'] for cc in [a,b,c] for e in unchanged(cc)['paymentEntries']))
  versions=[cc.row_version for cc in [a,b,c]];counts=[len(cc.payload['paymentEntries']) for cc in [a,b,c]]
  again=api(fin,body);check('same submission retries replay successful allocations',again.json()['newlyRecorded']==0 and all(x['replayed'] for x in again.json()['results']),again.content)
  check('retry does not change payload or case version',versions==[(cc.refresh_from_db() or cc.row_version) for cc in [a,b,c]] and counts==[len(cc.payload['paymentEntries']) for cc in [a,b,c]])
  altered=copy.deepcopy(body);altered['allocations'][0]['cashAmount']=601
  conflict=api(fin,altered).json();check('same item with different amount is a conflict, never a second receipt',conflict['results'][0]['error']=='cash_item_conflict' and conflict['newlyRecorded']==0,conflict)
  check('cross-currency group cancellation is blocked by active cash in any currency',cancel_group(bid).json().get('error')=='review_payment_locked')
  # Independent rows in one currency/direction: good rows persist; zero and stale rows fail.
  d=fixture('QA-CASH-D',party='Retry Cedant');e=fixture('QA-CASH-E',party='Retry Cedant');d1=leg(d,'Leg 1');e1=leg(e,'Leg 1')
  review([(d,d1),(e,e1)]);request=cash_request([(d,d1,100),(e,e1,0)])
  partial=api(fin,request).json();check('one zero amount does not roll back another account in the same group',partial['succeeded']==1 and partial['failed']==1 and partial['results'][1]['error']=='invalid_cash_amount',partial)
  e.refresh_from_db();check('zero never creates a fake journal',e.payload['paymentEntries']==[])
  retry=copy.deepcopy(request);retry['allocations']=[{**request['allocations'][1],'cashAmount':200}]
  r=api(fin,retry).json();check('failed item can be corrected and retried without resending success',r['succeeded']==1 and r['newlyRecorded']==1,r)
  check('retry creates a new registration instead of rewriting the completed one',r['results'][0]['batchId']!=partial['results'][0]['batchId'])
  repeated=api(fin,request).json();check('a previously zero request cannot overwrite its corrected saved item',repeated['newlyRecorded']==0 and repeated['results'][0]['replayed'])
  other=fixture('QA-CASH-OTHER',party='Another Cash Cedant');other_no=leg(other,'Leg 1');review([(other,other_no)])
  switch=cash_request([(other,other_no,10)],submission=request['cashSubmissionId']);r=api(fin,switch).json()
  check('failed-only retry cannot switch the submission counterparty',r['failed']==1 and r['results'][0]['error']=='incompatible_counterparty',r)
  # Multiple successful accounts in one case share one cash registration and accept the initial case version.
  f=fixture('QA-CASH-SAME',party='Same Case Cedant');p=copy.deepcopy(f.payload);p['reinsurers'][0]['sharePct']=50
  p['reinsurers'].append({**p['reinsurers'][0],'name':'Second Reinsurer'});p['transactions']=transactions(p,'2026-09-01T00:00:00Z');f.payload=p;f.save()
  f1=[x['txNo'] for x in rows(f) if x['legType']=='Leg 1'];review([(f,no) for no in f1])
  multi=cash_request([(f,f1[0],100),(f,f1[1],150)]);before=f.row_version;r=api(fin,multi).json()
  check('two allocations of one case both succeed despite internal version increments',r['succeeded']==2,r)
  check('same currency/direction successful rows form one registration',len({x['batchId'] for x in r['results']})==1)
  bank=next(x for x in fin.get('/api/accounting?view=list').json()['cashBatches'] if x['batchId']==r['results'][0]['batchId'])
  check('bank history uses the actual gross receipt and no offset',bank['netCash']==250 and bank['receivableSettled']==250 and bank['payableSettled']==0 and all(x['offsetAmount']==0 for x in bank['allocations']))
  bad=copy.deepcopy(multi);bad['allocations'][1]['cashItemId']=bad['allocations'][0]['cashItemId'];check('duplicate client identifiers rejected',api(fin,bad).status_code==400)
  bad=copy.deepcopy(multi);bad['allocations'][1]['txNo']=bad['allocations'][0]['txNo'];check('same account cannot be allocated twice in one submission',api(fin,bad).status_code==400)
  # Stale and oversized items fail independently; no excessive allocation is accepted.
  stale=cash_request([(d,d1,10),(e,e1,10)]);stale['allocations'][0]['rowVersion']-=1;r=api(fin,stale).json()
  check('stale account fails while another current account saves',r['succeeded']==1 and r['results'][0]['error']=='version_conflict',r)
  excess=cash_request([(d,d1,100000)]);check('over-allocation is a failed item',api(fin,excess).json()['failed']==1)
  check('Sales cannot record multi-account cash',api(sales,cash_request([(d,d1,1)])).status_code==403)
  malformed=cash_request([(d,d1,1)]);malformed['allocations'][0]['caseUid']=[];check('malformed identifiers do not crash or write',api(fin,malformed).status_code==400)
  # Original prerequisites remain even though partial premium payments are now allowed.
  a2=leg(a,'Leg 2');review([(a,a2)]);r=api(fin,cash_request([(a,a2,100)])).json()
  check('partly received T1 still blocks T2',r['failed']==1 and r['results'][0]['error']=='payment_prerequisite',r)
  topup=register([(a,a1,400,0)],400);check('remaining T1 receipt can complete collection',topup.status_code==200,topup.content)
  paid=api(fin,cash_request([(a,a2,100)])).json();check('partial T2 allowed once full T1 prerequisite is met',paid['succeeded']==1,paid)
  check('receipt reversal still cannot break downstream partial T2',reverse(topup.json()['batchId'],[a]).json().get('error')=='downstream_payment_locked')
  check('partial T2 does not settle retained brokerage',next(x for x in transaction_details(unchanged(a)).values() if x['cashTracking']=='derived')['settlement']=='open')
  # Return premium receipts and refunds are partial, but collection prerequisites still apply.
  refund=fixture('QA-CASH-REFUND',value=-1000,party='Refund Cedant');rt1=leg(refund,'Leg 1');rt2=leg(refund,'Leg 2');refund.payload.update(parentTwRef='QA-REFUND-PARENT',endoEffectiveDate='2026-09-01',endorsementAnnouncedAt='2026-09-01T00:00:00Z');refund.save()
  review([(refund,rt2)]);check('partial reinsurer refund receipt accepted',register([(refund,rt2,400,0)],400).status_code==200)
  review([(refund,rt1)]);blocked=api(fin,cash_request([(refund,rt1,200)])).json();check('Cedant refund still waits for all reinsurer collections',blocked['failed']==1)
  remaining=abs(transaction_details(unchanged(refund))[rt2]['outstanding']);r=register([(refund,rt2,remaining,0)],remaining);check('remaining reinsurer refund collected',r.status_code==200,r.content);r=api(fin,cash_request([(refund,rt1,200)])).json();check('Cedant refund may now be paid partially after collection',r['succeeded']==1 and transaction_details(unchanged(refund))[rt1]['outstanding']==-800,r)
  # New offsets are rejected through both current and legacy API shapes.
  check('pure offset cannot be created by legacy request',register([(d,d1,0,100)],0).status_code==400)
  net=copy.deepcopy(cash_request([(d,d1,1)]));net['allocations'][0]['offsetAmount']=1
  check('cash submission refuses offset amounts per item',api(fin,net).json()['results'][0]['error']=='offsets_disabled')
  # Oversea remains one cash T3; actual receipts may span dates and never move Production.
  p=dict(reinsuranceStructure='OVERSEA',classOfBusiness='Fine Art',classCode='FA',currency='USD',reinsured='Oversea Cedant',
   originalInsured='Oversea Insured',originalInsuredCn='海外保戶',policyFrom='2026-01-01',policyTo='2027-01-01',ae='QA',
   originalPremium=10000,receiptPaymentDate='2026-10-15',reinsurers=[dict(name='Cash Broker',sharePct=25,brokerageAmount=1000)],paymentEntries=[],claims=[])
  oversea_transactions(p,'QA-CASH-OVERSEA','2026-10-01T00:00:00Z');o=Case.objects.create(tw_ref='QA-CASH-OVERSEA',status='posted',currency='USD',reinsured_name_snapshot='Oversea Cedant',payload=p,announced_at=timezone.now(),created_by='qa',updated_by='qa');no=o.payload['transactions'][0]['txNo']
  review([(o,no)]);original=copy.deepcopy(installment_allocations(o.payload));date_before=transaction_details(o.payload)[no]['accountingDate']
  first=api(fin,cash_request([(o,no,800)],paymentDate='2026-10-20')).json();check('Oversea partial receipt accepts its true date',first['succeeded']==1,first)
  check('Oversea stays open with partial cash',transaction_details(unchanged(o))[no]['outstanding']==200 and transaction_details(o.payload)[no]['settlement']=='partial')
  second=api(fin,cash_request([(o,no,200)],paymentDate='2026-11-01')).json();check('Oversea closes only after remaining cash is received',second['succeeded']==1 and transaction_details(unchanged(o))[no]['settlement']=='settled',second)
  check('cash dates never rewrite Case, Accounting Date or Production months',o.payload['receiptPaymentDate']=='2026-10-15' and transaction_details(o.payload)[no]['accountingDate']==date_before and installment_allocations(o.payload)==original)
  check('no fictional T1/T2 was manufactured for Oversea',len(o.payload['transactions'])==1 and o.payload['transactions'][0]['legType']=='Leg 3')
  r=reverse(second['results'][0]['batchId'],[o]);check('Oversea reversal reopens its remaining balance',r.status_code==200 and transaction_details(unchanged(o))[no]['outstanding']==200)
  # A completed item is not replayed as a new payment even after its original registration is reversed.
  paid_body=cash_request([(o,no,10)]);receipt=api(fin,paid_body).json();reverse(receipt['results'][0]['batchId'],[o]);count=len(unchanged(o)['paymentEntries']);r=api(fin,paid_body).json()
  check('reversal does not make an old client item reusable',r['newlyRecorded']==0 and r['results'][0]['replayed'] and len(unchanged(o)['paymentEntries'])==count)
  print(str(len(checks))+' passed cash-only multi-currency workflow checks',flush=True)
  raise Done()
except Done:pass
