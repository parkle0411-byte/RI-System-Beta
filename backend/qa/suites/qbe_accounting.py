"""Owner-confirmed QBE Property dates, full manual collection gates and API isolation."""
import copy,json,os
from datetime import datetime,timezone
from unittest.mock import patch
from types import SimpleNamespace
from django.contrib.auth import get_user_model
from django.test import Client
from cases.models import Case
from personnel.models import Personnel
from cases.qbe_accounting import NAME,applies,target
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
 p={'twRef':'QBE-QA','currency':'TWD','classOfBusiness':'Property','reinsuranceStructure':'QS','reinsured':'QBE QA Cedant',
    'policyFrom':'2026-03-20','policyTo':'2027-03-20','paymentTermsDays':30,'originalPremium':1000,'riCommPct':0,'taxPct':0,
    'reinsurers':[{'name':NAME,'sharePct':100,'premium':800,'riCommPct':0,'taxPct':0,'paymentTermsDays':30}],'paymentEntries':[]}
 p.update(kw);return p
def schedules(p,day='2026-01-01'):return build_payment_schedule(p,day+'T01:00:00Z')['items']
def ga(p,day='2026-01-01'):return [i for i in schedules(p,day) if i.get('qbeFacility')]
check('only exact QBE Hongkong Facility Property applies',applies(raw()) and target(raw(),NAME.lower()) and not target(raw(classOfBusiness='CGL'),NAME) and not target(raw(),NAME.replace(' (Facility)','')) and not target(raw(),'QBE Other (Facility)'))
for source,base,remind,due in [('2026-10-20','2026-10-31','','2027-01-29'),('2027-01-30','2027-01-31','','2027-05-01'),('2027-02-15','2027-04-30','','2027-07-29'),('2027-07-20','2027-07-31','','2027-10-29'),('2027-12-20','2028-01-31','','2028-04-30')]:
 # 2026-10-20 四類統一：季末＋80 日開始提醒（取代＋75 日），＋90 日到期不變
 from datetime import date as _date,timedelta as _td
 remind=(_date.fromisoformat(base)+_td(80)).isoformat()
 p=raw(policyFrom=source);before=copy.deepcopy(p);item=ga(p)[0]
 check('quarter plus 90/80 '+source,(item['baseDate'],item['dueDate'],item['contractDueDate'],item['termsDays'])==(base,remind,due,90))
 check('schedule reads do not mutate '+source,p==before)
for klass in ('CGL','Marine','',None):
 p=raw(classOfBusiness=klass);check('other class remains ordinary '+str(klass),not ga(p) and schedules(p)[1]['termsDays']==30)
for premium in (200,-200):
 p=raw(parentTwRef='ROOT',endoEffectiveDate='2026-03-31',endorsementAnnouncedAt='2026-03-31T17:00:00Z',originalPremium=premium)
 p['reinsurers'][0]['premium']=premium*.8;i=ga(p)[0]
 check('endorsement later successful Taiwan Announce '+str(premium),(i['sourceBaseDate'],i['contractDueDate'])==('2026-04-01','2026-07-29'))
 p['endorsementAnnouncedAt']='';check('unannounced endorsement stays pending '+str(premium),not ga(p)[0]['contractDueDate'] and build_payment_schedule(p)['reviewRequired'])
p=raw(installmentEnabled=True,performanceInstallments=[{'id':'I1','paymentBaseDate':'2026-04-30','premium':500,'paymentTermsDays':30,'reinsurerPaymentTerms':{'r1':33}},{'id':'I2','paymentBaseDate':'2026-05-01','premium':500,'paymentTermsDays':30,'reinsurerPaymentTerms':{'r1':45}}])
check('installments use their own Payment Base Date quarters',[i['contractDueDate'] for i in ga(p)]==['2026-07-29','2026-10-29'])
normalized=normalize_draft(p)['value'];check('draft fixes only QBE per-period90',normalized['reinsurers'][0]['paymentTermsDays']==90 and all(i['reinsurerPaymentTerms']['r1']==90 for i in normalized['performanceInstallments']))
check('canonical fixed terms preserve old posted signatures',payment_terms_signature(p)==payment_terms_signature(normalized))
ordinary=normalize_draft(raw(classOfBusiness='CGL'));check('nonProperty Facility draft is rejected by selection scope',any('available only for Property' in e for e in ordinary['errors']))

