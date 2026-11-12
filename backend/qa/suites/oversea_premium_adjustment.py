"""Signed Oversea premium adjustments, accounting and Production; disposable DB."""
from pathlib import Path
exec(Path('/app/qa/suites/oversea_business.py').read_text().split('try:\n with transaction.atomic():')[0])
from cases.oversea import premium_period_amounts
from cases.calc.jsnum import js_round
from production.calc import build_production_preview, production_keys_for_case

try:
 with transaction.atomic():
  sales,person=account('sales','sales')
  for typ,name,code in [('class','Fine Art','FA'),('foreign_broker','Oversea QA Broker',None),('reinsured','Oversea QA Cedant',None)]:
   MasterRecord.objects.create(entity_type=typ,name=name,code=code,payload={},created_by='qa',updated_by='qa')
  raw=fixture(currency='USD',ownerPersonnelId=person.pk,ae=person.name,reinsurers=[dict(name='Oversea QA Broker',sharePct=25,brokerageAmount=100)])
  response=call(sales,'/api/cases',{'case':raw});check('original Draft created',response.status_code==201,response.content[:1000]);root=get_case(response.json()['case']['caseUid'])
  response=call(sales,'/api/case-announce',dict(caseUid=str(root.case_uid),rowVersion=root.row_version,confirmed=True,documentIds=upload_note(sales,str(root.case_uid))))
  check('original announced',response.status_code==200,response.content[:1000]);root.refresh_from_db();root_payload=copy.deepcopy(root.payload);previous=root
  for ordinal,adjustment in enumerate([1000.01,-1000.01],1):
   response=call(sales,'/api/case-workflow',dict(action='create_endorsement',caseUid=str(previous.case_uid),rowVersion=previous.row_version))
   check('create independent endorsement '+str(ordinal),response.status_code==201,response.content[:1000]);case=get_case(response.json()['case']['caseUid']);draft=case.payload
   check('premium adjustment starts at zero '+str(ordinal),draft['premiumAdjustment']==0)
   draft.update(endoEffectiveDate='2049-06-01',endoText='Premium change',premiumAdjustment=adjustment,installmentEnabled=True,performanceInstallments=[dict(id='I1',ratio=33.33,paymentBaseDate='2050-01-05'),dict(id='I2',ratio=33.33,paymentBaseDate='2050-02-05'),dict(id='I3',ratio=33.34,paymentBaseDate='2050-03-05')]);draft['reinsurers'][0]['brokerageAmount']=0
   response=call(sales,'/api/cases',dict(caseUid=str(case.case_uid),rowVersion=case.row_version,case=draft),method='put')
   check('save signed adjustment '+str(ordinal),response.status_code==200,response.content[:1500]);case.refresh_from_db()
   check('adjustment and original premium are separate '+str(ordinal),case.payload['premiumAdjustment']==adjustment and case.payload['originalPremium']==root_payload['originalPremium'])
   legacy_client=copy.deepcopy(case.payload);legacy_client.pop('premiumAdjustment')
   response=call(sales,'/api/cases',dict(caseUid=str(case.case_uid),rowVersion=case.row_version,case=legacy_client),method='put');case.refresh_from_db()
   check('omitting the field retains its stored value '+str(ordinal),response.status_code==200 and case.payload['premiumAdjustment']==adjustment,response.content[:1000])
   response=call(sales,'/api/case-announce',dict(caseUid=str(case.case_uid),rowVersion=case.row_version,confirmed=True,documentIds=upload_note(sales,str(case.case_uid),'broker_credit')))
   check('announce premium-only endorsement '+str(ordinal),response.status_code==200,response.content[:1200]);case.refresh_from_db()
   check('premium-only endorsement stays posted '+str(ordinal),case.status=='posted')
   check('no T1 or T2 created '+str(ordinal),all(t['legType']=='Leg 3' and t['amount']==0 for t in case.payload['transactions']))
   amount=premium_period_amounts(case.payload); expected=250.0 if adjustment>0 else -250.0
   check('Share and installment allocations preserve signed total '+str(ordinal),round(sum(amount),2)==expected and all(x>=0 if adjustment>0 else x<=0 for x in amount),amount)
   source=case_source(case); keys=production_keys_for_case(source)
   check('premium-only periods retain Production keys '+str(ordinal),len(keys)==3,keys)
   totals=[]
   for month in ['2050-01','2050-02','2050-03']:
    report=build_production_preview([source],month,{'USD':1})
    check('monthly Production includes premium-only period '+str(ordinal)+' '+month,len(report['rows'])==1,report)
    totals.append(report['rows'][0]['premium'])
   check('Production converts and rounds each period to NTD '+str(ordinal),totals==[js_round(x) for x in amount],totals)
   previous=case
  root.refresh_from_db();check('original policy unchanged',root.payload==root_payload)
  prior=copy.deepcopy(previous.payload);prior.pop('premiumAdjustment');check('historic endorsements remain zero premium',reinsurer_legs(prior,prior['reinsurers'][0])['cedantPremium']==0)
  invalid=copy.deepcopy(previous.payload);invalid['currency']='TWD';invalid['premiumAdjustment']=0.5;check('TWD fractional premium adjustment rejected',bool(normalize_draft(invalid,allow_negative_premiums=True)['errors']))
  print(str(len(checks))+' passed Oversea signed premium adjustment checks',flush=True)
  raise Done()
except Done:pass
from cases import storage
for key in note_storage_keys:storage.delete(key)
