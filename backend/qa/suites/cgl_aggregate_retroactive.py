import copy,json,uuid,os,io,zipfile
from pathlib import Path
from django.db import transaction
from django.test import Client
from django.contrib.auth import get_user_model
from personnel.models import Personnel
from cases.models import Case
from cases.draft import normalize_draft,validate_announce_ready
from cases import draft_input
from cases.cgl_information import *
from cases import placing_rules
assert os.environ.get('RI_DISPOSABLE_QA')=='true'
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
# Complete fixtures include the newly confirmed QS formal fields.
_legacy_ready = ready
def ready():
    p = _legacy_ready()
    p.setdefault('originalInsuredCn', 'QS QA CN')
    p.setdefault('riCommPct', 0)
    p.setdefault('taxPct', 0)
    return p

checks=[]
def check(name,ok,detail=''):
 checks.append({'name':name,'passed':bool(ok),'detail':str(detail)[:1200] if not ok else ''});print(('PASS ' if ok else 'FAIL ')+name+(' '+str(detail)[:400] if not ok else ''),flush=True)
class Rollback(Exception):pass
try:
 with transaction.atomic():
  owner=Personnel.objects.create(name='CGL Update QA',department='admin',role_code='admin',account_status='active',email='qa@example.invalid',created_by='qa',updated_by='qa')
  user=get_user_model().objects.create_user(username='cgl.update.qa',password='Cgl-Update-QA-9!');owner.auth_user_id=str(user.pk);owner.save()
  client=Client(HTTP_HOST='localhost',raise_request_exception=False);client.force_login(user)
  def call(method,path,body):return getattr(client,method)(path,data=json.dumps(body),content_type='application/json')
  base=ready();base['ownerPersonnelId']=owner.pk
  for structure in ('QS','XOL'):
   for swiss in (False,True):
    if swiss and structure=='XOL':continue
    p=copy.deepcopy(base);p['reinsuranceStructure']=structure;p['underlyingLimits']='USD 500,000'
    if swiss:p['reinsurers'][0]['name']='Swiss Re Asia Pte. Ltd., Hong Kong Branch (Facility)'
    for raw in (None,'',0,2000000):
     p['aggregateLimit']=raw;n=normalize_draft(p)
     check(f'{structure} Swiss={swiss} aggregate default {raw!r}',not n['errors'] and n['value']['aggregateLimit']==(raw or 1000000),n)
    p['aggregateLimit']=2000000;p['cglAggregateMode']='manual';p['limitOfLiability']=3000000
    check(f'{structure} custom aggregate retained',normalize_draft(p)['value']['aggregateLimit']==2000000)
    p['cglAggregateMode']='auto';check(f'{structure} auto follows changed limit',normalize_draft(p)['value']['aggregateLimit']==3000000)
    for raw in (None,'',0,-1,'unfinished'):
     q={**p,'aggregateLimit':raw,'cglAggregateMode':'manual'};n=draft_input.normalize(q)
     check(f'{structure} incomplete aggregate draft {raw!r}',not n['errors'] and draft_input.input_for(n['value'])['aggregateLimit']==raw,n)
     clean,errors=draft_input.validate(n['value']);issues=errors or validate_announce_ready(clean)
     check(f'{structure} formal blocks aggregate {raw!r}',bool(issues),issues)
  info={**base['cglInformation'],'policyForm':'Claims-Made Form','extendedReportingApplies':'notApplicable','retroactiveDate':'2002-09-01'}
  n=normalize_draft({**base,'cglInformation':info});check('legacy date becomes one row without required description',n['value']['cglInformation']['retroactiveDates']==[{'date':'2002-09-01','description':''}] and not information_issues(n['value']),n)
  rows=[{'date':'2018-09-01','description':'limit USD 5,000,000'},{'date':'2002-09-01','description':'limit USD 1,000,000'},{'date':'2018-03-01','description':'Usang Holding Company'},{'date':'2009-09-01','description':'limit USD 2,000,000'}]
  info['retroactiveDates']=rows;n=normalize_draft({**base,'cglInformation':info});clean=n['value']
  check('full date ascending including same-year March and September',[r['date'] for r in clean['cglInformation']['retroactiveDates']]==['2002-09-01','2009-09-01','2018-03-01','2018-09-01'])
  expected='(September 01, 2002 in respect of limit USD 1,000,000)\n(September 01, 2009 in respect of limit USD 2,000,000)\n(March 01, 2018 in respect of Usang Holding Company)\n(September 01, 2018 in respect of limit USD 5,000,000)'
  check('exact sorted multiline document wording',retroactive_text(clean['cglInformation'])==expected,retroactive_text(clean['cglInformation']))
  one={**info,'retroactiveDates':[{'date':'2002-09-01','description':''}]};check('single date has no parentheses',retroactive_text(one)=='September 01, 2002')
  for label,entries in [('missing',[]),('duplicate',[rows[0],rows[0]]),('description',[rows[0],{'date':'2002-09-01','description':''}]),('bad date',[{'date':'2002-02-30','description':''}])]:
   p={**base,'cglInformation':{**info,'retroactiveDates':entries}};n=draft_input.normalize(p)
   check(label+' retains incomplete draft',not n['errors'] and draft_input.input_for(n['value'])['cglInformation']['retroactiveDates']==entries,n)
   clean,errors=draft_input.validate(n['value']);issues=errors or information_issues(clean)
   check(label+' blocked at formal validation',bool(issues),issues)
  occurrence={**base,'cglInformation':{**info,'policyForm':'Occurrence Form'}};n=normalize_draft(occurrence)
  check('Occurrence clears all dates and descriptions',n['value']['cglInformation']['retroactiveDates']==[] and n['value']['cglInformation']['retroactiveDate']=='' and retroactive_text(n['value']['cglInformation'])=='')
  # Exercise actual save/reopen and document endpoints, not only helper functions.
  p={**base,'cglInformation':{**info,'insuredBusinessSelections':['Manufacturer']}};p['cglInformation']['estimatedTurnover']=[{'region':'USA/Canada','currency':'USD','amount':1000000}];res=call('post','/api/cases',{'case':p,'incompleteDraft':True,'draftKey':str(uuid.uuid4())});check('API incomplete draft saves',res.status_code==201,res.content)
  if res.status_code==201:
   c=Case.objects.get(case_uid=res.json()['case']['caseUid']);raw=copy.deepcopy(c.payload);check('API round trip retains all four rows',len(draft_input.input_for(raw)['cglInformation']['retroactiveDates'])==4)
   completed,errors=draft_input.validate(raw);check('complete raw Draft normalizes',not errors,errors)
   completed.pop('draftInput',None);completed['aeEmail']='qa@example.invalid';Case.objects.filter(pk=c.pk).update(payload=completed,status='posted',tw_ref='QA-CGL-UPD-001')
   res=call('post','/api/document-generation-log',{'caseUid':str(c.case_uid),'kind':'cover','format':'docx'});check('Cover authorization accepts four valid dates',res.status_code==204,res.content)
   for bad in (0,None):
    Case.objects.filter(pk=c.pk).update(payload={**completed,'aggregateLimit':bad,'cglAggregateMode':'manual'})
    for kind in ('cover','debit'):
     res=call('post','/api/document-generation-log',{'caseUid':str(c.case_uid),'kind':kind,'format':'docx'});check(f'{kind} authorizes no invalid aggregate {bad}',res.status_code==409 and res.json().get('error')=='aggregate_limit_required',res.content)
   bad=copy.deepcopy(completed);bad['cglInformation']['retroactiveDates']=[rows[0],rows[0]];Case.objects.filter(pk=c.pk).update(payload=bad)
   res=call('post','/api/document-generation-log',{'caseUid':str(c.case_uid),'kind':'cover','format':'docx'});check('Cover authorization blocks duplicate stored dates',res.status_code==409,res.content)
  # Placing Slip text is generated by the actual Word renderer.
  from cases.placing_word import render
  p=copy.deepcopy(base);placing_rules.promote(p);p['cglInformation']={**info,'insuredBusinessSelections':['Manufacturer']};p=normalize_draft(p)['value']
  data=render(p,'qa@example.invalid');z=zipfile.ZipFile(io.BytesIO(data));xml=z.read('word/document.xml').decode();check('Placing Word has all four sorted dates',all(x in xml for x in expected.split('\n')) and xml.index('September 01, 2002') < xml.index('March 01, 2018') < xml.index('September 01, 2018'),xml[-300:])
  for klass in ('Property','Engineering'):
   p={**base,'classOfBusiness':klass,'aggregateLimit':0};n=normalize_draft(p);check('non CGL aggregate unchanged '+klass,n['value']['aggregateLimit']==0 and 'cglAggregateMode' not in n['value'])
  raise Rollback()
except Rollback:pass
print('RESULT '+json.dumps({'passed':all(x['passed'] for x in checks),'checks':checks},ensure_ascii=False));assert all(x['passed'] for x in checks)
