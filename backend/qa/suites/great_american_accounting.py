"""Owner-confirmed GA Property dates, full manual collection gates and API isolation."""
import copy,json,os
from datetime import datetime,timezone
from unittest.mock import patch
from types import SimpleNamespace
from django.contrib.auth import get_user_model
from django.test import Client
from cases.models import Case
from personnel.models import Personnel
from cases.great_american_accounting import NAME,applies,target
from cases.calc.payment_terms import build_payment_schedule,premium_installment_plan
from cases.calc.accounting import build_premium_transactions
from cases.cash_ledger import transaction_details
from cases.calc.swiss_facility import case_payload
from cases.draft import normalize_draft
from cases.resolve import payment_terms_signature
assert os.environ.get('RI_DISPOSABLE_QA')=='true'
checks=[]
def check(name,condition,extra=None):
 assert condition,(name,extra)
 checks.append(name);print('PASS '+name,flush=True)
def raw(**kw):
 p={'twRef':'GA-QA','currency':'TWD','classOfBusiness':'Property','reinsuranceStructure':'QS','reinsured':'GA QA Cedant',
    'policyFrom':'2026-03-20','policyTo':'2027-03-20','paymentTermsDays':30,'originalPremium':1000,'riCommPct':0,'taxPct':0,
    'reinsurers':[{'name':NAME,'sharePct':100,'premium':800,'riCommPct':0,'taxPct':0,'paymentTermsDays':30}],'paymentEntries':[]}
 p.update(kw);return p
def schedules(p,day='2026-01-01'):return build_payment_schedule(p,day+'T01:00:00Z')['items']
def ga(p,day='2026-01-01'):return [i for i in schedules(p,day) if i.get('greatAmericanFacility')]
check('only exact Singapore Facility Property applies',applies(raw()) and target(raw(),NAME.lower()) and not target(raw(classOfBusiness='CGL'),NAME) and not target(raw(),NAME.replace(' (Facility)','')) and not target(raw(),'Great American Other (Facility)'))
for source,base,remind,due in [('2026-01-01','2026-03-31','2026-06-14','2026-06-29'),('2026-03-31','2026-03-31','2026-06-14','2026-06-29'),('2026-04-01','2026-06-30','2026-09-13','2026-09-28'),('2026-06-30','2026-06-30','2026-09-13','2026-09-28'),('2026-09-30','2026-09-30','2026-12-14','2026-12-29'),('2026-12-31','2026-12-31','2027-03-16','2027-03-31'),('2027-12-20','2027-12-31','2028-03-15','2028-03-30')]:
 p=raw(policyFrom=source);before=copy.deepcopy(p);item=ga(p)[0]
 check('quarter plus90/75 '+source,(item['baseDate'],item['dueDate'],item['contractDueDate'],item['termsDays'])==(base,remind,due,90))
 check('schedule reads do not mutate '+source,p==before)
for klass in ('CGL','Marine','',None):
 p=raw(classOfBusiness=klass);check('other class remains ordinary '+str(klass),not ga(p) and schedules(p)[1]['termsDays']==30)
for premium in (200,-200):
 p=raw(parentTwRef='ROOT',endoEffectiveDate='2026-03-31',endorsementAnnouncedAt='2026-03-31T17:00:00Z',originalPremium=premium)
 p['reinsurers'][0]['premium']=premium*.8;i=ga(p)[0]
 check('endorsement later successful Taiwan Announce '+str(premium),(i['sourceBaseDate'],i['contractDueDate'])==('2026-04-01','2026-09-28'))
 p['endorsementAnnouncedAt']='';check('unannounced endorsement stays pending '+str(premium),not ga(p)[0]['contractDueDate'] and build_payment_schedule(p)['reviewRequired'])
