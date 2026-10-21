"""Endorsement premium deltas, signed schedules, real close and refund/recovery APIs.

Synthetic fixtures only; must run against disposable QA database.
"""
import copy, json, os, uuid
from datetime import datetime, timezone as tz
from django.contrib.auth import get_user_model
from django.test import Client
from django.utils import timezone
from cases.models import Case, CaseDocument
from cases.calc.accounting import build_premium_transactions
from cases.calc.payment_terms import build_payment_schedule, reminder_kind
from reminders.messages import due_kind, message
from personnel.models import Personnel

assert os.environ.get('RI_DISPOSABLE_QA') == 'true'
checks=[]
def check(name,condition):
    assert condition,name
    checks.append(name); print('PASS '+name,flush=True)
user=get_user_model().objects.create_user(username='zz.refunds.api',password='Refund-API-Password-9!')
person=Personnel.objects.create(name='QA Refund AE',department='admin',role_code='admin',auth_user_id=str(user.pk),
    account_status='active',created_by='qa',updated_by='qa')
c=Client(enforce_csrf_checks=True,HTTP_HOST='localhost',raise_request_exception=False)
def call(method,url,body=None):
    c.get('/api/auth/csrf');kw={'HTTP_X_CSRFTOKEN':c.cookies['csrftoken'].value}
    if body is not None:kw.update(data=json.dumps(body),content_type='application/json')
    return getattr(c,method)(url,**kw)
assert call('post','/api/auth/login',{'username':user.username,'password':'Refund-API-Password-9!'}).status_code==200
ready=dict(reinsuranceStructure='QS',ae=person.name,currency='TWD',classOfBusiness='QA Class',classCode='PAR',newOrRenew='New',
    typePrefix='Fire',reinsured='QA Refund Cedant',originalInsured='QA Refund Policy',policyFrom='2037-05-01',policyTo='2038-05-01',
    interest='Buildings',situations=[{'address':'QA Road','postcode':'100'}],
    reinsurers=[{'name':'QA Refund Re','foreignBroker':'QA Refund RI Broker','sharePct':100,'premium':8000,'riCommPct':5,'taxPct':1}],
    limitOfLiability=1000000,deductibles='As original',originalConditions='As original',occupation='Office',construction='Concrete',
    sumInsured=[{'category':'Building','amount':1000000}],lossAdvisedDate='2037-04-01',lossRecordYears=5,
    originalPremium=10000,paymentTermsDays=30,riCommPct=10,taxPct=1)
r=call('post','/api/cases',{'case':ready});assert r.status_code==201,r.content
root=Case.objects.get(case_uid=r.json()['case']['caseUid'])
root.tw_ref='TWPAR3705001';root.status='closed';root.announced_at=timezone.now()
root.payload['confirmedProductionKeys']=[f'{root.pk}:FULL:R0']
root.payload['transactions']=build_premium_transactions({**root.payload,'twRef':root.tw_ref})
root.payload['paymentEntries']=[{'id':'root-original','entryType':'payment','scheduleKey':'case-effective-date:cedant','amount':100,'paymentDate':'2037-05-01'}]
root.save();root_before=Case.objects.filter(pk=root.pk).values().get()
bad=copy.deepcopy(ready);bad.update(parentTwRef=root.tw_ref,originalPremium=-1000);bad['reinsurers'][0]['premium']=-800
r=call('post','/api/cases',{'case':bad})
check('negative original premium cannot be enabled by spoofed parentTwRef',r.status_code==400)
def endorsement(premium=-1000,re_premium=-800,installments=False,zero_fee=False):
    source=Case.objects.filter(parent_case_id=root.pk).order_by('-id').first() or root
    r=call('post','/api/case-workflow',{'action':'create_endorsement','caseUid':str(source.case_uid),'rowVersion':source.row_version})
    assert r.status_code==201,r.content
    child=Case.objects.get(case_uid=r.json()['case']['caseUid']);payload=copy.deepcopy(child.payload)
    # 2026-10-21 使用者決定（取代 92 項規則第 35 條）：新批單的 Cedant 與再保人付款天數一律沿用來源保單，Draft 仍可修改。
    check('new endorsement inherits the Cedant days of the case it is created from',payload['paymentTermsDays']==source.payload.get('paymentTermsDays'))
    # 測試接著把批單天數改成 30 天（Draft 可修改）
    payload.update(originalPremium=premium,endoEffectiveDate='2037-05-10',endoTypes=['Premium'],endoText='Return premium for this endorsement',statementNo='REFUND-SOA',paymentTermsDays=30)
    payload['reinsurers'][0].update(premium=re_premium,riCommPct=10 if zero_fee else 5,settlementRef='RI-REFUND',paymentTermsDays=30)
    if zero_fee:payload['reinsurers'][0]['riCommPct']=10
    if installments:
        payload.update(installmentEnabled=True,performanceInstallments=[
            {'id':'refund-i1','performanceMonth':'2037-05','paymentBaseDate':'2037-05-10','premium':-250},
            {'id':'refund-i2','performanceMonth':'2037-06','paymentBaseDate':'2037-06-10','premium':-750}])
    return child,payload
