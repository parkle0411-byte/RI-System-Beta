"""Property-only Allianz selection: public APIs, atomicity and financial scope."""
import copy,json,os
from django.contrib.auth import get_user_model
from django.db import transaction
from django.test import Client
from audit.models import AuditLog,EntitySnapshot
from cases.models import Case
from personnel.models import Personnel
from cases.allianz_accounting import NAME,target,applies,selection_issues,claim_is_allianz
from cases.calc.payment_terms import build_payment_schedule
from cases.draft import normalize_draft,validate_announce_ready
from cases.payment_policy import kind
from cases.resolve import payment_terms_signature
assert os.environ.get('RI_DISPOSABLE_QA')=='true'
checks=[]
def check(label,ok,extra=None):
 assert ok,(label,extra)
 checks.append(label);print('PASS '+label,flush=True)
def raw(klass='Property',name=NAME):
 return {'classOfBusiness':klass,'reinsuranceStructure':'QS','currency':'TWD','originalInsured':'Scope QA insured',
  'reinsured':'Scope QA Cedant','policyFrom':'2026-01-01','policyTo':'2027-01-01','originalPremium':1000,
  'riCommPct':0,'taxPct':0,'paymentTermsDays':30,'lossAdvisedDate':'2026-01-01','lossRecordYears':5,
  'reinsurers':[{'name':name,'sharePct':100,'premium':800,'riCommPct':0,'taxPct':0,'paymentTermsDays':45}]}
for klass in ('Property',' property ','PROPERTY'):
 p=raw(klass);check('Property name normalization '+klass,target(p,NAME.lower()) and applies(p) and not selection_issues(p))
 norm=normalize_draft(p);check('valid Property draft keeps fixed90 '+klass,not norm['errors'] and norm['value']['reinsurers'][0]['paymentTermsDays']==90,norm['errors'])
 r=next(i for i in build_payment_schedule(p)['items'] if i['partyType']=='reinsurer')
 check('Property calendar remains80/90 '+klass,r.get('allianzFacility') and r['dueDate']=='2026-04-21' and r['contractDueDate']=='2026-05-01')
for klass in ('CGL','Marine','Engineering','',None):
 p=raw(klass);before=copy.deepcopy(p)
 check('reject non-Property selection '+str(klass),not applies(p) and not target(p,NAME) and len(selection_issues(p))==1 and kind(p,NAME)=='')
 check('normalizer rejects non-Property '+str(klass),any('available only for Property' in e for e in normalize_draft(p)['errors']))
 check('Announce validation rejects historical invalid selection '+str(klass),any(i['field']=='reinsurers.0.name' and 'only for Property' in i['label'] for i in validate_announce_ready(p)))
 check('non-Property schedule has no Allianz flags '+str(klass),not any(i.get('allianzFacility') or i.get('allianzCase') for i in build_payment_schedule(p)['items']) and p==before)
for name in (NAME.replace(' (Facility)',''),'Allianz Other (Facility)'):
 p=raw('Marine',name);check('other Allianz identity stays outside restriction '+name,not target(p,name) and not selection_issues(p) and not normalize_draft(p)['errors'])
p=raw();p['reinsurers'].append({'name':'Ordinary scope QA','paymentTermsDays':50,'premium':50,'sharePct':10})
sig=payment_terms_signature(p)
check('mixed Property case preserves independent ordinary terms',sig['reinsurers'][0]['paymentTermsDays']==90 and sig['reinsurers'][1]['paymentTermsDays']==50)
p=raw('Marine');p['classCode']='PAR'
check('Property Class Code cannot bypass wrong Class',not target(p,NAME) and bool(selection_issues(p)))
t={'source':'claim','txNo':'QA-C1-P1-R1-T1','reinsurerIdx':0,'allianzFacility':True}
check('claim marker cannot bypass non-Property',claim_is_allianz(raw(),t) and not claim_is_allianz(raw('Marine'),t))
check('frozen non-Property claim cannot inherit Property root scope',not claim_is_allianz(raw(),{**t,'splitSource':{'classOfBusiness':'Marine','reinsurers':[{'name':NAME}]}}))
check('Property frozen claim keeps its own applicable scope',claim_is_allianz(raw('Marine'),{**t,'splitSource':{'classOfBusiness':'Property','reinsurers':[{'name':NAME}]}}))

