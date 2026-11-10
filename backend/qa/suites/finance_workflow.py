"""Owner-approved Finance workflow: real API, isolated MySQL, adversarial rollback checks."""
import copy,json,os,uuid
from django.db import transaction
from django.test import Client
from django.contrib.auth import get_user_model
from django.utils import timezone
from cases.models import Case, FinanceReconciliationBatch
from cases.property_original import transactions, persist_settlements
from cases.cash_ledger import transaction_details, payment_batches
from audit.models import EntitySnapshot
from personnel.models import Personnel
assert os.environ.get('RI_DISPOSABLE_QA')=='true'
checks=[]
def check(name,condition,detail=''):
 assert condition,(name,detail);checks.append(name);print('PASS '+name,flush=True)
def client(tag,role):
 u=get_user_model().objects.create_user(username='finance-workflow-'+tag,password='Finance-Test-9!')
 Personnel.objects.create(name='Finance Test '+tag,department='finance' if role.startswith('accounting') else 'reinsurance',role_code=role,auth_user_id=str(u.pk),account_status='active',created_by='qa',updated_by='qa')
 c=Client(HTTP_HOST='localhost');c.force_login(u);return c
def api(c,body):return c.post('/api/accounting',json.dumps(body),content_type='application/json')
def fixture(ref,value=1000,currency='USD',party='QA Cedant'):
 p={'currency':currency,'reinsured':party,'originalInsured':'Finance Insured '+ref,'originalInsuredCn':'測試保戶'+ref,
 'classCode':'PD','classOfBusiness':'Property','reinsuranceStructure':'QS','policyFrom':'2026-09-01','policyTo':'2027-09-01',
 'paymentTermsDays':90,'originalPremium':value,'riCommPct':0,'taxPct':0,'premiumLedgerLayout':'per-reinsurer-v1',
 'accountingRules':'accounting-v1','reinsurers':[{'name':'QA Reinsurer','sharePct':100,'premium':value,'riCommPct':20,'taxPct':0,'paymentTermsDays':90}],
 'paymentEntries':[],'claims':[],'twRef':ref,'announcedAt':'2026-09-01T00:00:00Z'}
 p['transactions']=transactions(p,'2026-09-01T00:00:00Z')
 return Case.objects.create(tw_ref=ref,status='posted',currency=currency,reinsured_name_snapshot=party,payload=p,announced_at=timezone.now(),created_by='qa',updated_by='qa')
def rows(c):c.refresh_from_db();return [t for t in c.payload['transactions'] if not t.get('reversed') and not t.get('isReversalEntry')]
def leg(c,l):return next(t['txNo'] for t in rows(c) if t['legType']==l)
def member(c,no):c.refresh_from_db();return {'caseUid':str(c.case_uid),'txNo':no,'rowVersion':c.row_version}
def review(targets,c=None,**over):
 body={'action':'review_accounts','date':'2026-11-03','reference':'FIN-REVIEW','members':[member(x,n) for x,n in targets]};body.update(over);return api(c or fin,body)
def register(targets,net,c=None,**over):
 body={'action':'record_transaction_payments','paymentDate':'2026-11-03','reference':'FIN-CASH','amount':net,
 'allocations':[{**member(x,n),'cashAmount':cash,'offsetAmount':offset} for x,n,cash,offset in targets]};body.update(over);return api(c or fin,body)
def reverse(bid,cases,**over):
 body={'action':'reverse_batch_payment','batchId':bid,'paymentDate':'2026-11-03','note':'Correction of test registration',
 'cases':[{'caseUid':str(c.case_uid),'rowVersion':(c.refresh_from_db() or c.row_version)} for c in cases]};body.update(over);return api(fin,body)
def cancel(bid,cases):
 group=next(b for b in fin.get('/api/accounting?view=list').json()['reviewBatches'] if b['id']==bid)
 return api(fin,{'action':'cancel_review_batch','reviewBatchId':bid,'reason':'Review correction','members':group['members']})

