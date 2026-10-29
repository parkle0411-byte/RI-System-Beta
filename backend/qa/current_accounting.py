"""Synthetic API fixtures shared by current accounting suites, never production data."""
import json,os
from datetime import datetime,timezone
from django.contrib.auth import get_user_model
from django.test import Client
from personnel.models import Personnel
from cases.models import Case
from cases.calc.accounting import build_premium_transactions
from cases.calc.payment_terms import premium_installment_plan
from cases.cash_ledger import transaction_details

def client(tag,role='accounting',department='finance'):
 assert os.environ.get('RI_DISPOSABLE_QA')=='true'
 user=get_user_model().objects.create_user(username='current.qa.'+tag,password='Current-Synthetic-QA-9!')
 person=Personnel.objects.create(name='Current QA '+tag,department=department,role_code=role,
  auth_user_id=str(user.pk),account_status='active',created_by='qa',updated_by='qa')
 value=Client(HTTP_HOST='localhost');value.force_login(user);return value,person

def make(ref,names=None,shares=None,parent=None,**changes):
 names=names or ['QA Current Ordinary RI'];shares=shares or [100/len(names)]*len(names)
 premium=changes.pop('riPremium',800)
 p=dict(twRef=ref,reinsuranceStructure='QS',classOfBusiness='Property',classCode='PD',currency='TWD',
  reinsured='Current QA Cedant',originalInsured='Current QA Policy',originalInsuredCn='本輪會計測試保戶',
  reinsuredRetention='Synthetic retention',newOrRenew='New',typePrefix='Fire',type='Fire Facultative Reinsurance',
  ae='Current QA Executive',policyFrom='2026-01-01',policyTo='2027-01-01',paymentTermsDays=90,
  originalPremium=1000,riCommPct=0,taxPct=0,installmentEnabled=False,performanceInstallments=[],
  reinsurers=[dict(name=name,sharePct=share,premium=premium,riCommPct=0,taxPct=0,paymentTermsDays=90) for name,share in zip(names,shares)],
  transactions=[],paymentEntries=[],claims=[],lossAdvisedDate='2025-12-01',lossRecordYears=0,lossRecord=[],
  situations=[dict(address='1 QA Road',postcode='100')],sumInsured=[dict(category='Buildings',amount=10000)],
  limitOfLiability=10000,interest='Buildings',deductibles='As original',originalConditions='As original',occupation='Office',construction='Concrete')
 p.update(changes)
 if parent:p.update(parentTwRef=parent.tw_ref,endoEffectiveDate=p.get('endoEffectiveDate','2026-01-01'),endorsementAnnouncedAt='2026-01-01T00:00:00Z')
 if p.get('installmentEnabled'):
  p['transactions']=[t for period in premium_installment_plan(p) for t in build_premium_transactions(p,period)]
 else:p['transactions']=build_premium_transactions(p)
 return Case.objects.create(tw_ref=ref,status='posted',payload=p,currency=p['currency'],parent_case=parent,
  case_kind='endorsement' if parent else 'original',announced_at=datetime(2026,1,1,tzinfo=timezone.utc),created_by='qa',updated_by='qa')

def post(client,action,**body):
 return client.post('/api/accounting',json.dumps(dict(action=action,**body)),content_type='application/json')

def details(case,now=None):
 case.refresh_from_db();return transaction_details(case.payload,now)

def nos(case,leg,period=None):
 case.refresh_from_db()
 return [t['txNo'] for t in case.payload['transactions'] if t.get('legType')==leg and (period is None or t.get('installmentId')==period)]

def pay(client,case,numbers,value=None,**extra):
 case.refresh_from_db();data=details(case)
 amounts=numbers if isinstance(numbers,dict) else {no:abs(data[no]['outstanding']) if value is None else value for no in numbers}
 allocations=[dict(caseUid=str(case.case_uid),rowVersion=case.row_version,txNo=no,amount=amount) for no,amount in amounts.items()]
 return post(client,'record_transaction_payments',**{'paymentDate':'2026-10-27','amount':round(sum(amounts.values()),2),'allocations':allocations,'reference':'CURRENT-QA-EXTERNAL',**extra})
