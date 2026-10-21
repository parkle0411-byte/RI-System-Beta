"""Saved-case currency determines Debit Note availability; all test writes roll back."""
import copy,json,os
from django.contrib.auth import get_user_model
from django.db import transaction
from django.test import Client
from audit.models import AuditLog,EntitySnapshot
from cases.models import Case
from cases.draft import normalize_draft,validate_announce_ready
from personnel.models import Personnel

assert os.environ.get('RI_DISPOSABLE_QA')=='true'
MSG='Debit Note generation is available only for USD and TWD. The receiving bank account for other currencies is pending confirmation.'
checks=[]
def check(name,ok):
 assert ok,name
 checks.append(name);print('PASS '+name,flush=True)

with transaction.atomic():
 user=get_user_model().objects.create_user(username='zz.debit.bank.currency',password='QA-Bank-Currency-9!')
 person=Personnel.objects.create(name='QA Bank Currency',department='reinsurance',role_code='sales',auth_user_id=str(user.pk),account_status='active',created_by='qa',updated_by='qa')
 client=Client(enforce_csrf_checks=True,HTTP_HOST='localhost',raise_request_exception=False);client.force_login(user)
 def call(path,body):
  client.get('/api/auth/csrf')
  return client.post(path,data=json.dumps(body),content_type='application/json',HTTP_X_CSRFTOKEN=client.cookies['csrftoken'].value)
 base=dict(currency='USD',reinsuranceStructure='QS',ae='QA Bank Currency',aeEmail='qa@example.invalid',reinsured='Cedant',originalInsured='Insured',type='Property',policyFrom='2026-01-01',policyTo='2027-01-01',interest='Buildings',limitOfLiability=1000,underlyingLimits='Primary',deductibles='10%',reinsuredRetention='Nil',originalPremium=1000,paymentTermsDays=90,reinsurers=[dict(name='RI A',sharePct=100,paymentTermsDays=90)],situations=[dict(address='Risk A',postcode='100')],sumInsured=[dict(category='Building',amount=1000,locationIndex=0)],lossRecordYears=5,lossAdvisedDate='2026-10-15',lossRecord=[])
 case=Case.objects.create(status='posted',tw_ref='QA-BANK-CURRENCY',payload=base,owner_personnel=person,created_by='qa',updated_by='qa')
 saved_version=case.row_version
 # 2026-10-16「92 項會計規則重新確認」：每家再保人、每期每家再保人的付款天數須獨立填寫，不繼承 Case 預設；
 # 缺漏時 Debit Note 回 409 debit_payment_terms_required。本套件只測幣別，故 fixture 明確補齊各再保人及各期天數。
 periods=[dict(id='I1',performanceMonth='2026-01',paymentBaseDate='2026-01-01',ratio=50,reinsurerPaymentTerms={'r1':90}),dict(id='I2',performanceMonth='2026-04',paymentBaseDate='2026-04-01',ratio=50,reinsurerPaymentTerms={'r1':90})]
 variants=[('USD',True),('TWD',True),('usd',True),(' twd ',True),('EUR',False),('HKD',False),('JPY',False),('GBP',False),('NTD',False),('',False),(None,False),('　',False),('\ufeff',False)]
 for structure in ['QS','XOL']:
  for currency,supported in variants:
   for enabled in [False,True]:
    payload={**copy.deepcopy(base),'reinsuranceStructure':structure,'currency':currency,'installmentEnabled':enabled,'performanceInstallments':periods}
    Case.objects.filter(pk=case.pk).update(payload=payload)
    for kind in ['cover','debit','endorsement']:
     audits=AuditLog.objects.count();snapshots=EntitySnapshot.objects.count()
     response=call('/api/document-generation-log',dict(caseUid=str(case.case_uid),kind=kind,format='docx',currency='USD',reinsuranceStructure='TREATY',bankAccount='USD'))
     blocked=kind=='debit' and not supported
     check(f'{structure} {currency!r} {enabled=} {kind}: correct availability',response.status_code==(409 if blocked else 204))
     if blocked:check('unsupported saved currency cannot be overridden and produces no audit/snapshot',response.json()['error']=='debit_bank_currency_unsupported' and response.json()['message']==MSG and AuditLog.objects.count()==audits and EntitySnapshot.objects.count()==snapshots)
     case.refresh_from_db();check('generation never changes saved Case or its version',case.payload==payload and case.row_version==saved_version)
  # Missing currency is also unsupported, without affecting Case-save rules.
  payload={**base,'reinsuranceStructure':structure};payload.pop('currency')
  Case.objects.filter(pk=case.pk).update(payload=payload)
  response=call('/api/document-generation-log',dict(caseUid=str(case.case_uid),kind='debit',format='docx'))
  check(f'{structure} missing currency blocked',response.status_code==409 and response.json()['error']=='debit_bank_currency_unsupported')
 for currency,_ in variants:
  payload=dict(reinsuranceStructure='TREATY',currency=currency)
  Case.objects.filter(pk=case.pk).update(status='draft',tw_ref=None,payload=payload)
  for kind in ['cover','debit','endorsement']:
   response=call('/api/document-generation-log',dict(caseUid=str(case.case_uid),kind=kind,format='docx'))
   check(f'Treaty Draft {currency!r} {kind} retains full exemption',response.status_code==204)
 # The new document rule does not restrict saved Case currency or readiness.
 for currency in ['USD','TWD','EUR','HKD','JPY','GBP']:
  response=call('/api/cases',dict(case={**base,'currency':currency}))
  check(f'Case draft in {currency} remains saveable',response.status_code==201)
  normalized=normalize_draft({**base,'currency':currency})
  check(f'Case Review/Announce has no new bank-currency requirement for {currency}',not any('bank' in row['label'].lower() or row['field']=='currency' for row in validate_announce_ready(normalized['value'])))
 transaction.set_rollback(True)
print(f'{len(checks)}/{len(checks)} passed; database changes rolled back',flush=True)
