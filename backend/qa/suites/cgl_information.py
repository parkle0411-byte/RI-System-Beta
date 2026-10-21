"""Standard CGL Information: draft, required milestones, scope and stale text."""
import copy,json,uuid,os
from django.conf import settings
from django.contrib.auth import get_user_model
from django.db import transaction
from django.test import Client
from django.utils import timezone
from cases.cgl_information import is_standard_cgl,information_issues
from cases.draft import normalize_draft,validate_announce_ready
from cases.models import Case
from personnel.models import Personnel
assert os.environ.get('RI_DISPOSABLE_QA') == 'true'
checks=[]
def check(name,ok,detail=''):
 checks.append((name,bool(ok),str(detail)))
 if not ok:print('FAIL',name,detail)
def ready():
 return dict(coverages=['Premises-Operations Liability'],reinsuranceStructure='QS',classOfBusiness='Commercial General Liability',classCode='GL',currency='USD',newOrRenew='New',ae='CGL QA AE',
  typePrefix='Commercial General Liability',originalInsured='CGL QA Insured',reinsured='CGL QA Cedant',policyFrom='2026-01-01',policyTo='2027-01-01',
  situations=[dict(address='QA Road',postcode='100')],interest='Liability under original policy',limitOfLiability=1000000,deductibles='As original',originalConditions='As original',
  reinsuredRetention='Advice waived',originalPremium=1000,paymentTermsDays=90,lossAdvisedDate='2026-01-01',lossRecordYears=5,occupation='',construction='',sumInsured=[],
  reinsurers=[dict(name='CGL QA Reinsurer',sharePct=100,premium=1000,riCommPct=10,taxPct=0,paymentTermsDays=90)],
  cglInformation=dict(policyForm='Occurrence Form',territorialLimits='Worldwide excluding USA/Canada',insuredBusiness='Manufacturing\nWholesale',insuredProducts='QA products',
   estimatedTurnover=[dict(region='USA/Canada',currency='USD',amount=1000000),dict(region='Other regions',currency='TWD',amount=0)],insuredWebsite='free text without scheme',specialAgreementApplies='notApplicable'))
