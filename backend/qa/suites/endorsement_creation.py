"""Owner-approved endorsement/renewal API regression, disposable data only."""
import copy
import json
import os
import uuid
from datetime import date
from django.contrib.auth import get_user_model
from django.test import Client
from django.utils import timezone
from cases.models import Case, CaseDocument, ReferenceSequence
from cases.draft import normalize_draft, validate_announce_ready
from cases.endorsement_rules import period_issues, endorsement_issues, add_months
from cases.manual_reference import MANUAL_TW_REF_REINSURER, AUW_FOREIGN_BROKER
from cases.renewal_premiums import calculate_renewal_premiums
from personnel.models import Personnel

assert os.environ.get('RI_DISPOSABLE_QA') == 'true'
checks=[]
def check(label, condition):
    assert condition, label
    checks.append(label)
    print('PASS '+label, flush=True)

user=get_user_model().objects.create_user(username='qa.endorsement28',password='Synthetic-Flow-47!')
person=Personnel.objects.create(name='QA Endorsement Staff',department='reinsurance',role_code='sales',auth_user_id=str(user.pk),account_status='active',created_by='qa',updated_by='qa')
client=Client(enforce_csrf_checks=True,HTTP_HOST='localhost',raise_request_exception=False)
def call(method,url,body=None):
    client.get('/api/auth/csrf')
    opts={'HTTP_X_CSRFTOKEN':client.cookies['csrftoken'].value}
    if body is not None:opts.update(data=json.dumps(body),content_type='application/json')
    return getattr(client,method)(url,**opts)
assert call('post','/api/auth/login',{'username':user.username,'password':'Synthetic-Flow-47!'}).status_code==200

seq=[0]
def source(structure='QS', klass='QA Engineering', **changes):
    seq[0]+=1
    p=dict(reinsuranceStructure=structure, classOfBusiness=klass, classCode='PD' if klass=='Property' else 'QA',
           ownerPersonnelId=person.pk,ownerPersonnelName=person.name, ae='QA AE',currency='USD',
           newOrRenew='New',typePrefix='Industrial',reinsured='QA Cedant',originalInsured='QA Insured',originalInsuredCn='批單合成測試公司',
           policyFrom='2046-03-01',policyTo='2047-03-01',interest='Buildings',situations=[{'address':'1 Test Road','postcode':'100'}],
           originalPremium=1000,riCommPct=10,taxPct=0,paymentTermsDays=45,
           reinsurers=[dict(name='QA Re A',sharePct=60,premium=800,riCommPct=5,taxPct=0,paymentTermsDays=35,foreignBroker='QA Broker'),
                       dict(name='QA Re B',sharePct=40,premium=700,riCommPct=6,taxPct=0,paymentTermsDays=40,foreignBroker='QA Broker')],
           limitOfLiability=1000000,deductibles='As agreed',reinsuredRetention='As original',basisOfValuation='Replacement Value',originalConditions='As original',
           occupation='Office',construction='Concrete', constructionSelections=['A2 Class'],sumInsured=[{'category':'Building','amount':1000000}],lossAdvisedDate='2046-02-01',lossRecordYears=5)
    p.update(changes)
    n=normalize_draft(p)
    assert not n['errors'], n['errors']
    p=n['value']
    if changes.get('manualTwRef'):p['manualTwRef']=changes['manualTwRef']
    return Case.objects.create(case_kind='original',status='closed',tw_ref=changes.get('manualTwRef') if len(p['reinsurers'])==1 and p['reinsurers'][0]['name']==MANUAL_TW_REF_REINSURER else 'QA-END28-'+str(seq[0]),
        reinsurance_structure=structure, payload=p,owner_personnel=person,created_by='qa',updated_by='qa',
        effective_date=date.fromisoformat(p['policyFrom']),expiration_date=date.fromisoformat(p['policyTo']))

def action(root, name='create_endorsement'):
    root.refresh_from_db()
    r=call('post','/api/case-workflow',{'action':name,'caseUid':str(root.case_uid),'rowVersion':root.row_version})
    assert r.status_code==201, (r.status_code,r.content)
    return Case.objects.get(case_uid=r.json()['case']['caseUid'])

def save(case,p,**extra):
    case.refresh_from_db()
    r=call('put','/api/cases',{'caseUid':str(case.case_uid),'rowVersion':case.row_version,'case':p,**extra})
    case.refresh_from_db()
    return r

def evidence(case):
    names=[r['name'] for r in case.payload['reinsurers']]
    for kind, covered in [('offer',[]),('confirmation',names)]:
        CaseDocument.objects.create(case=case,kind=kind,reinsurers=covered,filename=kind+'.pdf',content_type='application/pdf',byte_size=5,sha256='0'*64,storage_key='qa-'+str(uuid.uuid4()),is_selected=True,uploaded_by='qa')

