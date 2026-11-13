from pathlib import Path
exec(Path('/app/qa/suites/oversea_business.py').read_text().split('try:\n with transaction.atomic():')[0])
from production.views import load_month
try:
 with transaction.atomic():
  sales,person=account('sales','sales')
  for typ,name,code in [('class','Fine Art','FA'),('foreign_broker','Oversea QA Broker',None),('reinsured','Oversea QA Cedant',None)]:
   MasterRecord.objects.create(entity_type=typ,name=name,code=code,payload={},created_by='qa',updated_by='qa')
  p=fixture(currency='USD',ownerPersonnelId=person.pk,ae=person.name,installmentEnabled=True,performanceInstallments=[dict(id='I1',ratio=50,paymentBaseDate='2050-05-01',performanceMonth='2050-01'),dict(id='I2',ratio=50,paymentBaseDate='2050-08-29',performanceMonth='2050-04')])
  r=call(sales,'/api/cases',{'case':p});check('new Draft created',r.status_code==201,r.content[:800]);case=get_case(r.json()['case']['caseUid'])
  r=call(sales,'/api/case-announce',dict(caseUid=str(case.case_uid),rowVersion=case.row_version,confirmed=True,documentIds=upload_note(sales,str(case.case_uid))))
  check('independent months pass Announce',r.status_code==200,r.content[:800]);case.refresh_from_db()
  dates=[t['actualPaymentDate'] for t in case.payload['transactions']]
  check('correct production months', [r['performanceMonth'] for r in installment_allocations(case.payload)]==['2050-01','2050-04'])
  changed=copy.deepcopy(case.payload);changed['performanceInstallments'][0]['performanceMonth']='2050-02'
  r=call(sales,'/api/cases',dict(caseUid=str(case.case_uid),rowVersion=case.row_version,case=changed,reason='Performance correction'),method='put')
  check('announced case month can be edited',r.status_code==200,r.content[:1000]);case.refresh_from_db()
  check('change retained and cash dates unchanged',[r['performanceMonth'] for r in installment_allocations(case.payload)]==['2050-02','2050-04'] and [t['actualPaymentDate'] for t in case.payload['transactions']]==dates)
  print(str(len(checks))+' passed Oversea performance API checks',flush=True)
  raise Done()
except Done: pass
from cases import storage
for key in note_storage_keys:storage.delete(key)
