"""Standard CGL optional Notices and retained hidden Property terms."""
import copy,json,os
from django.contrib.auth import get_user_model
from django.db import transaction
from django.test import Client
from django.utils import timezone
from cases.draft import normalize_draft,validate_announce_ready
from cases.models import Case,CaseDocument
from personnel.models import Personnel
assert os.environ.get('RI_DISPOSABLE_QA')=='true'
checks=[]
def check(name,ok,detail=''):
    assert ok,(name,detail)
    checks.append(name)
def ready():
    return dict(classOfBusiness='Commercial General Liability',classCode='GL',reinsuranceStructure='QS',
        typePrefix='Commercial General Liability',currency='USD',newOrRenew='New',ae='Notices QA AE',
        reinsured='QA Cedant',originalInsured='QA Insured',policyFrom='2026-01-01',policyTo='2027-01-01',
        interest='Liability under original policy',situations=[dict(address='First QA Road',postcode='001'),dict(address='Second QA Road',postcode='123456')],
        limitOfLiability=1000000,underlyingLimits='USD500,000',deductibles='As original',originalConditions='As original',reinsuredRetention='Advice waived',
        coverages=['Medical Payment'],lossRecordYears=5,lossAdvisedDate='2026-01-01',originalPremium=1000,paymentTermsDays=90,
        basisOfValuation='Other',basisOfValuationOther='',indemnityPeriod='Legacy 24 months',
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
    person=Personnel.objects.create(name='Notices QA AE',email='qa@example.invalid',department='reinsurance',role_code='sales',created_by='qa',updated_by='qa')
    user=get_user_model().objects.create_user(username='cgl.notices.qa',password='CGL-Notices-QA-9!');person.auth_user_id=str(user.pk);person.account_status='active';person.save()
    client=Client(enforce_csrf_checks=True,HTTP_HOST='localhost',raise_request_exception=False);client.force_login(user)
    def call(method,path,body):
        client.get('/api/auth/csrf');return getattr(client,method)(path,data=json.dumps(body),content_type='application/json',HTTP_X_CSRFTOKEN=client.cookies['csrftoken'].value)
    base=ready();base['ownerPersonnelId']=person.pk
    for structure in ['QS','XOL']:
        for wording in [None,'',' \n\t ','First notice & details\n第二行 {{TYPE}}']:
            p={**base,'reinsuranceStructure':structure,'notices':wording}
            result=normalize_draft(p)
            check(structure+' optional notices saves '+repr(wording),not result['errors'],result['errors'])
            check(structure+' hidden Other does not block readiness '+repr(wording),not validate_announce_ready(result['value']),validate_announce_ready(result['value']))
            check(structure+' hidden terms retained',result['value']['basisOfValuation']=='Other' and result['value']['basisOfValuationOther']=='' and result['value']['indemnityPeriod']=='Legacy 24 months')
    result=normalize_draft({**base,'basisOfValuationOther':'Legacy replacement wording','notices':'通知\nsecond'})
    check('legacy valuation explanation retained',result['value']['basisOfValuationOther']=='Legacy replacement wording')
    check('multi-line notices retained',result['value']['notices']=='通知\nsecond')
    check('multiple principal addresses and leading zeros retained',result['value']['situations']==base['situations'])
    for patch in [dict(classOfBusiness='Property'),dict(reinsuranceStructure='TREATY'),dict(reinsurers=[dict(name='QA (Facility)')]),dict(reinsurers=[dict(name='Swiss Re Asia')]),dict(reinsuranceStructure='XOL',reinsurers=[dict(name='QA',foreignBroker='PWS')])]:
        issues=validate_announce_ready({**base,**patch})
        check('non-standard scope still requires Other wording '+repr(patch),any(i['field']=='basisOfValuationOther' for i in issues))
    for patch,field in [(dict(address='',postcode='123'),'.address'),(dict(address='QA road',postcode='1234567'),'.postcode'),(dict(address='QA road',postcode='12'),'.postcode'),(dict(address='QA road',postcode='A12'),'.postcode')]:
        p={**base,'situations':[base['situations'][0],patch]}
        check('second address remains required '+repr(patch),any(i['field']=='situations.1'+field for i in validate_announce_ready(p)))
    response=call('post','/api/cases',dict(case={**base,'notices':''}));check('API creates draft with hidden Other and no notices',response.status_code==201,response.content[:400])
    uid=response.json()['case']['caseUid'];case=Case.objects.get(case_uid=uid)
    for kind in ['offer','signed']:
        CaseDocument.objects.create(case=case,kind=kind,reinsurers=['QA General Re'],filename='qa-'+kind+'.pdf',content_type='application/pdf',byte_size=1,sha256='a'*64,storage_key='notices-qa-'+kind,is_selected=True,uploaded_by='qa')
    response=call('post','/api/case-announce',dict(caseUid=uid,rowVersion=case.row_version,confirmed=True,documentIds=[str(d.pk) for d in CaseDocument.objects.filter(case=case)]))
    check('Announce allows optional blank notices and hidden Other',response.status_code==200,response.content[:400]);case.refresh_from_db()
    check('Announce retained hidden terms and both addresses',case.payload['basisOfValuation']=='Other' and case.payload['indemnityPeriod']=='Legacy 24 months' and case.payload['situations']==base['situations'])
    for wording in ['', 'Notice one & details\n第二行 {{TYPE}}']:
        complete={**base,'basisOfValuationOther':'Retained hidden wording','notices':wording}
        response=call('put','/api/cases',dict(caseUid=uid,rowVersion=case.row_version,case=complete));check('API updates notices '+repr(wording),response.status_code==200,response.content[:400]);case.refresh_from_db()
        check('saved hidden values preserved',case.payload['basisOfValuationOther']=='Retained hidden wording' and case.payload['indemnityPeriod']=='Legacy 24 months')
        response=client.get('/api/cases',{'caseUid':str(uid)})
        check('API read round-trips notices '+repr(wording),response.status_code==200 and response.json()['case']['payload']['notices']==wording,response.content[:400])
        response=call('post','/api/document-generation-log',dict(caseUid=str(uid),kind='cover',format='docx'));check('Cover allows optional notices '+repr(wording),response.status_code==204,response.content[:400])
    stored=copy.deepcopy(case.payload)
    for patch,error in [(dict(address='',postcode='123'),'situation_address_required'),(dict(address='QA Road',postcode='1234567'),'situation_postcode_required'),(dict(address='QA Road',postcode='12'),'situation_postcode_required')]:
        Case.objects.filter(pk=case.pk).update(payload={**stored,'situations':[base['situations'][0],patch]})
        response=call('post','/api/document-generation-log',dict(caseUid=str(uid),kind='cover',format='docx'))
        expected = response.status_code==204 if not patch['address'] else response.status_code==409 and response.json().get('error')==error
        check('New CGL optional address / supplied postcode '+repr(patch),expected,response.content[:400])
    raise Rollback()
except Rollback:pass
print(f'{len(checks)}/{len(checks)} CGL notices checks passed; database changes rolled back')
