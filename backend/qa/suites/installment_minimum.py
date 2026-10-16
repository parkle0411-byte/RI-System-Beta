"""Case save must reject an enabled schedule with fewer than two installments."""
import copy, json, os
from django.contrib.auth import get_user_model
from django.db import transaction
from django.test import Client
from audit.models import AuditLog, EntitySnapshot
from cases.models import Case
from cases.draft import normalize_draft, validate_announce_ready, MINIMUM_INSTALLMENTS_MESSAGE as MSG
from personnel.models import Personnel

assert os.environ.get('RI_DISPOSABLE_QA') == 'true'
checks=[]
def check(name, condition):
 assert condition, name
 checks.append(name)
 print('PASS '+name,flush=True)

with transaction.atomic():
 user=get_user_model().objects.create_user(username='zz.installment.minimum',password='QA-Minimum-9!')
 person=Personnel.objects.create(name='QA Minimum',department='reinsurance',role_code='sales',auth_user_id=str(user.pk),account_status='active',created_by='qa',updated_by='qa')
 client=Client(enforce_csrf_checks=True,HTTP_HOST='localhost',raise_request_exception=False)
 client.force_login(user)
 def call(method,body):
  client.get('/api/auth/csrf')
  return getattr(client,method)('/api/cases',data=json.dumps(body),content_type='application/json',HTTP_X_CSRFTOKEN=client.cookies['csrftoken'].value)
 def counts():return Case.objects.count(),AuditLog.objects.count(),EntitySnapshot.objects.count()
 def body(**over):
  return dict(currency='USD',reinsuranceStructure='QS',newOrRenew='New',lossAdvisedDate='2026-10-15',lossRecordYears=0,lossRecord=[],originalPremium=1000,paymentTermsDays=90,**over)
 periods=[dict(id='I1',performanceMonth='2026-01',paymentBaseDate='2026-01-01',premium=400),dict(id='I2',performanceMonth='2026-02',paymentBaseDate='2026-02-01',premium=600)]
 for structure in ['QS','XOL','TREATY']:
  for rows in [[],periods[:1],None,{},'invalid']:
   payload=body(installmentEnabled=True,performanceInstallments=rows)
   payload['reinsuranceStructure']=structure
   before=counts();response=call('post',dict(case=payload))
   check(f'{structure} POST enabled {rows!r} rejected',response.status_code==400 and response.json()['error']=='validation_failed' and MSG in response.json()['errors'])
   check(f'{structure} invalid POST leaves all business records unchanged',counts()==before)
  for enabled,rows in [(True,periods),(True,[{},{}]),(True,[{},{},{}]),(False,[]),(False,periods[:1])]:
   payload=body(installmentEnabled=enabled,performanceInstallments=rows);payload['reinsuranceStructure']=structure
   response=call('post',dict(case=payload))
   check(f'{structure} POST {enabled=} {len(rows)=} accepts draft',response.status_code==201)
   saved=Case.objects.get(case_uid=response.json()['case']['caseUid'])
   check(f'{structure} accepted save retains toggle and row count',saved.payload['installmentEnabled']==enabled and len(saved.payload['performanceInstallments'])==len(rows))
  response=call('post',dict(case=body()));uid=response.json()['case']['caseUid']
  saved=Case.objects.get(case_uid=uid);stored=copy.deepcopy(saved.payload)
  for rows in [[],periods[:1]]:
   before=counts();proposed={**stored,'reinsuranceStructure':structure,'installmentEnabled':True,'performanceInstallments':rows}
   response=call('put',dict(caseUid=uid,rowVersion=saved.row_version,case=proposed))
   saved.refresh_from_db()
   check(f'{structure} PUT with {len(rows)} rows rejected',response.status_code==400 and MSG in response.json()['errors'])
   check(f'{structure} failed PUT preserves payload, version and audit',saved.payload==stored and saved.row_version==1 and counts()==before)
  for enabled,rows in [(True,periods),(False,periods[:1])]:
   proposed={**saved.payload,'installmentEnabled':enabled,'performanceInstallments':rows}
   response=call('put',dict(caseUid=uid,rowVersion=saved.row_version,case=proposed))
   check(f'{structure} correction {enabled=} accepted',response.status_code==200)
   saved.refresh_from_db()
  # Existing legacy records are preserved until an explicit correction is saved.
  legacy={**stored,'reinsuranceStructure':structure,'installmentEnabled':True,'performanceInstallments':periods[:1]}
  Case.objects.filter(pk=saved.pk).update(payload=legacy)
  saved.refresh_from_db();version=saved.row_version;before=counts()
  response=call('put',dict(caseUid=uid,rowVersion=version,case=legacy))
  saved.refresh_from_db()
  check(f'{structure} legacy one-period save refuses without auto-conversion',response.status_code==400 and saved.payload==legacy and saved.row_version==version and counts()==before)
  response=call('put',dict(caseUid=uid,rowVersion=version,case={**legacy,'installmentEnabled':False}))
  check(f'{structure} legacy record can be explicitly turned off',response.status_code==200)
  for rows in [[],periods[:1],periods,[{},{}]]:
   payload=body(installmentEnabled=True,performanceInstallments=rows);payload['reinsuranceStructure']=structure
   original=copy.deepcopy(payload);norm=normalize_draft(payload)
   check(f'{structure} normalizer minimum is two', (MSG in norm['errors'])==(len(rows)<2))
   check(f'{structure} normalization does not mutate input',payload==original)
   issues=validate_announce_ready(norm['value'],allow_zero_loss_years=True)
   check(f'{structure} Announce minimum matches save',any(i['label']==MSG for i in issues)==(len(rows)<2))
 # Ordinary payment defaults and endorsement prohibitions are retained.
 check('ordinary incomplete draft without installments accepted',not normalize_draft({})['errors'])
 for rows in [periods[:1],periods]:
  norm=normalize_draft(body(installmentEnabled=True,performanceInstallments=rows),allow_negative_premiums=True)
  check('endorsement installment prohibition retained','Endorsements must use a single premium settlement; installments are not allowed.' in norm['errors'])
 transaction.set_rollback(True)
print(f'{len(checks)}/{len(checks)} passed; database changes rolled back',flush=True)
