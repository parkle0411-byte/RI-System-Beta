"""Facility field scope, document content, and GA lifecycle on disposable data."""
import copy
import io
import json
import os
import zipfile

from django.contrib.auth import get_user_model
from django.test import Client
from cases.draft import normalize_draft, validate_announce_ready
from cases.facility_rules import CGL_INTEREST, PROPERTY_INTEREST, fixed_interest, legacy_ga_tax_error, prepare_new_draft, property_qs_facility
from cases.great_american_accounting import NAME as GA
from cases.manual_reference import MANUAL_TW_REF_REINSURER as AUW
from cases.models import Case
from cases.placing_word import render
from cases.qs_documents import readiness_issues
from cases.workflow import build_renewal_payload
from cases.endorsement_rules import apply_fixed
from masterdata.models import MasterRecord
from personnel.models import Personnel

assert os.environ.get('RI_DISPOSABLE_QA') == 'true'
checks=[]
def check(name, value):
    assert value, name
    checks.append(name)
    print('PASS '+name, flush=True)

def p(klass='Property', names=(GA,)):
    return dict(reinsuranceStructure='QS',classOfBusiness=klass,classCode='PD' if klass=='Property' else 'GL',
        currency='TWD',newOrRenew='New',type='Fire Facultative Reinsurance',typePrefix='Fire',
        reinsured='Facility QA Cedant',originalInsured='Facility QA Insured',originalInsuredCn='測試被保險人',
        policyFrom='2045-01-01',policyTo='2046-01-01',interest='Old custom interest',
        reinsurers=[dict(name=name,sharePct=50,premium=1000,riCommPct=10,taxPct=1,paymentTermsDays=90) for name in names],
        originalConditions='',originalExclusions='',occupation='Office',construction='Concrete',constructionSelections=['A2 Class'],
        basisOfValuation='',specialAgreement='HISTORICAL FACILITY AGREEMENT',
        limitOfLiability=100000,deductibles='As original',situations=[dict(address='QA Street',postcode='100')],
        sumInsured=[dict(category='Building',amount=100000)],lossAdvisedDate='2044-12-01',lossRecordYears=5,
        originalPremium=1000,riCommPct=5,taxPct=1,paymentTermsDays=90,ae='Facility QA Admin')

for name in (GA, AUW, 'Swiss Re Asia Pte. Ltd., Hong Kong Branch (Facility)'):
    payload=p(names=(name,))
    check('pure Facility property scope '+name, property_qs_facility(payload))
    check('fixed Property interest '+name, fixed_interest(payload)==PROPERTY_INTEREST)
    issues=validate_announce_ready(normalize_draft(payload)['value'])
    check('blank original conditions do not block '+name,not any(i['field']=='originalConditions' for i in issues))
    check('blank interest not a cover requirement '+name,not any(i['code']=='interest_required' for i in readiness_issues({**payload,'interest':''},'cover','x@example.invalid')))
    prepared=prepare_new_draft(payload)
    check('new Facility Property QS defaults ACV '+name,prepared['basisOfValuation']=='Actual Cash Value')
    check('new default does not mutate original '+name,payload['basisOfValuation']=='')
    check('explicit valuation retained '+name,prepare_new_draft({**payload,'basisOfValuation':'Replacement Value'})['basisOfValuation']=='Replacement Value')
    check('cleared existing valuation remains clear '+name,prepare_new_draft(payload,previous=payload)['basisOfValuation']=='')

cgl=p('Commercial General Liability',('Swiss Re Asia Pte. Ltd., Hong Kong Branch (Facility)',))
check('Swiss CGL receives its own fixed interest',fixed_interest(cgl)==CGL_INTEREST and normalize_draft(cgl)['value']['interest']==CGL_INTEREST)
check('CGL does not get Property default',prepare_new_draft(cgl)['basisOfValuation']=='')
mixed=p(names=(GA,'Ordinary Reinsurer'))
check('mixed scope keeps ordinary interest',not fixed_interest(mixed) and normalize_draft(mixed)['value']['interest']=='Old custom interest')
check('mixed scope requires original conditions',any(i['field']=='originalConditions' for i in validate_announce_ready(normalize_draft(mixed)['value'])))
check('mixed scope retains valuation and agreement',not property_qs_facility(mixed) and prepare_new_draft(mixed)['basisOfValuation']=='')
check('empty reinsurer list is not Facility',not fixed_interest(p(names=())) and not property_qs_facility(p(names=())))

