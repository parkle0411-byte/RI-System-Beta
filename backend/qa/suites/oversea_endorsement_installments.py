"""End-to-end Oversea endorsement installments in a disposable database."""
from pathlib import Path
exec(Path('/app/qa/suites/oversea_business.py').read_text().split('try:\n with transaction.atomic():')[0])
from cases.oversea import periods

try:
 with transaction.atomic():
  sales,person=account('sales','sales');finance,_=account('finance','accounting')
  for typ,name,code in [('class','Fine Art','FA'),('foreign_broker','Oversea QA Broker',None),('reinsured','Oversea QA Cedant',None)]:
   MasterRecord.objects.create(entity_type=typ,name=name,code=code,payload={},created_by='qa',updated_by='qa')
  raw=fixture(currency='USD',ownerPersonnelId=person.pk,ae=person.name,reinsurers=[dict(name='Oversea QA Broker',sharePct=25,brokerageAmount=100)])
  saved=call(sales,'/api/cases',{'case':raw});check('original Draft created',saved.status_code==201,saved.content[:1000]);root=get_case(saved.json()['case']['caseUid'])
  res=call(sales,'/api/case-announce',dict(caseUid=str(root.case_uid),rowVersion=root.row_version,confirmed=True,documentIds=upload_note(sales,str(root.case_uid))))
  check('original announced',res.status_code==200,res.content[:1000]);root.refresh_from_db();original=copy.deepcopy(root.payload)
  previous=root
  for ordinal,amount,note in [(1,100.01,'broker_credit'),(2,-100.01,'broker_debit')]:
   res=call(sales,'/api/case-workflow',dict(action='create_endorsement',caseUid=str(previous.case_uid),rowVersion=previous.row_version))
   check('create endorsement '+str(ordinal),res.status_code==201,res.content[:1000]);case=get_case(res.json()['case']['caseUid']);draft=case.payload
   check('new endorsement starts without inherited installments '+str(ordinal),not draft['installmentEnabled'] and not draft['performanceInstallments'])
   draft.update(endoEffectiveDate='2049-06-01',endoText='Brokerage adjustment',installmentEnabled=True,performanceInstallments=[dict(id='I1',ratio=33.33,paymentBaseDate='2050-01-05'),dict(id='I2',ratio=33.33,paymentBaseDate='2050-02-05'),dict(id='I3',ratio=33.34,paymentBaseDate='2050-03-05')]);draft['reinsurers'][0]['brokerageAmount']=amount
   res=call(sales,'/api/cases',dict(caseUid=str(case.case_uid),rowVersion=case.row_version,case=draft),method='put');check('save installment Draft '+str(ordinal),res.status_code==200,res.content[:1500]);case.refresh_from_db()
   check('saved installment ratios and dates preserved '+str(ordinal),case.payload['installmentEnabled'] and [r['ratio'] for r in case.payload['performanceInstallments']]==[33.33,33.33,33.34])
   no_note=call(sales,'/api/case-announce',dict(caseUid=str(case.case_uid),rowVersion=case.row_version,confirmed=True,documentIds=[]));check('own Broker Note required '+str(ordinal),no_note.status_code==400,no_note.content[:1000]);case.refresh_from_db()
   res=call(sales,'/api/case-announce',dict(caseUid=str(case.case_uid),rowVersion=case.row_version,confirmed=True,documentIds=upload_note(sales,str(case.case_uid),note)))
   check('announce installment endorsement '+str(ordinal),res.status_code==200,res.content[:1500]);case.refresh_from_db();txs=case.payload['transactions']
   expected=[33.34,33.33,33.34] if amount>0 else [-33.34,-33.33,-33.34]
   check('only signed period T3s '+str(ordinal),case.tw_ref==root.tw_ref+f'-E{ordinal:02}' and len(txs)==3 and [t['amount'] for t in txs]==expected and all(t['legType']=='Leg 3' and f'-I{i+1}-T3' in t['txNo'] for i,t in enumerate(txs)))
   details=transaction_details(case.payload)
   check('each T3 has its own actual and accounting dates '+str(ordinal),[details[t['txNo']]['actualPaymentDate'] for t in txs]==['2050-01-05','2050-02-05','2050-03-05'] and [details[t['txNo']]['accountingDate'] for t in txs]==['2049-12-26','2050-01-26','2050-02-23'])
   allocations=installment_allocations(case.payload)
   check('Production preserves period amounts and months '+str(ordinal),[r['income'] for r in allocations]==expected and [r['performanceMonth'] for r in allocations]==['2050-01','2050-02','2050-03'],allocations)
   check('endorsement does not rebook original premium '+str(ordinal),reinsurer_legs(case.payload,case.payload['reinsurers'][0])['cedantPremium']==0)
   tx=txs[0]['txNo'];res=call(finance,'/api/accounting',dict(action='review_accounts',date='2050-01-05',reference='period review',members=[member(case,tx)]));check('review one period '+str(ordinal),res.status_code==200,res.content[:1000]);case.refresh_from_db()
   res=call(finance,'/api/accounting',dict(action='record_transaction_payments',paymentDate='2050-01-05',reference='period cash',amount=expected[0],allocations=[{**member(case,tx),'cashAmount':abs(expected[0]),'offsetAmount':0}]))
   check('settle one period '+str(ordinal),res.status_code==200,res.content[:1000]);case.refresh_from_db();details=transaction_details(case.payload)
   check('other periods remain unsettled '+str(ordinal),details[txs[1]['txNo']]['paid']==0 and details[txs[2]['txNo']]['paid']==0)
   previous=case
  root.refresh_from_db();check('original transactions and cash unchanged',root.payload['transactions']==original['transactions'] and root.payload['paymentEntries']==original['paymentEntries'])
  print(str(len(checks))+' passed Oversea endorsement installment checks',flush=True)
  raise Done()
except Done:pass
from cases import storage
for key in note_storage_keys:storage.delete(key)