class Rollback(Exception):pass
try:
 with transaction.atomic():
  person=Personnel.objects.create(name='CGL QA Owner',department='reinsurance',role_code='sales',created_by='qa',updated_by='qa')
  user=get_user_model().objects.create_user(username='cgl.qa',password='CGL-QA-only-9!');person.auth_user_id=str(user.pk);person.account_status='active';person.save()
  client=Client(enforce_csrf_checks=True,HTTP_HOST='localhost',raise_request_exception=False)
  def call(method,path,body=None):
   client.get('/api/auth/csrf');kw={'HTTP_X_CSRFTOKEN':client.cookies['csrftoken'].value}
   return getattr(client,method)(path,data=json.dumps(body),content_type='application/json',**kw) if body is not None else getattr(client,method)(path,**kw)
  response=call('post','/api/auth/login',{'username':user.username,'password':'CGL-QA-only-9!'});assert response.status_code==200,response.content
  base=ready();base['ownerPersonnelId']=person.pk
  norm=normalize_draft(base);check('valid CGL normalization',not norm['errors'],norm['errors'])
  value=norm['value'];check('CGL removes property readiness requirements',not validate_announce_ready(value,allow_zero_loss_years=True),validate_announce_ready(value,allow_zero_loss_years=True))
  check('turnover supports independent currencies and zero amount',value['cglInformation']['estimatedTurnover'][1]==dict(region='Other regions',currency='TWD',amount=0))
  check('Website accepts arbitrary optional text',value['cglInformation']['insuredWebsite']=='free text without scheme')
  for field in ['policyForm','territorialLimits','insuredBusiness','insuredProducts','specialAgreementApplies']:
   p=copy.deepcopy(base);p['cglInformation'][field]='';check('required '+field,any(i['field']=='cglInformation.'+field for i in information_issues(p)))
  p=copy.deepcopy(base);p['cglInformation']['estimatedTurnover']=[];check('at least one turnover',bool(information_issues(p)))
  for key,bad in [('region',''),('currency',''),('amount',None),('amount',-1)]:
   p=copy.deepcopy(base);p['cglInformation']['estimatedTurnover'][0][key]=bad;check('turnover '+key+' '+str(bad),any(i['field']=='cglInformation.estimatedTurnover.0.'+key for i in information_issues(p)))
  p=copy.deepcopy(base);p['cglInformation']['territorialLimits']='Other';check('Other requires wording',any(i['field'].endswith('territorialOther') for i in information_issues(p)))
  p['cglInformation']['territorialOther']='Taiwan only';check('Other wording accepted',not information_issues(p))
  p=copy.deepcopy(base);p['cglInformation'].update(policyForm='Claims-Made Form');issues=information_issues(p);check('Claims-Made requires retroactive and ERP selection',len(issues)==2,issues)
  p['cglInformation'].update(retroactiveDate='2020-01-01',extendedReportingApplies='notApplicable');check('Claims-Made ERP not applicable',not information_issues(p))
  p['cglInformation']['extendedReportingApplies']='applicable';check('ERP applicable requires text',any(i['field'].endswith('extendedReportingPeriod') for i in information_issues(p)))
  p['cglInformation']['extendedReportingPeriod']='60 days after expiry';check('ERP period wording accepted',not information_issues(p))
  p['cglInformation']['retroactiveDate']='2026-02-30';check('invalid retroactive date rejected',bool(normalize_draft(p)['errors']))
  p=copy.deepcopy(base);p['cglInformation'].update(retroactiveDate='2020-01-01',extendedReportingApplies='applicable',extendedReportingPeriod='HIDDEN ERP',territorialOther='HIDDEN TERRITORY');p['specialAgreement']='HIDDEN AGREEMENT'
  v=normalize_draft(p)['value'];check('inactive dependent content cleared on API normalization',all(v['cglInformation'][key]=='' for key in ['retroactiveDate','extendedReportingApplies','extendedReportingPeriod','territorialOther']) and v['specialAgreement']=='')
  p=copy.deepcopy(base);p['cglInformation']['specialAgreementApplies']='applicable';check('applicable agreement requires text',bool(information_issues(p)));p['specialAgreement']='Agreed';check('agreement text accepted',not information_issues(p))
  for name,patch in [('Property',dict(classOfBusiness='Property')),('Treaty',dict(reinsuranceStructure='TREATY')),('Facility',dict(reinsurers=[dict(name='QA (Facility)')])),('PWS',dict(reinsurers=[dict(name='QA',foreignBroker='PWS Global Risks Limited')])),('Swiss',dict(reinsurers=[dict(name='Swiss Re Asia Pte. Ltd., Hong Kong Branch')]))]:
   p=copy.deepcopy(base);p.update(patch);check(name+' scope unchanged',not is_standard_cgl(p) and not information_issues(p))
  p=copy.deepcopy(base);p['classOfBusiness']='Property';check('Property still requires occupation construction sums',{'occupation','construction','sumInsured'}.issubset({i['field'] for i in validate_announce_ready(p)}))
  incomplete=copy.deepcopy(base);incomplete['cglInformation']={}
  response=call('post','/api/cases',{'case':incomplete});check('incomplete Information saves Draft',response.status_code==201,response.content[:300]);uid=response.json()['case']['caseUid'];case=Case.objects.get(case_uid=uid)
  response=call('post','/api/case-announce',{'caseUid':uid,'rowVersion':case.row_version,'confirmed':True});check('Announce blocks incomplete Information',response.status_code==400 and response.json().get('error')=='case_not_ready',response.content[:300])
  before=case.row_version;response=call('put','/api/cases',{'caseUid':uid,'rowVersion':before,'case':base});check('complete Information saves',response.status_code==200,response.content[:300]);case.refresh_from_db();check('Information round-trip retains rows and website',case.payload['cglInformation']==value['cglInformation'])
  # Document readiness reads stored data, never request-provided overrides.
  Case.objects.filter(pk=case.pk).update(status='posted',tw_ref='ZZ-CGL-QA-001',announced_at=timezone.now(),payload={**case.payload,'aeEmail':'cgl@example.invalid'})
  response=call('post','/api/document-generation-log',{'caseUid':uid,'kind':'cover','format':'docx'});check('CGL Cover Note allows no property breakdown',response.status_code==204,response.content[:300])
  case.refresh_from_db();stored=copy.deepcopy(case.payload);stored['cglInformation']['insuredProducts']='';Case.objects.filter(pk=case.pk).update(payload=stored)
  response=call('post','/api/document-generation-log',{'caseUid':uid,'kind':'cover','format':'docx','cglInformation':base['cglInformation']});check('Cover Note rejects missing stored Information despite request override',response.status_code==409 and response.json().get('error')=='cgl_information_required',response.content[:300])
  response=call('post','/api/document-generation-log',{'caseUid':uid,'kind':'debit','format':'docx'});check('Debit Note has no new Information requirement',response.status_code==204,response.content[:300])
  p=copy.deepcopy(base);p['lossAdvisedDate']='';response=call('post','/api/cases',{'case':p});check('Loss Record save requirements preserved',response.status_code==400)
  p=copy.deepcopy(base);p['cglInformation']['estimatedTurnover'][0]['amount']=-1;response=call('post','/api/cases',{'case':p});check('invalid entered amount rejected at save',response.status_code==400)
  raise Rollback()
except Rollback:pass
print(f'{sum(ok for _,ok,_ in checks)}/{len(checks)} passed; database changes rolled back')
assert all(ok for _,ok,_ in checks),checks
