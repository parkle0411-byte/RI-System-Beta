"""CGL XOL underlying readiness; aggregate/sub-limits remain optional."""
import copy,json,os
from django.contrib.auth import get_user_model
from django.db import transaction
from django.test import Client
from django.utils import timezone
from cases.draft import normalize_draft,validate_announce_ready
from cases.cgl_risk_details import underlying_issues
from cases.models import Case
from personnel.models import Personnel
assert os.environ.get('RI_DISPOSABLE_QA')=='true'
checks=[]
def check(name,ok,detail=''):
    assert ok,(name,detail)
    checks.append(name)
def ready():
    return dict(classOfBusiness='Commercial General Liability',classCode='GL',reinsuranceStructure='XOL',
        typePrefix='Commercial General Liability',currency='USD',newOrRenew='New',ae='Limits QA AE',
        reinsured='QA Cedant',originalInsured='QA Insured',policyFrom='2026-01-01',policyTo='2027-01-01',
        interest='Liability under original policy',situations=[dict(address='QA Road',postcode='100')],
        limitOfLiability=1000000,aggregateLimit=None,underlyingLimits='USD500,000 each occurrence',subLimits='',
        deductibles='As original',originalConditions='As original',reinsuredRetention='Advice waived',
        coverages=['Medical Payment'],lossRecordYears=5,lossAdvisedDate='2026-01-01',originalPremium=1000,paymentTermsDays=90,
        reinsurers=[dict(name='QA General Re',sharePct=100,premium=1000,riCommPct=5,taxPct=0,paymentTermsDays=90)],
        cglInformation=dict(policyForm='Occurrence Form',territorialLimits='USA/Canada Only',insuredBusiness='Business',insuredBusinessSelections=['Other'],insuredBusinessOther='Business',insuredProducts='Products',
            estimatedTurnover=[dict(region='USA/Canada',currency='USD',amount=1000000)],specialAgreementApplies='notApplicable'))
# Complete fixtures include the newly confirmed QS formal fields.
_legacy_ready = ready
def ready():
    p = _legacy_ready()
    p.setdefault('originalInsuredCn', 'QS QA CN')
    p.setdefault('riCommPct', 0)
    p.setdefault('taxPct', 0)
    return p