with transaction.atomic():
 u=get_user_model().objects.create_user(username='allianz.scope.qa',password='Scope-QA-only-9!')
 person=Personnel.objects.create(name='Allianz Scope QA',department='reinsurance',role_code='sales',auth_user_id=str(u.pk),account_status='active',created_by='qa',updated_by='qa')
 c=Client(enforce_csrf_checks=True,HTTP_HOST='localhost');c.force_login(u);c.get('/api/auth/csrf')
 def call(method,url,body):return getattr(c,method)(url,data=json.dumps(body),content_type='application/json',HTTP_X_CSRFTOKEN=c.cookies['csrftoken'].value)
 def counts():return (Case.objects.count(),AuditLog.objects.count(),EntitySnapshot.objects.count())
 before=counts();res=call('post','/api/cases',{'case':raw('CGL')})
 check('public create API rejects non-Property',res.status_code==400 and res.json()['error']=='validation_failed' and 'only for Property' in res.json()['message'],res.content[:300])
 check('rejected create writes no cases or history',counts()==before)
 res=call('post','/api/cases',{'case':raw()});check('public create API accepts Property',res.status_code==201,res.content[:300])
 uid=res.json()['case']['caseUid'];case=Case.objects.get(case_uid=uid);before=(case.row_version,copy.deepcopy(case.payload),counts())
 res=call('put','/api/cases',{'caseUid':uid,'rowVersion':case.row_version,'case':raw('Marine')})
 check('edit API cannot switch Class while retaining Allianz',res.status_code==400 and 'only for Property' in res.json()['message'],res.content[:300])
 case.refresh_from_db();check('rejected Class change preserves all data/version/history',(case.row_version,case.payload,counts())==before)
 res=call('put','/api/cases',{'caseUid':uid,'rowVersion':case.row_version,'case':raw('Marine',NAME.replace(' (Facility)',''))})
 check('remove restricted Facility before changing Class is allowed',res.status_code==200,res.content[:300])
 case.refresh_from_db();check('ordinary Allianz remains editable outside Property',case.payload['classOfBusiness']=='Marine' and case.payload['reinsurers'][0]['paymentTermsDays']==45)
 legacy=Case.objects.create(status='draft',payload={**raw('Marine'),'ownerPersonnelId':person.pk},currency='TWD',owner_personnel_id=person.pk,created_by='qa',updated_by='qa')
 before=(legacy.row_version,copy.deepcopy(legacy.payload),counts())
 res=call('post','/api/case-announce',{'caseUid':str(legacy.case_uid),'rowVersion':legacy.row_version,'confirmed':True,'documentIds':[]})
 check('Announce API rejects preexisting invalid combination',res.status_code==400 and any('only for Property' in i['label'] for i in res.json().get('issues',[])),res.content[:300])
 legacy.refresh_from_db();check('blocked Announce preserves draft and version',legacy.status=='draft' and (legacy.row_version,legacy.payload,counts())==before)
 legacy.status='posted';legacy.tw_ref='AL-SCOPE-INVALID';legacy.save();before=counts()
 for doc_kind in ('cover','debit','endorsement'):
  res=call('post','/api/document-generation-log',{'caseUid':str(legacy.case_uid),'kind':doc_kind,'format':'docx','case':raw()})
  check('document API validates saved Class for '+doc_kind,res.status_code==409 and res.json()['error']=='allianz_property_required',res.content[:300])
 check('blocked document operations write no history',counts()==before)
 res=call('post','/api/accounting',{'action':'complete_payment_terms','caseUid':str(legacy.case_uid),'rowVersion':legacy.row_version,'partyKey':'r1','days':120,'reason':'QA bypass attempt'})
 check('accounting terms endpoint rejects invalid historical selection',res.status_code==409 and res.json()['error']=='allianz_property_required',res.content[:300])
 transaction.set_rollback(True)
print(str(len(checks))+'/'+str(len(checks))+' Allianz Property scope checks passed; test writes rolled back',flush=True)