def client(tag,role,department):
 u=get_user_model().objects.create_user(username='qbe.qa.'+tag,password='QBE-Test-Password-9!')
 who=Personnel.objects.create(name='QBE QA '+tag,department=department,role_code=role,auth_user_id=str(u.pk),account_status='active',created_by='qa',updated_by='qa')
 c=Client(HTTP_HOST='localhost');c.force_login(u);return c,who
fin,finance=client('finance','accounting','finance');staff,ae=client('staff','sales','reinsurance')
count=0
def make(**kw):
 global count;count+=1
 parent=kw.pop('parent',None);p=raw(twRef='QBE-QA-'+str(count),**kw)
 p['transactions']=[t for installment in premium_installment_plan(p) for t in build_premium_transactions(p,installment)] if p.get('installmentEnabled') else build_premium_transactions(p)
 stamp=datetime.fromisoformat(p.get('endorsementAnnouncedAt','2026-01-01T00:00:00Z').replace('Z','+00:00'))
 return Case.objects.create(tw_ref=p['twRef'],status='closed',payload=p,currency='TWD',case_kind='endorsement' if parent else 'original',parent_case=parent,announced_at=stamp,created_by='qa',updated_by='qa')
def api(action,who=fin,**kw):return who.post('/api/accounting',json.dumps({'action':action,**kw}),content_type='application/json')
def ds(c,day='2026-10-20'):
 c.refresh_from_db();return transaction_details(case_payload(c),day+'T01:00:00Z')
def number(c,leg,index=0):
 c.refresh_from_db();return [t['txNo'] for t in c.payload['transactions'] if t['legType']==leg][index]
def pay(c,no,value=None,who=fin,reference='QA synthetic registration'):
 d=ds(c)[no];value=abs(d['outstanding']) if value is None else value
 return api('record_transaction_payments',who,paymentDate='2026-10-20',reference=reference,amount=value,allocations=[{'caseUid':str(c.case_uid),'rowVersion':c.row_version,'txNo':no,'amount':value}])
def confirm(c,no,undo=False):
 c.refresh_from_db();return api('unconfirm_facility_settlement' if undo else 'confirm_facility_settlement',caseUid=str(c.case_uid),rowVersion=c.row_version,txNo=no,note='QA bank/reconciliation reference')
def collect(c):
 for t in [t for t in c.payload['transactions'] if t['legType'].startswith('Leg 1')]:
  assert pay(c,t['txNo']).status_code==200
  assert (ds(c)[t['txNo']]['settlement']=='settled')

c=make();t1=number(c,'Leg 1');t2=number(c,'Leg 2');before=copy.deepcopy(c.payload)
check('payout rejected before receipt',pay(c,t2,400).status_code==409)
c.refresh_from_db();check('blocked payout is atomic',c.payload==before)
check('receipt can be recorded',pay(c,t1).status_code==200)
check('full T1 auto settlement releases payment; partial T2 remains blocked',ds(c)[t2]['paymentAllowed'] and pay(c,t2,400).status_code==400)
check('automatic full Cedant settlement releases payout',(ds(c)[t1]['settlement']=='settled') and ds(c)[t2]['paymentAllowed'])
check('staff cannot record outgoing payment',pay(c,t2,400,staff).status_code==403)
# 2026-10-20 四類統一：QBE 不再允許分次匯出，保費須整筆登錄餘額
before_partial=copy.deepcopy(ds(c)[t2])
check('QBE partial remittance is rejected (full balance only)',pay(c,t2,400).status_code==400 and ds(c)[t2]['outstanding']==before_partial['outstanding'])
check('QBE full remittance accepted',pay(c,t2).status_code==200)
check('cannot cancel whole Cedant confirmation after payout',(confirm(c, t1, True).status_code==400))
check('full payment stops overdue and retains original deadline',ds(c)[t2]['outstanding']==0 and ds(c)[t2]['paymentStatus']=='settled' and ds(c)[t2]['contractDueDate']=='2026-07-29')
check('full payment settles automatically',(ds(c)[t2]['settlement']=='settled'))
check('automatic full settlement stops overdue',ds(c)[t2]['manualSettlementConfirmed'] and ds(c)[t2]['paymentStatus']=='settled')
check('bank return cannot reopen original completion',(confirm(c, t2, True).status_code==400))
c.refresh_from_db();entry=next(e for e in c.payload['paymentEntries'] if e.get('transactionNo')==t2)
check('settled bank remittance cannot be reversed',api('reverse_batch_payment',batchId=entry['batchId'],cases=[{'caseUid':str(c.case_uid),'rowVersion':c.row_version}],paymentDate='2026-10-20',note='bank return').status_code==409)
check('QBE fixed terms cannot be edited',api('complete_payment_terms',staff,caseUid=str(c.case_uid),rowVersion=c.row_version,partyKey='r1',days=30,reason='QA').status_code==409)
from cases.facility_accounting import schedule_signature
probe=copy.deepcopy(c.payload)
for e in probe['paymentEntries']:
 if e.get('transactionNo')==t1:e['nonCash']=True