p=raw(installmentEnabled=True,performanceInstallments=[{'id':'I1','paymentBaseDate':'2026-03-31','premium':500,'paymentTermsDays':30,'reinsurerPaymentTerms':{'r1':33}},{'id':'I2','paymentBaseDate':'2026-04-01','premium':500,'paymentTermsDays':30,'reinsurerPaymentTerms':{'r1':45}}])
check('installments use their own Payment Base Date quarters',[i['contractDueDate'] for i in ga(p)]==['2026-06-29','2026-09-28'])
normalized=normalize_draft(p)['value'];check('draft fixes only GA per-period90',normalized['reinsurers'][0]['paymentTermsDays']==90 and all(i['reinsurerPaymentTerms']['r1']==90 for i in normalized['performanceInstallments']))
check('canonical fixed terms preserve old posted signatures',payment_terms_signature(p)==payment_terms_signature(normalized))
ordinary=normalize_draft(raw(classOfBusiness='CGL'))['value'];check('nonProperty draft terms remain editable',ordinary['reinsurers'][0]['paymentTermsDays']==30)

def client(tag,role,department):
 u=get_user_model().objects.create_user(username='ga.qa.'+tag,password='GA-Test-Password-9!')
 who=Personnel.objects.create(name='GA QA '+tag,department=department,role_code=role,auth_user_id=str(u.pk),account_status='active',created_by='qa',updated_by='qa')
 c=Client(HTTP_HOST='localhost');c.force_login(u);return c,who
fin,finance=client('finance','accounting','finance');staff,ae=client('staff','sales','reinsurance')
count=0
def make(**kw):
 global count;count+=1
 parent=kw.pop('parent',None);p=raw(twRef='GA-QA-'+str(count),**kw)
 p['transactions']=[t for installment in premium_installment_plan(p) for t in build_premium_transactions(p,installment)] if p.get('installmentEnabled') else build_premium_transactions(p)
 stamp=datetime.fromisoformat(p.get('endorsementAnnouncedAt','2026-01-01T00:00:00Z').replace('Z','+00:00'))
 return Case.objects.create(tw_ref=p['twRef'],status='closed',payload=p,currency='TWD',case_kind='endorsement' if parent else 'original',parent_case=parent,announced_at=stamp,created_by='qa',updated_by='qa')
def api(action,who=fin,**kw):return who.post('/api/accounting',json.dumps({'action':action,**kw}),content_type='application/json')
def ds(c,day='2026-10-20'):
 c.refresh_from_db();return transaction_details(case_payload(c),day+'T01:00:00Z')
def number(c,leg,index=0):
 c.refresh_from_db();return [t['txNo'] for t in c.payload['transactions'] if t['legType']==leg][index]
def pay(c,no,value=None,who=fin,reference=''):
 d=ds(c)[no];value=abs(d['outstanding']) if value is None else value
 return api('record_transaction_payments',who,paymentDate='2026-10-20',reference=reference,amount=value,allocations=[{'caseUid':str(c.case_uid),'rowVersion':c.row_version,'txNo':no,'amount':value}])
def confirm(c,no,undo=False):
 c.refresh_from_db();return api('unconfirm_facility_settlement' if undo else 'confirm_facility_settlement',caseUid=str(c.case_uid),rowVersion=c.row_version,txNo=no,note='QA bank/reconciliation reference')
def collect(c):
 for t in [t for t in c.payload['transactions'] if t['legType'].startswith('Leg 1')]:
  assert pay(c,t['txNo']).status_code==200
  assert confirm(c,t['txNo']).status_code==200

