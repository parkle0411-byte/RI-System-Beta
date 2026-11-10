"""End-to-end Case edit, Finance and real Production lifecycle on disposable MySQL."""
from pathlib import Path
exec(Path('/app/qa/suites/property_original_suite.py').read_text().split('with transaction.atomic():\n try:')[0])
from cases.models import FinanceReconciliationBatch
from production.models import ProductionReport
from fxrates.models import FxRate
from cases.cash_ledger import direction
assert __import__('os').environ.get('RI_DISPOSABLE_QA')=='true'

def edit_case(c,index,increment):
 c.refresh_from_db();p=copy.deepcopy(c.payload);p['reinsurers'][index]['premium']+=increment
 result=call(sales,'put','/api/cases',{'caseUid':str(c.case_uid),'rowVersion':c.row_version,'case':p,'reason':'QA Finance-approved adjustment'})
 c.refresh_from_db();return result

def approve(c,numbers):
 c.refresh_from_db();return call(fin_client,'post','/api/accounting',{'action':'review_accounts','date':'2026-11-03','reference':'CASE-API-REVIEW',
 'members':[{'caseUid':str(c.case_uid),'txNo':no,'rowVersion':c.row_version} for no in numbers]})
def cash(c,numbers):
 c.refresh_from_db();d=transaction_details(c.payload);net=sum(abs(d[n]['outstanding'])*(1 if d[n]['paymentDirection']=='receivable' else -1) for n in numbers)
 return call(fin_client,'post','/api/accounting',{'action':'record_transaction_payments','paymentDate':'2026-11-03','reference':'CASE-API-CASH','amount':round(net,2),
 'allocations':[{'caseUid':str(c.case_uid),'rowVersion':c.row_version,'txNo':n,'cashAmount':abs(d[n]['outstanding']),'offsetAmount':0} for n in numbers]})