def announce(case):
    case.refresh_from_db()
    r=call('post','/api/case-announce',{'caseUid':str(case.case_uid),'rowVersion':case.row_version,'confirmed':True,'documentIds':[str(d.pk) for d in CaseDocument.objects.filter(case=case,is_selected=True)]})
    case.refresh_from_db()
    return r

def completed_input(case, premium=0):
    p=copy.deepcopy(case.payload)
    p.update(endoEffectiveDate=p['policyTo'],endoTypes=['Terms'],endoText='Current endorsement',originalPremium=premium)
    for row in p['reinsurers']:row['premium']=premium
    return p

for structure in ('QS','XOL'):
    root=source(structure)
    original=copy.deepcopy(root.payload)
    count=ReferenceSequence.objects.count()
    e=action(root)
    check(structure+' new draft clears delta premium/date/wording without consuming a reference',e.tw_ref is None and e.payload['originalPremium'] is None and not e.payload['endoEffectiveDate'] and not e.payload['endoText'] and all(r['premium'] is None for r in e.payload['reinsurers']) and ReferenceSequence.objects.count()==count)
    document=call('post','/api/document-generation-log',{'caseUid':str(e.case_uid),'kind':'endorsement','format':'docx'})
    check(structure+' formal Endorsement cannot be generated before Announce',document.status_code==409 and document.json()['error']=='endorsement_requires_announce')
    raw=copy.deepcopy(e.payload);raw.update(originalPremium='12..3',endoEffectiveDate='2047-02',endoText='')
    raw['reinsurers'][0]['premium']='-'
    r=save(e,raw,incompleteDraft=True)
    check(structure+' incomplete/invalid raw input is saved',r.status_code==200 and e.payload['draftInput']['originalPremium']=='12..3' and e.payload['draftInput']['reinsurers'][0]['premium']=='-')
    reloaded=call('get','/api/cases?caseUid='+str(e.case_uid)).json()['case']['payload']
    check(structure+' raw values survive reopening',reloaded['draftInput']['endoEffectiveDate']=='2047-02' and reloaded['draftInput']['originalPremium']=='12..3')
    check(structure+' invalid raw input blocks Announce',announce(e).status_code==400 and e.tw_ref is None)
    p=completed_input(e)
    p.pop('draftInput',None)
    p.update(currency='JPY',reinsured='Changed Cedant',riCommPct=99,taxPct=99,paymentTermsDays=99,splitEnabled=True,splitParties=[])
    p['reinsurers'][0].update(name='Changed Re',sharePct=99,foreignBroker='Changed Broker',riCommPct=99,taxPct=99,paymentTermsDays=99)
    r=save(e,p,incompleteDraft=True)
    check(structure+' fixed source fields cannot be overwritten through API',r.status_code==200 and all(e.payload[k]==original[k] for k in ('currency','reinsured','riCommPct','taxPct','paymentTermsDays','splitEnabled','splitParties')) and all(e.payload['reinsurers'][0][k]==original['reinsurers'][0][k] for k in ('name','sharePct','foreignBroker','riCommPct','taxPct','paymentTermsDays')))
    check(structure+' expiry date is an allowed general endorsement effective date',not any(i['field']=='endoEffectiveDate' for i in validate_announce_ready(e.payload)))
    p=completed_input(e);p['policyTo']='2047-04-01'
    r=save(e,p,incompleteDraft=True,endorsementUnlocked=True)
    check(structure+' changing period requires Period type',r.status_code==409 and r.json()['error']=='endorsement_period_locked')
    p['endoTypes']=['Period']
    r=save(e,p,incompleteDraft=True)
    check(structure+' changing period requires explicit unlock',r.status_code==409)
    r=announce(e)
    check(structure+' even zero premium requires current endorsement evidence',r.status_code==400 and r.json()['error']=='documents_not_ready' and 'Endorsement' in r.json()['message'])
    evidence(e)
    r=announce(e)
    check(structure+' zero premium becomes Confirmed on Announce',r.status_code==200 and e.status=='closed' and e.tw_ref.endswith('-E01'))
    from production.calc import build_production_preview,base_month
    preview=build_production_preview([{'id':e.pk,'caseUid':str(e.case_uid),'twRef':e.tw_ref,'status':e.status,'payload':e.payload}],base_month(e.payload),{'USD':1})
    check(structure+' zero premium has no Production rows',not preview['rows'])
    next_e=action(e)
    p=completed_input(next_e);p['endoEffectiveDate']='2047-02-28'
    assert save(next_e,p,incompleteDraft=True).status_code==200
    check(structure+' later endorsement cannot precede the prior effective date',any('preceding' in i['label'] for i in validate_announce_ready(next_e.payload)))
    root.refresh_from_db()
    check(structure+' original source remains unchanged',root.payload==original)

