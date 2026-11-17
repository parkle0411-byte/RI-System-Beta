"""Accounting server paging (owner decision 2026-11-17). Disposable MySQL only.

All Accounts / Settled/Closed / Brokerage are paged by the server (?view=page, 100 rows) with the browser's filters;
?view=options lists the dropdown names over every account including settled legacy history. Exact equality with the
browser's own code is checked separately by scripts/run_qa.sh pages (Node); this suite checks the API contract,
permissions, paging, filters, freshness after writes and the settled-history cache.
"""
import copy, json, os, time, uuid
from pathlib import Path
from django.db import connections
from django.test import Client
from django.utils import timezone
from django.contrib.auth import get_user_model
from cases.models import Case
from legacy.models import ImportBatch, LegacyTransaction
from personnel.models import Personnel
import cases.accounting_pages as P
import legacy.ledger as L

assert os.environ.get('RI_DISPOSABLE_QA') == 'true'
checks = []
def check(name, ok, detail=''):
    assert ok, (name, detail)
    checks.append(name); print('PASS ' + name, flush=True)

tag = uuid.uuid4().hex[:5]
def account(role, dept):
    u = get_user_model().objects.create_user(username=f'ap{tag}.{role}', password='Ap-Test-Pass-1')
    p = Personnel.objects.create(name=f'AP{tag} {role}', department=dept, role_code=role, auth_user_id=str(u.pk), account_status='active',
                                 email=f'{role}{tag}@example.test', created_by='qa', updated_by='qa')
    c = Client(HTTP_HOST='localhost', raise_request_exception=False); c.force_login(u); return c, p
R = {role: account(role, dept) for role, dept in (('admin', 'admin'), ('sales', 'reinsurance'), ('accounting', 'finance'), ('viewer', 'reinsurance'))}
sales, sp = R['sales']; fin = R['accounting'][0]
def post(c, url, data): return c.post(url, json.dumps(data), content_type='application/json')
def get(c, query, want=200):
    r = c.get('/api/accounting?' + query)
    assert r.status_code == want, (query, r.status_code, r.content[:300]); return r.json()

# ---- data: native cases with claim accounts, open legacy rows and 130 settled legacy transactions ----
def body(name):
    return dict(classOfBusiness='Property', classCode='PF', typePrefix='Property', reinsuranceStructure='QS', currency='TWD', originalInsured=name,
        originalInsuredCn='分頁測試', reinsured='AP Cedant', newOrRenew='New', policyFrom='2026-11-01', policyTo='2027-11-01', interest='Stock',
        situations=[{'address': 'Taipei', 'postcode': '100'}], sumInsured=[{'category': 'Building', 'amount': 1000000}], basisOfValuation='Actual Cash Value',
        originalPremium=100000, riCommPct=0, taxPct=1, paymentTermsDays=90, deductibles='TWD 1,000', originalConditions='A', reinsuredRetention='Waived',
        lossAdvisedDate='2026-01-01', lossRecordYears=5, ae=sp.name, ownerPersonnelId=sp.pk, ownerPersonnelName=sp.name,
        reinsurers=[{'name': 'AP Re A', 'sharePct': 60, 'premium': 100000, 'riCommPct': 10, 'taxPct': 1, 'paymentTermsDays': 90},
                    {'name': 'AP Re B', 'sharePct': 40, 'premium': 100000, 'riCommPct': 10, 'taxPct': 1, 'paymentTermsDays': 90}])
native = []
for n in range(3):
    r = post(sales, '/api/cases', {'case': body(f'AP{tag} Insured {n}')}); assert r.status_code == 201, r.content[:300]
    c = Case.objects.get(case_uid=r.json()['case']['caseUid'])
    Case.objects.filter(pk=c.pk).update(status='posted', tw_ref=f'APX{tag}{n:03d}', announced_at=timezone.now())
    c.refresh_from_db()
    for action in ({'action': 'create_claim', 'claim': {'dateOfLoss': '2026-11-05', 'outstandingReserve': 50000}},
                   {'action': 'record_payment', 'claimId': 1, 'payment': {'amount': 1000, 'date': '2026-11-10'}}):
        c.refresh_from_db(); r = post(sales, '/api/claims', {**action, 'caseUid': str(c.case_uid), 'rowVersion': c.row_version}); assert r.status_code == 200, r.content[:300]
    native.append(Case.objects.get(pk=c.pk))