with transaction.atomic():
 try:
  staff=person('sales','reinsurance',name='Finance Case Executive',is_split_eligible=True)
  finance=person('accounting_manager','finance',name='Finance Case Manager')
  sales=account(staff,'finance-case-sales');fin_client=account(finance,'finance-case-manager')
  protected=('financeCorrectionHistory','financeClaimTracking','financeWorkflowVersion','productionHistory','productionReversals','propertyReversalHistory','propertyEditHistory','propertyDateOverrides')
  injected={k:('forged-version' if k=='financeWorkflowVersion' else [{'forged':True}]) for k in protected}
  created=call(sales,'post','/api/cases',{'case':{**p_ready(ae=staff.name,ownerPersonnelId=staff.pk),**injected}})
  check('Case create cannot import client supplied Finance or Production history',created.status_code==201 and not any(k in Case.objects.get(case_uid=created.json()['case']['caseUid']).payload for k in protected),created.content[:500])
  probe=Case.objects.get(case_uid=created.json()['case']['caseUid']);attempt={**probe.payload,**injected,'facilityAccounting':{'forged':True}}
  changed=call(sales,'put','/api/cases',{'caseUid':str(probe.case_uid),'rowVersion':probe.row_version,'case':attempt});probe.refresh_from_db()
  check('Draft Case edit cannot fabricate absent Finance history or settlement state',changed.status_code==200 and not any(k in probe.payload for k in protected) and not probe.payload.get('facilityAccounting'),changed.content[:500])
  c=posted(sales,ae=staff.name,ownerPersonnelId=staff.pk,currency='USD')
  before_history={k:copy.deepcopy(c.payload.get(k)) for k in protected if k!='propertyEditHistory'}
  attempted={**c.payload,**injected,'occupation':'QA server-owned metadata probe'}
  changed=call(sales,'put','/api/cases',{'caseUid':str(c.case_uid),'rowVersion':c.row_version,'case':attempted,'reason':'QA metadata protection'});c.refresh_from_db()
  check('Announced Case edit restores authoritative financial histories instead of accepting forged rows',changed.status_code==200 and all(c.payload.get(k)==v for k,v in before_history.items()) and not any(h.get('forged') for h in c.payload.get('propertyEditHistory',[])),changed.content[:500])
  before=copy.deepcopy(c.payload['transactions']);r=edit_case(c,0,10)
  check('Case API unclosed financial correction updates directly',r.status_code==200 and len(c.payload['transactions'])==len(before),r.content[:500])
  t2=tx_rows(c,'Leg 2')[0]['txNo'];r=approve(c,[t2]);check('Case API setup reviewed account',r.status_code==200,r.content)
  bid=r.json()['reviewBatchId'];c.refresh_from_db();before=copy.deepcopy(c.payload);version=c.row_version
  r=edit_case(c,0,10);check('Case API blocks changing a reviewed member before whole cancellation',r.status_code==409 and c.payload==before and c.row_version==version,r.content[:600])
  c.refresh_from_db();r=call(fin_client,'post','/api/accounting',{'action':'cancel_review_batch','reviewBatchId':bid,'reason':'Correct account',
   'members':[{'caseUid':str(c.case_uid),'txNo':t2,'rowVersion':c.row_version}]});check('Case API setup cancellation',r.status_code==200,r.content)
  month=c.payload['policyFrom'][:7];FxRate.objects.create(year_month=month,currency='USD',rate=30,created_by='qa',updated_by='qa')
  preview=call(fin_client,'get','/api/production-report?month='+month).json();signature=preview['sourceSignature']
  check('Production correction fixture uses policy inception month and includes the case',any(row['caseUid']==str(c.case_uid) for row in preview['rows']),preview['rows'])
  generated=call(fin_client,'post','/api/production-report',{'action':'generate','month':month,'sourceSignature':signature})
  check('real Production generate accepts current Case',generated.status_code in (200,201),generated.content[:800])
  report=generated.json()['report'];closed=call(fin_client,'post','/api/production-report',{'action':'close','month':month,'sourceSignature':signature,'reportUid':report['reportUid'],'rowVersion':report['rowVersion']})
  check('real Production close recognizes Case',closed.status_code==200,closed.content[:700]);c.refresh_from_db()
  oldrows=copy.deepcopy(ProductionReport.objects.get(report_uid=report['reportUid']).rows);old_due={n:d['contractDueDate'] for n,d in transaction_details(c.payload).items()}
  r=edit_case(c,0,10);check('Case API permits closed Production correction on untreated accounts',r.status_code==200,r.content[:1000])
  check('Case API closed correction creates two reversing/replacement ledger pairs',len(c.payload['transactions'])==len(before['transactions'])+4)
  check('Case API closed report unchanged',ProductionReport.objects.get(report_uid=report['reportUid']).rows==oldrows)
  correction_month=c.payload['productionReversals'][-1]['month'];preview=call(fin_client,'get','/api/production-report?month='+correction_month)
  changed=[r for r in preview.json()['rows'] if r.get('financeCorrectionId')]
  check('API preview includes full premium and income reversal/replacement at original FX',preview.status_code==200 and len(changed)==2 and sum(r['premium'] for r in changed)==0 and all(r['rate']==30 for r in changed),changed)
  t1s=[t['txNo'] for t in tx_rows(c,'Leg 1')];approve(c,t1s);r=cash(c,t1s);check('Case API setup full T1 receipt',r.status_code==200,r.content)
  original_t1=[(t['txNo'],t['amount']) for t in tx_rows(c,'Leg 1')];r=edit_case(c,0,10)
  check('Case API paid T1 preserved during untreated T2 closed correction',r.status_code==200 and [(t['txNo'],t['amount']) for t in tx_rows(c,'Leg 1')]==original_t1,r.content[:700])
  current_a=tx_rows(c,'Leg 2')[0]['txNo'];approve(c,[current_a]);r=cash(c,[current_a]);check('Case API first reinsurer completes T2',r.status_code==200,r.content)
  r=edit_case(c,1,10);check('Case API completed first reinsurer does not lock second untreated T2/T3',r.status_code==200,r.content[:700])
  check('Case API completed own reinsurer remains locked',edit_case(c,0,10).status_code==409)
  raise Rollback()
 except Rollback:pass
assert results and all(ok for name,ok,detail in results), [row for row in results if not row[1]]
print(str(len(results))+' passed Finance Case API lifecycle checks')