# Month-based limits, inclusive exact limit and leap-month clamping.
for structure in ('QS','XOL'):
    p={'reinsuranceStructure':structure,'policyFrom':'2026-08-31','policyTo':'2028-02-29'}
    check(structure+' 18 calendar months includes the clamped leap-month limit',not period_issues(p))
    check(structure+' a day beyond 18 months is rejected',bool(period_issues({**p,'policyTo':'2028-03-01'})))

# Zero Period extension, automatic daily average, actual leap-year duration.
root=source(originalPremium=109800,reinsurers=[dict(name='QA Re A',sharePct=60,premium=87840,riCommPct=5,taxPct=0,paymentTermsDays=35),dict(name='QA Re B',sharePct=40,premium=76860,riCommPct=6,taxPct=0,paymentTermsDays=40)])
e=action(root);p=completed_input(e);p.update(endoTypes=['Period'],policyTo='2047-09-01')
assert save(e,p,incompleteDraft=True,endorsementUnlocked=True).status_code==200
evidence(e);assert announce(e).status_code==200
renewal=action(e,'create_renewal')
check('Period renewal starts at latest expiry and defaults to one year',renewal.payload['policyFrom']=='2047-09-01' and renewal.payload['policyTo']=='2048-09-01')
check('full-period average uses 549 source days and 366 renewal days',renewal.payload['originalPremium']==73200 and [r['premium'] for r in renewal.payload['reinsurers']]==[58560,51240])
nonannual=source(policyTo='2047-09-01',originalPremium=109800)
nonannual_renewal=action(nonannual,'create_renewal')
check('nonannual Original without Period renews from expiry for one calendar year',nonannual_renewal.payload['policyFrom']=='2047-09-01' and nonannual_renewal.payload['policyTo']=='2048-09-01' and nonannual_renewal.payload['originalPremium']==73200)
p=copy.deepcopy(renewal.payload);p['originalPremium']=50000;p['reinsurers'][0]['premium']=33333
assert save(renewal,p).status_code==200
p=copy.deepcopy(renewal.payload);p['policyTo']='2048-03-01'
assert save(renewal,p).status_code==200
check('period change retains per-field manual premiums and recalculates other premiums',renewal.payload['originalPremium']==50000 and renewal.payload['reinsurers'][0]['premium']==33333 and renewal.payload['reinsurers'][1]['premium']==25480)
check('manual premium flags persist on reopening',set(call('get','/api/cases?caseUid='+str(renewal.case_uid)).json()['case']['payload']['renewalPremiumManual'])=={'originalPremium','reinsurers.0.premium'})

root=source(originalPremium=None)
renewal=action(root,'create_renewal')
check('missing source amount still creates a renewal Draft with only affected premium blank',renewal.status=='draft' and renewal.payload['originalPremium'] is None and renewal.payload['reinsurers'][0]['premium'] is not None and renewal.payload['renewalPremiumIssues'])

# Pure and mixed AUW use one shared E suffix; no manual reference on new drafts.
for pure in (True,False):
    auw=dict(name=MANUAL_TW_REF_REINSURER,sharePct=100 if pure else 40,premium=700,riCommPct=5,taxPct=0,paymentTermsDays=120,foreignBroker=AUW_FOREIGN_BROKER)
    rows=[auw] if pure else [dict(name='QA Re A',sharePct=60,premium=800,riCommPct=5,taxPct=0,paymentTermsDays=35),auw]
    root=source(klass='Property',reinsurers=rows,manualTwRef='QA-AUW28-'+str(seq[0]+1))
    e=action(root)
    check(('pure' if pure else 'mixed')+' AUW draft needs no manual endorsement number',not e.payload.get('manualTwRef') and e.tw_ref is None)
    assert save(e,completed_input(e),incompleteDraft=True).status_code==200
    evidence(e);r=announce(e)
    check(('pure' if pure else 'mixed')+' AUW derives matching formal references',r.status_code==200 and e.tw_ref==root.tw_ref+'-E01' and e.payload['manualTwRef']==root.payload['manualTwRef']+'-E01')
    later=action(e);assert save(later,completed_input(later),incompleteDraft=True).status_code==200
    evidence(later);assert announce(later).status_code==200
    check(('pure' if pure else 'mixed')+' AUW subsequent number is derived from Original',later.tw_ref==root.tw_ref+'-E02' and later.payload['manualTwRef']==root.payload['manualTwRef']+'-E02')

