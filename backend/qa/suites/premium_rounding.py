"""Owner-confirmed precision and data conversion. Disposable DB only for API checks."""
import copy,io,json
from unittest.mock import patch
from django.db import transaction
from django.core.management import call_command
from rest_framework.test import APIRequestFactory
from cases.calc.accounting import calc_legs_for_reinsurer,build_premium_transactions
from cases.calc.payment_terms import premium_installment_plan,build_payment_schedule,allocate
from cases.calc.premium_money import premium_money,premium_input_errors
from cases.calc.totals import case_totals
from cases.draft import normalize_draft
from cases.premium_rounding import converted,has_history
from cases.models import Case
from cases.views import CasesView
from personnel.models import Personnel

checks=[]
def check(name,ok):
 checks.append((name,bool(ok)))
 assert ok,name

def sample(currency='TWD'):
 return dict(currency=currency,originalPremium=1001,riCommPct=12.5,taxPct=1.5,policyFrom='2026-01-01',policyTo='2027-01-01',classOfBusiness='Property',reinsuranceStructure='QS',originalInsured='Synthetic insured',reinsured='Synthetic cedant',paymentTermsDays=90,lossAdvisedDate='2026-01-01',lossRecordYears=5,twRef='ROUND-SAMPLE',reinsurers=[dict(name='Synthetic RI',sharePct=33.33,premium=1001,riCommPct=5,taxPct=0,paymentTermsDays=90)])
for currency,expected in [('TWD',(334,42,5,287)),('USD',(333.63,41.70,5,286.93))]:
 c=sample(currency);legs=calc_legs_for_reinsurer(c,c['reinsurers'][0]);check(currency+' confirmed example',tuple(legs[k] for k in ('cp','ri','tax','leg1'))==expected)
c=sample('USD');c['originalPremium']=1.005;c['reinsurers'][0]['sharePct']=50;check('USD starts from rounded original premium',calc_legs_for_reinsurer(c,c['reinsurers'][0])['cp']==.51)
c=sample();c.update(originalPremium=999,riCommPct=15,taxPct=1);c['reinsurers'][0]['sharePct']=10;legs=calc_legs_for_reinsurer(c,c['reinsurers'][0]);check('initial TWD999 example',tuple(legs[k] for k in ('cp','ri','tax','leg1'))==(100,15,1,84))
for currency in ['USD','TWD']:
 for periods in [2,3,6,24,60]:
  c=sample(currency);c['installmentEnabled']=True;c['performanceInstallments']=[dict(id='i'+str(i),premium='',ratio=1,performanceMonth='2026-01',paymentBaseDate='2026-01-01',paymentTermsDays=90,reinsurerPaymentTerms={'r1':90,'r2':90}) for i in range(periods)];c['reinsurers']*=2
  c['reinsurers']=[{**r,'sharePct':50} for r in c['reinsurers']]
  plan=premium_installment_plan(c);schedule=[r['amount'] for r in build_payment_schedule(c)['items'] if r['partyType']=='cedant'];t1=[premium_money(sum(r['leg1'] for r in p['amounts']),c) for p in plan]
  check(currency+str(periods)+' payment schedule equals period T1',schedule==t1)
  check(currency+str(periods)+' periods foot to total',premium_money(sum(t1),c)==case_totals(c)['leg1'])
  check(currency+str(periods)+' valid precision',all(premium_money(v,c)==v for v in t1))
c=sample('USD');c.update(originalPremium=.03,riCommPct=0,taxPct=0);check('small positive allocation never negative',allocate(.03,[{'weight':1}]*6,c)==[0,0,0,.01,.01,.01])
legacy_rounding={'currency':'TWD','premiumRounding':'legacy-cents'}
check('protected legacy keeps historical allocation tail',allocate(.03,[{'weight':1}]*6,legacy_rounding)==[-.02,.01,.01,.01,.01,.01])
for path in ['original','reinsurer','instalment']:
 c=sample();
 if path=='original':c['originalPremium']=999.5
 elif path=='reinsurer':c['reinsurers'][0]['premium']=999.5
 else:c['performanceInstallments']=[dict(premium=999.5)]
 check(path+' decimals rejected',bool(premium_input_errors(c)))
 check(path+' normalize validation rejects',any('whole number' in x for x in normalize_draft(c)['errors']))
 c['currency']='USD';check(path+' USD decimals allowed',not premium_input_errors(c))
