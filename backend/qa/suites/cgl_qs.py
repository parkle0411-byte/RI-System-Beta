"""CGL QS decisions, incomplete drafts and accounting boundaries."""
import copy,json,os
from django.contrib.auth import get_user_model
from django.db import transaction
from django.test import Client
from django.utils import timezone
from cases.models import Case,CaseDocument
from cases.draft import normalize_draft,validate_announce_ready
from cases.draft_input import validate as validate_input
from cases.cgl_information import is_standard_cgl
from personnel.models import Personnel
assert os.environ.get('RI_DISPOSABLE_QA')=='true'
checks=[]
def check(name,ok,detail=''):
    assert ok,(name,detail)
    checks.append(name)
def ready(person):
    return dict(ownerPersonnelId=person.pk,ae=person.name,classOfBusiness='Commercial General Liability',classCode='GL',reinsuranceStructure='QS',
        typePrefix='Commercial General Liability',currency='USD',newOrRenew='New',reinsured='QA Cedant',originalInsured='QA Insured',originalInsuredCn='測試被保險人',
        policyFrom='2026-01-01',policyTo='2027-01-01',situations=[dict(address='Synthetic test road',postcode='')],interest='Reinsurance of original liability.',
        limitOfLiability=1000000,aggregateLimit=5000000,deductibles='As original',originalConditions='As original',reinsuredRetention='Advice waived',originalExclusions='',
        coverages=['Medical Payment'],lossAdvisedDate='2026-01-01',lossRecordYears=0,lossRecord=[],originalPremium=1000,riCommPct=0,taxPct=0,paymentTermsDays=90,
        reinsurers=[dict(name='Berkley Insurance Company',sharePct=100,premium=800,riCommPct=0,taxPct=0,paymentTermsDays=90,foreignBroker='PWS Global Risks Limited')],
        cglInformation=dict(policyForm='Occurrence Form',territorialLimits='USA/Canada Only',insuredBusiness='Business',insuredBusinessSelections=['Other'],insuredBusinessOther='Business',insuredProducts='Products',
            estimatedTurnover=[dict(region='USA/Canada',currency='USD',amount=0)],specialAgreementApplies='notApplicable'))
