from qa.accounting_full import accounting_get   # 2026-11-17: retired Accounting reads are internal in tests
"""Accounting legacy historical-result cache (2026-11-10). Synthetic data in disposable MySQL only.

The cache must be invisible: every Accounting response is byte-identical to the uncached
computation. Only imported historical transactions are cached; new legacy endorsements/claims
are recomputed on every request, so reviews and cash registrations show immediately. Any change
to historical rows (ORM, raw SQL without version bump, status, new rows) forces a recompute.
2026-11-17 (owner): the settled history no longer depends on the Taipei date (verified on production data);
its result is shared between workers through one snapshot file (calculation-version + content key), and a
background thread in every web worker builds the Accounting history part before the first request.
2026-11-19 (owner): results are remembered per row (row content digest), so a change or an import computes only the
changed or new rows; the converted Accounting part and its sort keys are shared through a second snapshot file.
"""
import copy
from pathlib import Path
# Reuse the standalone-entry fixtures (users, source transaction, create/save/confirm helpers).
exec(Path('/app/qa/suites/legacy_entries.py').read_text().replace("print(f'{len(checks)}/{len(checks)} passed')",'pass'))
from django.db import connections
import legacy.ledger as L
from legacy.models import ImportBatch

owner=copy.deepcopy(connections.databases['default'])
owner.update(USER='ri_app',PASSWORD=Path('/run/secrets/mysql_app_password').read_text().strip())
connections.databases['legacy_cache_owner']=owner
O=LegacyTransaction.objects.using('legacy_cache_owner')
batch=ImportBatch.objects.using('legacy_cache_owner').create(filename='synthetic-cache.xlsx',sha256='c'*64,
    storage_key='qa/synthetic-cache.xlsx',status='imported',created_by='isolated-qa')

def make(n,rule='ordinary'):
    data=dict(reference=f'QA-CACHE-{n}',currency='TWD',insured=f'Synthetic Insured {n}',insuredCn='測試歷史被保險人',
        cedant='Synthetic Cedant',party='Synthetic Reinsurer',ae='Entry sales',statementNo=f'CACHE-ST-{n}',gross=10000,
        share=100,rule=rule,kind='premium',effectiveDate='2024-01-01',expiryDate='2024-12-31',
        receiveReminder='2024-03-15',payReminder='2024-04-15',
        amounts=dict(premium=10000+n,commission=0,tax=0,brokerage=500,claim=0,cedantNet=10000+n,reinsurerNet=9500+n))
    return O.create(number=f'QA-CACHE-{n}',original_serial=f'QA-CACHE-{n}',reference=f'QA-CACHE-{n}',currency='TWD',
        revenue_month='2024-01',status='confirmed',historical=True,batch=batch,first_confirmed_at=timezone.now(),
        data=data,fx_snapshot=dict(rate=1))

legacy=[make(1),make(2,'swiss'),make(3)]
fin=clients['accounting'];admin=clients['admin']

calls=[0];real_one=L._accounting_one
def counted(t):
    if t.historical:calls[0]+=1
    return real_one(t)
L._accounting_one=counted
saved_flag=os.environ.get('RI_LEGACY_RESULT_CACHE')

def get(view='?view=list'):
    r=accounting_get(admin, view)
    assert r.status_code==200,r.content[:300]
    return r.content
def uncached(view='?view=list'):
    os.environ['RI_LEGACY_RESULT_CACHE']='false'
    try:return get(view)
    finally:
        if saved_flag is None:os.environ.pop('RI_LEGACY_RESULT_CACHE',None)
        else:os.environ['RI_LEGACY_RESULT_CACHE']=saved_flag
def legacy_ids(content):
    return [r['legacyTransactionId'] for r in json.loads(content)['transactionRows'] if r.get('legacyTransactionId')]
def raw(sql,params):
    with connections['legacy_cache_owner'].cursor() as cur:cur.execute(sql,params)
def historical_count():
    return LegacyTransaction.objects.filter(status='confirmed',historical=True).count()