item=next(i for i in schedules(probe) if i['partyType']=='cedant')
probe.setdefault('facilityAccounting',{}).setdefault('confirmations',{})['schedule:'+item['scheduleKey']]={'confirmed':True,'confirmedAt':'2026-10-20T00:00:00Z','fingerprint':schedule_signature(probe,item)}
check('noncash fee or offset never proves full collected principal',not ga(probe)[0]['paymentAllowed'])

mixed=make(reinsurers=[{'name':NAME,'sharePct':50,'premium':400,'riCommPct':0,'taxPct':0,'paymentTermsDays':30},{'name':'Ordinary QBE QA','sharePct':50,'premium':400,'riCommPct':0,'taxPct':0,'paymentTermsDays':45}])
incoming=[t for t in mixed.payload['transactions'] if t['legType']=='Leg 1'];out=number(mixed,'Leg 2')
assert pay(mixed,incoming[0]['txNo']).status_code==200 and (ds(mixed)[incoming[0]['txNo']]['settlement']=='settled')
check('other reinsurer Cedant share is required',not ds(mixed)[out]['paymentAllowed'])
assert pay(mixed,incoming[1]['txNo']).status_code==200
check('all T1 shares auto settle and release payment',ds(mixed)[out]['paymentAllowed'])
assert (ds(mixed)[incoming[1]['txNo']]['settlement']=='settled')
check('all Cedant shares confirmed release QBE',ds(mixed)[out]['paymentAllowed'])
check('ordinary reinsurer keeps own deadline',ds(mixed)[number(mixed,'Leg 2',1)]['contractDueDate']=='2026-05-04')

period=make(installmentEnabled=True,performanceInstallments=p['performanceInstallments'])
first=number(period,'Leg 1');second=number(period,'Leg 1',1)
assert pay(period,first).status_code==200 and (ds(period)[first]['settlement']=='settled')
check('period1 releases without period2',ds(period)[number(period,'Leg 2')]['paymentAllowed'] and not ds(period)[number(period,'Leg 2',1)]['paymentAllowed'])
for same in (False,True):
 a=make();b=make(policyFrom='2026-03-30' if same else '2026-05-01');collect(a);collect(b);alloc=[]
 for obj in (a,b):
  no=number(obj,'Leg 2');alloc.append({'caseUid':str(obj.case_uid),'rowVersion':obj.row_version,'txNo':no,'amount':800})
 response=api('record_transaction_payments',note='QA synthetic registration', paymentDate='2026-10-20',amount=1600,allocations=alloc)
 check('same deadline requires separate case registrations' if same else 'different deadline requires separate case registrations',response.status_code==400 and response.json()['error']=='single_accounting_case',response.content)
 check('caseA can be manually registered with external reference '+str(same),pay(a,number(a,'Leg 2'),reference='EXT-SHARED-001').status_code==200)
 check('caseB may reuse the same external reference '+str(same),pay(b,number(b,'Leg 2'),reference='EXT-SHARED-001').status_code==200)
 a.refresh_from_db();b.refresh_from_db()
 ea=next(e for e in a.payload['paymentEntries'] if e.get('transactionNo')==number(a,'Leg 2'))
 eb=next(e for e in b.payload['paymentEntries'] if e.get('transactionNo')==number(b,'Leg 2'))
 check('shared external reference does not merge records '+str(same),ea['reference']==eb['reference']=='EXT-SHARED-001' and ea['batchId']!=eb['batchId'])