owner = copy.deepcopy(connections.databases['default']); owner.update(USER='ri_app', PASSWORD=Path('/run/secrets/mysql_app_password').read_text().strip())
connections.databases['ap_owner'] = owner
O = LegacyTransaction.objects.using('ap_owner')
batch = ImportBatch.objects.using('ap_owner').create(filename='ap.xlsx', sha256='b' * 64, storage_key='qa/ap.xlsx', status='imported', created_by='qa')
def legacy(n, historical):
    uid = uuid.uuid4(); number = f'AP-{tag}-{n:03d}'; reference = f'AP-REF-{n:03d}'
    data = dict(reference=reference, currency='USD' if n % 7 == 0 else 'TWD', insured=f'AP Legacy {n:03d}', insuredCn='舊資料分頁', cedant='AP History Cedant' if historical else 'AP Open Cedant',
        party='AP History Re', ae=sp.name, statementNo=f'AP-ST-{n}', gross=10000, share=100, rule='ordinary', kind='premium', classCode='PD', classOfBusiness='Property',
        effectiveDate=f'2024-{(n % 12) + 1:02d}-01', expiryDate='2025-12-31', receiveReminder='2024-03-15', payReminder='2024-04-15',
        amounts=dict(premium=10000 + n, commission=0, tax=0, brokerage=500, claim=0, cedantNet=10000 + n, reinsurerNet=9500 + n))
    entries = [dict(id=str(uuid.uuid4()), entryType='payment', transactionNo=f'{number}-T{leg}', scheduleKey='single:' + key, partyType=typ, partyName=name,
        paymentDirection=side, currency=data['currency'], amount=amount, nonCash=False, entryKind='legacy-import', batchId=f'legacy-import:{uid}:{number}-T{leg}',
        importBatchId=str(batch.pk), paymentDate='2024-03-15', reference=f'AP-REC-{n}-{leg}', note='Imported', createdAt=timezone.now().isoformat(), createdBy='qa', createdByName='QA')
        for leg, key, typ, name, side, amount in ((1, 'cedant', 'cedant', data['cedant'], 'receivable', 10000 + n), (2, 'r1', 'reinsurer', 'AP History Re', 'payable', 9500 + n))] if historical else []
    return O.create(uid=uid, number=number, original_serial=number, reference=reference, currency=data['currency'], revenue_month='2024-03', status='confirmed',
        historical=historical, batch=batch, first_confirmed_at=timezone.now(), data=data, fx_snapshot=dict(rate=1), financial={'paymentEntries': entries} if entries else {})
history = [legacy(n, True) for n in range(1, 131)]
open_legacy = [legacy(n, False) for n in range(200, 204)]
L._CACHE.clear(); P._HISTORY.clear()

# ---- contract ----
for role, want in (('accounting', 200), ('sales', 200), ('admin', 200), ('viewer', 403)):
    for q in ('view=page&tab=all', 'view=options'):
        check(f'{role} {q} -> {want}', R[role][0].get('/api/accounting?' + q).status_code == want)