initial=p();initial['draftInput']={'reinsurers':copy.deepcopy(initial['reinsurers']),'basisOfValuation':'','interest':'forged'}
prepared=prepare_new_draft(initial)
check('GA tax is zero in canonical and raw draft',prepared['reinsurers'][0]['taxPct']==0 and prepared['draftInput']['reinsurers'][0]['taxPct']==0)
check('Cedant tax unaffected',prepared['taxPct']==1)
old=p();old['twRef']='TEST-OLD';old['reinsurers'][0]['taxPct']=1
renewal=prepare_new_draft(build_renewal_payload(old,'TEST-OLD'))
check('renewal GA tax zero',renewal['reinsurers'][0]['taxPct']==0 and old['reinsurers'][0]['taxPct']==1)
context={'fixed':{},'reinsurers':[{'name':GA,'sharePct':50,'taxPct':1,'riCommPct':10,'paymentTermsDays':90,'foreignBroker':''}]}
endo={'parentTwRef':'TEST-OLD','reinsurers':[{'name':GA,'taxPct':0}]}
apply_fixed(endo,context)
check('endorsement retains source GA tax',prepare_new_draft(endo)['reinsurers'][0]['taxPct']==1)
check('historical GA rate retained on unrelated edit',not legacy_ga_tax_error(old,copy.deepcopy(old)))
changed=copy.deepcopy(old);changed['reinsurers'][0]['taxPct']=2
check('historical GA tax cannot be changed to new nonzero rate',bool(legacy_ga_tax_error(old,changed)))

user=get_user_model().objects.create_user(username='facility.rules.qa',password='Facility-Rules-QA-9!')
person=Personnel.objects.create(name='Facility QA Admin',department='admin',role_code='admin',auth_user_id=str(user.pk),account_status='active',created_by='qa',updated_by='qa')
for kind,name in [('ae',person.name),('class','Property'),('reinsured','Facility QA Cedant'),('reinsurer',GA),('reinsurer','Ordinary Reinsurer')]:
    MasterRecord.objects.get_or_create(entity_type=kind,name=name,defaults={'created_by':'qa','updated_by':'qa'})
client=Client(HTTP_HOST='localhost',raise_request_exception=False)
client.force_login(user)
payload=p();payload['ae']=person.name;payload['ownerPersonnelId']=person.pk;payload['ownerPersonnelName']=person.name
response=client.post('/api/cases',json.dumps({'case':payload}),content_type='application/json')
check('real Case API creates Facility draft',response.status_code==201)
case=Case.objects.get(case_uid=response.json()['case']['caseUid'])
check('real Case API persists GA zero and default valuation',case.payload['reinsurers'][0]['taxPct']==0 and case.payload['basisOfValuation']=='Actual Cash Value')
check('real Case API persists fixed interest and keeps old agreement',case.payload['interest']==PROPERTY_INTEREST and case.payload['specialAgreement']=='HISTORICAL FACILITY AGREEMENT')
edited=copy.deepcopy(case.payload);edited['reinsurers'][0]['taxPct']=7
response=client.put('/api/cases',json.dumps({'caseUid':str(case.case_uid),'rowVersion':case.row_version,'case':edited}),content_type='application/json')
case.refresh_from_db()
check('real Case API fixes attempted GA tax override',response.status_code==200 and case.payload['reinsurers'][0]['taxPct']==0)

# Render real Word and inspect its contents, without changing the source payload.
word_case=p();word_case.update(ae=person.name,placingRulesVersion='placing-qs-20261028-v1',basisOfValuation='Actual Cash Value')
original=copy.deepcopy(word_case)
word=render(word_case,'qa@example.invalid')
with zipfile.ZipFile(io.BytesIO(word)) as doc:
    xml=doc.read('word/document.xml').decode()
check('pure Property Facility Word suppresses legacy special agreement','HISTORICAL FACILITY AGREEMENT' not in xml)
check('pure Property Facility Word uses fixed Interest','The Reinsured' in xml and 'Insurance Interest in the Real and Personal Property' in xml)
check('Word rendering preserves case data',word_case==original)
word_case['reinsurers'].append(dict(name='Ordinary Reinsurer',sharePct=50,premium=1000,riCommPct=10,taxPct=1))
word=render(word_case,'qa@example.invalid')
with zipfile.ZipFile(io.BytesIO(word)) as doc:
    xml=doc.read('word/document.xml').decode()
check('mixed Property Word retains special agreement','HISTORICAL FACILITY AGREEMENT' in xml)
check('mixed Property Word retains ordinary Interest','Old custom interest' in xml)
print('FACILITY_INPUT_RULES: '+str(len(checks))+'/'+str(len(checks))+' passed')
