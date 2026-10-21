"""Final standard CGL batch: optional clauses and Annual without financial changes."""
import copy,json,os
from django.contrib.auth import get_user_model
from django.db import transaction
from django.test import Client
from cases.draft import normalize_draft,validate_announce_ready
from cases.calc.totals import case_totals
from cases.models import Case,CaseDocument
from personnel.models import Personnel
assert os.environ.get('RI_DISPOSABLE_QA')=='true'
checks=[]
PRESETS=[dict(code='LMA3100',title='LMA3100 Sanctions Limitations and Exclusion Clause'),dict(code='LMA5396',title='LMA5396 Communicable Disease Exclusion'),dict(code='EXGRATIA',title='Excluding Ex-Gratia and without prejudice payment')]
def check(name,ok,detail=''):
    assert ok,(name,detail)
    checks.append(name)
def ready():
    return dict(classOfBusiness='Commercial General Liability',classCode='GL',reinsuranceStructure='QS',
        typePrefix='Commercial General Liability',currency='USD',newOrRenew='New',ae='Final QA AE',
        reinsured='QA Cedant',originalInsured='QA Insured',policyFrom='2026-01-01',policyTo='2027-01-01',policyFromTime='00:00',policyToTime='12:00',
        interest='Liability under original policy',situations=[dict(address='First QA Road',postcode='001'),dict(address='Second QA Road',postcode='123456')],
        limitOfLiability=1000000,underlyingLimits='USD500,000',deductibles='As original',originalConditions='As original',reinsuredRetention='Advice waived',
        coverages=['Medical Payment'],lossRecordYears=5,lossAdvisedDate='2026-01-01',originalPremium=1234.56,paymentTermsDays=90,
        riCommPct=10,taxPct=1,lossPayee='Legacy loss payee retained',basisOfValuation='Other',basisOfValuationOther='Legacy valuation',indemnityPeriod='Legacy period',
        reinsurers=[dict(name='QA General Re',sharePct=100,premium=1234.56,riCommPct=5,taxPct=0,paymentTermsDays=90)],
        cglInformation=dict(policyForm='Occurrence Form',territorialLimits='USA/Canada Only',insuredBusiness='Business',insuredProducts='Products',
            estimatedTurnover=[dict(region='USA/Canada',currency='USD',amount=1000000)],specialAgreementApplies='notApplicable'))
