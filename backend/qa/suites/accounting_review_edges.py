"""Boundary, atomicity and migration protections for owner-approved accounting rules."""
from pathlib import Path
exec(Path('/app/qa/suites/accounting_review_92.py').read_text().split('class Rollback(Exception):pass')[0])
from cases.accounting_migration import repair_payload
from cases.manual_reference import MANUAL_TW_REF_REINSURER
from cases.calc.payment_terms import premium_installment_plan
from audit.models import AuditLog
class Rollback(Exception):pass
try:
 with transaction.atomic():
  fin,fp=client('edgefin','accounting','finance');sales,sp=client('edgesales','sales','reinsurance')
  a=make('EDGE')
  check('case staff cannot record money',pay(sales,a,'Leg 1',1000).status_code==403)
  check('overpayment rejected',pay(fin,a,'Leg 1',1000.01).status_code==400)
  version=a.row_version
  check('backdated receipt accepted as separate operation',pay(fin,a,'Leg 1',1000,date='2026-01-15').status_code==200)
  a.refresh_from_db();entry=a.payload['paymentEntries'][0]
  check('reported date and operation timestamp retained separately',entry['paymentDate']=='2026-01-15' and entry['createdAt'][:10]!='2026-01-15')
  check('stale version rejects duplicate writes',request(fin,'confirm_facility_settlement',caseUid=str(a.case_uid),rowVersion=version,txNo=tx(a,'Leg 1'),note='x').status_code==409)
  a.refresh_from_db();check('empty settlement note rejected',request(fin,'confirm_facility_settlement',caseUid=str(a.case_uid),rowVersion=a.row_version,txNo=tx(a,'Leg 1'),note=' ').status_code==400)
  check('manual confirmation cannot be backdated',settle(fin,a,'Leg 1',confirmationDate='2026-01-15').status_code==400)
  with override_settings(AUDIT_LOG_PAUSED=True):
   before=AuditLog.objects.count();check('manual settlement operates during Audit pause',settle(fin,a,'Leg 1').status_code==200)
   a.refresh_from_db();check('business settlement history persists during Audit pause',a.payload['facilityAccounting']['history'] and AuditLog.objects.count()==before and EntitySnapshot.objects.filter(entity_type='case',entity_id=str(a.case_uid),entity_version=a.row_version).exists())
  a.refresh_from_db();before_payload=copy.deepcopy(a.payload)
  ref=sales.post('/api/case-reconciliation-references',data=json.dumps({'caseUid':str(a.case_uid),'rowVersion':a.row_version,'statementNo':'EDGE-CHECKED','reinsurers':[{'index':0,'settlementRef':'EDGE-RI'}]}),content_type='application/json')
  a.refresh_from_db();check('reference-only changes preserve settled amount and confirmation',ref.status_code==200 and a.payload['paymentEntries']==before_payload['paymentEntries'] and details(a)[tx(a,'Leg 1')]['settlement']=='settled')
  draft=sales.post('/api/cases',data=json.dumps({'case':{**a.payload,'lossAdvisedDate':'2026-01-01','lossRecordYears':0,'lossRecord':[],'newOrRenew':'New','transactions':[{'txNo':'INJECTED','amount':999,'legType':'Leg 1'}],'claims':[{'id':1}],'paymentEntries':[{'amount':999,'entryType':'payment'}]}}),content_type='application/json')
  check('new draft cannot import posted obligations or cash records',draft.status_code==201 and not Case.objects.get(case_uid=draft.json()['case']['caseUid']).payload['transactions'] and not Case.objects.get(case_uid=draft.json()['case']['caseUid']).payload['paymentEntries'],draft.content)
  a.refresh_from_db();bid=entry['batchId']
  check('settled remittance reversal rejected',request(fin,'reverse_batch_payment',batchId=bid,note='x',cases=[{'caseUid':str(a.case_uid),'rowVersion':a.row_version}]).status_code==409)
  b=make('GROUP');c=make('GROUPOTHER',reinsured='Different Cedant')
  def batch(items):
   allocations=[]
   for case,leg,v in items:
    no=tx(case,leg);allocations.append({'caseUid':str(case.case_uid),'rowVersion':case.row_version,'txNo':no,'amount':v})
   return request(fin,'record_transaction_payments',paymentDate='2026-10-01',amount=sum(x[2] for x in items),allocations=allocations)
  check('different counterparties cannot share a remittance',batch([(b,'Leg 1',1000),(c,'Leg 1',1000)]).status_code==400)
  check('failed batch changes neither case',not Case.objects.get(pk=b.pk).payload['paymentEntries'] and not Case.objects.get(pk=c.pk).payload['paymentEntries'])
  usd=make('USD',currency='USD');check('mixed currency batch rejected',batch([(b,'Leg 1',1000),(usd,'Leg 1',1000)]).status_code==400)
  check('mixed cash direction batch rejected',batch([(b,'Leg 1',1000),(b,'Leg 2',800)]).status_code==400)
  peer=make('PEER');check('same-party batch retains independent full allocations',batch([(b,'Leg 1',1000),(peer,'Leg 1',1000)]).status_code==200)
  u=make('AUW',reinsurers=[{'name':MANUAL_TW_REF_REINSURER,'foreignBroker':'Howden Specialty Limited','sharePct':100,'premium':800,'riCommPct':0,'taxPct':0}])
  ur=make('AUWREF',parent=u,originalPremium=-200,reinsurers=[{'name':MANUAL_TW_REF_REINSURER,'foreignBroker':'Howden Specialty Limited','sharePct':100,'premium':-160,'riCommPct':0,'taxPct':0}])
  check('AUW reinsurer refund requires cash receipt instead of offset',offset(fin,u,ur,'reinsurer').status_code==400)
  unposted=make('PREPOST',status='posted');unposted.payload['transactions']=[];unposted.save()
  unposted_refund=make('PREPOSTREF',parent=unposted,originalPremium=-200,reinsurers=[{'name':'AR92 RI','sharePct':100,'premium':-160,'riCommPct':0,'taxPct':0,'paymentTermsDays':30}])
  check('unposted premium schedules cannot be manually offset',offset(fin,unposted,unposted_refund).status_code==400)
  root=make('SMALL');large=make('LARGEREF',parent=root,originalPremium=-1200,reinsurers=[{'name':'AR92 RI','sharePct':100,'premium':-960,'riCommPct':0,'taxPct':0,'paymentTermsDays':30}])
  check('insufficient original balance cannot partially offset refund',offset(fin,root,large).status_code==400)
  other=make('NOTROOT');check('unrelated policy refund cannot offset',offset(fin,other,large).status_code==400)
  large.currency='USD';large.save();check('cross-currency offset rejected',offset(fin,root,large).status_code==400)
  claim=make('CAP');claim.payload['transactions']=[{'txNo':'EDGE-C1','source':'claim','claimId':1,'paymentId':1,'legType':'Claim Leg 1','reinsurer':'AR92 RI','reinsurerIdx':0,'amount':1000,'dueDate':'2026-10-31'},{'txNo':'EDGE-C2','source':'claim','claimId':1,'paymentId':1,'legType':'Claim Leg 2','reinsurerIdx':0,'amount':1000,'dueDate':'2026-10-31'}];claim.save()
  check('claim cap fixture incoming and outgoing accepted',pay(fin,claim,'Claim Leg 1',400).status_code==200 and pay(fin,claim,'Claim Leg 2',300).status_code==200)
  claim.refresh_from_db();incoming=next(e for e in claim.payload['paymentEntries'] if e['transactionNo']=='EDGE-C1')
  check('cannot reverse claim receipt below already paid amount',request(fin,'reverse_batch_payment',batchId=incoming['batchId'],note='x',cases=[{'caseUid':str(claim.case_uid),'rowVersion':claim.row_version}]).status_code==409)
  installments=[{'id':'I'+str(i),'performanceMonth':'2026-0'+str(i),'paymentBaseDate':'2026-0'+str(i)+'-01','premium':1,'paymentTermsDays':30,'reinsurerPaymentTerms':{'r1':30}} for i in (1,2,3)]
  old=make('OLDTAIL',originalPremium=100,installmentEnabled=True,performanceInstallments=installments,reinsurers=[{'name':'AR92 RI','sharePct':100,'premium':80,'riCommPct':0,'taxPct':0,'paymentTermsDays':30}])
  old.payload['transactions']=[t for i in premium_installment_plan(old.payload) for t in build_premium_transactions(old.payload,i)]
  legs=[t for t in old.payload['transactions'] if t['legType']=='Leg 1'];legs[0]['amount']=33.33;legs[2]['amount']=33.34
  old.payload['paymentEntries']=[{'id':'handled','entryType':'payment','transactionNo':legs[2]['txNo'],'amount':1,'paymentDate':'2026-10-01'}];old.save()
  repaired,status,changes,pending=repair_payload(old,[old],[],set(),{},[])
  check('handled installment remainder is never duplicated across periods',repaired['transactions']==old.payload['transactions'] and any(p['kind']=='handled_installment_allocation' for p in pending))
  legacy=make('LEGACYNODATE');legacy.payload['claims']=[{'id':1,'dateOfLoss':'2026-03-01','payments':[{'id':1,'date':'2026-03-02','amount':1000}]}];legacy.payload['transactions']=copy.deepcopy(claim.payload['transactions']);legacy.save()
  repaired,status,changes,pending=repair_payload(legacy,[legacy],[],set(),{},[])
  check('unproven legacy creation date stays pending instead of guessed',any(p['kind']=='claim_creation_date' for p in pending) and all(not t.get('createdAt') for t in repaired['transactions']))
  check('Finance Staff cannot generate Production',fin.post('/api/production-report',data=json.dumps({'action':'generate','month':'2039-01'}),content_type='application/json').status_code==403)
  raise Rollback()
except Rollback:pass
print(str(len(checks))+'/'+str(len(checks))+' accounting boundary checks passed; rolled back')