periods=[{'id':'P1','paymentBaseDate':'2026-04-01','premium':500,'paymentTermsDays':30,'reinsurerPaymentTerms':{'r1':90}},{'id':'P2','paymentBaseDate':'2026-03-01','premium':500,'paymentTermsDays':30,'reinsurerPaymentTerms':{'r1':90}}]
samequarter=make(installmentEnabled=True,performanceInstallments=periods);collect(samequarter)
alloc=[]
for no,d in ds(samequarter).items():
 if d.get('qbeFacility'):alloc.append({'caseUid':str(samequarter.case_uid),'rowVersion':samequarter.row_version,'txNo':no,'amount':abs(d['outstanding'])})
response=api('record_transaction_payments',paymentDate='2026-10-20',reference='EXT-PERIODS',amount=sum(r['amount'] for r in alloc),allocations=alloc)
check('same deadline periods cannot be registered together',response.status_code==400 and response.json()['error']=='single_accounting_period',response.content)
for part in alloc:
 check('period registered individually using shared external reference '+part['txNo'],pay(samequarter,part['txNo'],reference='EXT-PERIODS').status_code==200)
check('period registration preserves original dates',len({d['contractDueDate'] for d in ds(samequarter).values() if d.get('qbeFacility')})==1)
splitcase=make(splitEnabled=True,splitParties=[{'name':'QA A','pct':50},{'name':'QA B','pct':50}]);collect(splitcase)
alloc=[]
for no,d in ds(splitcase).items():
 if d.get('qbeFacility'):alloc.append({'caseUid':str(splitcase.case_uid),'rowVersion':splitcase.row_version,'txNo':no,'amount':abs(d['outstanding'])})
check('underlying split legs remain one case-period registration',api('record_transaction_payments',paymentDate='2026-10-20',reference='EXT-SPLIT',amount=sum(x['amount'] for x in alloc),allocations=alloc).status_code==200)
legacy=make(installmentEnabled=True,performanceInstallments=periods)
# Authentic pre-installment ledger: one aggregate row per leg across both periods.
legacy.payload['transactions']=[{k:v for k,v in {**next(t for t in legacy.payload['transactions'] if t['legType']==leg),'txNo':legacy.tw_ref+'-OLD-T'+str(i),'amount':value}.items() if k not in ('installmentId','installmentLabel','perReinsurer')} for i,(leg,value) in enumerate([('Leg 1',1000),('Leg 2',800),('Leg 3',200)],1)];legacy.save()
response=pay(legacy,number(legacy,'Leg 1'))
check('legacy multi-period total cannot auto-distribute a new registration',response.status_code==400 and response.json()['error']=='single_accounting_period',response.content)

refund=make(parent=mixed,parentTwRef=mixed.tw_ref,endoEffectiveDate='2026-03-31',endorsementAnnouncedAt='2026-03-31T17:00:00Z',originalPremium=-200,reinsurers=[{'name':NAME,'sharePct':50,'premium':-80,'riCommPct':0,'taxPct':0,'paymentTermsDays':90},{'name':'Ordinary QBE QA','sharePct':50,'premium':-80,'riCommPct':0,'taxPct':0,'paymentTermsDays':45}])
rf1=number(refund,'Leg 1');rfga=number(refund,'Leg 2');rfother=number(refund,'Leg 2',1)
check('Cedant refund cannot precede all refunds',pay(refund,rf1).status_code==409)
assert pay(refund,rfga).status_code==200
# 2026-10-20 四類統一：「全額付款後未確認仍逾期」只適用付出款項；向再保人收回的退款全額收到後顯示待人工確認
check('QBE refund receipt settles automatically',ds(refund)[rfga]['paymentStatus']=='settled' and ds(refund)[rfga]['settlement']=='settled')
assert (ds(refund)[rfga]['settlement']=='settled') and pay(refund,rfother).status_code==200
check('Cedant refund must select all independent T1 in one registration',pay(refund,rf1).status_code==400)
assert (ds(refund)[rfother]['settlement']=='settled')
check('partial Cedant refund is rejected',pay(refund,rf1,50).status_code==400)
alloc=[]
for no,d in ds(refund).items():
 if d['partyType']=='cedant' and d['amount']<0:alloc.append({'caseUid':str(refund.case_uid),'rowVersion':refund.row_version,'txNo':no,'amount':abs(d['outstanding'])})