def add_claim(c,value=200,pid=1):
 c.refresh_from_db();p=copy.deepcopy(c.payload)
 for l in (1,2):p['transactions'].append({'txNo':c.tw_ref+f'-C{pid}-P1-R1-T{l}','source':'claim','legType':f'Claim Leg {l}',
 'claimId':pid,'paymentId':1,'reinsurerIdx':0,'reinsurer':'QA Reinsurer','amount':value,'createdAt':'2026-11-01T00:00:00Z','dueDate':'2026-11-16'})
 c.payload=p;c.save();return c.tw_ref+f'-C{pid}-P1-R1-T1',c.tw_ref+f'-C{pid}-P1-R1-T2'
class Done(Exception):pass
try:
 with transaction.atomic():
  fin=client('fin','accounting');manager=client('manager','accounting_manager');sales=client('sales','sales');president=client('president','president')
  a=fixture('QA-FIN-A');b=fixture('QA-FIN-B',500);t1a=leg(a,'Leg 1');t1b=leg(b,'Leg 1')
  r=fin.get('/api/accounting?view=list');check('legacy accounts start unreviewed without writes',r.status_code==200 and not any(x['financeReviewed'] for x in r.json()['transactionRows']) and FinanceReconciliationBatch.objects.count()==0,r.content[:500])
  check('unreviewed cash is blocked',register([(a,t1a,1000,0)],1000).json().get('error')=='finance_review_required')
  check('sales cannot mark Finance review',review([(a,t1a)],sales).status_code==403)
  check('President cannot mark Finance review',review([(a,t1a)],president).status_code==403)
  check('review date remains required',review([(a,t1a)],date='',reference='',note='').status_code==400)
  r=review([(a,t1a),(b,t1b)]);check('same-party/currency cross-case review accepted',r.status_code==200,r.content);review_id=r.json()['reviewBatchId']
  r=fin.get('/api/accounting?view=list');check('reviewed rows expose date/reference/batch',all(x['reviewBatchId']==review_id and x['reviewDate']=='2026-11-03' for x in r.json()['transactionRows'] if x['txNo'] in (t1a,t1b)))
  check('duplicate review rejected',review([(a,t1a)]).status_code==409)
  c=fixture('QA-FIN-C',100,currency='TWD');d=fixture('QA-FIN-D',100,party='Other Cedant')
  check('mixed currency review blocked atomically',review([(c,leg(c,'Leg 1')),(d,leg(d,'Leg 1'))]).status_code==400)
  check('mixed counterparty review blocked',review([(a,t1a),(d,leg(d,'Leg 1'))]).status_code==409)
  r=api(fin,{'action':'cancel_review_batch','reviewBatchId':review_id,'reason':'test','members':[member(a,t1a)]});check('partial batch review cancellation blocked',r.status_code==409)
  with transaction.atomic():
   r=register([(a,t1a,999,0),(b,t1b,500,0)],1499);check('partial premium allocation accepted',r.status_code==200,r.content)
   transaction.set_rollback(True)
  r=register([(a,t1a,1000,0),(b,t1b,500,0)],1500);check('cross-case full premium receipt accepted',r.status_code==200,r.content);receipt=r.json()['batchId']
  check('review cancellation blocked by any active cash member',cancel(review_id,[a,b]).status_code==409)
  a.refresh_from_db();check('full cash automatically settles T1',transaction_details(a.payload)[t1a]['settlement']=='settled')
  check('legacy direct Edit amount API retired',api(fin,{'action':'edit_payment'}).status_code==410)
  check('legacy manual settlement API retired',api(fin,{'action':'confirm_facility_settlement'}).status_code==410)
  check('legacy schedule payment bypass retired',api(fin,{'action':'record_payment'}).status_code==410)
  r=reverse(receipt,[a,b]);check('settled cross-case registration reverses atomically',r.status_code==200,r.content)
  a.refresh_from_db();b.refresh_from_db();check('reversal reopens both account balances',transaction_details(a.payload)[t1a]['outstanding']==1000 and transaction_details(b.payload)[t1b]['outstanding']==500)
  r=cancel(review_id,[a,b]);check('whole review cancellation allowed after cash reversal',r.status_code==200,r.content)
  review([(a,t1a),(b,t1b)]);r=register([(a,t1a,1000,0),(b,t1b,500,0)],1500,replacementOfBatchId=receipt)
  check('replacement linked to reversed registration',r.status_code==200,r.content);replacement=r.json()['batchId']
  t2a=leg(a,'Leg 2');review([(a,t2a)]);r=register([(a,t2a,800,0)],-800);check('T2 payment allowed after whole T1 receipt',r.status_code==200,r.content)
  check('receipt reversal blocked by downstream T2',reverse(replacement,[a,b]).json().get('error')=='downstream_payment_locked')
  # Actual cash stays separate by direction; all new offsets are disabled.
  e=fixture('QA-FIN-E');ct1,ct2=add_claim(e)
  review([(e,leg(e,'Leg 1')),(e,ct2)])
  r=register([(e,leg(e,'Leg 1'),800,200),(e,ct2,0,200)],800)
  check('new mixed offsets rejected',r.status_code==400 and r.json()['error']=='offsets_disabled',r.content)
  e.refresh_from_db();check('failed mixed registration leaves no partial entries',e.payload['paymentEntries']==[])
  r=register([(e,ct2,1,0)],-1);check('claim payment still requires its own receipts',r.status_code==409)
  review([(e,ct1)]);r=register([(e,ct1,200,0)],200);check('claim receipt works for general reinsurer',r.status_code==200,r.content)
  r=register([(e,leg(e,'Leg 1'),1000,0),(e,ct2,200,0)],800)
  check('single registration cannot net two cash directions',r.status_code==400 and r.json()['error']=='cash_direction_mismatch',r.content)
  r=register([(e,leg(e,'Leg 1'),1000,0)],1000);check('actual premium receipt accepted',r.status_code==200,r.content);cashbid=r.json()['batchId']
  r=register([(e,ct2,200,0)],-200);check('actual claim payment recorded separately',r.status_code==200,r.content)
  e.refresh_from_db();ds=transaction_details(e.payload);check('cash-only balances retain no offset',ds[leg(e,'Leg 1')]['cashPaid']==1000 and ds[leg(e,'Leg 1')]['nonCashPaid']==0 and ds[ct2]['outstanding']==0,ds)
  review([(e,leg(e,'Leg 2'))]);r=register([(e,leg(e,'Leg 2'),800,0)],-800);check('full actual T1 releases premium T2',r.status_code==200,r.content)
  z=fixture('QA-FIN-Z',200);zin,zout=add_claim(z,200);review([(z,zin)]);register([(z,zin,200,0)],200)
  review([(z,leg(z,'Leg 1')),(z,zout)]);r=register([(z,leg(z,'Leg 1'),0,200),(z,zout,0,200)],0)
  check('pure offset creation rejected without fake cash',r.status_code==400 and r.json()['error']=='offsets_disabled',r.content)
  z.refresh_from_db();check('rejected pure offset leaves premium outstanding',transaction_details(z.payload)[leg(z,'Leg 1')]['outstanding']==200)
  r=api(fin,{'action':'record_claim_followup',**member(e,ct2),'note':'Follow up'});check('settled claim follow-up blocked',r.status_code==409)
  f=fixture('QA-FIN-F');fin1,fin2=add_claim(f,300);r=api(fin,{'action':'record_claim_followup',**member(f,fin1),'note':'Await response'})
  check('follow-up available on every outstanding claim',r.status_code==200,r.content)
  f.refresh_from_db();check('claim follow-up leaves amounts unchanged',transaction_details(f.payload)[fin1]['outstanding']==300 and transaction_details(f.payload)[fin1]['trackingHistory'][-1]['note']=='Await response')
  history=fin.get('/api/accounting?view=list').json()['cashBatches'];n=next(x for x in history if x['batchId']==cashbid)
  check('History shows actual gross cash without invented offsets',n['receivableSettled']==1000 and n['payableSettled']==0 and n['netCash']==1000 and not n['pureOffset'])
  check('History links replacement registrations',replacement in next(x for x in history if x['batchId']==receipt)['replacementBatchIds'])
  check('read-only roles can inspect Finance workflow',president.get('/api/accounting?view=list').status_code==200 and sales.get('/api/accounting?view=list').status_code==200)
  print(str(len(checks))+' passed Finance workflow checks',flush=True)
  raise Done()
except Done:pass
