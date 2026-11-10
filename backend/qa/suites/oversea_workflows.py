"""Oversea installments and signed endorsements; disposable DB only."""
from pathlib import Path
exec(Path('/app/qa/suites/oversea_business.py').read_text().split('try:\n with transaction.atomic():')[0])
from cases.oversea import periods
from cases.workflow import build_endorsement_payload
from production.calc import production_keys_for_case
try:
 with transaction.atomic():
  sales,person=account('sales','sales');finance,_=account('finance','accounting')
  for typ,name,code in [('class','Fine Art','FA'),('foreign_broker','Oversea QA Broker',None),('reinsured','Oversea QA Cedant',None)]:MasterRecord.objects.create(entity_type=typ,name=name,code=code,payload={},created_by='qa',updated_by='qa')
  incomplete=fixture(ownerPersonnelId=person.pk,ae=person.name,installmentEnabled=True,performanceInstallments=[dict(id='DRAFT-I1',ratio=50,paymentBaseDate='')])
  saved_draft=call(sales,'/api/cases',{'case':incomplete});check('one incomplete installment can save as Draft',saved_draft.status_code==201,saved_draft.content[:1000]);unfinished=get_case(saved_draft.json()['case']['caseUid'])
  refused=call(sales,'/api/case-announce',dict(caseUid=str(unfinished.case_uid),rowVersion=unfinished.row_version,confirmed=True,documentIds=[]));check('one incomplete installment cannot Announce',refused.status_code==400);unfinished.refresh_from_db();check('incomplete installment Draft has no reference or cash',not unfinished.tw_ref and not unfinished.payload['transactions'] and not unfinished.payload['paymentEntries'])
  rows=[dict(id=f'I{i+1}',ratio=ratio,paymentBaseDate=stamp,premium=999999) for i,(ratio,stamp) in enumerate([(33.33,'2050-01-05'),(33.33,'2050-02-05'),(33.34,'2050-03-05')])]
  raw=fixture(currency='USD',ownerPersonnelId=person.pk,ae=person.name,installmentEnabled=True,performanceInstallments=rows,reinsurers=[dict(name='Oversea QA Broker',sharePct=25,brokerageAmount=100.01)])
  n=normalize_draft(raw);check('ratio draft normalizes',not n['errors'],n['errors']);p=n['value'];check('all installment facts ready',not validate_announce_ready(p),validate_announce_ready(p))
  check('premium injection cannot override Brokerage ratios',all(r['premium'] is None for r in p['performanceInstallments']))
  check('Effective Date supplies reference month independent of first installment',reference_prefix(p)=='TWFA4901')
  parts=periods(p);check('automatic allocation retains exact total and first-period tail',[r['amount'] for r in parts]==[33.34,33.33,33.34],parts)
  check('each installment has independent exact dates',[r['accountingDate'] for r in parts]==['2049-12-26','2050-01-26','2050-02-23'])
  bad=copy.deepcopy(raw);bad['performanceInstallments'][0]['ratio']=10;check('ratios must total 100',any(i['field']=='performanceInstallments' for i in validate_announce_ready(normalize_draft(bad)['value'])))
  for actual in ['', '2050-02-30']:
   bad=copy.deepcopy(raw);bad['performanceInstallments'][1]['paymentBaseDate']=actual;n=normalize_draft(bad);check('missing or invalid per-period date rejected '+actual,bool(n['errors']) or bool(validate_announce_ready(n['value'])))
  bad=copy.deepcopy(raw);bad['performanceInstallments'][1]['id']='I1';check('duplicate period IDs rejected',bool(normalize_draft(bad)['errors']))
  for currency,total in [('TWD',100),('USD',-100.01),('USD',0)]:
   q=copy.deepcopy(p);q['currency']=currency;q['reinsurers'][0]['brokerageAmount']=total;values=periods(q);check('allocation exact for '+currency+str(total),round(sum(r['amount'] for r in values),2)==total,values)
  for currency,total in [('TWD',-1),('TWD',-2),('USD',-0.01),('USD',-0.02),('TWD',1),('TWD',2)]:
   q=copy.deepcopy(p);q['currency']=currency;q['reinsurers'][0]['brokerageAmount']=total;q['performanceInstallments']=[dict(id=f'S{i}',ratio=25,paymentBaseDate='2050-01-05') for i in range(4)];values=periods(q)
   check('small installment rounding preserves sign '+currency+str(total),round(sum(r['amount'] for r in values),2)==total and all(r['amount']<=0 if total<0 else r['amount']>=0 for r in values),values)
  saved=call(sales,'/api/cases',{'case':raw});check('installment API creates Draft',saved.status_code==201,saved.content[:1200]);uid=saved.json()['case']['caseUid'];case=get_case(uid)
  announced=call(sales,'/api/case-announce',dict(caseUid=uid,rowVersion=case.row_version,confirmed=True,documentIds=upload_note(sales,uid)));check('installment Announce requires its Broker Credit Note',announced.status_code==200,announced.content[:1400]);case.refresh_from_db();txs=case.payload['transactions']
  check('Announce creates three distinct T3s only',len(txs)==3 and len({t['txNo'] for t in txs})==3 and all(t['legType']=='Leg 3' for t in txs))
  no=txs[0]['txNo'];details=transaction_details(case.payload);check('ledger preserves dates per T3',[details[t['txNo']]['actualPaymentDate'] for t in txs]==['2050-01-05','2050-02-05','2050-03-05'])
  review=call(finance,'/api/accounting',dict(action='review_accounts',date='2050-01-05',reference='period one review',members=[member(case,no)]));check('Finance reviews one period independently',review.status_code==200,review.content[:1000]);case.refresh_from_db();details=transaction_details(case.payload)
  accounting=finance.get('/api/accounting?view=list');reviews={r['txNo']:r for r in accounting.json()['transactionRows'] if r['caseUid']==uid}
  check('date signature preserves period review and does not review others',reviews[no]['financeReviewed'] and not reviews[txs[1]['txNo']]['financeReviewed'])
  payment=dict(action='record_transaction_payments',paymentDate='2050-02-05',reference='period one receipt',amount=33.34,allocations=[{**member(case,no),'cashAmount':33.34,'offsetAmount':0}])
  with transaction.atomic():
   response=call(finance,'/api/accounting',payment);check('actual cash date may differ from installment date',response.status_code==200,response.content[:1000])
   transaction.set_rollback(True)
  case.refresh_from_db()
  payment['paymentDate']='2050-01-05';response=call(finance,'/api/accounting',payment);check('one period receipt can settle independently',response.status_code==200,response.content[:1300]);case.refresh_from_db();details=transaction_details(case.payload)
  check('only received period is settled',details[no]['paid']==33.34 and details[txs[1]['txNo']]['paid']==0)
  allocations=installment_allocations(case.payload);check('Production uses actual period months and exact Brokerage',[r['performanceMonth'] for r in allocations]==['2050-01','2050-02','2050-03'] and [r['income'] for r in allocations]==[33.34,33.33,33.34])
  source=case_source(case);closed=confirm_case(source,[{'reinsurerKey':f'{case.pk}:I1:R0'}],'2050-01');check('partial Production never duplicates T3 or loses receipt',len(closed['payload']['transactions'])==3 and closed['payload']['paymentEntries']==case.payload['paymentEntries'])
  created=call(sales,'/api/case-workflow',dict(action='create_endorsement',caseUid=uid,rowVersion=case.row_version));check('Oversea creates endorsement from Announced source',created.status_code==201,created.content[:1500]);child_uid=created.json()['case']['caseUid'];child=get_case(child_uid);draft=child.payload
  check('endorsement inherits base facts but clears old money and cash',draft['originalPremium']==case.payload['originalPremium'] and draft['reinsurers'][0]['brokerageAmount'] is None and not draft['receiptPaymentDate'] and not draft['transactions'] and not draft['paymentEntries'] and not draft['installmentEnabled'])
  draft.update(endoEffectiveDate='2049-06-01',endoText='Additional Brokerage',receiptPaymentDate='2050-04-05');draft['reinsurers'][0]['brokerageAmount']=12.34
  saved=call(sales,'/api/cases',dict(caseUid=child_uid,rowVersion=child.row_version,case=draft),method='put');check('signed endorsement Draft saves',saved.status_code==200,saved.content[:1500]);child.refresh_from_db()
  response=call(sales,'/api/case-announce',dict(caseUid=child_uid,rowVersion=child.row_version,confirmed=True,documentIds=upload_note(sales,child_uid)));check('signed endorsement Announce has its own Credit Note',response.status_code==200,response.content[:1500]);child.refresh_from_db()
  check('positive endorsement gets E01 and only its positive T3',child.tw_ref==case.tw_ref+'-E01' and len(child.payload['transactions'])==1 and child.payload['transactions'][0]['amount']==12.34)
  check('Brokerage-only endorsement does not rebook original premium',reinsurer_legs(child.payload,child.payload['reinsurers'][0])['cedantPremium']==0 and installment_allocations(child.payload)[0]['income']==12.34)
  stale=call(sales,'/api/case-workflow',dict(action='create_endorsement',caseUid=uid,rowVersion=case.row_version));check('cannot branch from superseded source',stale.status_code==409)
  created=call(sales,'/api/case-workflow',dict(action='create_endorsement',caseUid=child_uid,rowVersion=child.row_version));check('latest endorsement can create next',created.status_code==201,created.content[:1000]);refund_uid=created.json()['case']['caseUid'];refund=get_case(refund_uid);draft=refund.payload
  draft.update(endoEffectiveDate='2049-07-01',endoText='Brokerage refund',receiptPaymentDate='2050-05-05');draft['reinsurers'][0]['brokerageAmount']=-5.67
  saved=call(sales,'/api/cases',dict(caseUid=refund_uid,rowVersion=refund.row_version,case=draft),method='put');check('negative refund Draft saves',saved.status_code==200,saved.content[:1000]);refund.refresh_from_db()
  response=call(sales,'/api/case-announce',dict(caseUid=refund_uid,rowVersion=refund.row_version,confirmed=True,documentIds=upload_note(sales,refund_uid,'broker_debit')));check('refund Announce with its own Debit Note succeeds',response.status_code==200,response.content[:1300]);refund.refresh_from_db();detail=transaction_details(refund.payload)[refund.payload['transactions'][0]['txNo']]
  check('negative endorsement gets E02 and payable T3',refund.tw_ref==case.tw_ref+'-E02' and detail['amount']==-5.67 and detail['paymentDirection']=='payable' and detail['accountingDate']=='2050-04-25')
  check('refund Production records only signed Brokerage',reinsurer_legs(refund.payload,refund.payload['reinsurers'][0])['cedantPremium']==0 and installment_allocations(refund.payload)[0]['income']==-5.67)
  refund_no=refund.payload['transactions'][0]['txNo']
  response=call(finance,'/api/accounting',dict(action='review_accounts',date='2050-05-05',reference='refund review',members=[member(refund,refund_no)]));check('Finance can review negative endorsement',response.status_code==200,response.content[:1000])
  response=call(finance,'/api/accounting',dict(action='record_transaction_payments',paymentDate='2050-05-05',reference='actual refund',amount=-5.67,allocations=[{**member(refund,refund_no),'cashAmount':5.67,'offsetAmount':0}]))
  check('Finance records a refund as an independent payment',response.status_code==200,response.content[:1200]);refund.refresh_from_db();check('negative endorsement cash settles',transaction_details(refund.payload)[refund_no]['outstanding']==0)
  corrected=copy.deepcopy(p);refresh_transactions(corrected,'QA-CORRECT','2050-01-01T00:00:00Z');corrected['performanceInstallments'][0]['id']='NEW-FIRST';refresh_transactions(corrected,'QA-CORRECT','2050-01-01T00:00:00Z')
  check('unreviewed period correction does not preserve stale installment identity',corrected['transactions'][0]['installmentId']=='NEW-FIRST' and corrected['transactions'][0]['actualPaymentDate']=='2050-01-05')
  case.refresh_from_db();check('endorsements never overwrite original T3 or receipt',len(case.payload['transactions'])==3 and transaction_details(case.payload)[no]['paid']==33.34)
  print(str(len(checks))+' passed Oversea installment and endorsement checks',flush=True)
  raise Done()
except Done:pass

from cases import storage
for key in note_storage_keys:storage.delete(key)