check('one remittance refunds entire endorsement immediately',api('record_transaction_payments',note='QA synthetic registration', paymentDate='2026-10-20',amount=sum(x['amount'] for x in alloc),allocations=alloc).status_code==200)
check('refund confirmations cannot be undone after paying Cedant',(confirm(refund, rfga, True).status_code==400))
for party,idx in (('cedant',0),('reinsurer',0),('reinsurer',1)):
 original=[i for i in schedules(case_payload(mixed)) if i['partyType']==party][idx]
 returned=[i for i in schedules(case_payload(refund)) if i['partyType']==party][idx]
 mixed.refresh_from_db();refund.refresh_from_db()
 response=api('record_premium_offset',originalCaseUid=str(mixed.case_uid),refundCaseUid=str(refund.case_uid),originalRowVersion=mixed.row_version,refundRowVersion=refund.row_version,originalKey=original['scheduleKey'],refundKey=returned['scheduleKey'],paymentDate='2026-10-20',amount=abs(returned['amount']))
 # 2026-10-20：再保人退款一律須全額實收（refund_cash_receipt_required），比 QBE 專屬限制先擋下；兩者都禁止抵銷
 check('QBE premium/refund netting rejected '+party+str(idx),response.status_code==400 and response.json()['error']=='offset_not_allowed',response.content)

root=make();stamp=datetime(2026,10,18,17,tzinfo=timezone.utc)
def claim(action,**kw):
 root.refresh_from_db();return staff.post('/api/claims',json.dumps({'action':action,'caseUid':str(root.case_uid),'rowVersion':root.row_version,**kw}),content_type='application/json')
check('claim creation succeeds',claim('create_claim',claim={'dateOfLoss':'2026-03-25','outstandingReserve':2000}).status_code==200)
with patch('cases.claims_views.timezone',SimpleNamespace(now=lambda:stamp)):
 response=claim('record_payment',note='QA synthetic registration', claimId=1,payment={'date':'2020-01-01','amount':1000,'claimAnnouncedAt':'1900-01-01'})
check('claim obligation announces successfully',response.status_code==200,response.content)
no=number(root,'Claim Leg 1');root.refresh_from_db();stored=next(t for t in root.payload['transactions'] if t['txNo']==no)
check('Claim Announced timestamp is server-owned',stored['createdAt']==stamp.isoformat())
# 2026-10-20 四類統一：賠款建帳＋15 日到期；到期前 7 日、到期日、其後每 7 日提醒（取代建帳第 7 日起追蹤）
for day,tracking,nextday in [('2026-10-26',False,'2026-10-27'),('2026-10-27',True,'2026-10-27'),('2026-11-02',False,'2026-11-03'),('2026-11-03',True,'2026-11-03'),('2026-11-04',False,'2026-11-10'),('2026-11-10',True,'2026-11-10')]:
 d=ds(root,day)[no];check('claim calendar 15 days, reminders 7 days before / due / every 7 days '+day,(d['baseDate'],d['contractDueDate'],d['trackingDue'],d['nextTrackingDate'])==('2026-10-19','2026-11-03',tracking,nextday))