child,payload=endorsement()
wrong=copy.deepcopy(payload);wrong['originalPremium']='NaN'
check('endorsement still rejects invalid numeric premiums',call('put','/api/cases',{'caseUid':str(child.case_uid),'rowVersion':1,'case':wrong}).status_code==400)
def save_and_announce(child,payload):
    sent=copy.deepcopy(payload);sent['parentTwRef']='';sent['endorsementSeq']=999
    r=call('put','/api/cases',{'caseUid':str(child.case_uid),'rowVersion':child.row_version,'case':sent})
    assert r.status_code==200,r.content
    child.refresh_from_db()
    check('signed endorsement premiums persist',child.payload['originalPremium']==payload['originalPremium'] and child.payload['reinsurers'][0]['premium']==payload['reinsurers'][0]['premium'])
    check('workflow parent and endorsement sequence cannot be overwritten',child.payload['parentTwRef']==root.tw_ref and child.payload['endorsementSeq']!=999)
    docs=[CaseDocument.objects.create(case=child,kind=kind,reinsurers=['QA Refund Re'] if kind!='offer' else [],
        filename=kind+'.pdf',content_type='application/pdf',byte_size=5,sha256='0'*64,storage_key='qa-'+str(uuid.uuid4()),is_selected=True,uploaded_by='qa') for kind in ['offer','signed']]
    r=call('post','/api/case-announce',{'caseUid':str(child.case_uid),'rowVersion':child.row_version,'confirmed':True,'documentIds':[str(d.pk) for d in docs]})
    assert r.status_code==200,r.content;child.refresh_from_db()
    check('negative-premium endorsement announces successfully',child.status=='posted' and child.tw_ref.startswith(root.tw_ref+'-E'))
    return child
child=save_and_announce(child,payload)
zero,zero_payload=endorsement(-500,-500,zero_fee=True);zero=save_and_announce(zero,zero_payload)
split,split_payload=endorsement(installments=True)
bad=copy.deepcopy(split_payload);bad['performanceInstallments'][0]['premium']=250
r=call('put','/api/cases',{'caseUid':str(split.case_uid),'rowVersion':split.row_version,'case':bad})
check('refund installment signs must agree with total premium',r.status_code==400)
r=call('put','/api/cases',{'caseUid':str(split.case_uid),'rowVersion':split.row_version,'case':split_payload})
check('refund endorsement cannot use installments',r.status_code==400)
split_payload.update(installmentEnabled=False,performanceInstallments=[])
split=save_and_announce(split,split_payload)
def close_month(month):
    preview=call('get','/api/production-report?month='+month).json()
    rep=call('post','/api/production-report',{'action':'generate','month':month,'sourceSignature':preview['sourceSignature']})
    assert rep.status_code in [200,201],rep.content
    report=rep.json()['report']
    r=call('post','/api/production-report',{'action':'close','month':month,'reportUid':report['reportUid'],'rowVersion':report['rowVersion'],'sourceSignature':preview['sourceSignature']})
    assert r.status_code==200,r.content
    return preview
