"""Unreadable financial data: visible pending amounts, unchanged raw data, blocked writes."""
import copy,json,os
from datetime import datetime,timezone
from django.contrib.auth import get_user_model
from django.db import transaction
from django.test import Client
from audit.models import AuditLog,EntitySnapshot
from personnel.models import Personnel
from cases.models import Case
from cases.data_integrity import financial_issues
from cases.calc.totals import case_totals,list_financials
from cases.calc.accounting import build_premium_transactions
from cases.resolve import payment_terms_signature
from cases.draft import normalize_draft
from cases.accounting_policy import FACILITIES
assert os.environ.get('RI_DISPOSABLE_QA')=='true'
checks=[]
def check(name,ok,extra=None):
 assert ok,(name,extra)
 checks.append(name);print('PASS '+name,flush=True)
def payload(name='QA Integrity RI'):
 return dict(reinsuranceStructure='QS',classOfBusiness='Property',classCode='PD',currency='USD',
   reinsured='QA Integrity Cedant',originalInsured='QA Integrity Policy',originalInsuredCn='格式測試合成資料',
   policyFrom='2026-03-01',policyTo='2027-03-01',originalPremium=1000,riCommPct=10,taxPct=0,paymentTermsDays=90,
   reinsurers=[dict(name=name,sharePct=100,premium=800,riCommPct=0,taxPct=0,paymentTermsDays=30)],
   performanceInstallments=[],paymentEntries=[],transactions=[])
for value in [{},'broken',True,1,[None],[5],[[]],[{'name':42}]]:
 p=payload();p['reinsurers']=value;before=copy.deepcopy(p)
 check('malformed reinsurers are identified '+repr(value),bool(financial_issues(p)))
 check('malformed amounts remain pending, never zero '+repr(value),all(v is None for v in case_totals(p).values()) and list_financials(p).get('dataError') is True and p==before)
for value in [{},[1],True,'NaN','Infinity']:
 p=payload();p['originalPremium']=value
 check('invalid financial number remains pending '+repr(value),all(v is None for v in case_totals(p).values()))
check('ordinary empty draft remains incomplete, not corrupted',not financial_issues({}) and not financial_issues({'reinsurers':None}) and all(v==0 for v in case_totals({}).values()))
check('known valid totals are unchanged',case_totals(payload())['leg1']==900 and case_totals(payload())['leg2']==800)
p=payload();p['paymentTermsDays']='bad';p['reinsurers'][0]['paymentTermsDays']='0x5a';check('underwriting/date validity retains existing gates without erasing readable monetary amounts',not financial_issues(p) and case_totals(p)['leg1']==900)
p=payload();p['riCommPct']='\ufeff10\ufeff';check('valid JavaScript whitespace is parsed consistently by the number guard',not financial_issues(p) and case_totals(p)['leg1']==900)
for name in FACILITIES[1:4]:
 p=payload(name);p.update(installmentEnabled=True,performanceInstallments=[dict(id='I1',premium=1000,paymentBaseDate='2026-03-01',paymentTermsDays=30,reinsurerPaymentTerms={'r1':30})])
 canonical=normalize_draft(p)['value'];original=copy.deepcopy(p)
 check('fixed 90-day signatures match normalized saved terms '+name,payment_terms_signature(p)==payment_terms_signature(canonical) and p==original)
 changed=copy.deepcopy(canonical);changed['performanceInstallments'][0]['paymentBaseDate']='2026-03-02'
 check('real payment base date change remains detectable '+name,payment_terms_signature(canonical)!=payment_terms_signature(changed))