class Rollback(Exception):pass
try:
 with transaction.atomic():
    person=Personnel.objects.create(name='Limits QA AE',email='qa@example.invalid',department='reinsurance',role_code='sales',created_by='qa',updated_by='qa')
    user=get_user_model().objects.create_user(username='cgl.limits.qa',password='CGL-Limits-QA-9!');person.auth_user_id=str(user.pk);person.account_status='active';person.save()
    client=Client(enforce_csrf_checks=True,HTTP_HOST='localhost',raise_request_exception=False);client.force_login(user)
    def call(method,path,body):
        client.get('/api/auth/csrf');return getattr(client,method)(path,data=json.dumps(body),content_type='application/json',HTTP_X_CSRFTOKEN=client.cookies['csrftoken'].value)
    base=ready();base['ownerPersonnelId']=person.pk
    for aggregate in [None,'',0,1234567.89]:
        for sub in ['', '  \n\t ', 'Medical USD25,000\n附加 & wording']:
            result=normalize_draft({**base,'aggregateLimit':aggregate,'subLimits':sub})
            check('valid optionals '+repr((aggregate,sub)),not result['errors'] and not validate_announce_ready(result['value']),result)
            if aggregate==0:check('explicit aggregate zero retained',result['value']['aggregateLimit']==0)
    for raw in [None,'','  \t\n ','\ufeff']:
        p={**base,'underlyingLimits':raw};result=normalize_draft(p)
        check('blank underlying draft accepted '+repr(raw),not result['errors'],result['errors'])
        check('XOL readiness blocks blank underlying '+repr(raw),[i for i in validate_announce_ready(result['value']) if i['field']=='underlyingLimits']==[dict(field='underlyingLimits',label='Underlying Limits')])
    p={**base};p.pop('underlyingLimits');check('missing underlying field blocked',bool(underlying_issues(p)))
    for structure in ['QS','FACULTATIVE']:
        p={**base,'reinsuranceStructure':structure,'underlyingLimits':'STALE QS UNDERLYING'};result=normalize_draft(p)
        check(structure+' uses existing clearing rule',result['value']['underlyingLimits']=='')
        check(structure+' has no underlying readiness requirement',not underlying_issues(p) and not validate_announce_ready(result['value']))
    for scope,patch in [('Property',dict(classOfBusiness='Property')),('Treaty',dict(reinsuranceStructure='TREATY')),('Facility',dict(reinsurers=[dict(name='QA (Facility)')])),('PWS',dict(reinsurers=[dict(name='QA',foreignBroker='PWS')])),('Swiss',dict(reinsurers=[dict(name='Swiss Re Asia')]))]:
        p={**base,**patch,'underlyingLimits':''}
        check(scope+' unchanged underlying milestone',not underlying_issues(p) and not any(i['field']=='underlyingLimits' for i in validate_announce_ready(p)))
    check('negative aggregate still rejected',any('Aggregate Limit' in e for e in normalize_draft({**base,'aggregateLimit':-1})['errors']))
    response=call('post','/api/cases',dict(case={**base,'underlyingLimits':''}));check('API saves incomplete XOL draft',response.status_code==201,response.content[:400])
    uid=response.json()['case']['caseUid'];case=Case.objects.get(case_uid=uid)
    response=call('post','/api/case-announce',dict(caseUid=uid,rowVersion=case.row_version,confirmed=True))
    check('Announce blocks missing underlying',response.status_code==400 and 'Underlying Limits' in response.content.decode(),response.content[:400])
    Case.objects.filter(pk=case.pk).update(status='posted',tw_ref='ZZ-CGL-LIMITS-001',announced_at=timezone.now())
    response=call('post','/api/document-generation-log',dict(caseUid=uid,kind='cover',format='docx',underlyingLimits='Request override'))
    check('Cover reads saved underlying and rejects override',response.status_code==409 and response.json().get('error')=='underlying_limits_required',response.content[:400])
    Case.objects.filter(pk=case.pk).update(status='draft',tw_ref=None,announced_at=None)
    complete={**base,'aggregateLimit':0,'underlyingLimits':'USD500,000\nOriginal terms & conditions','subLimits':'Medical USD25,000\n附加限額'}
    response=call('put','/api/cases',dict(caseUid=uid,rowVersion=case.row_version,case=complete));check('API saves all limit fields',response.status_code==200,response.content[:400]);case.refresh_from_db()
    stored=copy.deepcopy(case.payload)
    check('aggregate zero and Case currency round-trip',stored['aggregateLimit']==0 and stored['currency']=='USD')
    check('underlying multiline round-trip',stored['underlyingLimits']==complete['underlyingLimits'])
    check('optional sub-limits multiline round-trip',stored['subLimits']==complete['subLimits'])
    Case.objects.filter(pk=case.pk).update(status='posted',tw_ref='ZZ-CGL-LIMITS-001',announced_at=timezone.now())
    response=call('post','/api/document-generation-log',dict(caseUid=uid,kind='cover',format='docx'));check('complete XOL Cover authorized',response.status_code==204,response.content[:400])
    Case.objects.filter(pk=case.pk).update(payload={**stored,'aggregateLimit':None,'subLimits':''})
    response=call('post','/api/document-generation-log',dict(caseUid=uid,kind='cover',format='docx'));check('blank optionals do not block Cover',response.status_code==204,response.content[:400])
    Case.objects.filter(pk=case.pk).update(payload={**stored,'cglInformation':base['cglInformation'],'reinsuranceStructure':'QS','underlyingLimits':'STALE QS UNDERLYING','aggregateLimit':None,'subLimits':''})
    response=call('post','/api/document-generation-log',dict(caseUid=uid,kind='cover',format='docx'));check('QS has no underlying document requirement',response.status_code==204,response.content[:400])
    result=normalize_draft({**base,'currency':'TWD','aggregateLimit':1234567.89})
    check('aggregate always uses Case currency without changing amount',result['value']['currency']=='TWD' and result['value']['aggregateLimit']==1234567.89)
    raise Rollback()
except Rollback:pass
print(f'{len(checks)}/{len(checks)} CGL limits checks passed; database changes rolled back')