def snapshot():
    return json.dumps(L._CACHE.get('value'),default=str,sort_keys=True)
def finance(body,want=200):
    r=fin.post('/api/accounting',json.dumps(body),content_type='application/json')
    check('Finance '+body['action']+' '+str(want),r.status_code==want,r.content[:600]);return r.json()
def member(t,leg):
    obj=LegacyTransaction.objects.get(pk=t['uid'])
    return dict(caseUid=str(obj.uid),rowVersion=obj.version,txNo=obj.number+'-T'+str(leg))

try:
    columns={f.column for f in LegacyTransaction._meta.concrete_fields}
    H=historical_count()
    check('row digests cover every column except the raw Excel original and only historical rows',
        len(L.history_digests())==H==L._fingerprint(L.historical_queryset())[0] and 'original' in columns and len(columns)>10)

    # A new (non-historical) endorsement exists alongside the historical rows.
    e=create();e=save(e,dict(gross=400,commissionRate=0,taxRate=0,brokerage=10,effectiveDate='2020-07-01',endorsementNo='E-CACHE',oldReason='late_entry'));e=confirm(e)

    for view in ('?view=list',''):
        L._CACHE.clear();n=calls[0];base=uncached(view);again=uncached(view)
        check('switch off computes every request with no cache '+view,calls[0]==n+2*H and base==again and not L._CACHE)
        first=get(view);n=calls[0];second=get(view)
        check('cached response is byte-identical to the uncached response '+view,first==base and second==base)
        check('second response reuses the historical cache '+view,calls[0]==n)
    check('legacy rows are present (historical and new)',str(legacy[0].pk) in legacy_ids(base) and e['uid'] in legacy_ids(base))

    before=snapshot();get();get('')
    check('full Accounting requests never change the remembered result',snapshot()==before)
    views,rows=L.accounting_data()
    for r in rows:r['amount']=123456789;r['twRef']='MUTATED'
    for v in views:v['twRef']='MUTATED'
    rows.clear();views.clear()
    n=calls[0]
    check('callers cannot change the remembered result',get()==uncached() and calls[0]==n+H and snapshot()==before)

    # New legacy transactions are recomputed every time: review and cash show immediately.
    n=calls[0]
    finance(dict(action='review_accounts',date='2026-11-10',members=[member(e,1)]))
    after_review=get()
    check('review on a new legacy endorsement is visible at once without recomputing history',
        after_review==uncached() and after_review!=base and calls[0]==n+H)
    m=member(e,1)
    finance(dict(action='record_transaction_payments',cashSubmissionId=str(uuid.uuid4()),paymentDate='2026-11-10',reference='QA-CACHE',
        allocations=[dict(cashItemId=str(uuid.uuid4()),caseUid=m['caseUid'],txNo=m['txNo'],cashAmount=100,rowVersion=m['rowVersion'])]))
    paid=get();row=[r for r in json.loads(paid)['transactionRows'] if r.get('txNo')==m['txNo']]
    check('cash on a new legacy endorsement is visible at once',paid==uncached() and row and row[0]['paid']==100,row)
    e2=create();e2=save(e2,dict(gross=200,commissionRate=0,taxRate=0,brokerage=5,effectiveDate='2020-07-01',endorsementNo='E-CACHE-2',oldReason='late_entry'));e2=confirm(e2)
    n=calls[0];added=get()
    check('a newly confirmed endorsement appears at once without recomputing history',
        e2['uid'] in legacy_ids(added) and added==uncached() and calls[0]==n+H)

    t=legacy[0];O.filter(pk=t.pk).update(data={**t.data,'insured':'Changed Through ORM'},version=2)
    n=calls[0];changed=get()
    check('ORM change with version bump recomputes only that row (2026-11-19)',calls[0]==n+1 and b'Changed Through ORM' in changed)
    check('recomputed response equals uncached after ORM change',changed==uncached())

    before=O.get(pk=legacy[1].pk)
    raw("UPDATE ri_legacy_transactions SET data=JSON_SET(data,'$.cedant','Raw SQL Cedant') WHERE uid=%s",[legacy[1].pk.hex])
    after=O.get(pk=legacy[1].pk)
    check('raw SQL change keeps version and updated_at (direct database repair)',
        after.version==before.version and after.updated_at==before.updated_at)
    n=calls[0];changed=get()
    check('raw SQL change without version bump is still detected (only that row is recomputed)',calls[0]==n+1 and b'Raw SQL Cedant' in changed)
    check('recomputed response equals uncached after raw SQL change',changed==uncached())

    raw("UPDATE ri_legacy_transactions SET financial=JSON_OBJECT('note','raw') WHERE uid=%s",[legacy[2].pk.hex])
    n=calls[0];changed=get()
    check('change to the financial column is detected',calls[0]==n+1 and changed==uncached())

    raw("UPDATE ri_legacy_transactions SET status='withdrawn' WHERE uid=%s",[legacy[2].pk.hex])
    H=historical_count();n=calls[0];changed=get()
    check('row leaving the Accounting scope is detected (nothing recomputed)',calls[0]==n and str(legacy[2].pk) not in legacy_ids(changed)
        and changed==uncached())

    extra=make(4);H=historical_count();n=calls[0];changed=get()
    check('new historical row entering the Accounting scope is detected and only it is computed (import)',calls[0]==n+1 and str(extra.pk) in legacy_ids(changed)
        and changed==uncached())

    real_today=L._today
    try:
        L._today=lambda:'2099-01-01';n=calls[0];later=get()
        check('a Taipei date change no longer recomputes the settled history (2026-11-17)',calls[0]==n and later==uncached())
    finally:L._today=real_today

    # ---- 2026-11-17 shared snapshot file ----
    path=L._results_file()
    check('the result is kept in one snapshot file for the calculation version',
        path.exists() and [p.name for p in path.parent.glob('*.pickle.z') if L._snapshot_kind(p)=='results']==[path.name])
    L._CACHE.clear();n=calls[0];other=get()
    check('another worker (empty memory) reads the snapshot without recomputing',calls[0]==n and other==uncached())
    path.write_bytes(b'not a snapshot');L._CACHE.clear();n=calls[0];fixed=get()
    check('an unreadable snapshot is recomputed and rewritten',calls[0]==n+H and fixed==uncached() and L._read_snapshot(path) is not None)
    extra2=make(5);H=historical_count();L._CACHE.clear();n=calls[0];grown=get()
    check('an empty-memory worker reads the file and computes only the new row',calls[0]==n+1 and str(extra2.pk) in legacy_ids(grown) and grown==uncached())
    L._CACHE.clear();n=calls[0];again=get()
    check('another worker then finds the new row in the file (nothing computed)',calls[0]==n and again==grown)
    real_logic=L._LOGIC
    try:
        L._LOGIC='changed-code';L._CACHE.clear();n=calls[0];newcode=get()
        check('a calculation code change recomputes once (new file, old one removed)',calls[0]==n+H and newcode==uncached()
            and L._results_file().exists() and not path.exists())
    finally:L._LOGIC=real_logic
    L._CACHE.clear();get()
    os.environ['RI_LEGACY_HISTORY_SNAPSHOT']='false'
    try:
        L._CACHE.clear();n=calls[0];off=get();get()
        check('snapshot switched off: an empty-memory worker recomputes, then remembers in memory',calls[0]==n+H and off==uncached())
    finally:os.environ.pop('RI_LEGACY_HISTORY_SNAPSHOT',None)

    # ---- 2026-11-17 background warm-up (every web worker) ----
    from legacy import warm
    from cases import accounting_pages as P
    check('the warm-up thread starts only in web workers (not in manage.py)',not warm.in_web_worker() and (warm.start() or not warm._started))
    P._HISTORY.clear();L._CACHE.clear();warm.warm_once()
    part=P._HISTORY.get('value')
    slots={(tab,None if part and part['dateFree'] else L._today()) for tab in P.TAB_KEYS}
    check('warm-up builds the Accounting history part and the sort keys of all three tabs without a user',
        bool(part) and part['dateFree'] and slots<=set(part['sortKeys']) and P._HISTORY.get('checked',0)>0)
    stored=L._read_snapshot(P._part_file(L))
    check('the converted part and its sort keys are kept in one shared file',isinstance(stored,dict) and len(stored['rows'])==len(part['rows'])
        and slots<=set(stored['sortKeys']) and [p.name for p in P._part_file(L).parent.glob('*-part.pickle.z')]==[P._part_file(L).name])
    builds=[0];real_build=P._build_part
    def counted_build(*a):
        builds[0]+=1;return real_build(*a)
    P._build_part=counted_build
    try:
        expected=admin.get('/api/accounting?view=page&tab=all&page=1').content
        P._HISTORY.clear();L._CACHE.clear();n=calls[0]
        fromfile=admin.get('/api/accounting?view=page&tab=all&page=1').content
        check('another worker reads the converted part from the file (no conversion, no calculation)',builds==[0] and calls[0]==n and fromfile==expected)
        check('a part read from the file is marked for the content check',P._HISTORY.get('checked')==0)
        P._HISTORY.clear();warm.warm_once()
        check('the warm-up compares the digests of a part read from the file itself',P._HISTORY.get('checked',0)>0 and builds==[0])
    finally:P._build_part=real_build
    import cases.calc.payment_terms as PT
    real_date=PT.taipei_date;cached_page=admin.get('/api/accounting?view=page&tab=all&page=1').content
    try:
        PT.taipei_date=lambda *a,**k:'2099-06-30';later_cached=admin.get('/api/accounting?view=page&tab=all&page=1').content
        P._HISTORY.clear();L._CACHE.clear();os.environ['RI_LEGACY_HISTORY_SNAPSHOT']='false'
        try:later_cold=admin.get('/api/accounting?view=page&tab=all&page=1').content
        finally:os.environ.pop('RI_LEGACY_HISTORY_SNAPSHOT',None)
        check('a settled history part and its sort keys do not depend on the Taipei date',later_cached==later_cold)
    finally:PT.taipei_date=real_date
    warm._wake.clear();warm.poke()
    check('a committed web import wakes the warm-up at once',warm._wake.is_set())
    warm._wake.clear()
    n=calls[0];page=admin.get('/api/accounting?view=page&tab=all&page=1');opts=admin.get('/api/accounting?view=options')
    check('the first page and options after warm-up use it (no recompute)',page.status_code==200 and opts.status_code==200 and calls[0]==n)
    warmed=(page.content,opts.content);P._HISTORY.clear();L._CACHE.clear();os.environ['RI_LEGACY_HISTORY_SNAPSHOT']='false'
    try:cold=(admin.get('/api/accounting?view=page&tab=all&page=1').content,admin.get('/api/accounting?view=options').content)
    finally:os.environ.pop('RI_LEGACY_HISTORY_SNAPSHOT',None)
    check('warmed responses are byte-identical to a cold rebuild',warmed==cold)

    real_digests=L.history_digests
    try:
        L.history_digests=lambda:[(u,'stale' if i==0 else d) for i,(u,d) in enumerate(real_digests())]
        L._CACHE.clear();P._HISTORY.clear();views,rows=L.accounting_data()
        check('result computed while the data changed is used but not remembered as complete',
            'identity' not in L._CACHE and json.dumps(rows,default=str)==json.dumps(L._compute_accounting_data()[1],default=str))
    finally:L.history_digests=real_digests

    # Inconsistent snapshot (history set differs from the ordering list) falls back to full computation.
    get();real_hist=L._historical_results
    try:
        L._historical_results=lambda:{k:v for k,v in list(real_hist().items())[1:]}
        check('missing cached member falls back to the full uncached computation',get()==uncached())
    finally:L._historical_results=real_hist
finally:
    L._accounting_one=real_one
    L._CACHE.clear()
print(f'{len(checks)}/{len(checks)} passed')