preview=close_month('2037-05')
check('refund production premium and income remain negative',any(r['caseUid']==str(child.case_uid) and r['premium']<0 and r['income']<0 for r in preview['rows']))
check('zero-brokerage refund still appears in production',any(r['caseUid']==str(zero.case_uid) and r['premium']<0 and r['income']==0 for r in preview['rows']))
child.refresh_from_db();zero.refresh_from_db();split.refresh_from_db()
tx=child.payload['transactions']
check('refund generates negative T1 T2 T3 with independent expected amounts',[t['amount'] for t in tx]==[-890,-752,-138])
check('refund is an endorsement transaction, without Reverse or RVS',len(tx)==3 and all('-RVS' not in t['txNo'] and not t.get('reversed') and not t.get('isReversalEntry') for t in tx) and not child.payload.get('pendingReversalOffset'))
check('refund direction labels reverse T1 and T2',tx[0]['label'].startswith('Payable') and tx[1]['label'].startswith('Receivable'))
check('zero-brokerage refund closes with valid T1 T2 and zero T3',zero.status=='closed' and [t['amount'] for t in zero.payload['transactions']]==[-445,-445,0])
check('refund settles as one full premium entry',split.status=='closed' and [t['amount'] for t in split.payload['transactions']]==[-890,-752,-138])
def rows(case):
    return [r for r in call('get','/api/accounting').json()['rows'] if r['caseUid']==str(case.case_uid)]
ledger=rows(child);cedant=next(r for r in ledger if r['partyType']=='cedant');ri=next(r for r in ledger if r['partyType']=='reinsurer')
check('signed refund balances are open, not clipped or falsely settled',cedant['amount']==-890 and cedant['outstanding']==-890 and cedant['settlement']=='open' and ri['amount']==-752)
check('cedant is payable, RI broker is receivable',cedant['partyName']=='QA Refund Cedant' and cedant['paymentDirection']=='payable' and ri['partyName']=='QA Refund RI Broker' and ri['paymentDirection']=='receivable')
check('refund due dates use endorsement effective date',cedant['baseDate']=='2037-05-10' and cedant['dueDate']=='2037-05-25' and ri['dueDate']=='2037-05-30')
def pay(row,amount,version=None):
    child.refresh_from_db()
    return call('post','/api/accounting',{'action':'record_payment','caseUid':str(child.case_uid),'rowVersion':version or child.row_version,
        'scheduleKey':row['scheduleKey'],'paymentDate':'2037-05-20','amount':amount})
def leg(name):
    child.refresh_from_db();return next(t['txNo'] for t in child.payload['transactions'] if t['legType']==name)
# 2026-10-20 四類統一：須先收到所有再保人退款並逐筆人工銷帳，才可一次全額退清 Cedant
r=pay(cedant,890)
check('Cedant refund is blocked until every reinsurer refund is received and settled',r.status_code==400 and next(x for x in rows(child) if x['partyType']=='cedant')['paid']==0)
check('refund recovery still rejects overpayment',pay(ri,752.01).status_code==400)
# 2026-10-16 92 項規則（第 52 項）：保費（含退費）每次須登錄整筆餘額，不得部分收付（取代舊的部分退款情境）
check('partial reinsurer refund receipt is rejected',pay(ri,100).status_code==400)
stale=child.row_version
check('reinsurer recovery accepts a positive cash magnitude for the full balance',pay(ri,752).status_code==200)
check('stale refund writes are rejected',pay(ri,1,version=stale).status_code==409)
child.refresh_from_db();ri_entry=child.payload['paymentEntries'][-1]
check('recovery entry stores signed amount and explicit direction',ri_entry['amount']==-752 and ri_entry['paymentDirection']=='receivable')
check('full receipt alone does not yet release the Cedant refund',pay(cedant,890).status_code==400)
child.refresh_from_db()
r=call('post','/api/accounting',{'action':'confirm_facility_settlement','caseUid':str(child.case_uid),'rowVersion':child.row_version,'txNo':leg('Leg 2'),'note':'QA RI refund write-off'})
check('Finance manually settles the reinsurer refund receipt',r.status_code==200)
check('Cedant refund still rejects overpayment',pay(cedant,890.01).status_code==400)
check('Cedant refund still rejects a partial amount',pay(cedant,100).status_code==400)
check('Cedant refund API accepts a positive cash magnitude for the full balance',pay(cedant,890).status_code==200)
child.refresh_from_db();entry=child.payload['paymentEntries'][-1]
check('refund entry stores signed amount and explicit direction',entry['amount']==-890 and entry['paymentDirection']=='payable')
ledger=rows(child)
# 2026-10-14：餘額歸零後等待會計人工確認
check('full refund and recovery both settle to zero; Cedant awaits manual settlement, RI already settled',all(r['outstanding']==0 for r in ledger)
      and [r['settlement'] for r in ledger if r['partyType']=='cedant']==['pending_confirmation'] and [r['settlement'] for r in ledger if r['partyType']=='reinsurer']==['settled'])
