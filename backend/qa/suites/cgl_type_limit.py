"""CGL type enum/structure format and legacy Interest/limit persistence."""
import copy,json,os
from django.contrib.auth import get_user_model
from django.db import transaction
from django.test import Client
from django.utils import timezone
from cases.draft import normalize_draft,validate_announce_ready
from cases.cgl_risk_details import TYPE_PREFIXES,type_issues
from cases.models import Case
from personnel.models import Personnel
assert os.environ.get('RI_DISPOSABLE_QA')=='true'
checks=[]
def check(name,ok,detail=''):
    assert ok,(name,detail)
    checks.append(name)
def ready():
    return dict(classOfBusiness='Commercial General Liability',classCode='GL',reinsuranceStructure='QS',
        typePrefix='Commercial General Liability',currency='USD',newOrRenew='New',ae='Type QA AE',
        reinsured='QA Cedant',originalInsured='QA Insured',policyFrom='2026-01-01',policyTo='2027-01-01',
        interest='LEGACY INTEREST & 自訂\nUnchanged',situations=[dict(address='QA Road',postcode='100')],
        limitOfLiability=1234567.89,deductibles='As original',originalConditions='As original',reinsuredRetention='Advice waived',
        coverages=['Medical Payment'],selfInsuredRetention='',lossRecordYears=5,lossAdvisedDate='2026-01-01',
        originalPremium=1000,paymentTermsDays=90,reinsurers=[dict(name='QA General Re',sharePct=100,premium=1000,riCommPct=5,taxPct=0,paymentTermsDays=90)],
        cglInformation=dict(policyForm='Occurrence Form',territorialLimits='USA/Canada Only',insuredBusiness='Business',insuredProducts='Products',
            estimatedTurnover=[dict(region='USA/Canada',currency='USD',amount=1000000)],specialAgreementApplies='notApplicable'))
class Rollback(Exception):pass
try:
 with transaction.atomic():
    person=Personnel.objects.create(name='Type QA AE',email='qa@example.invalid',department='reinsurance',role_code='sales',created_by='qa',updated_by='qa')
    user=get_user_model().objects.create_user(username='cgl.type.qa',password='CGL-Type-QA-9!');person.auth_user_id=str(user.pk);person.account_status='active';person.save()
    client=Client(enforce_csrf_checks=True,HTTP_HOST='localhost',raise_request_exception=False);client.force_login(user)
    def call(method,path,body):
        client.get('/api/auth/csrf');return getattr(client,method)(path,data=json.dumps(body),content_type='application/json',HTTP_X_CSRFTOKEN=client.cookies['csrftoken'].value)
    base=ready();base['ownerPersonnelId']=person.pk
    for structure,suffix in [('QS','Facultative Reinsurance'),('FACULTATIVE','Facultative Reinsurance'),('XOL','Excess of Loss Facultative Reinsurance')]:
        for prefix in TYPE_PREFIXES:
            expected=prefix+' '+suffix+' as original'
            for explicit in [True,False]:
                p={**base,'reinsuranceStructure':structure,'type':prefix+' '+suffix}
                if explicit:p['typePrefix']=prefix
                else:p.pop('typePrefix')
                result=normalize_draft(p)
                check('Type canonical '+structure+' '+prefix+' '+str(explicit),not result['errors'] and result['value']['type']==expected,result)
                again=normalize_draft(result['value']);check('as original not duplicated '+structure+prefix+str(explicit),again['value']['type']==expected)
                check('Interest preserved '+structure+prefix+str(explicit),result['value']['interest']==base['interest'])
    for raw in ['Property','Other']:
        check('invalid CGL choice rejected at save '+raw,bool(normalize_draft({**base,'typePrefix':raw})['errors']))
    result=normalize_draft({**base,'typePrefix':'','type':''})
    check('blank Type draft normalizes without default selection',not result['errors'] and result['value']['type']=='',result)
    check('blank Type milestone blocks',any(row['field']=='typePrefix' for row in validate_announce_ready(result['value'])))
    for value in [None,-1,'bad']:
        result=normalize_draft({**base,'limitOfLiability':value})
        issues=validate_announce_ready(result['value'])
        check('CGL limit label '+str(value),any('Limit of Indemnity' in s for s in result['errors']) or any(i['label']=='Limit of Indemnity' for i in issues))
    p={**base,'classOfBusiness':'Property','typePrefix':'Fire / Lightning','limitOfLiability':-1}
    result=normalize_draft(p);check('Property limit save label remains',any('Limit of Liability' in s for s in result['errors']))
    for scope,patch in [('Property',dict(classOfBusiness='Property')),('Treaty',dict(reinsuranceStructure='TREATY')),('Facility',dict(reinsurers=[dict(name='QA (Facility)')])),('PWS',dict(reinsurers=[dict(name='QA',foreignBroker='PWS')])),('Swiss',dict(reinsurers=[dict(name='Swiss Re Asia')]))]:
        p={**base,**patch,'typePrefix':'Custom liability'};result=normalize_draft(p)
        check(scope+' free Type unchanged',not result['errors'] and 'as original' not in result['value']['type'],result['errors'])
    blank={**base,'typePrefix':'','type':''}
    response=call('post','/api/cases',{'case':blank});check('API saves no selected Type draft',response.status_code==201,response.content[:400])
    uid=response.json()['case']['caseUid'];case=Case.objects.get(case_uid=uid)
    response=call('post','/api/case-announce',dict(caseUid=uid,rowVersion=case.row_version,confirmed=True))
    check('Announce blocks blank Type',response.status_code==400 and 'Type' in response.content.decode())
    response=call('put','/api/cases',dict(caseUid=uid,rowVersion=case.row_version,case=base));check('selected Type saves',response.status_code==200,response.content[:400]);case.refresh_from_db()
    stored=copy.deepcopy(case.payload)
    check('Type stored with suffix',stored['type']=='Commercial General Liability Facultative Reinsurance as original')
    check('existing Interest exact text retained',stored['interest']==base['interest'])
    check('existing numeric limit/currency retained',stored['limitOfLiability']==1234567.89 and stored['currency']=='USD')
    Case.objects.filter(pk=case.pk).update(status='posted',tw_ref='ZZ-CGL-TYPE-001',announced_at=timezone.now())
    response=call('post','/api/document-generation-log',dict(caseUid=uid,kind='cover',format='docx'));check('valid Type Cover authorized',response.status_code==204,response.content[:400])
    Case.objects.filter(pk=case.pk).update(payload={**stored,'typePrefix':'Property','type':'Property Facultative Reinsurance'})
    response=call('post','/api/document-generation-log',dict(caseUid=uid,kind='cover',format='docx',type=stored['type'],typePrefix=base['typePrefix']))
    check('Cover checks saved enum despite request override',response.status_code==409 and response.json().get('error')=='cgl_type_required',response.content[:400])
    Case.objects.filter(pk=case.pk).update(payload={**stored,'limitOfLiability':None})
    response=call('post','/api/document-generation-log',dict(caseUid=uid,kind='cover',format='docx'))
    check('Cover limit error label renamed, key preserved',response.status_code==409 and response.json().get('error')=='limit_of_liability_required' and 'Limit of Indemnity' in response.content.decode(),response.content[:400])
    raise Rollback()
except Rollback:pass
print(f'{len(checks)}/{len(checks)} CGL type/interest/limit checks passed; database changes rolled back')
