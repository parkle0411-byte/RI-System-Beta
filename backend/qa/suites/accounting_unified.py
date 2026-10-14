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
def check(name,condition):
    assert condition,name
    checks.append(name);print('PASS '+name)
def client(tag,role='accounting',dept='finance'):
    u=get_user_model().objects.create_user(username='zz.unified.'+tag,password='Unified-QA-Password-9!')
    Personnel.objects.create(name='ZZ Unified '+tag,department=dept,role_code=role,auth_user_id=str(u.pk),account_status='active',created_by='qa',updated_by='qa')
    c=Client(HTTP_HOST='localhost');c.force_login(u);return c
def make(ref,**over):
    p={'twRef':ref,'currency':'TWD','statementNo':'SOA-'+ref,'reinsured':'QA Cedant', 'policyFrom':'2026-09-01','policyTo':'2027-09-01','paymentTermsDays':30,'originalPremium':1000,'riCommPct':0,'taxPct':0,'reinsurers':[{'name':'QA RI','sharePct':100,'premium':800,'riCommPct':0,'taxPct':0}], 'paymentEntries':[]}
    p.update(over)
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
    return post(c,{'action':'reverse_batch_payment','batchId':bid,'cases':versions,**over})
class Rollback(Exception):pass
try:
 with transaction.atomic():
    fin=client('finance');admin=client('admin','admin','admin');read=client('read','sales','reinsurance')
    a,b=make('QA-A'),make('QA-B')
    original=copy.deepcopy(a.payload['transactions'])
    result=pay(fin,[alloc(a,'Leg 1',200),alloc(b,'Leg 1',300)],reference='BANK-001')
    check('same counterparty across cases records one remittance',result.status_code==200)
    bid=result.json()['batchId'];ra,rb=rows(a),rows(b)
    check('manual partial allocation is isolated per transaction',ra[no(a,'Leg 1')]['paid']==200 and rb[no(b,'Leg 1')]['paid']==300 and ra[no(a,'Leg 2')]['paid']==0)
    # 2026-10-14：不再自動結清；餘額歸零後為 pending_confirmation，須會計人工確認
    check('T3 is derived and cannot be recorded independently',ra[no(a,'Leg 3')]['settlement']=='open' and not ra[no(a,'Leg 3')]['canRecord'])
    response=fin.get('/api/accounting').json();batch=next(x for x in response['cashBatches'] if x['batchId']==bid)
    check('batch history retains all allocations and bank reference',len(batch['allocations'])==2 and batch['amount']==500 and batch['reference']=='BANK-001')
    for label,allocations,total,error in [
      ('manual sum',[alloc(a,'Leg 1',10)],11,'allocation_mismatch'),
      ('cash direction',[alloc(a,'Leg 1',10),alloc(a,'Leg 2',10)],20,'incompatible_allocations'),
      ('duplicate transaction',[alloc(a,'Leg 1',10),alloc(a,'Leg 1',10)],20,'duplicate_allocation'),
      ('overpayment',[alloc(a,'Leg 1',801)],801,'overpayment'),
      ('retained brokerage',[alloc(a,'Leg 3',1)],1,'transaction_not_payable')]:
       before=copy.deepcopy(a.payload);res=pay(fin,allocations,total);a.refresh_from_db()
       check(label+' rejected without writes',res.status_code==400 and res.json()['error']==error and a.payload==before)
    for val in [True,0,-1,0.001,'NaN','Infinity']:
       allocation=alloc(a,'Leg 1',1);allocation['amount']=val
       check('invalid amount '+str(val)+' rejected',pay(fin,[allocation],1).status_code==400)
    check('invalid calendar date rejected',pay(fin,[alloc(a,'Leg 1',1)],paymentDate='2026-02-30').status_code==400)
    check('read-only role cannot record or reverse',pay(read,[alloc(a,'Leg 1',1)]).status_code==403 and reverse(read,bid,[a,b]).status_code==403)
    stale=alloc(b,'Leg 1',20);stale['rowVersion']-=1;valid=alloc(a,'Leg 1',20);before=copy.deepcopy(a.payload)
    check('one stale case blocks complete batch',pay(fin,[valid,stale]).status_code==409)
    a.refresh_from_db();check('no partial write on stale batch',a.payload==before)
    other=make('QA-C',currency='USD');different=make('QA-D',reinsured='Another Cedant')
    check('mixed currency rejected',pay(fin,[alloc(a,'Leg 1',1),alloc(other,'Leg 1',1)]).status_code==400)
    check('different actual counterparty rejected',pay(fin,[alloc(a,'Leg 1',1),alloc(different,'Leg 1',1)]).status_code==400)
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
    check('T3 reopens after underlying cash reversal',reverse(fin,full.json()['batchId'],[a]).status_code==200 and rows(a)[no(a,'Leg 3')]['settlement']=='open' and rows(a)[no(a,'Leg 2')]['settlement']=='open')
    refund=make('QA-REFUND',parentTwRef='ROOT',originalPremium=-1000,reinsurers=[{'name':'QA RI','sharePct':100,'premium':-800,'riCommPct':0,'taxPct':0}])
    check('refund T1 pays Cedant and T2 receives RI recovery',rows(refund)[no(refund,'Leg 1')]['paymentDirection']=='payable' and rows(refund)[no(refund,'Leg 2')]['paymentDirection']=='receivable')
    check('partial refund preserves signed cash and balance',pay(fin,[alloc(refund,'Leg 1',123.45)]).status_code==200 and rows(refund)[no(refund,'Leg 1')]['paid']==-123.45 and rows(refund)[no(refund,'Leg 1')]['outstanding']==-876.55)
    claim=make('QA-CLAIM');claim.payload['transactions']=[{'txNo':'QA-CLAIM-C1-T1','source':'claim','legType':'Claim Leg 1','reinsurer':'QA RI','amount':100,'settlement':'open'},{'txNo':'QA-CLAIM-C1-T2','source':'claim','legType':'Claim Leg 2','reinsurer':'QA RI','amount':100,'settlement':'open'}];claim.save()
    check('claim obligation creates no actual cash',all(d['paid']==0 for d in rows(claim).values()))
    check('claim Cedant leg resolves actual counterparty',rows(claim)['QA-CLAIM-C1-T2']['partyName']=='QA Cedant')
    check('claim RI receipt recorded independently',pay(fin,[alloc(claim,'Claim Leg 1',100)]).status_code==200 and rows(claim)['QA-CLAIM-C1-T2']['paid']==0)
    check('claim Cedant payment settles independently',pay(fin,[alloc(claim,'Claim Leg 2',100)]).status_code==200 and rows(claim)['QA-CLAIM-C1-T2']['settlement']=='pending_confirmation' and settle(fin,claim,'Claim Leg 2').status_code==200 and rows(claim)['QA-CLAIM-C1-T2']['settlement']=='settled')
    multi=make('QA-MULTI',reinsurers=[{'name':'RI A','sharePct':60,'premium':800,'riCommPct':0,'taxPct':0},{'name':'RI B','sharePct':40,'premium':800,'riCommPct':0,'taxPct':0}])
    check('multi RI single T1 allocation does not settle other T1',pay(fin,[alloc(multi,'Leg 1',600)]).status_code==200 and list(rows(multi).values())[3]['paid']==0)
    legacy_key=next(iter(rows(multi).values()))['cashParts'][0]['scheduleKey']
    multi.payload['paymentEntries'].append({'id':'legacy','entryType':'payment','scheduleKey':legacy_key,'amount':100,'paymentDate':'2026-10-07'});multi.save()
    details=rows(multi);check('legacy schedule cash counted once beside tagged cash',sum(d['paid'] for no_,d in details.items() if '-T1' in no_)==700)
    split=make('QA-SPLIT',splitEnabled=True,splitParties=[{'pct':60},{'pct':40}]);sd=rows(split)
    check('split T3 dependencies stay within a/b suffix',all(len(d.get('settlementDependencies',[]))==2 for d in sd.values() if d['cashTracking']=='derived'))
    unposted=make('QA-UNPOSTED');unposted.payload['transactions']=[];unposted.save()
    check('preclose schedule never fabricates transaction rows',not any(r['caseUid']==str(unposted.case_uid) for r in fin.get('/api/accounting').json()['transactionRows']))
    check('case SoA settlement agrees with Accounting',admin.get('/api/cases?caseUid='+str(a.case_uid)).json()['case']['payload']['transactions'][0]['paymentScheduleSettlement']==rows(a)[no(a,'Leg 1')]['settlement'])
    extra=make('QA-TWO',reinsurers=[{'name':'RI A','sharePct':60,'premium':800,'riCommPct':0,'taxPct':0},{'name':'RI B','sharePct':40,'premium':800,'riCommPct':0,'taxPct':0}])
    legs=[t for t in extra.payload['transactions'] if t['legType']=='Leg 1']
    version=extra.row_version
    allocations=[{'caseUid':str(extra.case_uid),'txNo':t['txNo'],'rowVersion':version,'amount':0.01} for t in legs]
    tiny=pay(fin,allocations,0.02)
    check('two allocations in one case preserve cents and increment version once',tiny.status_code==200 and rows(extra)[legs[0]['txNo']]['paid']==0.01 and rows(extra)[legs[1]['txNo']]['paid']==0.01 and extra.row_version==version+1)
    check('negative claim direction follows actual liability sign',transaction_details({'reinsured':'QA Cedant','currency':'TWD','transactions':[{'txNo':'NEG-C1-T2','source':'claim','legType':'Claim Leg 2','amount':-10}]})['NEG-C1-T2']['paymentDirection']=='receivable')
    missing=make('QA-MISSING',reinsured='')
    check('missing actual counterparty blocks cash allocation',pay(fin,[alloc(missing,'Leg 1',1)]).status_code==400)
    bad=alloc(extra,'Leg 1',1);bad['txNo']='DOES-NOT-EXIST'
    check('unknown transaction rejected',pay(fin,[bad]).status_code==400)
    bad_reverse=post(fin,{'action':'reverse_batch_payment','batchId':tiny.json()['batchId'],'cases':[{'caseUid':[],'rowVersion':1}]})
    check('malformed reversal case reference rejected',bad_reverse.status_code==400)
    history=make('QA-HISTORY');history.payload['transactions'][0]['reversed']=True;history.save()
    check('historical reversed transaction cannot accept new cash',pay(fin,[alloc(history,'Leg 1',1)]).status_code==400)
    inst=make('QA-INSTALLMENTS',installmentEnabled=True,performanceInstallments=[{'id':'i1','performanceMonth':'2026-09','premium':400,'paymentBaseDate':'2026-09-01'},{'id':'i2','performanceMonth':'2026-10','premium':600,'paymentBaseDate':'2026-10-01'}])
    from cases.calc.payment_terms import premium_installment_plan
    plan=premium_installment_plan(inst.payload)
    inst.payload['transactions']=build_premium_transactions(inst.payload,plan[0]);inst.status='posted';inst.save()
    check('only generated installment transactions appear',len([r for r in fin.get('/api/accounting').json()['transactionRows'] if r['caseUid']==str(inst.case_uid)])==3)
    check('generated installment can collect its own balance',pay(fin,[alloc(inst,'Leg 1',400)]).status_code==200 and rows(inst)[no(inst,'Leg 1')]['settlement']=='pending_confirmation')
    raise Rollback()
except Rollback:pass
print(f'{len(checks)}/{len(checks)} passed; database changes rolled back')