txrows=[r for r in call('get','/api/accounting').json()['transactionRows'] if r['caseUid']==str(child.case_uid)]
check('SoA T1 reflects the full refund awaiting manual settlement',next(r for r in txrows if r['legType']=='Leg 1')['settlement']=='pending_confirmation')
child.refresh_from_db()
# 2026-10-16：record_payment 改為單筆匯款批次，更正須整筆沖回該匯款
r=call('post','/api/accounting',{'action':'reverse_batch_payment','batchId':entry['batchId'],'paymentDate':'2037-05-21','note':'QA mistaken refund',
    'cases':[{'caseUid':str(child.case_uid),'rowVersion':child.row_version}]})
check('mistaken cash payment can be reversed independently',r.status_code==200)
cedant=next(r for r in rows(child) if r['partyType']=='cedant')
check('cash reversal reopens exact refund balance',cedant['outstanding']==-890 and cedant['paid']==0)
check('reversing the Cedant refund keeps the reinsurer receipt',next(r for r in rows(child) if r['partyType']=='reinsurer')['paid']==-752)
child.refresh_from_db()
item=build_payment_schedule(child.payload,datetime(2037,5,25,4,tzinfo=tz.utc))['items'][0]
check('refund screen reminder is not suppressed by negative outstanding',reminder_kind(item,'2037-05-25')=='due_today')
# 2026-10-16 92 項規則（第 83、84 項）：提醒信以實際到期日（較晚日 5/10＋30＝6/9）判斷，畫面維持提前 15 日
check('refund e-mail reminder uses the actual due date',item['contractDueDate']=='2037-06-09' and due_kind(item,'2037-06-09',{})=='due_today'
      and due_kind(item,'2037-06-02',{})=='seven_days_before' and due_kind(item,'2037-05-25',{})=='')
check('refund reminder identifies the actual cash direction','應退分保人' in message(child.payload,'due_today',[item])['html'])
after=Case.objects.filter(pk=root.pk).values().get()
check('parent policy fields, transactions and cash entries remain unchanged',root_before==after)
check('premium refund never turns the endorsement into reversed status',child.status=='closed' and all(not t.get('reversed') for t in child.payload['transactions']))
multi=copy.deepcopy(child.payload);multi['paymentEntries']=[]
multi['reinsurers']=[{**multi['reinsurers'][0],'sharePct':60},
                     {**multi['reinsurers'][0],'name':'QA Second Re','foreignBroker':'','sharePct':40,'premium':-700,'riCommPct':10}]
mt=build_premium_transactions({**multi,'twRef':child.tw_ref})
# 2026-10-20 逐步取位：TWD 每一步四捨五入到整數（佣金／Tax 以取位後分出保費計），取代舊的兩位小數結果 -451.2／-82.8／-249.2／-106.8
check('multiple reinsurers retain independent signed leg amounts',[t['amount'] for t in mt]==[-534,-451,-83,-356,-249,-107])
ms=build_payment_schedule(multi)['items']
check('refund schedule aggregates cedant and separates each RI recovery',[i['amount'] for i in ms]==[-890,-451,-249])
# 2026-10-20 逐步取位：TWD 保費只准整數、每步取整；為保留「分期兩位小數尾差」測試意旨，此情境改用 USD（每步保留兩位小數）
rounding=copy.deepcopy(child.payload);rounding.update(currency='USD',originalPremium=-1000.01,paymentEntries=[],installmentEnabled=True,
    performanceInstallments=[{'id':'round1','premium':-333.33,'performanceMonth':'2037-05','paymentBaseDate':'2037-05-10'},
                             {'id':'round2','premium':-666.68,'performanceMonth':'2037-06','paymentBaseDate':'2037-06-10'}])
rounding['reinsurers'][0]['premium']=-800.01
rs=build_payment_schedule(rounding)['items']
check('unequal refund installments preserve rounded cedant total',rs[0]['amount']==-296.66 and rs[2]['amount']==-593.35)
check('unequal refund installments preserve rounded RI total',rs[1]['amount']==-250.66 and rs[3]['amount']==-501.35)
print(str(len(checks))+'/'+str(len(checks))+' passed',flush=True)