c=make();t1=number(c,'Leg 1');t2=number(c,'Leg 2');before=copy.deepcopy(c.payload)
check('payout rejected before receipt',pay(c,t2,400).status_code==400)
c.refresh_from_db();check('blocked payout is atomic',c.payload==before)
check('receipt can be recorded',pay(c,t1).status_code==200)
check('cash full without manual confirmation still blocks payout',not ds(c)[t2]['paymentAllowed'] and pay(c,t2,400).status_code==400)
check('manual whole Cedant confirmation releases payout',confirm(c,t1).status_code==200 and ds(c)[t2]['paymentAllowed'])
check('staff cannot record outgoing payment',pay(c,t2,400,staff).status_code==403)
check('GA first partial remittance accepted',pay(c,t2,400).status_code==200)
d=ds(c)[t2];check('partial retains original deadline and remaining balance',d['outstanding']==400 and d['contractDueDate']=='2026-06-29' and d['paymentStatus']=='overdue' and not d['fullPaymentRequired'])
check('cannot confirm payment complete while partially paid',confirm(c,t2).status_code==400)
check('cannot cancel whole Cedant confirmation after payout',confirm(c,t1,True).status_code==409)
check('remaining partial remittance accepted',pay(c,t2,400).status_code==200)
check('cash full keeps overdue until manual payment confirmation',ds(c)[t2]['outstanding']==0 and ds(c)[t2]['paymentStatus']=='overdue')
check('manual bank-success full payment completes',confirm(c,t2).status_code==200)
check('confirmation stops overdue',ds(c)[t2]['manualSettlementConfirmed'] and ds(c)[t2]['paymentStatus']=='settled')
check('bank return cannot reopen original completion',confirm(c,t2,True).status_code==409)
c.refresh_from_db();entry=next(e for e in c.payload['paymentEntries'] if e.get('transactionNo')==t2)
check('settled bank remittance cannot be reversed',api('reverse_batch_payment',batchId=entry['batchId'],cases=[{'caseUid':str(c.case_uid),'rowVersion':c.row_version}],paymentDate='2026-10-20',note='bank return').status_code==409)
check('GA fixed terms cannot be edited',api('complete_payment_terms',staff,caseUid=str(c.case_uid),rowVersion=c.row_version,partyKey='r1',days=30,reason='QA').status_code==409)
from cases.facility_accounting import schedule_signature
probe=copy.deepcopy(c.payload)
for e in probe['paymentEntries']:
 if e.get('transactionNo')==t1:e['nonCash']=True
item=next(i for i in schedules(probe) if i['partyType']=='cedant')
probe['facilityAccounting']['confirmations']['schedule:'+item['scheduleKey']]['fingerprint']=schedule_signature(probe,item)
check('noncash fee or offset never proves full collected principal',not ga(probe)[0]['paymentAllowed'])

mixed=make(reinsurers=[{'name':NAME,'sharePct':50,'premium':400,'riCommPct':0,'taxPct':0,'paymentTermsDays':30},{'name':'Ordinary GA QA','sharePct':50,'premium':400,'riCommPct':0,'taxPct':0,'paymentTermsDays':45}])
incoming=[t for t in mixed.payload['transactions'] if t['legType']=='Leg 1'];out=number(mixed,'Leg 2')
assert pay(mixed,incoming[0]['txNo']).status_code==200 and confirm(mixed,incoming[0]['txNo']).status_code==200
check('other reinsurer Cedant share is required',not ds(mixed)[out]['paymentAllowed'])
assert pay(mixed,incoming[1]['txNo']).status_code==200
check('other share also requires manual confirmation',not ds(mixed)[out]['paymentAllowed'])
assert confirm(mixed,incoming[1]['txNo']).status_code==200
check('all Cedant shares confirmed release GA',ds(mixed)[out]['paymentAllowed'])
check('ordinary reinsurer keeps own deadline',ds(mixed)[number(mixed,'Leg 2',1)]['contractDueDate']=='2026-05-04')

