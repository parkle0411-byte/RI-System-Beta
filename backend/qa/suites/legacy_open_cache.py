"""Unsettled legacy rows: computed once per request and cached per transaction (2026-11-13).
Batch import: Insured masters read once. Synthetic data in disposable MySQL only.

The cache must be invisible: responses are byte-identical with it on or off; any change to a row
(review, cash, edit, raw SQL without a version bump, status) or the Taipei date recomputes that row
only; payment-schedule rows equal the former separate computation; the shared Insured lookup links
exactly the same masters as the row-by-row lookup.
"""
import copy
from pathlib import Path
exec(Path('/app/qa/suites/legacy_entries.py').read_text().replace("print(f'{len(checks)}/{len(checks)} passed')",'pass'))
from django.db import connections
import legacy.ledger as L
from legacy import policy
from legacy.ledger import payload_for, schedule
from cases import insured_master as im
from masterdata.models import MasterRecord

owner=copy.deepcopy(connections.databases['default'])
owner.update(USER='ri_app',PASSWORD=Path('/run/secrets/mysql_app_password').read_text().strip())
connections.databases['open_cache_owner']=owner
fin=clients['accounting'];admin=clients['admin']
flags=('RI_LEGACY_OPEN_CACHE','RI_LEGACY_RESULT_CACHE');saved={k:os.environ.get(k) for k in flags}
def restore():
    for k,v in saved.items():
        if v is None:os.environ.pop(k,None)
        else:os.environ[k]=v
def get(q='?view=list',client=None):
    r=(client or admin).get('/api/accounting'+q);assert r.status_code==200,(q,r.status_code,r.content[:300]);return r.content
def uncached(q='?view=list'):
    for k in flags:os.environ[k]='false'
    try:return get(q)
    finally:restore()
def finance(payload,want=200):
    r=fin.post('/api/accounting',json.dumps(payload),content_type='application/json')
    check('Finance '+payload['action']+' '+str(want),r.status_code==want,r.content[:500]);return r.json()
def raw(sql,params):
    with connections['open_cache_owner'].cursor() as cur:cur.execute(sql,params)
calls=[];real_full=L._accounting_full
def counted(t):
    if not t.historical:calls.append(str(t.uid))
    return real_full(t)
L._accounting_full=counted
def reference_schedules():
    """The separate computation used before 2026-11-13 (legacy.ledger.accounting_schedules)."""
    result=[]
    for t in LegacyTransaction.objects.filter(status='confirmed',historical=False).order_by('uid'):
        p=payload_for(t)
        if p['legacyData'].get('kind')=='claim':continue
        for row in schedule(p)['items']:
            result.append({**row,'key':str(t.uid)+':'+row['scheduleKey'],'caseUid':str(t.uid),'rootCaseUid':str(t.uid),'caseRowVersion':t.version,
                'rowVersion':t.version,'caseStatus':'posted','twRef':t.reference,'source':'premium','origin':'legacy','legacyTransactionId':str(t.uid),
                'legacyHistorical':False,'entries':[e for e in p['paymentEntries'] if e.get('scheduleKey')==row['scheduleKey']]})
    return result

