"""Allianz calendar, finance APIs, claim follow-ups and isolation regression."""
import copy,json,os
from datetime import datetime,date,timedelta,timezone as tz
from unittest.mock import patch
from types import SimpleNamespace
from django.contrib.auth import get_user_model
from django.test import Client
from cases.models import Case
from personnel.models import Personnel
from cases.allianz_accounting import NAME,is_allianz
from cases.calc.payment_terms import build_payment_schedule
from cases.calc.accounting import build_premium_transactions
from cases.cash_ledger import transaction_details
from cases.resolve import payment_terms_signature
from cases.draft import normalize_draft
assert os.environ.get('RI_DISPOSABLE_QA')=='true'
checks=[]
def check(label,value,extra=None):
 assert value,(label,extra)
 checks.append(label);print('PASS '+label,flush=True)
def now(day):return day+'T01:00:00Z'
def raw(**changes):
 p={'twRef':'AL-QA','currency':'TWD','classOfBusiness':'Property','reinsuranceStructure':'QS','reinsured':'Allianz QA Cedant',
    'policyFrom':'2026-01-01','policyTo':'2027-01-01','paymentTermsDays':30,'originalPremium':1000,'riCommPct':0,'taxPct':0,
    'reinsurers':[{'name':NAME,'sharePct':100,'premium':800,'riCommPct':0,'taxPct':0,'paymentTermsDays':30}],'paymentEntries':[]}
 p.update(changes);return p
def ri(p,day='2026-01-01'):return [i for i in build_payment_schedule(p,now(day))['items'] if i.get('allianzFacility')]
check('exact Facility identity is required',is_allianz(NAME.lower()) and not is_allianz(NAME.replace(' (Facility)','')) and not is_allianz('Allianz Other (Facility)'))
for month_end,reminder,due in [('2026-01-31','2026-04-16','2026-05-01'),('2026-02-28','2026-05-14','2026-05-29'),('2028-02-29','2028-05-14','2028-05-29'),('2026-12-31','2027-03-16','2027-03-31')]:
 p=raw(policyFrom=month_end);r=ri(p)[0]
 check('calendar month-end90/75 '+month_end,(r['baseDate'],r['dueDate'],r['contractDueDate'])==(month_end,reminder,due))
 check('read does not mutate source '+month_end,p['reinsurers'][0]['paymentTermsDays']==30)
p=raw(parentTwRef='ROOT',endoEffectiveDate='2026-01-20',endorsementAnnouncedAt='2026-02-02T17:00:00Z',originalPremium=-200)
p['reinsurers'][0]['premium']=-160;r=ri(p)[0]
check('refund uses later actual Announce Taiwan month',(r['sourceBaseDate'],r['contractDueDate'],r['paymentDirection'])==('2026-02-03','2026-05-29','receivable'))
check('refund has no outgoing Cedant gate',r['paymentAllowed'] and r['offsetAllowed'] is False)
p['endorsementAnnouncedAt']='';result=build_payment_schedule(p)
check('unannounced endorsement never guesses dates',ri(p)[0]['dueDate']=='' and result['reviewRequired'])
p=raw(installmentEnabled=True,performanceInstallments=[{'id':'I1','paymentBaseDate':'2026-01-10','premium':500,'paymentTermsDays':30,'reinsurerPaymentTerms':{'r1':22}}, {'id':'I2','paymentBaseDate':'2026-02-10','premium':500,'paymentTermsDays':45,'reinsurerPaymentTerms':{'r1':45}}])
items=ri(p);check('installments have independent base months and fixed terms',[(i['contractDueDate'],i['termsDays']) for i in items]==[('2026-05-01',90),('2026-05-29',90)])
before=payment_terms_signature(p);p2=copy.deepcopy(p);p2['reinsurers'][0]['paymentTermsDays']=90
for i in p2['performanceInstallments']:i['reinsurerPaymentTerms']['r1']=90
check('legacy fixed terms canonicalize without false posted changes',payment_terms_signature(p2)==before)
normal=normalize_draft(p)['value'];check('draft stores Allianz90 including each period',normal['reinsurers'][0]['paymentTermsDays']==90 and all(i['reinsurerPaymentTerms']['r1']==90 for i in normal['performanceInstallments']))
p['paymentEntries']=[{'entryType':'payment','scheduleKey':'I1:cedant','amount':500}]
check('first installment releases independently without ledger settlement',ri(p)[0]['paymentAllowed'] and not ri(p)[1]['paymentAllowed'])
p['paymentEntries'][0]['nonCash']=True
check('noncash offsets cannot prove full cash receipt',not ri(p)[0]['paymentAllowed'])
p=raw();p['reinsurers']+=[{'name':"Lloyd's Underwriter Syndicate No. 0609 AUW (Facility)",'premium':100,'sharePct':0,'riCommPct':0,'taxPct':0}, {'name':'Ordinary QA','premium':100,'sharePct':0,'riCommPct':0,'taxPct':0,'paymentTermsDays':45}]
items=build_payment_schedule(p)['items'];check('mixed AUW and ordinary retain own date formulas',items[2]['contractDueDate']=='2026-05-31' and items[3]['contractDueDate']=='2026-02-15')