class Rollback(Exception):pass
try:
 with transaction.atomic():
    person=Personnel.objects.create(name='CGL QS AE',email='',department='reinsurance',role_code='sales',is_split_eligible=True,created_by='qa',updated_by='qa')
    user=get_user_model().objects.create_user(username='cgl.qs.qa',password='CGL-QS-QA-9!');person.auth_user_id=str(user.pk);person.account_status='active';person.save()
    client=Client(enforce_csrf_checks=True,HTTP_HOST='localhost',raise_request_exception=False);client.force_login(user)
    def call(method,path,body):
        client.get('/api/auth/csrf');return getattr(client,method)(path,data=json.dumps(body),content_type='application/json',HTTP_X_CSRFTOKEN=client.cookies['csrftoken'].value)
    def create(p,relaxed=True):
        r=call('post','/api/cases',dict(case=p,incompleteDraft=relaxed));check('create draft',r.status_code==201,r.content[:700]);return Case.objects.get(case_uid=r.json()['case']['caseUid'])
    def update(case,p,relaxed=True,version=None):
        return call('put','/api/cases',dict(caseUid=str(case.case_uid),rowVersion=version or case.row_version,case=p,incompleteDraft=relaxed))
    def docs(case):
        for kind in ['offer','signed']:
            CaseDocument.objects.create(case=case,kind=kind,reinsurers=['Berkley Insurance Company'],filename='qa-'+kind+'.pdf',content_type='application/pdf',byte_size=1,sha256='a'*64,storage_key='qa-'+str(case.pk)+'-'+kind,is_selected=True,uploaded_by='qa')
        return [str(d.pk) for d in CaseDocument.objects.filter(case=case)]
    minimum=dict(reinsuranceStructure='QS',classOfBusiness='Commercial General Liability',currency='USD')
    nonce='synthetic-cgl-retry-key-20261023'
    first=call('post','/api/cases',dict(case=minimum,incompleteDraft=True,draftKey=nonce))
    again=call('post','/api/cases',dict(case=minimum,incompleteDraft=True,draftKey=nonce))
    check('retry recovers the same draft instead of duplicating it',first.status_code==201 and again.status_code==200 and first.json()['case']['caseUid']==again.json()['case']['caseUid'])
    for p in [dict(reinsuranceStructure='QS'),dict(classOfBusiness='Commercial General Liability'),{**minimum,'reinsuranceStructure':'XOL'},{**minimum,'reinsurers':[{'name':'QA (Facility)'}]}]:
        r=call('post','/api/cases',dict(case=p,incompleteDraft=True));check('incomplete mode stays in approved scope',r.status_code==400,r.content[:300])
    case=create(minimum)
    check('incomplete draft does not create accounting entries',case.payload.get('transactions')==[] and not case.tw_ref)
    bad={**minimum,'originalPremium':'not a number','policyFrom':'2026-99-xx','lossRecordYears':'unfinished','situations':[dict(address='Partial',postcode='bad-postcode')],
        'pendingClause':dict(code='LMA1234',title=''),'splitEnabled':True,'splitParties':[dict(personnelId=None,name='',pct='40.')],
        'transactions':[{'txNo':'FORGED'}],'claims':[{'id':'FORGED'}],'paymentEntries':[{'amount':999}],
        'reinsurers':[dict(name='Berkley Insurance Company',sharePct='120',premium='-',paymentTermsDays='1.5')],
        'installmentEnabled':True,'performanceInstallments':[dict(id='I1',paymentBaseDate='unfinished',performanceMonth='20',premium='-',paymentTermsDays='0',reinsurerPaymentTerms={'r1':'ten'})]}
    r=update(case,bad);check('invalid and unfinished fields save',r.status_code==200,r.content[:700]);case.refresh_from_db()
    saved=case.payload['draftInput']
    for key in ['originalPremium','policyFrom','lossRecordYears','situations','reinsurers','performanceInstallments']:
        check('raw round trip '+key,saved[key]==bad[key])
    check('pending clause round trips',case.payload['pendingClause']==bad['pendingClause'])
    check('financial state cannot be injected',case.payload['transactions']==[] and case.payload['claims']==[] and case.payload['paymentEntries']==[])
    r=client.get('/api/cases',{'caseUid':str(case.case_uid)});check('invalid draft remains readable',r.status_code==200,r.content[:500])
    check('formal validator rejects retained invalid input',bool(validate_announce_ready(case.payload,allow_zero_loss_years=True)))
    r=call('post','/api/case-announce',dict(caseUid=str(case.case_uid),rowVersion=case.row_version,confirmed=True));check('invalid draft cannot announce',r.status_code==400,r.content[:400])
    r=update(case,minimum,version=1);check('stale autosave cannot overwrite later input',r.status_code==409,r.content[:500])
    r=update(case,{**minimum,'classOfBusiness':'','reinsuranceStructure':''});check('cleared setup values still save an existing draft',r.status_code==200,r.content[:500]);case.refresh_from_db()
    check('cleared setup values retained',case.payload['draftInput']['classOfBusiness']=='' and case.payload['draftInput']['reinsuranceStructure']=='')
    base=ready(person)
    other=Personnel.objects.create(name='QS Other Staff',department='business_1',role_code='viewer',is_split_eligible=True,created_by='qa',updated_by='qa')
    from cases.resolve import resolve_personnel_splits
    for pair in [(40,60),(70,30)]:
        p={**base,'splitEnabled':True,'splitParties':[dict(personnelId=person.pk,name=person.name,pct=pair[0]),dict(personnelId=other.pk,name=other.name,pct=pair[1])]}
        norm=normalize_draft(p);check('paired split percentages accepted '+str(pair),not norm['errors'] and not resolve_personnel_splits(norm['value']),norm['errors'])
    p={**base,'splitEnabled':True,'splitParties':[dict(personnelId=other.pk,name=other.name,pct=40),dict(personnelId=person.pk,name=person.name,pct=60)]}
    check('split staff roles cannot be swapped',bool(resolve_personnel_splits(p)))
    xol=create({**base,'reinsuranceStructure':'XOL'},False)
    r=update(xol,{**base,'reinsuranceStructure':''});check('clearing XOL does not opt into QS autosave',r.status_code==409,r.content[:400])
    check('PWS stays in ordinary CGL QS',is_standard_cgl(base))
    check('PWS XOL scope is unchanged',not is_standard_cgl({**base,'reinsuranceStructure':'XOL'}))
    normalized=normalize_draft(base);check('complete QS normalizes',not normalized['errors'],normalized['errors'])
    check('PD required timing, blank postcode and zero commissions accepted',not validate_announce_ready(normalized['value'],allow_zero_loss_years=True),validate_announce_ready(normalized['value'],allow_zero_loss_years=True))
    hidden={**base,'aggregateLimit':'unfinished legacy value','sumInsured':[dict(category='Legacy item',amount='unfinished')]}
    normalized_hidden=normalize_draft(hidden)
    check('inactive legacy fields are retained without blocking CGL QS',not normalized_hidden['errors'] and not validate_announce_ready(normalized_hidden['value'],allow_zero_loss_years=True),normalized_hidden['errors'])
    check('inactive legacy values are not erased',normalized_hidden['value']['aggregateLimit']==hidden['aggregateLimit'] and normalized_hidden['value']['sumInsured']==hidden['sumInsured'])
    for key in ['originalInsuredCn','reinsuredRetention','riCommPct','taxPct','paymentTermsDays']:
        p=copy.deepcopy(base);p[key]='';check('PD-aligned field required '+key,any(i['field']==key for i in validate_announce_ready(p,allow_zero_loss_years=True)))
    for key,value in [('currency','EUR'),('limitOfLiability',0),('policyTo','2026-01-01'),('originalPremium',0)]:
        p={**base,key:value};check('new QS constraint '+key,any(i['field']==key for i in validate_announce_ready(p,allow_zero_loss_years=True)))
    p=copy.deepcopy(base);p['reinsurers'].append({**p['reinsurers'][0],'sharePct':1});check('share sum over 100 rejected',any(i['field']=='reinsurers' for i in validate_announce_ready(p,allow_zero_loss_years=True)))
    p=copy.deepcopy(base);p['reinsurers'][0]['sharePct']=0;check('zero share accepted',not any(i['field'].endswith('sharePct') for i in validate_announce_ready(p,allow_zero_loss_years=True)))
    for postcode in ['123','123456','']:
        p=copy.deepcopy(base);p['situations'][0]['postcode']=postcode;check('optional valid postcode '+repr(postcode),not normalize_draft(p)['errors'])
    for postcode in ['ab','12','1234567']:
        p=copy.deepcopy(base);p['situations'][0]['postcode']=postcode;check('invalid postcode rejected formally '+postcode,bool(normalize_draft(p)['errors']))
    p=copy.deepcopy(base);p['lossRecordYears']=1;p['lossRecord']=[dict(date='2025-01-01',cause='Cause',lossPaid=0)]
    check('zero Loss Amount rejected',any(i['field']=='lossRecord.0.lossPaid' for i in validate_announce_ready(p,allow_zero_loss_years=True)))
    p=copy.deepcopy(base);p['parentTwRef']='QA-PARENT';p['originalPremium']=-100;p['reinsurers'][0]['premium']=-80
    check('endorsement premium sign retained',not any('Premium must be greater' in i['label'] for i in validate_announce_ready(p,allow_zero_loss_years=True)))
    r=update(case,base);check('corrected incomplete draft saves',r.status_code==200,r.content[:600]);case.refresh_from_db()
    clean,issues=validate_input(case.payload);check('valid raw draft becomes canonical',not issues and 'draftInput' not in clean,issues)
    Case.objects.filter(pk=case.pk).update(tw_ref='QA-OLD-DRAFT-REF')
    for kind in ['cover','debit']:
        r=call('post','/api/document-generation-log',dict(caseUid=str(case.case_uid),kind=kind,format='docx'))
        check('old reference does not bypass revised draft validation '+kind,r.status_code==409 and r.json()['error']=='draft_announcement_required',r.content[:500])
    Case.objects.filter(pk=case.pk).update(tw_ref=None)
    ids=docs(case)
    r=call('post','/api/case-announce',dict(caseUid=str(case.case_uid),rowVersion=case.row_version,confirmed=True,documentIds=ids));check('Announce accepts no AE Email',r.status_code==200,r.content[:700]);case.refresh_from_db()
    check('Announce creates current accounting T1/T2/T3',len(case.payload.get('transactions') or [])==3)
    check('formal case has no draft input metadata','draftInput' not in case.payload and 'pendingClause' not in case.payload)
    r=call('post','/api/document-generation-log',dict(caseUid=str(case.case_uid),kind='cover',format='docx'));check('AE Email required only at document stage',r.status_code==409 and r.json()['error']=='ae_email_required',r.content[:500])
    person.email='qa@example.invalid';person.save()
    for kind in ['cover','debit']:
        r=call('post','/api/document-generation-log',dict(caseUid=str(case.case_uid),kind=kind,format='docx'));check('document accepted '+kind,r.status_code==204,r.content[:700])
    r=update(case,base);check('automatic saving cannot edit Announced accounting',r.status_code==409,r.content[:500])
    inst=copy.deepcopy(case.payload);inst.update(installmentEnabled=True,performanceInstallments=[dict(id='I1',performanceMonth='2026-01',paymentBaseDate='2026-01-01',premium=500,paymentTermsDays=None,reinsurerPaymentTerms={'r1':90}),dict(id='I2',performanceMonth='2026-07',paymentBaseDate='2026-07-01',premium=500,paymentTermsDays=90,reinsurerPaymentTerms={'r1':90})])
    Case.objects.filter(pk=case.pk).update(payload=inst)
    r=call('post','/api/document-generation-log',dict(caseUid=str(case.case_uid),kind='debit',format='docx'));check('backend verifies every Cedant installment day',r.status_code==409 and r.json()['error']=='debit_installment_cedant_terms_required',r.content[:700])
    prop={**minimum,'classOfBusiness':'Property','classCode':'PD','originalPremium':'invalid','policyTo':'unfinished'}
    pc=create(prop);check('Property shares incomplete draft storage',pc.payload['draftInput']['originalPremium']=='invalid' and pc.payload['draftInput']['policyTo']=='unfinished')
    check('Property invalid draft is blocked formally',bool(validate_announce_ready(pc.payload,allow_zero_loss_years=True)))
    raise Rollback()
except Rollback:pass
print(f'{len(checks)}/{len(checks)} CGL QS checks passed; database writes rolled back')