class Rollback(Exception):pass
try:
 with transaction.atomic():
    person=Personnel.objects.create(name='Final QA AE',email='qa@example.invalid',department='reinsurance',role_code='sales',created_by='qa',updated_by='qa')
    user=get_user_model().objects.create_user(username='cgl.final.qa',password='CGL-Final-QA-9!');person.auth_user_id=str(user.pk);person.account_status='active';person.save()
    client=Client(enforce_csrf_checks=True,HTTP_HOST='localhost',raise_request_exception=False);client.force_login(user)
    def call(method,path,body):
        client.get('/api/auth/csrf');return getattr(client,method)(path,data=json.dumps(body),content_type='application/json',HTTP_X_CSRFTOKEN=client.cookies['csrftoken'].value)
    base=ready();base['ownerPersonnelId']=person.pk
    for structure in ['QS','XOL']:
        for annual in ['missing',None,True,False]:
            p={**base,'reinsuranceStructure':structure}
            if annual!='missing':p['cglAnnual']=annual
            result=normalize_draft(p);value=result['value']
            check(structure+' Annual boolean/default '+repr(annual),not result['errors'] and value['cglAnnual']==(annual is not False),result['errors'])
            check('Annual does not change readiness',not validate_announce_ready(value),validate_announce_ready(value))
            check('template clauses are not inserted automatically',not value['manualClauses'] and not any(r['code'] in ['LMA3100','LMA5396','EXGRATIA'] for r in value['clauseDetails']))
            check('premium, tax and deductions unchanged',all(value[k]==base[k] for k in ['originalPremium','riCommPct','taxPct']))
            check('Annual does not change financial totals',case_totals(value)==case_totals(base))
            check('legacy loss payee and hidden Property values retained',all(value[k]==base[k] for k in ['lossPayee','basisOfValuation','basisOfValuationOther','indemnityPeriod']))
            check('actual times and addresses retained',value['policyFromTime']=='00:00' and value['policyToTime']=='12:00' and value['situations']==base['situations'])
    for annual in [0,1,'false','true',[],{}]:
        result=normalize_draft({**base,'cglAnnual':annual});check('invalid Annual rejected '+repr(annual),'Annual must be a boolean.' in result['errors'])
    for scope,patch in [('property',dict(classOfBusiness='Property')),('facility',dict(reinsurers=[dict(name='QA (Facility)')])),('pws',dict(reinsurers=[dict(name='QA',foreignBroker='PWS')])),('swiss',dict(reinsurers=[dict(name='Swiss Re Asia')])),('treaty',dict(reinsuranceStructure='TREATY'))]:
        result=normalize_draft({**base,**patch});check(scope+' has no new Annual default','cglAnnual' not in result['value'])
        result=normalize_draft({**base,**patch,'cglAnnual':False});check(scope+' preserves inactive saved Annual',result['value']['cglAnnual'] is False)
    for clause in PRESETS:
        result=normalize_draft({**base,'manualClauses':[clause]})
        check('manual preset saves '+clause['code'],not result['errors'] and result['value']['manualClauses']==[clause],result['errors'])
        check('manual preset appears in snapshot '+clause['code'],clause in result['value']['clauseDetails'])
    result=normalize_draft({**base,'manualClauses':PRESETS})
    check('all three are independent manual choices',not result['errors'] and len(result['value']['manualClauses'])==3 and all(c in result['value']['clauseDetails'] for c in PRESETS))
    response=call('post','/api/cases',dict(case=base));check('API creates new CGL',response.status_code==201,response.content[:400])
    uid=response.json()['case']['caseUid'];case=Case.objects.get(case_uid=uid)
    check('API new CGL defaults Annual on',case.payload['cglAnnual'] is True)
    complete={**base,'cglAnnual':False,'manualClauses':PRESETS}
    response=call('put','/api/cases',dict(caseUid=uid,rowVersion=case.row_version,case=complete));check('API saves Annual off and manual presets',response.status_code==200,response.content[:400]);case.refresh_from_db()
    check('saved Annual off round-trips',case.payload['cglAnnual'] is False)
    check('manual choices round-trip',case.payload['manualClauses']==PRESETS)
    check('saving preserved original amounts and legacy values',all(case.payload[k]==base[k] for k in ['originalPremium','riCommPct','taxPct','lossPayee','basisOfValuationOther','indemnityPeriod']))
    for kind in ['offer','signed']:
        CaseDocument.objects.create(case=case,kind=kind,reinsurers=['QA General Re'],filename='qa-'+kind+'.pdf',content_type='application/pdf',byte_size=1,sha256='a'*64,storage_key='final-qa-'+kind,is_selected=True,uploaded_by='qa')
    response=call('post','/api/case-announce',dict(caseUid=uid,rowVersion=case.row_version,confirmed=True,documentIds=[str(d.pk) for d in CaseDocument.objects.filter(case=case)]));check('Announce allows Annual off and selected clauses',response.status_code==200,response.content[:400]);case.refresh_from_db()
    response=call('post','/api/document-generation-log',dict(caseUid=uid,kind='cover',format='docx'));check('Cover accepts saved choices',response.status_code==204,response.content[:400])
    stored=copy.deepcopy(case.payload);stored.pop('cglAnnual');Case.objects.filter(pk=case.pk).update(payload=stored)
    response=client.get('/api/cases',{'caseUid':uid});check('legacy GET does not add Annual to stored payload',response.status_code==200 and 'cglAnnual' not in response.json()['case']['payload'],response.content[:400])
    response=call('post','/api/document-generation-log',dict(caseUid=uid,kind='cover',format='docx'));case.refresh_from_db()
    check('legacy document authorization does not rewrite payload',response.status_code==204 and case.payload==stored,response.content[:400])
    raise Rollback()
except Rollback:pass
print(f'{len(checks)}/{len(checks)} CGL final batch checks passed; database changes rolled back')