legacy=sample();legacy['originalPremium']=999.5;legacy['paymentEntries']=[{'amount':1}];legacy['reinsurers'][0]['premium']=999.5;before=copy.deepcopy(legacy);after=converted(legacy)
check('protected legacy retains every value', {k:v for k,v in after.items() if k!='premiumRounding'}==before and legacy==before)
check('protected legacy uses cents',after['premiumRounding']=='legacy-cents' and premium_money(1.25,after)==1.25)
check('legacy unchanged fractional input allowed',not premium_input_errors(after,after))
changed=copy.deepcopy(after);changed['originalPremium']=998.5;check('legacy cannot introduce different fraction',bool(premium_input_errors(changed,after)))
for history in [{'facilityAccounting':{'history':[{'confirmed':False}]}},{'swissAccounting':{'confirmations':{'old':{'confirmed':False}}}},{'transactions':[{'settlement':'settled'}]}]:
 c=sample();c.update(history);check('historical '+str(list(history))+' protected',converted(c)['premiumRounding']=='legacy-cents')
c=sample();c['originalPremium']=999.5;c['transactions']=build_premium_transactions({**c,'premiumRounding':'legacy-cents'});before=copy.deepcopy(c);out=converted(c);check('eligible legacy input rounds once',out['originalPremium']==1000 and c==before);check('eligible transactions recalculate',out['transactions']==build_premium_transactions(out));check('conversion idempotent',converted(out)==out)
class Rollback(Exception):pass
try:
 with transaction.atomic():
  person=Personnel.objects.create(name='ROUND QA',department='admin',role_code='admin',created_by='qa',updated_by='qa')
  factory=APIRequestFactory();view=CasesView.as_view()
  def request(method,data):
   with patch('ri_system.authz.load_principal',return_value=person),patch('ri_system.authz.is_supervisor',return_value=False):return view(getattr(factory,method)('/api/cases',data,format='json'))
  for path in ['original','reinsurer','instalment']:
   c=sample();c.pop('twRef',None)
   if path=='original':c['originalPremium']=1.5
   elif path=='reinsurer':c['reinsurers'][0]['premium']=1.5
   else:c.update(installmentEnabled=True,performanceInstallments=[dict(premium=1.5),dict(premium=1)])
   response=request('post',{'case':c});check('POST rejects '+path,response.status_code==400 and 'whole number' in str(response.data))
  c=sample();c.pop('twRef',None);response=request('post',{'case':c});check('POST valid integer',response.status_code==201)
  case=Case.objects.get(case_uid=response.data['case']['caseUid']);check('server-owned version set',case.payload['premiumRounding']=='currency-stepwise-v1')
  c=copy.deepcopy(case.payload);c['originalPremium']=1.5;c['premiumRounding']='legacy-cents';response=request('put',{'caseUid':str(case.case_uid),'rowVersion':case.row_version,'case':c});check('PUT cannot bypass integer via marker',response.status_code==400 and 'whole number' in str(response.data))
  case=Case.objects.create(case_kind='original',status='draft',currency='TWD',payload=before,created_by='qa',updated_by='qa')
  sink=io.StringIO();call_command('convert_twd_premiums',stdout=sink);case.refresh_from_db();check('management dry run no writes',case.payload==before)
  call_command('convert_twd_premiums',apply=True,stdout=sink);case.refresh_from_db();check('management applies eligible conversion',case.payload['originalPremium']==1000)
  version=case.row_version;call_command('convert_twd_premiums',apply=True,stdout=sink);case.refresh_from_db();check('management conversion idempotent',case.row_version==version)
  raise Rollback
except Rollback:pass
for name,ok in checks:print(('PASS ' if ok else 'FAIL ')+name)
print(f'{len(checks)}/{len(checks)} passed')