def user(tag,role,department):
 u=get_user_model().objects.create_user(username='allianz.qa.'+tag,password='Allianz-Test-Password-9!')
 who=Personnel.objects.create(name='Allianz QA '+tag,department=department,role_code=role,auth_user_id=str(u.pk),account_status='active',created_by='qa',updated_by='qa')
 c=Client(HTTP_HOST='localhost');c.force_login(u);return c,who
fin,finance=user('finance','accounting','finance');staff,ae=user('staff','sales','reinsurance')
counter=0
def make(**changes):
 global counter;counter+=1
 parent=changes.pop('parent',None);p=raw(twRef='AL-QA-'+str(counter),**changes)
 p['transactions']=build_premium_transactions(p)
 return Case.objects.create(tw_ref=p['twRef'],status='closed',payload=p,currency='TWD',case_kind='endorsement' if parent else 'original',parent_case=parent,announced_at=datetime(2026,1,1,tzinfo=tz.utc),created_by='qa',updated_by='qa')
def account(client,action,**kw):return client.post('/api/accounting',json.dumps({'action':action,**kw}),content_type='application/json')
def tx(c,leg):c.refresh_from_db();return next(t['txNo'] for t in c.payload['transactions'] if t['legType']==leg)
def pay(c,leg,value,client=fin):
 no=tx(c,leg);return account(client,'record_transaction_payments',paymentDate='2026-10-19',amount=value,allocations=[{'caseUid':str(c.case_uid),'rowVersion':c.row_version,'txNo':no,'amount':value}])