swiss='Swiss Re Asia Pte. Ltd., Hong Kong Branch (Facility)'
root=source(klass='Property',reinsurers=[dict(name=swiss,sharePct=60,premium=800,riCommPct=5,taxPct=0,paymentTermsDays=90),dict(name='QA Re B',sharePct=40,premium=700,riCommPct=6,taxPct=0,paymentTermsDays=40)])
e=action(root);p=completed_input(e,10);p['reinsurers'][0]['premium']=-10;p['reinsurers'][1]['premium']=20
assert save(e,p,incompleteDraft=True).status_code==200
evidence(e);r=announce(e)
check('Swiss Property accepts mixed per-reinsurer directions and remains Announced',r.status_code==200 and e.status=='posted')
check('Announce immediately creates independent premium ledgers',len(e.payload['transactions'])==6)

root=source();e=action(root);p=completed_input(e);p['reinsurers'][0]['premium']=20;p['reinsurers'][1]['premium']=-20
assert save(e,p,incompleteDraft=True).status_code==200
evidence(e);assert announce(e).status_code==200
check('net-zero mixed nonzero premium does not use the all-zero exception',e.status=='posted')
preview=build_production_preview([{'id':e.pk,'caseUid':str(e.case_uid),'twRef':e.tw_ref,'status':e.status,'payload':e.payload}],base_month(e.payload),{'USD':1})
check('mixed nonzero premiums retain Production recognition rows',bool(preview['rows']))

retired=Personnel.objects.create(name='Renamed Historical Credit',department='business_1',role_code='viewer',is_active=False,is_split_eligible=False,deactivated_by='qa',deactivated_at=timezone.now(),created_by='qa',updated_by='qa')
parties=[{'personnelId':person.pk,'name':person.name,'pct':70},{'personnelId':retired.pk,'name':'Historical Credit Snapshot','pct':30}]
root=source(splitEnabled=True,splitParties=parties);e=action(root)
assert save(e,completed_input(e),incompleteDraft=True).status_code==200
evidence(e);r=announce(e)
check('locked source Performance Split retains historical identities and names',r.status_code==200 and e.payload['splitParties']==root.payload['splitParties'])

# Failed corrections must precede all insured-directory and ledger writes.
root=source();e=action(root);p=completed_input(e,10)
assert save(e,p,incompleteDraft=True).status_code==200
evidence(e);assert announce(e).status_code==200
before=copy.deepcopy(e.payload);version=e.row_version;master=e.insured_master;old_name=master.name
p=copy.deepcopy(e.payload);p.update(endoTypes=['Period'],policyTo='2047-10-01',originalInsuredCn='不得儲存的期間錯誤名稱')
r=save(e,p,endorsementUnlocked=True,reason='QA invalid period must be atomic');master.refresh_from_db()
check('invalid announced correction changes neither Case nor insured master',r.status_code==400 and e.row_version==version and e.payload==before and master.name==old_name)

auw=dict(name=MANUAL_TW_REF_REINSURER,sharePct=100,premium=700,riCommPct=5,taxPct=0,paymentTermsDays=120)
root=source(klass='Property',reinsurers=[auw],manualTwRef='QA-AUW-SOURCE-BEFORE-LEGACY')
root.tw_ref='QA-SYSTEM-ONLY-AUW-LEGACY';root.payload.update(manualTwRef='',twRefSource='system');root.save()
e=action(root);assert save(e,completed_input(e),incompleteDraft=True).status_code==200
evidence(e);r=announce(e)
check('missing historical AUW base is not invented from its system reference',r.status_code==409 and r.json()['error']=='source_auw_reference_required' and e.tw_ref is None)

root=source();e=action(root);assert save(e,completed_input(e),incompleteDraft=True).status_code==200
evidence(e);root.status='reversed';root.save(update_fields=['status'])
r=announce(e)
check('source reversed after Draft creation cannot be used for Announce',r.status_code==409 and e.tw_ref is None and e.status=='draft')

root=source();prior=action(root);assert save(prior,completed_input(prior),incompleteDraft=True).status_code==200
evidence(prior);assert announce(prior).status_code==200
e=action(prior);assert save(e,completed_input(e),incompleteDraft=True).status_code==200
evidence(e);prior.status='reversed';prior.save(update_fields=['status'])
r=announce(e)
check('a reversed preceding endorsement cannot be skipped to its root',r.status_code==409 and e.tw_ref is None)

root=source();e=action(root);assert save(e,completed_input(e),incompleteDraft=True).status_code==200
evidence(e)
newer=Case.objects.create(case_kind='endorsement',parent_case=root,status='draft',payload=copy.deepcopy(e.payload),reinsurance_structure='QS',currency='USD',owner_personnel=person,created_by='qa',updated_by='qa')
r=announce(e)
check('restored older Draft cannot announce ahead of a newer Draft',r.status_code==409 and r.json()['error']=='latest_endorsement_required' and e.tw_ref is None)

print(str(len(checks))+'/'+str(len(checks))+' endorsement creation checks passed',flush=True)