check('an unknown tab is refused', fin.get('/api/accounting?view=page&tab=unreconciled').status_code == 400 and fin.get('/api/accounting?view=page').status_code == 400)
check('a page that is not a number is refused', fin.get('/api/accounting?view=page&tab=all&page=x').status_code == 400)
first = get(fin, 'view=page&tab=all')
check('page 1 has the fixed size and at most 100 rows', first['page'] == 1 and first['pageSize'] == 100 and len(first['rows']) == 100 and first['total'] > 200, first['total'])
check('a size parameter is ignored', len(get(fin, 'view=page&tab=all&size=500')['rows']) == 100)
check('page 0 and negative pages mean page 1', get(fin, 'view=page&tab=all&page=0')['rows'] == first['rows'] == get(fin, 'view=page&tab=all&page=-3')['rows'])
pages = -(-first['total'] // 100)
everything = [row for n in range(1, pages + 1) for row in get(fin, f'view=page&tab=all&page={n}')['rows']]
check('pages are disjoint and together hold every account once', len(everything) == first['total'] and len({r['key'] for r in everything}) == first['total'])
beyond = get(fin, f'view=page&tab=all&page={pages + 1}')
check('a page after the last is empty with the same total', beyond['rows'] == [] and beyond['total'] == first['total'])
check('the response carries no other accounts', set(first) == {'ok', 'tab', 'page', 'pageSize', 'total', 'rows', 'options', 'cashBatches', 'caseHistories'})

# ---- tabs and filters ----
settled = get(fin, 'view=page&tab=settled&settlement=settled')
check('Settled/Closed holds the settled history (two cash accounts per transaction)', settled['total'] >= 2 * 130 and all(r['settlement'] == 'settled' for r in settled['rows']))
broker = get(fin, 'view=page&tab=brokerage')
check('Brokerage holds the derived brokerage of the history', broker['total'] >= 130 and all(r.get('cashTracking') == 'derived' or r.get('overseaBusiness') for r in broker['rows']))
ref = get(fin, 'view=page&tab=all&reference=ap-ref-01')
check('the TW Ref filter is a case-insensitive substring match', ref['total'] > 0 and all('AP-REF-01' in (r.get('twRef') or '') + (r.get('manualTwRef') or '') for r in ref['rows']), ref['total'])
check('surrounding spaces in a filter are ignored', get(fin, 'view=page&tab=all&reference=%20ap-ref-01%20')['total'] == ref['total'])
ced = get(fin, 'view=page&tab=settled&settlement=settled&cedant=AP%20History%20Cedant')
check('the Cedant filter keeps only that cedant\'s accounts', ced['total'] == 130 and all(r.get('reinsured') == 'AP History Cedant' for r in ced['rows']), ced['total'])
usd = get(fin, 'view=page&tab=all&currency=USD')
check('the currency filter', usd['total'] > 0 and all(r['currency'] == 'USD' for r in usd['rows']))
check('the origin filter', get(fin, 'view=page&tab=all&origin=native')['total'] + get(fin, 'view=page&tab=all&origin=legacy')['total'] == first['total'])
check('the settlement filter (several values)', get(fin, 'view=page&tab=all&settlement=open,settled')['total'] <= first['total']
      and get(fin, 'view=page&tab=all&settlement=open')['total'] + get(fin, 'view=page&tab=all&settlement=settled')['total'] == get(fin, 'view=page&tab=all&settlement=open,settled')['total'])
check('a due-date filter with no match is empty', get(fin, 'view=page&tab=all&due=1990-01-01')['total'] == 0)

# ---- options and page data ----
opts = get(fin, 'view=options')['options']
check('the dropdowns include names found only in the settled history', 'AP History Cedant' in opts['cedants'] and 'AP Open Cedant' in opts['cedants'] and 'AP History Re' in opts['reinsurers'])
check('the currency choices combine open accounts and history, sorted', opts['currencies'] == sorted(set(opts['currencies'])) and {'TWD', 'USD'} <= set(opts['currencies']))
check('a page carries the same dropdown names', first['options'] == opts)
ids = {e.get('batchId') for r in settled['rows'] for e in (r.get('entries') or [])}
check('a page carries the registrations of its rows only', {b['batchId'] for b in settled['cashBatches']} <= ids and len(settled['cashBatches']) > 0)
check('a page carries correction histories of its rows only', set(settled['caseHistories']) <= {r['caseUid'] for r in settled['rows']})

# ---- freshness ----
row = next(r for n in range(1, pages + 1) for r in get(fin, f'view=page&tab=all&page={n}&origin=native')['rows'] if r.get('txNo', '').endswith('-T1') and not r.get('financeReviewed'))
case = Case.objects.get(case_uid=row['caseUid'])
r = post(fin, '/api/accounting', dict(action='review_accounts', date='2026-11-17', members=[dict(caseUid=row['caseUid'], rowVersion=case.row_version, txNo=row['txNo'])]))
check('a review is recorded', r.status_code == 200, r.content[:200])
after = [x for x in get(fin, f'view=page&tab=all&origin=native&reference={row["twRef"]}')['rows'] if x['key'] == row['key']]
check('a review shows on the next page request at once', after and after[0]['financeReviewed'] is True)
gone = history[0]
before = get(fin, 'view=page&tab=settled&settlement=settled')['total']
O.filter(pk=gone.pk).update(status='withdrawn')
check('withdrawing a settled history transaction shows at once', get(fin, 'view=page&tab=settled&settlement=settled')['total'] == before - 2)
O.filter(pk=gone.pk).update(status='confirmed')
check('and restoring it too', get(fin, 'view=page&tab=settled&settlement=settled')['total'] == before)
target = history[1]
def insured_of(uid):
    return {r.get('originalInsured') for r in get(fin, 'view=page&tab=all&reference=' + target.reference)['rows']}
original = insured_of(target.uid)
with connections['ap_owner'].cursor() as cur:   # direct edit that keeps version and update time, as a raw script could
    cur.execute("UPDATE ri_legacy_transactions SET data=JSON_SET(data,'$.insured',%s), updated_at=updated_at WHERE uid=%s", ['AP Edited Directly', target.uid.hex])
check('a direct edit keeping the update time is caught within the recheck interval, not before', insured_of(target.uid) == original)
P._HISTORY['checked'] = time.monotonic() - P.RECHECK_SECONDS - 1
check('after the recheck interval the full content fingerprint shows it', insured_of(target.uid) == {'AP Edited Directly'}, insured_of(target.uid))
saved = os.environ.get('RI_LEGACY_RESULT_CACHE')
try:
    os.environ['RI_LEGACY_RESULT_CACHE'] = 'false'; L._CACHE.clear(); P._HISTORY.clear()
    off = get(fin, 'view=page&tab=all')
    check('with the legacy cache switched off the pages are the same', off['rows'] == get(fin, 'view=page&tab=all')['rows'] and off['total'] == first['total'])
finally:
    if saved is None: os.environ.pop('RI_LEGACY_RESULT_CACHE', None)
    else: os.environ['RI_LEGACY_RESULT_CACHE'] = saved
    L._CACHE.clear(); P._HISTORY.clear()
check('the cached pages equal the uncached ones', get(fin, 'view=page&tab=all')['rows'] == off['rows'])

# ---- only the reads the screen uses are served (2026-11-17 owner decision) ----
from qa.accounting_full import accounting_get
for query in ('', '?view=list', '?view=list&legacy=history', '?view=list&legacy=zzz', '?legacy=open', '?view=detail'):
    r = fin.get('/api/accounting' + query)
    check(f'the retired read {query or "(no parameters)"} is refused', r.status_code == 400 and r.json().get('error') == 'unsupported_view', (r.status_code, r.content[:120]))
check('viewers are still refused before the read is examined', R['viewer'][0].get('/api/accounting').status_code == 403)
check('anonymous requests are still refused', Client(HTTP_HOST='localhost').get('/api/accounting').status_code == 401)
open_ = get(fin, 'view=list&legacy=open')
full, hist = accounting_get(fin, '?view=list').json(), accounting_get(fin, '?view=list&legacy=history').json()
check('the open list still answers, and with the internal reads still equals the complete list', 'legacyHistory' not in full and open_['legacyHistory']['scope'] == 'open'
      and hist['legacyHistory']['scope'] == 'history' and len(open_['transactionRows']) + len(hist['transactionRows']) == len(full['transactionRows']))
print(f'{len(checks)}/{len(checks)} passed')