root.refresh_from_db();v=root.row_version
check('follow-up permission enforced',api('record_qbe_claim_followup',staff,caseUid=str(root.case_uid),rowVersion=v,txNo=no,note='QA').status_code==403)
check('follow-up rejects blank note',api('record_qbe_claim_followup',caseUid=str(root.case_uid),rowVersion=v,txNo=no,note=' ').status_code==400)
check('dedicated claim follow-up is retired',api('record_qbe_claim_followup',caseUid=str(root.case_uid),rowVersion=v,txNo=no,note='Contacted QBE; awaiting full receipt').status_code==400)
check('stale follow-up conflicts',api('record_qbe_claim_followup',caseUid=str(root.case_uid),rowVersion=v-1,txNo=no,note='stale').status_code==409)
check('retired follow-up does not create history',not ds(root)[no].get('trackingHistory'))
check('partial claim receipt accepted',pay(root,no,400).status_code==200)
d=ds(root,'2026-11-10')[no];check('partial claim retains original due/reminders',d['outstanding']==600 and d['contractDueDate']=='2026-11-03' and d['trackingDue'])
check('remaining claim receipt accepted',pay(root,no,600).status_code==200)
# 2026-10-20 四類統一：全額收款登錄即停止該筆提醒，不等待銷帳
d=ds(root,'2026-11-10')[no];check('full receipt settles claim and stops reminders',d['paymentStatus']=='settled' and not d['trackingDue'] and not d['nextTrackingDate'],(d['paymentStatus'],d['trackingDue'],d['nextTrackingDate']))
check('claim full receipt is automatically settled',(ds(root)[no]['settlement']=='settled'))
d=ds(root,'2026-11-10')[no];check('full actual receipt automatically settles the claim',d['paymentStatus']=='settled' and not d['trackingDue'] and not d['nextTrackingDate'])
with patch('cases.claims_views.timezone',SimpleNamespace(now=lambda:datetime(2026,11,2,1,tzinfo=timezone.utc))):
 check('new claim request succeeds',claim('record_payment',note='QA synthetic registration', claimId=1,payment={'date':'2026-03-25','amount':100}).status_code==200)
newno=number(root,'Claim Leg 1',1);check('new request independently starts15-day deadline',ds(root)[newno]['contractDueDate']=='2026-11-17' and ds(root)[no]['contractDueDate']=='2026-11-03')
with patch('cases.claims_views.timezone',SimpleNamespace(now=lambda:datetime(2026,11,2,1,tzinfo=timezone.utc))):
 check('third claim request is created independently',claim('record_payment',note='QA synthetic registration', claimId=1,payment={'date':'2026-03-25','amount':100}).status_code==200)
third=number(root,'Claim Leg 1',2);root.refresh_from_db()
alloc=[{'caseUid':str(root.case_uid),'rowVersion':root.row_version,'txNo':n,'amount':100} for n in (newno,third)]
response=api('record_transaction_payments',paymentDate='2026-10-20',reference='EXT-CLAIM',amount=200,allocations=alloc)
check('same-date claim requests are registered individually',response.status_code==400 and response.json()['error']=='single_accounting_period')
check('claim request2 may use shared external reference',pay(root,newno,reference='EXT-CLAIM').status_code==200)
check('claim request3 may reuse shared external reference',pay(root,third,reference='EXT-CLAIM').status_code==200)
from reminders.messages import due_kind
check('settled QBE claim no longer emits reminders',due_kind(d,'2026-11-09',{})=='')
listing=fin.get('/api/accounting?view=list');check('lean accounting returns QBE schedules',listing.status_code==200 and any(i.get('qbeFacility') for i in listing.json()['scheduleRows']))
check('claim tracking reaches transaction rows',any(i.get('source')=='claim' and i.get('claimId')==1 and 'nextTrackingDate' in i for i in listing.json()['transactionRows']))
root.refresh_from_db()
check('completed claim cannot receive further follow-up',api('record_qbe_claim_followup',caseUid=str(root.case_uid),rowVersion=root.row_version,txNo=no,note='already complete').status_code==400)
from cases.qbe_accounting import claim_is_qbe
fake={'source':'claim','reinsurerIdx':0,'qbeFacility':True}
check('claim marker cannot activate another reinsurer',not claim_is_qbe(raw(reinsurers=[{'name':'Ordinary'}]),fake))
fake.update(txNo='HIST-CLM1-P1-R1-T1',splitSource={'classOfBusiness':'CGL','reinsurers':[{'name':NAME}]})
check('historical claim split class bounds Property rule',not claim_is_qbe(raw(),fake))
from datetime import date,timedelta
for source,base,year,quarter in [('2026-07-31','2026-07-31',2025,4),('2026-08-01','2026-10-31',2026,1),('2026-10-31','2026-10-31',2026,1),('2026-11-01','2027-01-31',2026,2),('2027-01-31','2027-01-31',2026,2),('2027-02-01','2027-04-30',2026,3),('2027-04-30','2027-04-30',2026,3),('2027-05-01','2027-07-31',2026,4),('2027-07-31','2027-07-31',2026,4),('2027-08-01','2027-10-31',2027,1),('2028-02-29','2028-04-30',2027,3)]:
 item=ga(raw(policyFrom=source))[0]
 check('underwriting calendar boundary '+source,(item['baseDate'],item['underwritingYear'],item['underwritingQuarter'])==(base,year,quarter))
 check('no holiday adjustment '+source,(item['dueDate'],item['contractDueDate'])==((date.fromisoformat(base)+timedelta(days=80)).isoformat(),(date.fromisoformat(base)+timedelta(days=90)).isoformat()))