try:
    pol=make_source('OPEN-CACHE-SRC',effectiveDate='2025-01-01',expiryDate='2025-12-31')
    swiss=make_source('OPEN-CACHE-SW',rule='swiss',party='Swiss Re Asia Pte. Ltd., Hong Kong Branch (Facility)',effectiveDate='2025-01-01',expiryDate='2025-12-31')
    made=[]
    for n,(src,extra) in enumerate(((pol,{}),(pol,{}),(swiss,{'cedantDays':90})),1):
        e=create(src=src);e=save(e,dict(gross=400+n,commissionRate=0,taxRate=0,brokerage=10,endorsementNo=f'E-OC-{n}',effectiveDate=f'2025-0{n+1}-01',**extra));made.append(confirm(e))
    c=create('claim',src=pol);c=save(c,dict(claim=300,lossDate='2025-04-01',lossNo='L-OC',causeOfLoss='Fire'));made.append(confirm(c))
    N=LegacyTransaction.objects.filter(status='confirmed',historical=False).count()
    check('fixture has unsettled legacy transactions including a claim and a Swiss endorsement',N>=4)

    # 1. Invisible: byte-identical with the caches on or off, for every variant of the request.
    for q in ('?view=list','','?view=list&legacy=open','?view=list&legacy=history'):
        L._OPEN.clear();L._CACHE.clear()
        base=uncached(q);first=get(q);second=get(q)
        check(f'{q or "(full)"}: cached responses are byte-identical to the uncached response',first==base and second==base)
    L._OPEN.clear();del calls[:];get('?view=list&legacy=open')
    check('a cold request computes every unsettled transaction exactly once (rows and schedule together)',sorted(calls)==sorted(set(calls)) and len(calls)==N,(len(calls),N))
    del calls[:];get('?view=list&legacy=open');get('?view=list');get('')
    check('warm requests recompute nothing',calls==[])
    os.environ['RI_LEGACY_OPEN_CACHE']='false';del calls[:];get('?view=list&legacy=open')
    check('with the cache switched off every request computes each transaction once',len(calls)==N and len(set(calls))==N and not any(True for _ in []))
    restore()

    # 2. Schedule rows equal the former separate computation, in the former order.
    body=json.loads(get('?view=list&legacy=open'));ref=json.loads(json.dumps(reference_schedules(),default=str))
    mine=[r for r in body['swissRows'] if r.get('origin')=='legacy']
    check('payment-schedule rows equal the former separate computation and order',json.loads(json.dumps(mine,default=str))==ref and len(ref)>=3,(len(mine),len(ref)))
    check('claims contribute no schedule rows',not any(r['caseUid']==made[3]['uid'] for r in mine))

    # 3. Callers cannot change what is remembered.
    before=uncached('?view=list&legacy=open')
    for uid,view,rows,srows in L._open_results():
        view['twRef']='MUTATED'
        for r in rows:r['amount']=123456789;r['txNo']='MUTATED'
        for r in srows:r['amount']=987654321
        rows.clear();srows.clear()
    check('callers cannot change the remembered results',get('?view=list&legacy=open')==before)

    # 4. Any change to a row recomputes that row only, and is visible at once.
    target=LegacyTransaction.objects.get(pk=made[0]['uid'])
    member=dict(caseUid=str(target.uid),rowVersion=target.version,txNo=target.number+'-T1')
    del calls[:];finance(dict(action='review_accounts',date='2026-11-13',members=[member]))
    after=get('?view=list&legacy=open')
    row=[r for r in json.loads(after)['transactionRows'] if r.get('txNo')==member['txNo']][0]
    check('a review is visible at once and equals the uncached response',row['financeReviewed'] is True and after==uncached('?view=list&legacy=open'))
    target.refresh_from_db();del calls[:]
    finance(dict(action='record_transaction_payments',cashSubmissionId=str(uuid.uuid4()),paymentDate='2026-11-13',reference='OC-CASH',
        allocations=[dict(cashItemId=str(uuid.uuid4()),caseUid=str(target.uid),txNo=member['txNo'],cashAmount=50,rowVersion=target.version)]))
    del calls[:];paid=get('?view=list&legacy=open')
    row=[r for r in json.loads(paid)['transactionRows'] if r.get('txNo')==member['txNo']][0]
    check('a receipt is visible at once, recomputes only that transaction and equals the uncached response',
          row['paid']==50 and set(calls)=={str(target.uid)} and paid==uncached('?view=list&legacy=open'),(row['paid'],calls))
    other=LegacyTransaction.objects.get(pk=made[1]['uid']);v=other.version;stamp=other.updated_at
    raw("UPDATE ri_legacy_transactions SET data=JSON_SET(data,'$.insured','Raw SQL Insured') WHERE uid=%s",[other.pk.hex])
    other.refresh_from_db();del calls[:];changed=get('?view=list&legacy=open')
    check('a direct database change without a version bump is detected for that row only',
          other.version==v and other.updated_at==stamp and set(calls)=={str(other.uid)} and b'Raw SQL Insured' in changed and changed==uncached('?view=list&legacy=open'),calls)
    raw("UPDATE ri_legacy_transactions SET status='withdrawn' WHERE uid=%s",[made[3]['uid'].replace('-','')])
    del calls[:];gone=get('?view=list&legacy=open')
    check('a withdrawn transaction disappears at once without recomputing the others',
          made[3]['uid'].encode() not in gone and calls==[] and gone==uncached('?view=list&legacy=open'))
    e=create(src=pol);e=save(e,dict(gross=250,commissionRate=0,taxRate=0,brokerage=5,endorsementNo='E-OC-NEW',effectiveDate='2025-06-01'));e=confirm(e)
    del calls[:];added=get('?view=list&legacy=open')
    check('a newly confirmed transaction appears at once and is the only one computed',e['uid'].encode() in added and set(calls)=={e['uid']} and added==uncached('?view=list&legacy=open'),calls)

    # 5. The Taipei date is part of the key.
    real_today=L._today
    try:
        L._today=lambda:'2099-01-01';del calls[:];get('?view=list&legacy=open');n=len(set(calls));del calls[:];get('?view=list&legacy=open')
        check('a new Taipei date recomputes every unsettled transaction once, then caches again',n==LegacyTransaction.objects.filter(status='confirmed',historical=False).count() and calls==[])
    finally:L._today=real_today
    del calls[:];back=get('?view=list&legacy=open')
    check('returning to today reuses the earlier results and matches uncached',calls==[] and back==uncached('?view=list&legacy=open'))

    # 6. Bounded size.
    os.environ['RI_LEGACY_OPEN_CACHE_SIZE']='2';L._OPEN.clear();get('?view=list&legacy=open')
    check('the cache size is bounded',len(L._OPEN)<=2 and get('?view=list&legacy=open')==uncached('?view=list&legacy=open'))
    os.environ.pop('RI_LEGACY_OPEN_CACHE_SIZE',None);L._OPEN.clear()

    # 7. Batch import: the shared Insured lookup links exactly the same masters as the row-by-row lookup.
    actor={'id':'personnel:qa','name':'QA'}
    def master(name,**payload):
        return MasterRecord.objects.create(entity_type='insured',name=name,payload={'aliases':[],**payload},created_by='qa',updated_by='qa')
    a=master('甲公司');b=master('乙公司/丙公司');al=master('丁公司',announcedAliases=['舊丁公司'],**{im.OFFICIAL_KEY:'2026-01-01T00:00:00+00:00'})
    tgt=master('合併後公司');src=master('被合併公司',mergedInto=tgt.pk);MasterRecord.objects.filter(pk=src.pk).update(is_active=False)
    names=['甲公司','丙公司/乙公司','乙公司','舊丁公司','丁公司','被合併公司','合併後公司','全新公司','全新公司','  甲公司  ','新A/新B','新B/新A','甲公司/',
           '','x'*300,'被合併公司','全新公司二','舊丁公司','丙公司 / 乙公司']
    def snapshot():
        return {r.name:(r.pk,r.row_version,bool((r.payload or {}).get(im.OFFICIAL_KEY)),len((r.payload or {}).get('history',[])),r.is_active)
                for r in MasterRecord.objects.filter(entity_type='insured')}
    def run(use_lookup):
        sid=transaction.savepoint();lookup=policy.insured_lookup() if use_lookup else None;out=[]
        for i,name in enumerate(names):
            pk=policy.link_insured(name,actor,f'tx-{i}',lookup) if use_lookup else policy.link_insured(name,actor,f'tx-{i}')
            out.append(MasterRecord.objects.get(pk=pk).name if pk else None)
        state={k:(v[1:]) for k,v in snapshot().items()};transaction.savepoint_rollback(sid);return out,state
    with transaction.atomic():
        plain=run(False);shared=run(True)
        transaction.set_rollback(True)
    check('shared Insured lookup links every name to the same master as the row-by-row lookup',plain[0]==shared[0],(plain[0],shared[0]))
    check('shared Insured lookup leaves the masters in the same state (versions, official marks, history, new records)',plain[1]==shared[1])
    check('the comparison covered reuse, reordered members, aliases, merges, new and invalid names',
          plain[0][0]=='甲公司' and plain[0][1]=='乙公司/丙公司' and plain[0][2]=='乙公司' and plain[0][3]=='丁公司' and plain[0][5]=='合併後公司'
          and plain[0][7]==plain[0][8]=='全新公司' and plain[0][10]==plain[0][11] and plain[0][12] is None and plain[0][13] is None,plain[0])
finally:
    L._accounting_full=real_full;restore();os.environ.pop('RI_LEGACY_OPEN_CACHE_SIZE',None)
    L._OPEN.clear();L._CACHE.clear()
print(f'{len(checks)}/{len(checks)} passed')
