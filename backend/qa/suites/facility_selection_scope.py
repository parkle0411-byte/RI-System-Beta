"""Facility/Class allowlist across all Case creation and mutation paths."""
from pathlib import Path
exec(Path('/app/qa/suites/case_workflow.py').read_text().split('try:\n    with transaction.atomic():')[0])
import os
from cases.facility_selection import RULES,selection_issues
from cases.draft import normalize_draft,validate_announce_ready
assert os.environ.get('RI_DISPOSABLE_QA')=='true'
results=[]
classes=['Property','Commercial General Liability','Electronic Equipment','Jewelers Block','Marine Cargo','Personal Accident','Products Recall','Stock Throughput','Terrorism','',None]
def sample(name,klass):
 return ready(typePrefix='Commercial General Liability' if klass=='Commercial General Liability' else 'ZZ Type',classOfBusiness=klass,classCode='PD',manualTwRef='SCOPE-READONLY-TEST',reinsurers=[dict(name=name,sharePct=100,premium=1000,riCommPct=5,taxPct=0,paymentTermsDays=90)])
for name,label,allowed in RULES:
 for klass in classes:
  for variant in (name,'  '+name.upper().replace(' ','  ')+'  '):
   p=sample(variant,klass);before=copy.deepcopy(p);ok=klass in allowed;issues=selection_issues(p)
   check(f'{label} selection {klass!r}',bool(issues)!=ok and p==before)
   check(f'{label} normalization {klass!r}',not any('available only for' in s for s in normalize_draft(p)['errors']) if ok else any('available only for' in s for s in normalize_draft(p)['errors']))
   check(f'{label} Announce {klass!r}',not any('available only for' in i['label'] for i in validate_announce_ready(p)) if ok else any(i['field']=='reinsurers.0.name' and 'available only for' in i['label'] for i in validate_announce_ready(p)))
 for klass in allowed:
  check(label+' accepts case/outer whitespace Class',not selection_issues(sample(name,'  '+klass.upper()+'  ')))
 check(label+' ordinary identity outside restriction',not selection_issues(sample(name.replace(' (Facility)',''),'Marine Cargo')))
check('Malformed payload and unrelated names remain safe',all(not selection_issues(p) for p in [None,[],{},dict(reinsurers=[None,True,{'name':'Ordinary (Facility)'}])]))
p=sample('Ordinary RI','Marine Cargo');p['reinsurers']=[{'name':r[0]} for r in RULES]
check('Mixed placement reports all five offending rows',[i['field'] for i in selection_issues(p)]==[f'reinsurers.{i}.name' for i in range(5)])
p['classOfBusiness']='Commercial General Liability';check('CGL allows Swiss but rejects four other rows',len(selection_issues(p))==4)
p['classOfBusiness']='Property';check('Property allows all five together',not selection_issues(p))
try:
 with transaction.atomic():
  sales=account(person('sales','reinsurance'),'facilityscope')
  def counts():return (Case.objects.count(),EntitySnapshot.objects.count(),AuditLog.objects.count())
  for n,(name,label,allowed) in enumerate(RULES):
   for klass in allowed:
    body=sample(name,klass);body['manualTwRef']=f'SCOPE-VALID-{n}-{klass}'
    r=call(sales,'post','/api/cases',{'case':body});check(label+' API accepts '+klass,r.status_code==201,(r.status_code,r.content[:250]))
   valid=Case.objects.get(case_uid=r.json()['case']['caseUid']) if r.status_code==201 else None
   for klass in [c for c in classes if c not in allowed]:
    before=counts();r=call(sales,'post','/api/cases',{'case':sample(name,klass)})
    check(label+' API rejects '+str(klass),r.status_code==400 and 'available only for' in r.json().get('message','') and counts()==before,(r.status_code,r.content[:200]))
   if valid:
    before=(counts(),valid.row_version,copy.deepcopy(valid.payload))
    r=call(sales,'put','/api/cases',{'caseUid':str(valid.case_uid),'rowVersion':valid.row_version,'case':sample(name,'Marine Cargo')});valid.refresh_from_db()
    check(label+' edit cannot bypass restriction atomically',r.status_code==400 and (counts(),valid.row_version,valid.payload)==before)
   # Seed an old invalid combination directly, to exercise every guarded entry point.
   legacy=Case.objects.create(status='draft',payload={**sample(name,'Marine Cargo'),'ownerPersonnelId':valid.owner_personnel_id},currency='USD',owner_personnel_id=valid.owner_personnel_id,created_by='qa',updated_by='qa')
   before=(counts(),legacy.row_version,copy.deepcopy(legacy.payload))
   r=call(sales,'post','/api/case-announce',{'caseUid':str(legacy.case_uid),'rowVersion':legacy.row_version,'confirmed':True,'documentIds':[]});legacy.refresh_from_db()
   check(label+' legacy Announce rejected atomically',r.status_code==400 and any('available only for' in i['label'] for i in r.json().get('issues',[])) and (counts(),legacy.row_version,legacy.payload)==before,(r.status_code,r.content[:200]))
   legacy.status='closed';legacy.tw_ref=f'SCOPE-LEGACY-{n}';legacy.save();before=(counts(),legacy.row_version,copy.deepcopy(legacy.payload))
   for action in ('create_endorsement','create_renewal'):
    r=call(sales,'post','/api/case-workflow',{'action':action,'caseUid':str(legacy.case_uid),'rowVersion':legacy.row_version,'manualTwRef':'SCOPE-WORKFLOW-REF'})
    check(label+' workflow '+action+' rejects invalid inherited selection',r.status_code==400 and 'available only for' in r.json().get('message',''),(r.status_code,r.content[:300]))
   for kind in ('cover','debit','endorsement'):
    r=call(sales,'post','/api/document-generation-log',{'caseUid':str(legacy.case_uid),'kind':kind,'format':'docx','case':sample(name,'Property')})
    check(label+' document validates saved Class '+kind,r.status_code==409 and r.json().get('error') in ('facility_class_required','allianz_property_required'))
   r=call(sales,'post','/api/accounting',{'action':'complete_payment_terms','caseUid':str(legacy.case_uid),'rowVersion':legacy.row_version,'partyKey':'r1','days':120,'reason':'Scope test'})
   check(label+' payment terms cannot bypass restriction',r.status_code==409 and r.json().get('error') in ('facility_class_required','allianz_property_required'),(r.status_code,r.content[:200]))
   legacy.refresh_from_db();check(label+' rejected legacy actions preserve version/data/history',(counts(),legacy.row_version,legacy.payload)==before)
  raise Rollback()
except Rollback:pass
passed=sum(ok for _,ok,_ in results)
for name,ok,detail in results:
 if not ok:print('FAIL '+name+' '+str(detail),flush=True)
print(f'{passed}/{len(results)} Facility selection checks passed; test writes rolled back',flush=True);assert passed==len(results)
