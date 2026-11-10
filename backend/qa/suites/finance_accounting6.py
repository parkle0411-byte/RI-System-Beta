"""Accounting 2026-11-06: merged review groups, optional evidence, real date metadata."""
from pathlib import Path
exec(Path('/app/qa/suites/finance_workflow.py').read_text().split('class Done(Exception):')[0])
from cases.finance_workflow import active_reviews, review_batches
from cases.transaction_ledger import transaction_rows

def whole(bid):
 b=next(b for b in fin.get('/api/accounting?view=list').json()['reviewBatches'] if b['id']==bid)
 return b['members']
def cancel_group(bid,members=None):
 return api(fin,{'action':'cancel_review_batch','reviewBatchId':bid,'reason':'QA whole group','members':members if members is not None else whole(bid)})
class Done(Exception):pass
try:
 with transaction.atomic():
  fin=client('accounting6','accounting');sales=client('accounting6-sales','sales')
  a=fixture('QA-GROUP-A');b=fixture('QA-GROUP-B');c=fixture('QA-GROUP-C',currency='TWD');d=fixture('QA-GROUP-D',party='Different Cedant')
  an=leg(a,'Leg 1');bn=leg(b,'Leg 1');cn=leg(c,'Leg 1');dn=leg(d,'Leg 1')
  r=review([(a,an)],reference='',note='');check('review accepts both optional evidence fields blank',r.status_code==200,r.content);bid=r.json()['reviewBatchId']
  stale=whole(bid)
  r=review([(b,bn)],date='2026-11-04',reference='SECOND',note='Second review event')
  check('later same-party same-currency review joins existing logical batch',r.status_code==200 and r.json()['reviewBatchId']==bid,r.content)
  q=fin.get('/api/accounting?view=list').json();rs={x['txNo']:x for x in q['transactionRows']}
  check('individual review dates and references retained after merging',rs[an]['reviewDate']=='2026-11-03' and rs[an]['reviewReference']=='' and rs[bn]['reviewDate']=='2026-11-04' and rs[bn]['reviewReference']=='SECOND')
  check('merged batch exposes all accounts',len(whole(bid))==2)
  check('original review event records retained',FinanceReconciliationBatch.objects.filter(status='active').count()==2)
  check('stale cancellation cannot omit later review event',cancel_group(bid,stale).status_code==409)
  check('same-party different-currency joins whole group',review([(c,cn)]).json()['reviewBatchId']==bid)
  check('different counterparty remains separate',review([(d,dn)]).json()['reviewBatchId']!=bid)
  before=FinanceReconciliationBatch.objects.count();fin.get('/api/accounting?view=list')
  check('reading merged batches does not rewrite historical records',FinanceReconciliationBatch.objects.count()==before)
  r=register([(b,bn,1000,0)],1000);check('one merged group member can receive cash',r.status_code==200,r.content);cashid=r.json()['batchId']
  check('cash on peer member blocks cancellation of entire merged group',cancel_group(bid).json().get('error')=='review_payment_locked')
  from cases.finance_corrections import review_change_error
  a.refresh_from_db();changed=copy.deepcopy(a.payload);next(x for x in changed['transactions'] if x['txNo']==an)['amount']+=10
  check('reviewed account changes still require whole group cancellation',bool(review_change_error(a,a.payload,changed)))
  check('reverse registration before group cancellation',reverse(cashid,[b]).status_code==200)
  check('whole merged group cancellation succeeds',cancel_group(bid).status_code==200)
  check('all original events marked cancelled with history retained',FinanceReconciliationBatch.objects.filter(status='cancelled').count()==3)
  q=fin.get('/api/accounting?view=list').json();rs={x['txNo']:x for x in q['transactionRows']}
  check('all cancelled members return to unreviewed while other groups remain reviewed',not rs[an]['financeReviewed'] and not rs[bn]['financeReviewed'] and not rs[cn]['financeReviewed'] and rs[dn]['financeReviewed'])
  check('review still requires date',review([(a,an)],date='',reference='',note='').status_code==400)
  check('optional evidence still enforces field lengths',review([(a,an)],reference='x'*201).status_code==400)
  check('unprivileged actor cannot submit blank-evidence review',review([(a,an)],sales,reference='',note='').status_code==403)
  r=review([(a,an)],reference='',note='');check('re-review after cancellation starts a new logical batch',r.status_code==200 and r.json()['reviewBatchId']!=bid)
  # Installment labels/base dates do not replace the Case Effective Date.
  a.refresh_from_db();p=copy.deepcopy(a.payload);p['transactions'][0].update(installmentLabel='2027-01',baseDate='2027-01-01');p['claims']=[{'id':7,'dateOfLoss':'2026-10-12'}]
  p['transactions'].append({'txNo':'QA-DATE-CLAIM','source':'claim','legType':'Claim Leg 1','claimId':7,'paymentId':1,'amount':10,'reinsurer':'QA Reinsurer','reinsurerIdx':0})
  p['statementNo']='CEDANT-SOA';p['reinsurers'][0]['settlementRef']='REINSURER-SOA'
  source={'caseUid':str(a.case_uid),'twRef':a.tw_ref,'rootCaseUid':str(a.case_uid),'rowVersion':a.row_version,'status':'posted','announcedAt':'2026-11-01','currency':'USD','reinsured':'QA Cedant','payload':p}
  rs=transaction_rows([source]);by={x['txNo']:x for x in rs}
  check('installment account displays Case Effective Date',by[an]['accountDisplayDate']=='2026-09-01')
  check('claim displays own Date of Loss',by['QA-DATE-CLAIM']['accountDisplayDate']=='2026-10-12')
  check('Cedant and reinsurer SoA use distinct reconciliation refs',by[an]['reconciliationRef']=='CEDANT-SOA' and by[leg(a,'Leg 2')]['reconciliationRef']=='REINSURER-SOA')
  p['parentTwRef']='PARENT';p['endoEffectiveDate']='2026-10-20';rs=transaction_rows([source]);by={x['txNo']:x for x in rs}
  check('endorsement displays its effective date and claim keeps loss date',by[an]['accountDisplayDate']=='2026-10-20' and by['QA-DATE-CLAIM']['accountDisplayDate']=='2026-10-12')
  print(str(len(checks))+' passed Accounting merged-batch checks',flush=True)
  raise Done()
except Done:pass
