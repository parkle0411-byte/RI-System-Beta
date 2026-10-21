"""Cash allocation integration checks, exclusively in the disposable QA database."""
import copy,json,os
from django.contrib.auth import get_user_model
from django.db import transaction
from django.test import Client
from cases.calc.accounting import build_premium_transactions
from cases.cash_ledger import transaction_details
from cases.models import Case
from personnel.models import Personnel
assert os.environ.get('RI_DISPOSABLE_QA')=='true'
checks=[]
def check(name,condition,extra=None):
    assert condition,(name,extra) if extra is not None else name
    checks.append(name);print('PASS '+name)
def client(tag,role='accounting',dept='finance'):
    u=get_user_model().objects.create_user(username='zz.unified.'+tag,password='Unified-QA-Password-9!')
    Personnel.objects.create(name='ZZ Unified '+tag,department=dept,role_code=role,auth_user_id=str(u.pk),account_status='active',created_by='qa',updated_by='qa')
    c=Client(HTTP_HOST='localhost');c.force_login(u);return c
def make(ref,**over):
    p={'twRef':ref,'currency':'TWD','statementNo':'SOA-'+ref,'reinsured':'QA Cedant', 'policyFrom':'2026-09-01','policyTo':'2027-09-01','paymentTermsDays':30,'originalPremium':1000,'riCommPct':0,'taxPct':0,'reinsurers':[{'name':'QA RI','sharePct':100,'premium':800,'riCommPct':0,'taxPct':0,'paymentTermsDays':30}], 'paymentEntries':[]}
    p.update(over)
    # 2026-10-16「92 項會計規則」：每家再保人約定天數須獨立填寫、不繼承 Cedant；缺漏列待確認、不得收付，夾具補齊
    for r in p['reinsurers']:r.setdefault('paymentTermsDays',30)
    if p.get('parentTwRef'):p.update(endorsementAnnouncedAt='2026-09-01T00:00:00Z',endoEffectiveDate='2026-09-01')
    p['transactions']=build_premium_transactions(p)
    return Case.objects.create(tw_ref=ref,status='closed',payload=p,currency=p['currency'],created_by='qa',updated_by='qa')
def rows(c):c.refresh_from_db();return transaction_details(c.payload)
def no(c,leg):return next(t['txNo'] for t in c.payload['transactions'] if t['legType']==leg)
def alloc(c,leg,value):c.refresh_from_db();return {'caseUid':str(c.case_uid),'txNo':no(c,leg),'rowVersion':c.row_version,'amount':value}
def post(c,body):return c.post('/api/accounting',data=json.dumps(body),content_type='application/json')
def settle(c,case,leg):
    # 2026-10-14：不再自動結清，餘額歸零後由會計人工確認
    case.refresh_from_db();return post(c,{'action':'confirm_facility_settlement','caseUid':str(case.case_uid),'rowVersion':case.row_version,'txNo':no(case,leg),'note':'QA reconciled'})
def pay(c,allocations,total=None,**over):return post(c,{'action':'record_transaction_payments','paymentDate':'2026-10-07','amount':total if total is not None else sum(a['amount'] for a in allocations),'allocations':allocations,**over})
def reverse(c,bid,cases,**over):
    versions=[]
    for case in cases:case.refresh_from_db();versions.append({'caseUid':str(case.case_uid),'rowVersion':case.row_version})
    # 2026-10-16「92 項會計規則」：更正（沖回）須填原因並保留歷史
    return post(c,{'action':'reverse_batch_payment','batchId':bid,'cases':versions,'note':'QA correction',**over})