period=make(installmentEnabled=True,performanceInstallments=p['performanceInstallments'])
first=number(period,'Leg 1');second=number(period,'Leg 1',1)
assert pay(period,first).status_code==200 and confirm(period,first).status_code==200
check('period1 releases without period2',ds(period)[number(period,'Leg 2')]['paymentAllowed'] and not ds(period)[number(period,'Leg 2',1)]['paymentAllowed'])
for same in (False,True):
 a=make();b=make(policyFrom='2026-03-30' if same else '2026-04-01');collect(a);collect(b);alloc=[]
 for obj in (a,b):
  no=number(obj,'Leg 2');alloc.append({'caseUid':str(obj.case_uid),'rowVersion':obj.row_version,'txNo':no,'amount':800})
 response=api('record_transaction_payments',paymentDate='2026-10-20',amount=1600,allocations=alloc)
 check('same deadline requires separate case registrations' if same else 'different deadline requires separate case registrations',response.status_code==400 and response.json()['error']=='great_american_payment_rule',response.content)
 check('caseA can be manually registered with external reference '+str(same),pay(a,number(a,'Leg 2'),reference='EXT-SHARED-001').status_code==200)
 check('caseB may reuse the same external reference '+str(same),pay(b,number(b,'Leg 2'),reference='EXT-SHARED-001').status_code==200)
 a.refresh_from_db();b.refresh_from_db()
 ea=next(e for e in a.payload['paymentEntries'] if e.get('transactionNo')==number(a,'Leg 2'))
 eb=next(e for e in b.payload['paymentEntries'] if e.get('transactionNo')==number(b,'Leg 2'))
 check('shared external reference does not merge records '+str(same),ea['reference']==eb['reference']=='EXT-SHARED-001' and ea['batchId']!=eb['batchId'])

periods=[{'id':'P1','paymentBaseDate':'2026-01-01','premium':500,'paymentTermsDays':30,'reinsurerPaymentTerms':{'r1':90}},{'id':'P2','paymentBaseDate':'2026-03-01','premium':500,'paymentTermsDays':30,'reinsurerPaymentTerms':{'r1':90}}]
samequarter=make(installmentEnabled=True,performanceInstallments=periods);collect(samequarter)
alloc=[]
for no,d in ds(samequarter).items():
 if d.get('greatAmericanFacility'):alloc.append({'caseUid':str(samequarter.case_uid),'rowVersion':samequarter.row_version,'txNo':no,'amount':abs(d['outstanding'])})
response=api('record_transaction_payments',paymentDate='2026-10-20',reference='EXT-PERIODS',amount=sum(r['amount'] for r in alloc),allocations=alloc)
check('same deadline periods cannot be registered together',response.status_code==400 and response.json()['error']=='great_american_payment_rule')
for part in alloc:
 check('period registered individually using shared external reference '+part['txNo'],pay(samequarter,part['txNo'],reference='EXT-PERIODS').status_code==200)
check('period registration preserves original dates',len({d['contractDueDate'] for d in ds(samequarter).values() if d.get('greatAmericanFacility')})==1)
splitcase=make(splitEnabled=True,splitParties=[{'name':'QA A','pct':50},{'name':'QA B','pct':50}]);collect(splitcase)
alloc=[]
for no,d in ds(splitcase).items():
 if d.get('greatAmericanFacility'):alloc.append({'caseUid':str(splitcase.case_uid),'rowVersion':splitcase.row_version,'txNo':no,'amount':abs(d['outstanding'])})
check('underlying split legs remain one case-period registration',api('record_transaction_payments',paymentDate='2026-10-20',reference='EXT-SPLIT',amount=sum(x['amount'] for x in alloc),allocations=alloc).status_code==200)
legacy=make(installmentEnabled=True,performanceInstallments=periods)
legacy.payload['transactions']=build_premium_transactions(legacy.payload);legacy.save()
response=pay(legacy,number(legacy,'Leg 1'))
check('legacy multi-period total cannot auto-distribute a new registration',response.status_code==400 and response.json()['error']=='great_american_payment_rule')

