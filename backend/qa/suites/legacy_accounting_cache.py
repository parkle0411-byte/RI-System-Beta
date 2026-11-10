"""Accounting legacy historical-result cache (2026-11-10). Synthetic data in disposable MySQL only.

The cache must be invisible: every Accounting response is byte-identical to the uncached
computation. Only imported historical transactions are cached; new legacy endorsements/claims
are recomputed on every request, so reviews and cash registrations show immediately. Any change
to historical rows (ORM, raw SQL without version bump, status, new rows) or the Taipei date
forces a recompute.
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
    r=admin.get('/api/accounting'+view)
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
    check('fingerprint covers every column except the raw Excel original and only historical rows',
        L._fingerprint(L.historical_queryset())[0]==H and 'original' in columns and len(columns)>10)

    # A new (non-historical) endorsement exists alongside the historical rows.
    e=create();e=save(e,dict(gross=400,commissionRate=0,taxRate=0,brokerage=10,revenueMonth='2035-06',endorsementNo='E-CACHE',oldReason='late_entry'));e=confirm(e)

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
    e2=create();e2=save(e2,dict(gross=200,commissionRate=0,taxRate=0,brokerage=5,revenueMonth='2035-06',endorsementNo='E-CACHE-2',oldReason='late_entry'));e2=confirm(e2)
    n=calls[0];added=get()
    check('a newly confirmed endorsement appears at once without recomputing history',
        e2['uid'] in legacy_ids(added) and added==uncached() and calls[0]==n+H)

    t=legacy[0];O.filter(pk=t.pk).update(data={**t.data,'insured':'Changed Through ORM'},version=2)
    n=calls[0];changed=get()
    check('ORM change with version bump recomputes',calls[0]==n+H and b'Changed Through ORM' in changed)
    check('recomputed response equals uncached after ORM change',changed==uncached())

    before=O.get(pk=legacy[1].pk)
    raw("UPDATE ri_legacy_transactions SET data=JSON_SET(data,'$.cedant','Raw SQL Cedant') WHERE uid=%s",[legacy[1].pk.hex])
    after=O.get(pk=legacy[1].pk)
    check('raw SQL change keeps version and updated_at (direct database repair)',
        after.version==before.version and after.updated_at==before.updated_at)
    n=calls[0];changed=get()
    check('raw SQL change without version bump is still detected',calls[0]==n+H and b'Raw SQL Cedant' in changed)
    check('recomputed response equals uncached after raw SQL change',changed==uncached())

    raw("UPDATE ri_legacy_transactions SET financial=JSON_OBJECT('note','raw') WHERE uid=%s",[legacy[2].pk.hex])
    n=calls[0];changed=get()
    check('change to the financial column is detected',calls[0]==n+H and changed==uncached())

    raw("UPDATE ri_legacy_transactions SET status='withdrawn' WHERE uid=%s",[legacy[2].pk.hex])
    H=historical_count();n=calls[0];changed=get()
    check('row leaving the Accounting scope is detected',calls[0]==n+H and str(legacy[2].pk) not in legacy_ids(changed)
        and changed==uncached())

    extra=make(4);H=historical_count();n=calls[0];changed=get()
    check('new historical row entering the Accounting scope is detected',calls[0]==n+H and str(extra.pk) in legacy_ids(changed)
        and changed==uncached())

    real_today=L._today
    try:
        L._today=lambda:'2099-01-01';n=calls[0];get();get()
        check('Taipei date change recomputes once, then caches again',calls[0]==n+H)
    finally:L._today=real_today
    n=calls[0];back=get()
    check('returning to today recomputes and matches uncached',calls[0]==n+H and back==uncached())

    real_fingerprint=L._fingerprint;seq=iter([(1,1),(1,2)])
    try:
        L._fingerprint=lambda qs:next(seq);L._CACHE.clear();L.accounting_data()
        check('result computed while the data changed is not remembered',not L._CACHE)
    finally:L._fingerprint=real_fingerprint

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
