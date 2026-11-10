"""Closed Production retains both sides at original FX; review batches remain indivisible."""
from pathlib import Path
exec(Path('/app/qa/suites/finance_workflow.py').read_text().split('class Done(Exception):')[0])
from cases.finance_corrections import correct_accounts
from cases.property_original import confirm_production
from production.calc import build_production_preview
from production.views import case_source
from production.models import ProductionReport
from datetime import datetime,timezone as dtz

def proposed(c,ri_premium):
 c.refresh_from_db();old=copy.deepcopy(c.payload);p=copy.deepcopy(old);p['reinsurers'][0]['premium']=ri_premium
 live=[t for t in old['transactions'] if t.get('source')!='claim' and not t.get('reversed') and not t.get('isReversalEntry')]
 expected=transactions(p,'2026-11-03T04:00:00Z',old=live)
 error=correct_accounts(c,p,old,live,expected,transaction_details(old),{'reinsurers'}, {'id':'qa','name':'QA Finance'}, '2026-11-03T04:00:00Z','QA approved correction')
 return p,error

def closed_report(month,rows):
 return ProductionReport.objects.create(year_month=month,version=1,status='closed',rows=rows,excluded_rows=[],source_signature='qa',created_by='qa',closed_by='qa',closed_at=timezone.now(),close_token=uuid.uuid4())