refund=make(parent=mixed,parentTwRef=mixed.tw_ref,endoEffectiveDate='2026-03-31',endorsementAnnouncedAt='2026-03-31T17:00:00Z',originalPremium=-200,reinsurers=[{'name':NAME,'sharePct':50,'premium':-80,'riCommPct':0,'taxPct':0,'paymentTermsDays':90},{'name':'Ordinary GA QA','sharePct':50,'premium':-80,'riCommPct':0,'taxPct':0,'paymentTermsDays':45}])
rf1=number(refund,'Leg 1');rfga=number(refund,'Leg 2');rfother=number(refund,'Leg 2',1)
check('Cedant refund cannot precede all refunds',pay(refund,rf1).status_code==400)
assert pay(refund,rfga).status_code==200
check('refund full cash remains overdue until manual confirmation',ds(refund)[rfga]['paymentStatus']=='overdue')
assert confirm(refund,rfga).status_code==200 and pay(refund,rfother).status_code==200
check('other reinsurer refund must also be confirmed',pay(refund,rf1).status_code==400)
assert confirm(refund,rfother).status_code==200
check('partial Cedant refund is rejected',pay(refund,rf1,50).status_code==400)
alloc=[]
for no,d in ds(refund).items():
 if d['partyType']=='cedant' and d['amount']<0:alloc.append({'caseUid':str(refund.case_uid),'rowVersion':refund.row_version,'txNo':no,'amount':abs(d['outstanding'])})
check('one remittance refunds entire endorsement immediately',api('record_transaction_payments',paymentDate='2026-10-20',amount=sum(x['amount'] for x in alloc),allocations=alloc).status_code==200)
check('refund confirmations cannot be undone after paying Cedant',confirm(refund,rfga,True).status_code==409)
for party,idx in (('cedant',0),('reinsurer',0),('reinsurer',1)):
 original=[i for i in schedules(case_payload(mixed)) if i['partyType']==party][idx]
 returned=[i for i in schedules(case_payload(refund)) if i['partyType']==party][idx]
 mixed.refresh_from_db();refund.refresh_from_db()
 response=api('record_premium_offset',originalCaseUid=str(mixed.case_uid),refundCaseUid=str(refund.case_uid),originalRowVersion=mixed.row_version,refundRowVersion=refund.row_version,originalKey=original['scheduleKey'],refundKey=returned['scheduleKey'],paymentDate='2026-10-20',amount=abs(returned['amount']))
 check('GA premium/refund netting rejected '+party+str(idx),response.status_code==400 and response.json()['error']=='great_american_offset_not_allowed',response.content)

root=make();stamp=datetime(2026,10,18,17,tzinfo=timezone.utc)
def claim(action,**kw):
 root.refresh_from_db();return staff.post('/api/claims',json.dumps({'action':action,'caseUid':str(root.case_uid),'rowVersion':root.row_version,**kw}),content_type='application/json')
check('claim creation succeeds',claim('create_claim',claim={'dateOfLoss':'2026-03-25','outstandingReserve':2000}).status_code==200)
with patch('cases.claims_views.timezone',SimpleNamespace(now=lambda:stamp)):
 response=claim('record_payment',claimId=1,payment={'date':'2020-01-01','amount':1000,'claimAnnouncedAt':'1900-01-01'})
check('claim obligation announces successfully',response.status_code==200,response.content)
no=number(root,'Claim Leg 1');root.refresh_from_db();stored=next(t for t in root.payload['transactions'] if t['txNo']==no)
check('Claim Announced timestamp is server-owned',stored['claimAnnouncedAt']==stamp.isoformat())
for day,tracking,nextday in [('2026-10-26',True,'2026-10-26'),('2026-10-27',False,'2026-11-02'),('2026-11-02',True,'2026-11-02'),('2026-11-09',True,'2026-11-09')]:
 d=ds(root,day)[no];check('claim calendar15/7 '+day,(d['baseDate'],d['contractDueDate'],d['trackingDue'],d['nextTrackingDate'])==('2026-10-19','2026-11-03',tracking,nextday))
