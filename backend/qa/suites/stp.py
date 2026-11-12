"""STP isolated API persistence and underwriting validation."""
import base64, copy, json, uuid
from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.test import Client
from django.db import transaction
from personnel.models import Personnel
from cases.models import Case, CaseDocument
from cases.draft import normalize_draft, validate_announce_ready
from cases.qs_documents import readiness_issues, scope as word_scope

results=[]
def check(name, condition, detail=''):
    results.append((name,bool(condition),detail))

p={'classCode':'ST','classOfBusiness':'Stock Throughput','reinsuranceStructure':'QS','currency':'USD','typePrefix':'Stock Throughput',
'limitOfLiability':'USD 1,000,000 per event\nUSD 2,000,000 aggregate','conveyance':'Sea and air','voyage':'Worldwide',
'stpTurnoverMode':'combined','stpTurnover':[{'company':'','currency':'USD','amount':123},{'company':'','currency':'TWD','amount':456}],
'stpHubs':[{'name':'A','address':'Taipei','currency':'USD','amount':500}], 'originalInsured':'STP Insured', 'originalInsuredCn':'測試',
'reinsured':'STP Cedant','newOrRenew':'New','policyFrom':'2026-01-01','policyTo':'2027-01-01','interest':'Stock',
'situations':[{'address':'Taipei','postcode':'100'}], 'originalPremium':1000,'riCommPct':0,'taxPct':1,'paymentTermsDays':90,
'reinsurers':[{'name':'STP Re','sharePct':20,'premium':1000,'riCommPct':10,'taxPct':0,'paymentTermsDays':90}],
'deductibles':'USD 1,000','originalConditions':'A','reinsuredRetention':'Waived','expressWarranties':'None',
'conditionsPrecedent':'None','subjectivities':'None','lossAdvisedDate':'2026-01-01','lossRecordYears':5,'ae':'STP AE'}
class Rollback(Exception): pass
try:
 with transaction.atomic():
  person=Personnel.objects.create(name='STP QA',department='reinsurance',role_code='sales',created_by='qa',updated_by='qa')
  Personnel.objects.create(name='STP AE',department='reinsurance',role_code='sales',email='stp-ae@example.test',created_by='qa',updated_by='qa')
  user=get_user_model().objects.create_user(username='stp.qa',password='Case-Test-Pass-1')
  person.auth_user_id=str(user.pk);person.account_status='active';person.save();p['ownerPersonnelId']=person.pk;p['ownerPersonnelName']=person.name
  client=Client(enforce_csrf_checks=True,HTTP_HOST='localhost',raise_request_exception=False);cache.clear();client.get('/api/auth/csrf')
  csrf=client.cookies['csrftoken'].value; headers={'HTTP_X_CSRFTOKEN':csrf}
  response=client.post('/api/auth/login',data=json.dumps({'username':'stp.qa','password':'Case-Test-Pass-1'}),content_type='application/json',**headers)
  check('login',response.status_code==200,response.content[:500])
  headers={'HTTP_X_CSRFTOKEN':client.cookies['csrftoken'].value}
  response=client.post('/api/cases',data=json.dumps({'case':p,'incompleteDraft':True}),content_type='application/json',**headers)
  check('create STP draft',response.status_code==201,response.content[:1000])
  if response.status_code==201:
   case=Case.objects.get(case_uid=response.json()['case']['caseUid']); raw=case.payload.get('draftInput',{})
   check('draft text and HUB retained',raw.get('limitOfLiability')==p['limitOfLiability'] and raw.get('stpHubs')==p['stpHubs'],raw)
   check('multi-currency turnover retained',raw.get('stpTurnover')==p['stpTurnover'],raw)
   issues=validate_announce_ready(case.payload,allow_zero_loss_years=True,case_kind='original')
   check('complete STP ready for review',not issues,issues)
   check('uses stored QS Word workflow',word_scope(case.payload,'cover'))
   issues=readiness_issues(case.payload,'cover','qa@example.test')
   check('STP Cover Note ready without Sum Insured',not issues,issues)
   bad=copy.deepcopy(p);bad['stpTurnoverMode']='companies';bad['stpTurnover']=[{'company':'ACME','currency':'USD','amount':1},{'company':' acme ','currency':'TWD','amount':2}]
   norm=normalize_draft(bad);issues=validate_announce_ready(norm['value'],allow_zero_loss_years=True,case_kind='original')
   check('duplicate company blocked',any(i['field']=='stpTurnover.1.company' for i in issues),issues)
   for key, changed, expected in [('zero premium', {'originalPremium':0}, 'originalPremium'), ('blank cedant days', {'paymentTermsDays':None}, 'paymentTermsDays'), ('zero reinsurer premium', {'reinsurers':[dict(p['reinsurers'][0],premium=0)]}, 'reinsurers.0.premium'), ('blank reinsurer days', {'reinsurers':[dict(p['reinsurers'][0],paymentTermsDays=None)]}, 'reinsurers.0.paymentTermsDays')]:
    altered={**p,**changed}; norm=normalize_draft(altered); found=validate_announce_ready(norm['value'],allow_zero_loss_years=True,case_kind='original')
    check('Property QS rules: '+key,any(i['field']==expected for i in found),found)

  if response.status_code == 201:
   docs=[]
   for kind, names in [('offer',[]), ('signed',['STP Re'])]:
    docs.append(CaseDocument.objects.create(case=case,kind=kind,reinsurers=names,filename=kind+'.pdf',content_type='application/pdf',byte_size=5,sha256='0'*64,storage_key='stp-test-'+str(uuid.uuid4()),is_selected=True,uploaded_by='qa'))
   body={'caseUid':str(case.case_uid),'rowVersion':case.row_version,'confirmed':True,'documentIds':[str(d.pk) for d in docs]}
   r=client.post('/api/case-announce',data=json.dumps(body),content_type='application/json',**headers)
   check('Announce assigns TWST reference',r.status_code==200 and r.json().get('case',{}).get('twRef','').startswith('TWST'),r.content[:1000])
   if r.status_code==200:
    case.refresh_from_db()
    revised=copy.deepcopy(case.payload);revised['stpHubs'][0]['name']='Announced hub'
    no_reason=client.put('/api/cases',data=json.dumps({'caseUid':str(case.case_uid),'rowVersion':case.row_version,'case':revised}),content_type='application/json',**headers)
    check('Announced STP edit requires reason',no_reason.status_code==409,no_reason.content[:1000])
    edit=client.put('/api/cases',data=json.dumps({'caseUid':str(case.case_uid),'rowVersion':case.row_version,'case':revised,'reason':'STP test update'}),content_type='application/json',**headers)
    check('Announced STP fields can be changed with reason',edit.status_code==200,edit.content[:1000])
    if edit.status_code==200:
     case.refresh_from_db();p['stpHubs'][0]['name']='Announced hub'
    locked=client.put('/api/case-documents',data=json.dumps({'caseUid':str(case.case_uid),'fileId':str(docs[0].pk),'selected':False}),content_type='application/json',**headers)
    check('Selected evidence locked after Announce',locked.status_code==409 and locked.json().get('error')=='announced_document_locked',locked.content[:1000])
    generation={'caseUid':str(case.case_uid),'rowVersion':case.row_version,'kind':'cover','format':'docx','saveWorkflow':1}
    word=client.post('/api/document-generation-log',data=json.dumps(generation),content_type='application/json',**headers)
    check('STP Cover Note generation is authorized',word.status_code==200,word.content[:1000])
    if word.status_code==200:
     raw=b'PK\x03\x04[Content_Types].xml word/document.xml'
     save={'caseUid':str(case.case_uid),'rowVersion':case.row_version,'kind':'cover','generationId':str(uuid.uuid4()),'filename':'stp-test.docx','base64':base64.b64encode(raw).decode()}
     stored=client.post('/api/generated-case-documents',data=json.dumps(save),content_type='application/json',**headers)
     check('STP Cover Note saved to Case Documents',stored.status_code==201,stored.content[:1000])
    case.status='closed'; case.save(update_fields=['status'])
    r=client.post('/api/case-workflow',data=json.dumps({'action':'create_renewal','caseUid':str(case.case_uid),'rowVersion':case.row_version}),content_type='application/json',**headers)
    check('Renewal created',r.status_code==201,r.content[:1000])
    if r.status_code==201:
     renewal=Case.objects.get(case_uid=r.json()['case']['caseUid'])
     check('Renewal inherits STP turnover and hubs',renewal.payload.get('stpTurnover')==p['stpTurnover'] and renewal.payload.get('stpHubs')==p['stpHubs'],renewal.payload)
    case.refresh_from_db()
    r=client.post('/api/case-workflow',data=json.dumps({'action':'create_endorsement','caseUid':str(case.case_uid),'rowVersion':case.row_version}),content_type='application/json',**headers)
    check('Endorsement created',r.status_code==201,r.content[:1000])
    if r.status_code==201:
     endo=Case.objects.get(case_uid=r.json()['case']['caseUid'])
     check('Endorsement inherits STP turnover and hubs',endo.payload.get('stpTurnover')==p['stpTurnover'] and endo.payload.get('stpHubs')==p['stpHubs'],endo.payload)
     changes=copy.deepcopy(endo.payload);changes['stpHubs'][0]['name']='Updated hub';changes['stpTurnover'][0]['amount']=999
     updated=client.put('/api/cases',data=json.dumps({'caseUid':str(endo.case_uid),'rowVersion':endo.row_version,'case':changes,'incompleteDraft':True}),content_type='application/json',**headers)
     check('Endorsement STP fields can be edited',updated.status_code==200,updated.content[:1000])
     if updated.status_code==200:
      endo.refresh_from_db(); data=endo.payload.get('draftInput',endo.payload)
      check('Endorsement changes persist',data.get('stpHubs',[{}])[0].get('name')=='Updated hub' and data.get('stpTurnover',[{}])[0].get('amount')==999,data)

  raise Rollback()
except Rollback: pass
for name,ok,detail in results:
 print(('PASS ' if ok else 'FAIL ')+name+((' '+str(detail)) if not ok else ''))
print(f'{sum(ok for _,ok,_ in results)}/{len(results)} passed STP API checks')
if not all(ok for _,ok,_ in results): raise AssertionError('STP API checks failed')