c=make();original=copy.deepcopy(c.payload)
check('cash API blocks outgoing before full Cedant receipt',pay(c,'Leg 2',800).status_code==400)
c.refresh_from_db();check('blocked payment is atomic',c.payload==original)
check('Finance records full Cedant receipt',pay(c,'Leg 1',1000).status_code==200)
c.refresh_from_db();check('receipt remains distinct from manual settlement',transaction_details(c.payload)[tx(c,'Leg 1')]['settlement']=='pending_confirmation')
check('Allianz can be paid without T1 write-off confirmation',pay(c,'Leg 2',800).status_code==200)
c.refresh_from_db();d=transaction_details(c.payload,now('2026-05-02'))[tx(c,'Leg 2')]
check('manual full payment stops overdue without automatic ledger settlement',d['outstanding']==0 and d['paymentStatus']=='pending_confirmation' and d['settlement']=='pending_confirmation')
incoming=next(e for e in c.payload['paymentEntries'] if e.get('transactionNo')==tx(c,'Leg 1'))
correction=account(fin,'edit_payment',caseUid=str(c.case_uid),rowVersion=c.row_version,entryId=incoming['id'],amount=900,reason='QA negative test')
check('receipt correction cannot bypass paid Allianz gate',correction.status_code==400 and correction.json()['error']=='full_premium_required')
unpaid=make();d=transaction_details(unpaid.payload,now('2026-05-02'))[tx(unpaid,'Leg 2')]
check('overdue uses90-day contract date and never shifts',d['paymentStatus']=='overdue' and d['contractDueDate']=='2026-05-01')
check('75-day screen reminder starts on its calendar date',transaction_details(unpaid.payload,now('2026-04-16'))[tx(unpaid,'Leg 2')]['paymentStatus']=='reminder')
refund=make(parent=unpaid,parentTwRef=unpaid.tw_ref,endoEffectiveDate='2026-01-10',endorsementAnnouncedAt='2026-02-03T00:00:00Z',originalPremium=-200,reinsurers=[{'name':NAME,'sharePct':100,'premium':-160,'riCommPct':0,'taxPct':0,'paymentTermsDays':90}])
for party in ('cedant','reinsurer'):
 a=next(i for i in build_payment_schedule(unpaid.payload)['items'] if i['partyType']==party)
 b=next(i for i in build_payment_schedule(refund.payload)['items'] if i['partyType']==party)
 response=account(fin,'record_premium_offset',originalCaseUid=str(unpaid.case_uid),refundCaseUid=str(refund.case_uid),originalRowVersion=unpaid.row_version,refundRowVersion=refund.row_version,originalKey=a['scheduleKey'],refundKey=b['scheduleKey'],paymentDate='2026-10-19',amount=abs(b['outstanding']))
 check('Allianz offset blocked for '+party,response.status_code==400 and response.json()['error']=='allianz_offset_not_allowed')
a=make();b=make(policyFrom='2026-02-01')
assert pay(a,'Leg 1',1000).status_code==200 and pay(b,'Leg 1',1000).status_code==200
alloc=[]
for obj in (a,b):
 no=tx(obj,'Leg 2');alloc.append({'caseUid':str(obj.case_uid),'rowVersion':obj.row_version,'txNo':no,'amount':800})
response=account(fin,'record_transaction_payments',paymentDate='2026-10-19',amount=1600,allocations=alloc)
check('different original due dates cannot share remittance',response.status_code==400 and response.json()['error']=='allianz_separate_due_dates')
check('fixed Allianz terms cannot be completed to another value',account(staff,'complete_payment_terms',caseUid=str(a.case_uid),rowVersion=a.row_version,partyKey='r1',days=30,reason='QA').status_code==409)

root=make();stamp=datetime(2026,10,18,17,tzinfo=tz.utc)
def claim(action,**kw):
 root.refresh_from_db();return staff.post('/api/claims',json.dumps({'action':action,'caseUid':str(root.case_uid),'rowVersion':root.row_version,**kw}),content_type='application/json')
check('claim can be created',claim('create_claim',claim={'dateOfLoss':'2026-03-01','outstandingReserve':1000}).status_code==200)
with patch('cases.claims_views.timezone',SimpleNamespace(now=lambda:stamp)):
 response=claim('record_payment',claimId=1,payment={'date':'2020-01-01','amount':1000,'claimAnnouncedAt':'1900-01-01'})
check('successful recording announces claim obligation',response.status_code==200,response.content)
root.refresh_from_db();no=tx(root,'Claim Leg 1');stored=next(t for t in root.payload['transactions'] if t['txNo']==no)
check('claim announcement is server-owned',stored['claimAnnouncedAt']==stamp.isoformat())
d=transaction_details(root.payload,now('2026-10-26'))[no]
check('claim15-day due and7-day first tracking use Taiwan announcement',(d['baseDate'],d['contractDueDate'],d['reminderDate'])==('2026-10-19','2026-11-03','2026-10-26'))
for day,tracking,next_day in [('2026-10-26',True,'2026-10-26'),('2026-10-27',False,'2026-11-02'),('2026-11-02',True,'2026-11-02'),('2026-11-09',True,'2026-11-09')]:
 d=transaction_details(root.payload,now(day))[no]
 check('claim repeating display '+day,(d['trackingDue'],d['nextTrackingDate'])==(tracking,next_day))