root.refresh_from_db();v=root.row_version
check('follow-up permission enforced',api('record_great_american_claim_followup',staff,caseUid=str(root.case_uid),rowVersion=v,txNo=no,note='QA').status_code==403)
check('follow-up rejects blank note',api('record_great_american_claim_followup',caseUid=str(root.case_uid),rowVersion=v,txNo=no,note=' ').status_code==400)
check('manual claim follow-up saved',api('record_great_american_claim_followup',caseUid=str(root.case_uid),rowVersion=v,txNo=no,note='Contacted GA; awaiting full receipt').status_code==200)
check('stale follow-up conflicts',api('record_great_american_claim_followup',caseUid=str(root.case_uid),rowVersion=v,txNo=no,note='stale').status_code==409)
check('follow-up retains accountant and time',ds(root)[no]['trackingHistory'][0]['recordedByName']==finance.name and ds(root)[no]['trackingHistory'][0]['recordedAt'])
check('partial claim receipt accepted',pay(root,no,400).status_code==200)
d=ds(root,'2026-11-09')[no];check('partial claim retains original due/reminders',d['outstanding']==600 and d['contractDueDate']=='2026-11-03' and d['trackingDue'])
check('remaining claim receipt accepted',pay(root,no,600).status_code==200)
d=ds(root,'2026-11-09')[no];check('full receipt without manual confirmation keeps claim overdue and reminder',d['paymentStatus']=='overdue' and d['trackingDue'] and d['nextTrackingDate'])
check('claim full receipt manual confirmation succeeds',confirm(root,no).status_code==200)
d=ds(root,'2026-11-09')[no];check('manual confirmation stops claim reminders',d['paymentStatus']=='settled' and not d['trackingDue'] and not d['nextTrackingDate'])
with patch('cases.claims_views.timezone',SimpleNamespace(now=lambda:datetime(2026,11,2,1,tzinfo=timezone.utc))):
 check('new claim request succeeds',claim('record_payment',claimId=1,payment={'date':'2026-03-25','amount':100}).status_code==200)
newno=number(root,'Claim Leg 1',1);check('new request independently starts15-day deadline',ds(root)[newno]['contractDueDate']=='2026-11-17' and ds(root)[no]['contractDueDate']=='2026-11-03')
with patch('cases.claims_views.timezone',SimpleNamespace(now=lambda:datetime(2026,11,2,1,tzinfo=timezone.utc))):
 check('third claim request is created independently',claim('record_payment',claimId=1,payment={'date':'2026-03-25','amount':100}).status_code==200)
third=number(root,'Claim Leg 1',2);root.refresh_from_db()
alloc=[{'caseUid':str(root.case_uid),'rowVersion':root.row_version,'txNo':n,'amount':100} for n in (newno,third)]
response=api('record_transaction_payments',paymentDate='2026-10-20',reference='EXT-CLAIM',amount=200,allocations=alloc)
check('same-date claim requests are registered individually',response.status_code==400 and response.json()['error']=='great_american_payment_rule')
check('claim request2 may use shared external reference',pay(root,newno,reference='EXT-CLAIM').status_code==200)
check('claim request3 may reuse shared external reference',pay(root,third,reference='EXT-CLAIM').status_code==200)
from reminders.messages import due_kind
check('GA reminders remain screen-only',due_kind(d,'2026-11-09',{})=='')
listing=fin.get('/api/accounting?view=list');check('lean accounting returns GA schedules',listing.status_code==200 and any(i.get('greatAmericanFacility') for i in listing.json()['scheduleRows']))
check('claim tracking reaches transaction rows',any(i.get('greatAmericanClaim') and 'nextTrackingDate' in i for i in listing.json()['transactionRows']))
root.refresh_from_db()
check('completed claim cannot receive further follow-up',api('record_great_american_claim_followup',caseUid=str(root.case_uid),rowVersion=root.row_version,txNo=no,note='already complete').status_code==400)
from cases.great_american_accounting import claim_is_great_american
fake={'source':'claim','reinsurerIdx':0,'greatAmericanFacility':True}
check('claim marker cannot activate another reinsurer',not claim_is_great_american(raw(reinsurers=[{'name':'Ordinary'}]),fake))
fake.update(txNo='HIST-CLM1-P1-R1-T1',splitSource={'classOfBusiness':'CGL','reinsurers':[{'name':NAME}]})
check('historical claim split class bounds Property rule',not claim_is_great_american(raw(),fake))
print(f'{len(checks)}/{len(checks)} Great American accounting checks passed',flush=True)