class Rollback(Exception):pass
try:
 with transaction.atomic():
    fin=client('finance');admin=client('admin','admin','admin');read=client('read','sales','reinsurance')
    a,b=make('QA-A'),make('QA-B')
    original=copy.deepcopy(a.payload['transactions'])
    # 2026-10-16「92 項會計規則」：保費每次須登錄整筆餘額（只有賠款可部分收付），跨案同對象改以整筆餘額登錄
    partial=pay(fin,[alloc(a,'Leg 1',200)])
    check('partial premium allocation rejected (whole balance required)',partial.status_code==400 and rows(a)[no(a,'Leg 1')]['paid']==0)
    result=pay(fin,[alloc(a,'Leg 1',1000),alloc(b,'Leg 1',1000)],reference='BANK-001')
    check('same counterparty across cases records one remittance',result.status_code==200)
    bid=result.json()['batchId'];ra,rb=rows(a),rows(b)
    check('manual allocation is isolated per transaction',ra[no(a,'Leg 1')]['paid']==1000 and rb[no(b,'Leg 1')]['paid']==1000 and ra[no(a,'Leg 2')]['paid']==0)
    # 2026-10-14：不再自動結清；餘額歸零後為 pending_confirmation，須會計人工確認
    check('T3 is derived and cannot be recorded independently',ra[no(a,'Leg 3')]['settlement']=='open' and not ra[no(a,'Leg 3')]['canRecord'])
    response=fin.get('/api/accounting').json();batch=next(x for x in response['cashBatches'] if x['batchId']==bid)
    check('batch history retains all allocations and bank reference',len(batch['allocations'])==2 and batch['amount']==2000 and batch['reference']=='BANK-001')
    # 2026-10-16「92 項會計規則」：保費須整筆餘額；驗證改在未收付的案件 v 上以整筆金額測試，才能觸及各自的錯誤
    v,w=make('QA-V'),make('QA-W')
    for label,allocations,total,error in [
      ('manual sum',[alloc(v,'Leg 1',1000)],1001,'allocation_mismatch'),
      ('cash direction',[alloc(v,'Leg 1',1000),alloc(v,'Leg 2',800)],1800,'incompatible_allocations'),
      ('duplicate transaction',[alloc(v,'Leg 1',1000),alloc(v,'Leg 1',1000)],2000,'duplicate_allocation'),
      # 2026-10-16：保費超額即「非整筆餘額」，由整筆規則擋下；賠款超額（overpayment）見下方賠款段
      ('premium overpayment',[alloc(v,'Leg 1',1001)],1001,'swiss_payment_blocked'),
      ('premium partial',[alloc(v,'Leg 1',999)],999,'swiss_payment_blocked'),
      ('fully received premium',[alloc(a,'Leg 1',1)],1,'transaction_not_payable'),
      ('retained brokerage',[alloc(v,'Leg 3',1)],1,'transaction_not_payable')]:
       target=a if label=='fully received premium' else v
       before=copy.deepcopy(target.payload);res=pay(fin,allocations,total);target.refresh_from_db()
       check(label+' rejected without writes',res.status_code==400 and res.json()['error']==error and target.payload==before)
    for val in [True,0,-1,0.001,'NaN','Infinity']:
       allocation=alloc(v,'Leg 1',1);allocation['amount']=val
       check('invalid amount '+str(val)+' rejected',pay(fin,[allocation],1).status_code==400)
    check('invalid calendar date rejected',pay(fin,[alloc(v,'Leg 1',1000)],paymentDate='2026-02-30').status_code==400)
    check('read-only role cannot record or reverse',pay(read,[alloc(v,'Leg 1',1000)]).status_code==403 and reverse(read,bid,[a,b]).status_code==403)
    stale=alloc(w,'Leg 1',1000);stale['rowVersion']-=1;valid=alloc(v,'Leg 1',1000);before=copy.deepcopy(v.payload)
    check('one stale case blocks complete batch',pay(fin,[valid,stale]).status_code==409)
    v.refresh_from_db();check('no partial write on stale batch',v.payload==before)
    other=make('QA-C',currency='USD');different=make('QA-D',reinsured='Another Cedant')
    check('mixed currency rejected',pay(fin,[alloc(v,'Leg 1',1000),alloc(other,'Leg 1',1000)]).json().get('error')=='incompatible_allocations')
    check('different actual counterparty rejected',pay(fin,[alloc(v,'Leg 1',1000),alloc(different,'Leg 1',1000)]).json().get('error')=='incompatible_allocations')
    check('incomplete reversal blocked',reverse(fin,bid,[a]).status_code==400)
    entry=a.payload['paymentEntries'][0]
    check('batch cannot be reversed one allocation at a time',post(fin,{'action':'reverse_payment','caseUid':str(a.case_uid),'rowVersion':a.row_version,'entryId':entry['id']}).json()['error']=='batch_reverse_required')
    check('complete batch reversal succeeds',reverse(fin,bid,[a,b]).status_code==200)
    check('reversal restores all balances and T3',rows(a)[no(a,'Leg 1')]['paid']==0 and rows(b)[no(b,'Leg 1')]['paid']==0 and rows(a)[no(a,'Leg 3')]['settlement']=='open')
    check('repeated reversal rejected',reverse(fin,bid,[a,b]).status_code==409)
    check('immutable original transactions preserved',a.payload['transactions']==original)
    check('T1 full collection recorded',pay(fin,[alloc(a,'Leg 1',1000)]).status_code==200)
    check('T3 waits for T2',rows(a)[no(a,'Leg 3')]['settlement']=='open')
    full=pay(fin,[alloc(a,'Leg 2',800)]);check('T2 actual payment alone does not settle brokerage',full.status_code==200 and rows(a)[no(a,'Leg 3')]['settlement']=='open')
    check('cleared T1 and T2 settle only by manual confirmation',rows(a)[no(a,'Leg 2')]['settlement']=='pending_confirmation' and settle(fin,a,'Leg 1').status_code==200 and settle(fin,a,'Leg 2').status_code==200)
    check('brokerage settles after T1 and T2 confirmation plus its own confirmation',settle(fin,a,'Leg 3').status_code==200 and rows(a)[no(a,'Leg 3')]['settlement']=='settled' and rows(a)[no(a,'Leg 3')]['paid']==200)
    # 2026-10-16「92 項會計規則」：曾銷帳金額永久鎖定；T3 完成後整組都不能取消 → 已銷帳的 T2 不可再沖回，T3 維持已銷帳
    locked=reverse(fin,full.json()['batchId'],[a])
    check('settled T2 cash cannot be reversed and T3 stays settled',locked.status_code==409 and locked.json()['error']=='settled_amount_locked' and rows(a)[no(a,'Leg 3')]['settlement']=='settled' and rows(a)[no(a,'Leg 2')]['settlement']=='settled')
    refund=make('QA-REFUND',parentTwRef='ROOT',originalPremium=-1000,reinsurers=[{'name':'QA RI','sharePct':100,'premium':-800,'riCommPct':0,'taxPct':0}])
    check('refund T1 pays Cedant and T2 receives RI recovery',rows(refund)[no(refund,'Leg 1')]['paymentDirection']=='payable' and rows(refund)[no(refund,'Leg 2')]['paymentDirection']=='receivable')
    # 2026-10-20「四類會計收付」：再保退款須全額實收並逐筆人工銷帳後，才可一次全額退清 Cedant；保費（含退費）均整筆登錄
    check('Cedant refund waits for the reinsurer refund receipt and settlement',pay(fin,[alloc(refund,'Leg 1',1000)]).status_code==400 and rows(refund)[no(refund,'Leg 1')]['paid']==0)
    check('partial refund rejected (whole balance required)',pay(fin,[alloc(refund,'Leg 2',400)]).status_code==400)
    check('reinsurer refund received in full and settled',pay(fin,[alloc(refund,'Leg 2',800)]).status_code==200 and settle(fin,refund,'Leg 2').status_code==200)
    check('full refund preserves signed cash and balance',pay(fin,[alloc(refund,'Leg 1',1000)]).status_code==200 and rows(refund)[no(refund,'Leg 1')]['paid']==-1000 and rows(refund)[no(refund,'Leg 1')]['outstanding']==0)
    # 2026-10-16／10-20：賠款建立即建帳，到期日＝建帳台灣日期＋15 日；夾具補上建帳時間（createdAt），否則無到期日、不能收付
    claim=make('QA-CLAIM');claim.payload['transactions']=[{'txNo':'QA-CLAIM-C1-T1','source':'claim','legType':'Claim Leg 1','reinsurer':'QA RI','amount':100,'settlement':'open','createdAt':'2026-10-01T02:00:00Z'},{'txNo':'QA-CLAIM-C1-T2','source':'claim','legType':'Claim Leg 2','reinsurer':'QA RI','amount':100,'settlement':'open','createdAt':'2026-10-01T02:00:00Z'}];claim.save()
    check('claim obligation creates no actual cash',all(d['paid']==0 for d in rows(claim).values()))
    check('claim due date is creation Taiwan date plus 15 days',rows(claim)['QA-CLAIM-C1-T1']['contractDueDate']=='2026-10-16')
    check('claim Cedant leg resolves actual counterparty',rows(claim)['QA-CLAIM-C1-T2']['partyName']=='QA Cedant')
    before=copy.deepcopy(claim.payload);res=pay(fin,[alloc(claim,'Claim Leg 1',101)]);claim.refresh_from_db()
    check('claim overpayment rejected without writes',res.status_code==400 and res.json()['error']=='overpayment' and claim.payload==before)
    # 2026-10-16：只有賠款可部分收付
    check('partial claim receipt accepted',pay(fin,[alloc(claim,'Claim Leg 1',40)]).status_code==200 and rows(claim)['QA-CLAIM-C1-T1']['outstanding']==60)
    check('claim RI receipt recorded independently',pay(fin,[alloc(claim,'Claim Leg 1',60)]).status_code==200 and rows(claim)['QA-CLAIM-C1-T2']['paid']==0)
    check('claim Cedant payment settles independently',pay(fin,[alloc(claim,'Claim Leg 2',100)]).status_code==200 and rows(claim)['QA-CLAIM-C1-T2']['settlement']=='pending_confirmation' and settle(fin,claim,'Claim Leg 2').status_code==200 and rows(claim)['QA-CLAIM-C1-T2']['settlement']=='settled')
    multi=make('QA-MULTI',reinsurers=[{'name':'RI A','sharePct':60,'premium':800,'riCommPct':0,'taxPct':0},{'name':'RI B','sharePct':40,'premium':800,'riCommPct':0,'taxPct':0}])
    # 2026-10-16：保費整筆餘額；第一家 T1 全額登錄，第二家 T1 用舊排程（未指定交易）現金驗證只計一次
    t1s=[t['txNo'] for t in multi.payload['transactions'] if t['legType']=='Leg 1'];first=abs(rows(multi)[t1s[0]]['outstanding'])
    check('multi RI single T1 allocation does not settle other T1',pay(fin,[alloc(multi,'Leg 1',first)]).status_code==200 and rows(multi)[t1s[1]]['paid']==0)
    legacy_key=rows(multi)[t1s[1]]['cashParts'][0]['scheduleKey']
    multi.payload['paymentEntries'].append({'id':'legacy','entryType':'payment','scheduleKey':legacy_key,'amount':100,'paymentDate':'2026-10-07'});multi.save()
    details=rows(multi);check('legacy schedule cash counted once beside tagged cash',sum(d['paid'] for no_,d in details.items() if '-T1' in no_)==first+100 and details[t1s[1]]['paid']==100)
    split=make('QA-SPLIT',splitEnabled=True,splitParties=[{'pct':60},{'pct':40}]);sd=rows(split)
    check('split T3 dependencies stay within a/b suffix',all(len(d.get('settlementDependencies',[]))==2 for d in sd.values() if d['cashTracking']=='derived'))
    unposted=make('QA-UNPOSTED');unposted.payload['transactions']=[];unposted.save()
    check('preclose schedule never fabricates transaction rows',not any(r['caseUid']==str(unposted.case_uid) for r in fin.get('/api/accounting').json()['transactionRows']))
    check('case SoA settlement agrees with Accounting',admin.get('/api/cases?caseUid='+str(a.case_uid)).json()['case']['payload']['transactions'][0]['paymentScheduleSettlement']==rows(a)[no(a,'Leg 1')]['settlement'])
    # 2026-10-16：保費整筆餘額；2026-10-20 逐步取位：USD 保留兩位小數 → 改以 USD 整筆含分的餘額驗證保留 cents
    extra=make('QA-TWO',currency='USD',originalPremium=1000.05,reinsurers=[{'name':'RI A','sharePct':60,'premium':800,'riCommPct':0,'taxPct':0},{'name':'RI B','sharePct':40,'premium':800,'riCommPct':0,'taxPct':0}])
    legs=[t for t in extra.payload['transactions'] if t['legType']=='Leg 1']
    version=extra.row_version
    dues=[abs(rows(extra)[t['txNo']]['outstanding']) for t in legs]
    allocations=[{'caseUid':str(extra.case_uid),'txNo':t['txNo'],'rowVersion':version,'amount':d} for t,d in zip(legs,dues)]
    tiny=pay(fin,allocations,round(sum(dues),2))
    check('two allocations in one case preserve cents and increment version once',tiny.status_code==200 and any(round(d*100)%100 for d in dues) and [rows(extra)[t['txNo']]['paid'] for t in legs]==dues and extra.row_version==version+1,(tiny.content[:200],dues))
    check('negative claim direction follows actual liability sign',transaction_details({'reinsured':'QA Cedant','currency':'TWD','transactions':[{'txNo':'NEG-C1-T2','source':'claim','legType':'Claim Leg 2','amount':-10}]})['NEG-C1-T2']['paymentDirection']=='receivable')
    missing=make('QA-MISSING',reinsured='')
    check('missing actual counterparty blocks cash allocation',pay(fin,[alloc(missing,'Leg 1',1000)]).status_code==400)
    bad=alloc(extra,'Leg 1',1);bad['txNo']='DOES-NOT-EXIST'
    check('unknown transaction rejected',pay(fin,[bad]).status_code==400)
    bad_reverse=post(fin,{'action':'reverse_batch_payment','batchId':tiny.json()['batchId'],'cases':[{'caseUid':[],'rowVersion':1}]})
    check('malformed reversal case reference rejected',bad_reverse.status_code==400)
    history=make('QA-HISTORY');history.payload['transactions'][0]['reversed']=True;history.save()
    check('historical reversed transaction cannot accept new cash',pay(fin,[alloc(history,'Leg 1',1000)]).status_code==400)
    # 2026-10-16：每期 Cedant 及每期每家再保人天數須獨立填寫、不繼承，夾具逐期補齊
    inst=make('QA-INSTALLMENTS',installmentEnabled=True,performanceInstallments=[{'id':'i1','performanceMonth':'2026-09','premium':400,'paymentBaseDate':'2026-09-01','paymentTermsDays':30,'reinsurerPaymentTerms':{'r1':30}},{'id':'i2','performanceMonth':'2026-10','premium':600,'paymentBaseDate':'2026-10-01','paymentTermsDays':30,'reinsurerPaymentTerms':{'r1':30}}])
    from cases.calc.payment_terms import premium_installment_plan
    plan=premium_installment_plan(inst.payload)
    inst.payload['transactions']=build_premium_transactions(inst.payload,plan[0]);inst.status='posted';inst.save()
    check('only generated installment transactions appear',len([r for r in fin.get('/api/accounting').json()['transactionRows'] if r['caseUid']==str(inst.case_uid)])==3)
    check('generated installment can collect its own balance',pay(fin,[alloc(inst,'Leg 1',400)]).status_code==200 and rows(inst)[no(inst,'Leg 1')]['settlement']=='pending_confirmation')
    raise Rollback()
except Rollback:pass
print(f'{len(checks)}/{len(checks)} passed; database changes rolled back')