p=payload();q=copy.deepcopy(p);q['paymentTermsDays']=30
check('ordinary variable Cedant days remain detectable',payment_terms_signature(p)!=payment_terms_signature(q))
class Rollback(Exception):pass
try:
 with transaction.atomic():
  user=get_user_model().objects.create_user(username='qa.integrity.admin',password='Integrity-Test-9!')
  owner=Personnel.objects.create(name='QA Integrity Admin',department='admin',role_code='admin',auth_user_id=str(user.pk),account_status='active',created_by='qa',updated_by='qa')
  client=Client(HTTP_HOST='localhost');client.force_login(user)
  bad=payload();bad['reinsurers']={'name':'Do not discard raw data'}
  c=Case.objects.create(tw_ref='QA-INTEGRITY-BAD',status='posted',owner_personnel=owner,payload=bad,currency='USD',announced_at=datetime(2026,3,1,tzinfo=timezone.utc),created_by='qa',updated_by='qa')
  draft=Case.objects.create(status='draft',owner_personnel=owner,payload=bad,currency='USD',created_by='qa',updated_by='qa')
  good=payload();good['twRef']='QA-INTEGRITY-GOOD';good['transactions']=build_premium_transactions(good)
  safe=Case.objects.create(tw_ref=good['twRef'],status='posted',payload=good,currency='USD',created_by='qa',updated_by='qa')
  state=(copy.deepcopy(c.payload),c.row_version,AuditLog.objects.count(),EntitySnapshot.objects.count())
  single=client.get('/api/cases?caseUid='+str(c.case_uid)).json()['case']
  check('single-case GET preserves original malformed data and reports issues',single['payload']==bad and single['dataError'] and single['dataIssues'])
  rows=client.get('/api/cases').json()['cases'];item=next(r for r in rows if r['caseUid']==str(c.case_uid))
  check('case-list financial amounts are pending, not zero',item['ourSharePremium'] is None and item['brokerage'] is None and item['dataError'])
  body=client.get('/api/accounting').json()
  check('Accounting flags only bad case and still displays valid case',any(w['caseUid']==str(c.case_uid) and w.get('dataError') for w in body['warnings']) and any(r['caseUid']==str(safe.case_uid) for r in body['transactionRows']) and not any(r['caseUid']==str(c.case_uid) for r in body['transactionRows']))
  dashboard=client.get('/api/dashboard')
  check('Dashboard remains readable and explicitly marks incomplete amounts',dashboard.status_code==200 and dashboard.json()['metrics']['accountingTotalIncomplete'] and any(w['caseId']==c.pk for w in dashboard.json()['metrics']['dataErrors']))
  preview=client.get('/api/production-report?month=2026-03')
  check('Production warns about corrupt sources and excludes their amounts',preview.status_code==200 and any(w['caseUid']==str(c.case_uid) for w in preview.json()['dataErrors']) and not any(r['caseUid']==str(c.case_uid) for r in preview.json()['rows']))
  def post(url,body):return client.post(url,json.dumps(body),content_type='application/json')
  r=post('/api/case-announce',dict(caseUid=str(draft.case_uid),rowVersion=draft.row_version,confirmed=True,documentIds=[]))
  check('Announce rejects corrupted data before generating a reference',r.status_code==400 and any(i['field']=='reinsurers' for i in r.json()['issues']))
  r=post('/api/document-generation-log',dict(caseUid=str(c.case_uid),kind='cover',format='docx'))
  check('document generation rejects corrupted data',r.status_code==409 and r.json()['error']=='case_data_invalid')
  r=post('/api/accounting',dict(action='record_transaction_payments',paymentDate='2026-10-27',reference='QA',amount=1000,allocations=[dict(caseUid=str(c.case_uid),rowVersion=c.row_version,txNo='QA-INTEGRITY-BAD-R1-T1',amount=1000)]))
  check('cash allocation rejects corrupted data',r.status_code==409 and r.json()['error']=='case_data_invalid')
  r=post('/api/case-workflow',dict(caseUid=str(c.case_uid),rowVersion=c.row_version,action='create_endorsement'))
  check('workflow does not propagate corrupted source data',r.status_code==409 and r.json()['error']=='case_data_invalid')
  r=post('/api/claims',dict(caseUid=str(c.case_uid),rowVersion=c.row_version,action='create_claim',claim={'dateOfLoss':'2026-04-01','outstandingReserve':100}))
  check('claims reject corrupted source security',r.status_code==409 and r.json()['error']=='case_data_invalid')
  c.refresh_from_db();check('rejected formal operations leave raw data, version, audit and snapshots unchanged',state==(c.payload,c.row_version,AuditLog.objects.count(),EntitySnapshot.objects.count()))
  # Reversed Cases still permit legitimate claim cash corrections, but cannot
  # bypass the data check. No historical row or entry is rewritten.
  c.status='reversed';c.payload['transactions']=[dict(txNo='BAD-CLAIM-T1',source='claim',claimId=1,paymentId=1,legType='Claim Leg 1',amount=100,createdAt='2026-10-01T00:00:00Z')]
  c.payload['paymentEntries']=[dict(id='bad-old-claim-entry',batchId='bad-old-claim-batch',transactionNo='BAD-CLAIM-T1',entryType='payment',amount=20,paymentDate='2026-10-01')];c.save()
  original=(copy.deepcopy(c.payload),c.row_version)
  r=post('/api/accounting',dict(action='edit_payment',caseUid=str(c.case_uid),rowVersion=c.row_version,entryId='bad-old-claim-entry',amount=10,reason='QA correction'))
  check('reversed-claim exception cannot bypass corrupted-source check',r.status_code==409 and r.json()['error']=='case_data_invalid')
  r=post('/api/accounting',dict(action='reverse_batch_payment',batchId='bad-old-claim-batch',cases=[dict(caseUid=str(c.case_uid),rowVersion=c.row_version)],note='QA bank return'))
  check('bank reversal also blocks corrupted-source computation',r.status_code==409 and r.json()['error']=='case_data_invalid')
  c.refresh_from_db();check('corrupted-source edit/reversal preserves immutable history',original==(c.payload,c.row_version))
  check('anonymous write remains denied',Client(HTTP_HOST='localhost').post('/api/accounting',json.dumps({'action':'record_transaction_payments'}),content_type='application/json').status_code==401)
  raise Rollback()
except Rollback:pass
print(f'{len(checks)}/{len(checks)} data-integrity checks passed; writes rolled back')