with patch('cases.claims_views.timezone',SimpleNamespace(now=lambda:datetime(2026,11,1,tzinfo=tz.utc))):
 check('unprocessed correction succeeds',claim('correct_payment',claimId=1,paymentId=1,reason='QA correction',payment={'date':'2020-01-01','amount':1000}).status_code==200)
root.refresh_from_db();check('correction does not reset announcement',next(t for t in root.payload['transactions'] if t['txNo']==no)['claimAnnouncedAt']==stamp.isoformat())
root.refresh_from_db();version=root.row_version
check('follow-up requires Accounting permission',account(staff,'record_allianz_claim_followup',caseUid=str(root.case_uid),rowVersion=version,txNo=no,note='QA').status_code==403)
check('follow-up requires note',account(fin,'record_allianz_claim_followup',caseUid=str(root.case_uid),rowVersion=version,txNo=no,note=' ').status_code==400)
check('Accounting can save follow-up record',account(fin,'record_allianz_claim_followup',caseUid=str(root.case_uid),rowVersion=version,txNo=no,note='Contacted Allianz on claim status').status_code==200)
root.refresh_from_db();history=transaction_details(root.payload)[no]['trackingHistory']
check('follow-up retains actor time and note',len(history)==1 and history[0]['recordedByName']==finance.name and history[0]['recordedAt'] and history[0]['note']=='Contacted Allianz on claim status')
check('stale follow-up conflicts',account(fin,'record_allianz_claim_followup',caseUid=str(root.case_uid),rowVersion=version,txNo=no,note='stale').status_code==409)
check('partial claim receipt accepted',pay(root,'Claim Leg 1',400).status_code==200)
root.refresh_from_db();d=transaction_details(root.payload,now('2026-11-09'))[no]
check('partial claim keeps due date and repeating tracking',d['outstanding']==600 and d['contractDueDate']=='2026-11-03' and d['trackingDue'])
check('remaining claim receipt accepted',pay(root,'Claim Leg 1',600).status_code==200)
root.refresh_from_db();d=transaction_details(root.payload,now('2026-11-09'))[no]
check('manual full receipt stops follow-up without auto settlement',not d['nextTrackingDate'] and not d['trackingDue'] and d['settlement']=='pending_confirmation')
with patch('cases.claims_views.timezone',SimpleNamespace(now=lambda:datetime(2026,11,2,1,tzinfo=tz.utc))):
 check('additional claim request succeeds',claim('record_payment',claimId=1,payment={'date':'2026-03-01','amount':100}).status_code==200)
root.refresh_from_db();new=next(t for t in root.payload['transactions'] if t.get('source')=='claim' and t.get('paymentId')==2 and t['legType']=='Claim Leg 1')
check('new request has independent announcement and due date',transaction_details(root.payload)[new['txNo']]['contractDueDate']=='2026-11-17' and transaction_details(root.payload)[no]['contractDueDate']=='2026-11-03')
from reminders.messages import due_kind
check('screen-only reminders do not introduce email flow',due_kind(d,'2026-10-26',{})=='')
listing=fin.get('/api/accounting?view=list')
check('lean Accounting includes Allianz metadata',listing.status_code==200 and any(r.get('allianzFacility') and r.get('offsetAllowed') is False for r in listing.json()['scheduleRows']))
check('Allianz follow-up metadata reaches transaction rows',any(r.get('allianzClaim') and 'nextTrackingDate' in r for r in listing.json()['transactionRows']))
print(f'{len(checks)}/{len(checks)} Allianz accounting checks passed',flush=True)