class Done(Exception):pass
try:
 with transaction.atomic():
  fin=client('correction-fin','accounting');sales=client('correction-sales','sales')
  a=fixture('QA-COR-A');b=fixture('QA-COR-B');ta=leg(a,'Leg 2');tb=leg(b,'Leg 2')
  r=review([(a,ta),(b,tb)]);check('multi-case batch review accepted before financial correction',r.status_code==200,r.content);bid=r.json()['reviewBatchId']
  p,error=proposed(a,900);check('any reviewed member change requires cancelling entire batch',bool(error) and 'entire Finance review batch' in error,error)
  bt1=leg(b,'Leg 1');review([(b,bt1)]);setup=register([(b,bt1,1000,0)],1000)
  check('peer batch setup receives its own T1',setup.status_code==200,setup.content)
  paid_peer=register([(b,tb,800,0)],-800);check('one member of original review batch has effective T2 payment',paid_peer.status_code==200,paid_peer.content)
  check('untreated member cannot cancel review while another original member remains paid',cancel(bid,[a,b]).status_code==409)
  check('reverse paid peer before cancelling original review batch',reverse(paid_peer.json()['batchId'],[b]).status_code==200)
  check('whole-batch cancellation permits correction',cancel(bid,[a,b]).status_code==200)
  p,error=proposed(a,900);check('unclosed untreated ledger updates directly with audit history',not error and len(p['transactions'])==3 and next(t for t in p['transactions'] if t['legType']=='Leg 2')['amount']==720 and p['financeCorrectionHistory'][-1]['ledgerChanges'],error)
  check('unclosed correction preserves due/reminder snapshot',next(t for t in p['transactions'] if t['legType']=='Leg 2')['financeDates']['dueDate']==transaction_details(a.payload)[ta]['dueDate'])
  # Prepare a genuinely recognized closed original report.
  c=fixture('QA-COR-C');c.announced_at=datetime(2026,9,1,tzinfo=dtz.utc);c.save()
  before=build_production_preview([case_source(c)],'2026-09',{'2026-09':{'USD':30}},[])['rows']
  check('original report has recognized premium and income',len(before)==1 and before[0]['rate']==30 and before[0]['income']==6000,before)
  result=confirm_production(case_source(c),before,'2026-09');c.payload=result['payload'];c.status=result['nextStatus'];c.save()
  report=closed_report('2026-09',before);oldrows=copy.deepcopy(report.rows)
  p,error=proposed(c,900);check('closed report financial correction allowed',not error,error)
  ledger=p['transactions'];live=[t for t in ledger if not t.get('reversed') and not t.get('isReversalEntry')]
  check('closed T2/T3 retain old + reversal + replacement, T1 unchanged',len(ledger)==7 and len(live)==3 and next(t for t in live if t['legType']=='Leg 1')['txNo']==leg(c,'Leg 1'),ledger)
  c.payload=p;c.save();preview=build_production_preview([case_source(c)],'2026-11',{'2026-11':{'USD':40}},[])['rows']
  check('closed correction reverses full premium and income at original FX',len(preview)==2 and sorted(t['premium'] for t in preview)==[-30000,30000] and sorted(t['income'] for t in preview)==[-6000,8400] and all(t['rate']==30 for t in preview),preview)
  report.refresh_from_db();check('closed original report remains byte-for-byte unchanged',report.rows==oldrows)
  p,error=proposed(c,850);check('second correction builds on latest effective version',not error,error)
  check('second correction has no duplicate active transaction numbers',len({t['txNo'] for t in p['transactions']})==len(p['transactions']),p['transactions'])
  c.payload=p;c.save();preview=build_production_preview([case_source(c)],'2026-11',{'2026-11':{'USD':99}},[])['rows']
  check('repeated corrections telescope to current income',len(preview)==4 and sum(t['income'] for t in preview)==3600 and sum(t['premium'] for t in preview)==0,preview)
  result=confirm_production(case_source(c),preview,'2026-11');c.payload=result['payload'];c.save()
  check('confirmed correction batches no longer reappear',not build_production_preview([case_source(c)],'2026-11',{'2026-11':{'USD':99}},[])['rows'])
  from cases.property_original import reverse_payload
  reversed_p=reverse_payload(c.payload,'2026-12','2026-11-03T04:00:00Z',{'id':'qa'},'QA whole Case reversal')
  expected_latest=c.payload['financeCorrectionHistory'][-1]['productionEffectiveRows'][0]
  case_reverse_rows=reversed_p['productionReversals'][-1]['rows']
  check('whole Case Reverse after closed corrections reverses latest effective premium and income',len(case_reverse_rows)==1 and case_reverse_rows[0]['premium']==-expected_latest['premium'] and case_reverse_rows[0]['income']==-expected_latest['income'],case_reverse_rows)
  source={**case_source(c),'payload':reversed_p,'status':'reversed'}
  reversal_preview=build_production_preview([source],'2026-12',{'2026-12':{'USD':99}},[])['rows']
  check('whole Case reversal after corrections appears once at original FX',len(reversal_preview)==1 and reversal_preview[0]['income']==-expected_latest['income'] and reversal_preview[0]['rate']==30,reversal_preview)
  for changed_leg in ('T2','T1'):
   agg=fixture('QA-AGGREGATE-'+changed_leg);agg.payload['premiumLedgerLayout']='preserved'
   agg.payload['transactions']=transactions(agg.payload,'2026-09-01T00:00:00Z');agg.announced_at=datetime(2026,9,1,tzinfo=dtz.utc);agg.save()
   original=build_production_preview([case_source(agg)],'2026-09',{'2026-09':{'USD':30}},[])['rows']
   state=confirm_production(case_source(agg),original,'2026-09');agg.payload=state['payload'];agg.status=state['nextStatus'];agg.save()
   if changed_leg=='T2':updated,error=proposed(agg,900)
   else:
    old=copy.deepcopy(agg.payload);updated=copy.deepcopy(old);updated['originalPremium']=1200
    live=[t for t in old['transactions'] if not t.get('reversed') and not t.get('isReversalEntry')]
    error=correct_accounts(agg,updated,old,live,transactions(updated,'2026-11-03T04:00:00Z',old=live),transaction_details(old),{'originalPremium'},{'id':'qa','name':'QA'},'2026-11-03T04:00:00Z','Legacy aggregate correction')
   check('closed preserved aggregate '+changed_leg+' versions both changed account and shared T3',not error and len(updated['transactions'])==7,(error,updated['transactions']))
   changes=build_production_preview([{**case_source(agg),'payload':updated}],'2026-11',{'2026-11':{'USD':99}},[])['rows']
   check('closed preserved aggregate '+changed_leg+' reverses full affected Production at original FX',len(changes)==2 and all(t['rate']==30 for t in changes) and sum(t['premium'] for t in changes)==(6000 if changed_leg=='T1' else 0) and sum(t['income'] for t in changes)==(6000 if changed_leg=='T1' else 2400),changes)
  closed_report('2026-11',preview);p,error=proposed(c,800)
  check('closed current month defers correction to first open month',not error and p['productionReversals'][-1]['month']=='2026-12',error)
  # All receipts reversed permits correction but never whole Case Reverse.
  d=fixture('QA-COR-D',party='Independent Correction Cedant');dt1=leg(d,'Leg 1');review_d=review([(d,dt1)]);r=register([(d,dt1,1000,0)],1000);check('setup settled T1',r.status_code==200,r.content)
  d.refresh_from_db();p,error=proposed(d,900);check('paid T1 remains unchanged while untreated T2 changes',not error and next(t for t in p['transactions'] if t['legType']=='Leg 1')['amount']==1000,error)
  r=reverse(r.json()['batchId'],[d]);check('settled cash can be reversed before correction',r.status_code==200,r.content)
  # Cancel the original T1 review before changing its value.
  d.refresh_from_db();active=FinanceReconciliationBatch.objects.get(pk=review_d.json()['reviewBatchId']);check('cancel reviewed T1 after reversal',cancel(str(active.pk),[d]).status_code==200)
  d.refresh_from_db();old=copy.deepcopy(d.payload);corrected=copy.deepcopy(old);corrected['originalPremium']=1200
  live=[t for t in old['transactions'] if t.get('source')!='claim' and not t.get('reversed') and not t.get('isReversalEntry')]
  error=correct_accounts(d,corrected,old,live,transactions(corrected,'2026-11-03T04:00:00Z',old=live),transaction_details(old),{'originalPremium'}, {'id':'qa','name':'QA'},'2026-11-03T04:00:00Z','Correct fully reversed T1')
  check('all cash reversed and review cancelled permits T1 Case correction with original history retained',not error and next(t for t in corrected['transactions'] if t['legType']=='Leg 1')['amount']==1200 and corrected['paymentEntries']==old['paymentEntries'],error)
  from cases.property_original import reverse_payload
  try:reverse_payload(d.payload,'2026-11','2026-11-03T04:00:00Z',{'id':'qa'},'QA');blocked=False
  except ValueError:blocked=True
  check('ever having premium cash history still prohibits whole Case Reverse',blocked)
  print(str(len(checks))+' passed Finance correction checks',flush=True)
  raise Done()
except Done:pass