# Existing incomplete/partial records use the new dates without changing stored entries.
old=make(policyFrom='2026-10-20')
old.payload['paymentEntries']=[{'id':'old-partial','entryType':'payment','transactionNo':number(old,'Leg 1'),'scheduleKey':'case-effective-date:cedant','amount':200,'paymentDate':'2026-10-20','createdAt':'2026-10-20T00:00:00Z'}]
old.save();before=copy.deepcopy(old.payload)
check('existing open QBE obligations adopt underwriting due date',ds(old)[number(old,'Leg 2')]['contractDueDate']=='2027-01-29')
old.refresh_from_db();check('existing partial cash and historical payload untouched',old.payload==before)

# Simulate pre-feature completion using the unchanged legacy date calculation.
from cases.facility_accounting import schedule_signature,tx_signature
from cases.qbe_accounting import legacy_completed
historic=make();collect(historic)
hno=number(historic,'Leg 2');assert pay(historic,hno).status_code==200 and (ds(historic)[hno]['settlement']=='settled')
historic.refresh_from_db()
# Synthetic pre-feature bank history precedes its historical completion time.
for entry in historic.payload['paymentEntries']:
 entry.update(paymentDate='2026-04-19',createdAt='2026-04-19T00:00:00Z')
for entry in historic.payload['transactions']:
 if entry.get('settlement')=='settled':entry['settledAt']='2026-04-19T00:00:00Z'
# Seed an actual old completed confirmation and its unversioned fingerprint.
old_item=next(i for i in schedules(case_payload(historic)) if i.get('qbeFacility'))
historic.payload['facilityAccounting']={'confirmations':{'schedule:'+old_item['scheduleKey']:{'confirmed':True,'confirmedAt':'2026-04-19T00:00:00Z','fingerprint':schedule_signature(historic.payload,old_item)}}}
historic.save();before=copy.deepcopy(historic.payload)
item=next(i for i in schedules(case_payload(historic)) if i.get('qbeFacility'))
check('completed legacy schedule retains original base and contractual date',(item['baseDate'],item['contractDueDate'],item['termsDays'])==('2026-03-20','2026-04-19',30))
check('completed legacy confirmation remains settled',ds(historic)[hno]['manualSettlementConfirmed'] and ds(historic)[hno]['paymentStatus']=='settled')
historic.refresh_from_db();check('completed historical payload remains byte-equivalent',historic.payload==before)
probe=copy.deepcopy(historic.payload)
probe['paymentEntries']=[e for e in probe['paymentEntries'] if e.get('transactionNo')!=hno]
reopened=next(i for i in schedules(probe) if i.get('qbeFacility'))
check('stale old confirmation cannot exempt an open balance from new dates',reopened['contractDueDate']=='2026-07-29' and not reopened['qbeLegacyCompleted'])
probe=copy.deepcopy(historic.payload)
probe['facilityAccounting']['confirmations']['schedule:'+item['scheduleKey']]['fingerprint']='stale'
reopened=next(i for i in schedules(probe) if i.get('qbeFacility'))
check('invalidated historic fingerprint uses new rule while awaiting confirmation',reopened['contractDueDate']=='2026-07-29' and not reopened['qbeLegacyCompleted'])
check('new QBE confirmation retains new date after completing',ds(c)[t2]['contractDueDate']=='2026-07-29' and not legacy_completed(case_payload(c),next(i['scheduleKey'] for i in schedules(case_payload(c)) if i.get('qbeFacility'))))

print(f'{len(checks)}/{len(checks)} QBE accounting checks passed',flush=True)
