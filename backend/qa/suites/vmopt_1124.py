"""2026-11-24 owner decisions: Facility Declaration Claim limit, CGL Coverages type check on incomplete drafts,
Dashboard legacy-input cache (shared, keyed by legacy / FX change fingerprints and the Taipei date) and the
Accounting page cache (filtered and sorted settled history kept per query). Disposable MySQL only."""
import base64, copy, json, os, random, uuid
from pathlib import Path
from django.conf import settings
from django.db import connections
from django.test import Client
from django.utils import timezone
from django.contrib.auth import get_user_model
from fxrates.models import FxRate
from legacy.models import ImportBatch, LegacyTransaction
from personnel.models import Personnel
import cases.accounting_pages as P
import legacy.dashboard as LD
import legacy.ledger as L
from ri_system import result_cache

assert os.environ.get('RI_DISPOSABLE_QA') == 'true'
checks = []


def check(name, ok, detail=''):
    assert ok, (name, str(detail)[:400])
    checks.append(name); print('PASS ' + name, flush=True)


tag = uuid.uuid4().hex[:5]


def account(role, dept):
    u = get_user_model().objects.create_user(username=f'vm{tag}.{role}', password='Vm-Test-Pass-1')
    p = Personnel.objects.create(name=f'VM{tag} {role}', department=dept, role_code=role, auth_user_id=str(u.pk), account_status='active',
                                 email=f'{role}{tag}@example.test', created_by='qa', updated_by='qa')
    c = Client(enforce_csrf_checks=True, HTTP_HOST='localhost', raise_request_exception=False); c.force_login(u); c.get('/api/auth/csrf')
    return c, p


sales, sp = account('sales', 'reinsurance')
admin, _ = account('admin', 'admin')


def call(c, method, url, data=None):
    c.get('/api/auth/csrf')
    kw = {'HTTP_X_CSRFTOKEN': c.cookies['csrftoken'].value}
    if data is not None:
        kw.update(data=json.dumps(data), content_type='application/json')
    return getattr(c, method)(url, **kw)


# ---- B2: Facility Declaration Claim limit (same as Premium, 999,999,999,999) ----
FAC = {'facilityName': 'VM Facility', 'facilityTypePrefix': 'Travel', 'classOfBusiness': 'Personal Accident', 'reinsured': 'Cedant',
       'currency': 'USD', 'policyFrom': '2026-07-01', 'policyTo': '2027-07-01', 'riCommPct': 20, 'taxPct': 0, 'ppwDays': 75,
       'reinsurers': [{'name': 'A', 'sharePct': 50, 'deductionPct': 30, 'taxPct': 0, 'facilityReference': 'RA'},
                      {'name': 'B', 'sharePct': 30, 'deductionPct': 25, 'taxPct': 0, 'facilityReference': 'RB'}]}
r = call(sales, 'post', '/api/facility-placement', {'case': FAC}); assert r.status_code == 201, r.content
uid = r.json()['case']['caseUid']
r = call(sales, 'post', '/api/facility-announce', {'caseUid': uid, 'rowVersion': 1, 'confirmed': True}); assert r.status_code == 200, r.content
decl = {'periodFrom': '2026-07-01', 'periodTo': '2026-09-30', 'statementNo': 'S1', 'premium': 100}
for claim in ('1000000000000', '-1000000000000', '1' + '0' * 27, '-1' + '0' * 40):
    r = call(sales, 'post', '/api/facility-declarations', {'facilityUid': uid, 'declaration': {**decl, 'claim': claim}})
    check(f'Claim {claim[:6]}… over the limit is refused with a message', r.status_code == 400 and 'Claim exceeds the supported amount' in r.json().get('message', ''), r.content)
r = call(sales, 'post', '/api/facility-declarations', {'facilityUid': uid, 'declaration': {**decl, 'claim': '999999999999'}})
check('Claim at the limit is accepted', r.status_code == 201, r.content)
du, ver = r.json()['declaration']['declarationUid'], r.json()['declaration']['rowVersion']
r = call(sales, 'post', '/api/facility-declaration-documents', {'facilityUid': uid, 'declarationUid': du, 'filename': 's.pdf',
                                                                 'base64': base64.b64encode(b'%PDF-1.4\nVM\n').decode()})
assert r.status_code == 201, r.content
r = call(sales, 'post', '/api/facility-declaration-announce', {'facilityUid': uid, 'declarationUid': du, 'rowVersion': ver, 'confirmed': True})
check('Declaration with the largest Claim announces', r.status_code == 200 and r.json()['declaration']['status'] == 'posted', r.content)
posted = r.json()['declaration']
r = call(sales, 'put', '/api/facility-declarations', {'facilityUid': uid, 'declarationUid': du, 'rowVersion': posted['rowVersion'],
                                                      'declaration': {**decl, 'claim': '5' + '0' * 30}})
check('correcting an announced Declaration with a Claim over the limit is refused', r.status_code == 400 and 'Claim exceeds' in r.json().get('message', ''), r.content)
r = call(sales, 'post', '/api/facility-declarations', {'facilityUid': uid, 'declaration': {**decl, 'periodFrom': '2026-10-01', 'periodTo': '2026-12-31',
                                                                                          'statementNo': 'S2', 'premium': '1000000000000', 'claim': 1}})
check('the Premium limit is unchanged', r.status_code == 400 and 'Premium exceeds' in r.json().get('message', ''), r.content)

# ---- B3: CGL Coverages must be a list on an incomplete draft ----
CGL = dict(reinsuranceStructure='QS', classOfBusiness='Commercial General Liability', classCode='GL', currency='USD', newOrRenew='New',
           ownerPersonnelId=sp.pk, aePersonnelId=sp.pk, ae=sp.name, originalInsuredCn='QS QA CN', riCommPct=0, taxPct=0,
           typePrefix='Commercial General Liability', originalInsured='QA Insured', reinsured='QA Cedant', policyFrom='2026-01-01', policyTo='2027-01-01',
           situations=[dict(address='QA Road', postcode='100')], interest='Liability', limitOfLiability=1000000, deductibles='As original',
           originalConditions='As original', reinsuredRetention='Advice waived', originalPremium=1000, paymentTermsDays=90,
           lossAdvisedDate='2026-01-01', lossRecordYears=5, reinsurers=[dict(name='QA General Re', sharePct=100, premium=1000, riCommPct=10, taxPct=0, paymentTermsDays=90)],
           coverages=['Premises-Operations Liability'], coveragesOther='', selfInsuredRetention='',
           cglInformation=dict(policyForm='Occurrence Form', territorialLimits='Worldwide excluding USA/Canada', insuredBusiness='Business',
                               insuredBusinessSelections=['Other'], insuredBusinessOther='Business', insuredProducts='Products',
                               specialAgreementApplies='notApplicable', estimatedTurnover=[dict(region='USA/Canada', currency='USD', amount=1000000)]))
for value in (1.5, True, 'Other', {'Other': 1}, 7):
    r = call(sales, 'post', '/api/cases', {'case': {**CGL, 'coverages': value, 'coveragesOtherItems': ['Extra']}, 'incompleteDraft': True})
    check(f'incomplete CGL draft with Coverages {value!r} is refused, not a server error', r.status_code == 400 and
          'Coverages must be a list' in json.dumps(r.json()), r.content[:300])
for value in (None, [], 0, False, ['Other']):
    r = call(sales, 'post', '/api/cases', {'case': {**CGL, 'coverages': value, 'coveragesOtherItems': ['Extra']}, 'incompleteDraft': True})
    check(f'incomplete CGL draft with Coverages {value!r} is still saved', r.status_code == 201, r.content[:300])
r = call(sales, 'post', '/api/cases', {'case': {**CGL, 'coverages': ['Other'], 'coveragesOtherItems': ['Extra', ' extra ']}, 'incompleteDraft': True})
check('duplicate Other entries are still refused', r.status_code == 400, r.content[:300])
r = call(sales, 'post', '/api/cases', {'case': {**CGL, 'coverages': 1.5}})
check('a complete draft with Coverages not a list is refused as before', r.status_code == 400, r.content[:300])
r = call(sales, 'post', '/api/cases', {'case': {**CGL, 'classOfBusiness': 'Property', 'classCode': 'PF', 'typePrefix': 'Property', 'coverages': 1.5}, 'incompleteDraft': True})
check('the check applies only to standard CGL', r.status_code != 500 and 'Coverages must be a list' not in r.content.decode(), r.content[:300])

# ---- Dashboard legacy inputs: cache keyed by legacy / FX fingerprints and the Taipei date, shared through a file ----
settings.RESULT_CACHE_ENABLED = True
settings.RESULT_CACHE_TTL_SECONDS = 3600
owner = copy.deepcopy(connections.databases['default']); owner.update(USER='ri_app', PASSWORD=Path('/run/secrets/mysql_app_password').read_text().strip())
connections.databases['vm_owner'] = owner
O = LegacyTransaction.objects.using('vm_owner')
batch = ImportBatch.objects.using('vm_owner').create(filename='vm.xlsx', sha256='c' * 64, storage_key='qa/vm.xlsx', status='imported', created_by='qa')


def legacy(n):
    data = dict(reference=f'VM-REF-{n}', currency='TWD', insured=f'VM Legacy {n}', insuredCn='舊資料', cedant='VM Cedant', party='VM Re', ae=sp.name,
                statementNo=f'VM-ST-{n}', gross=10000, share=100, rule='ordinary', kind='premium', classCode='PD', classOfBusiness='Property',
                effectiveDate='2026-03-01', expiryDate='2027-02-28', receiveReminder='2026-03-15', payReminder='2026-04-15', newRenew='New',
                amounts=dict(premium=10000 + n, commission=0, tax=0, brokerage=500, claim=0, cedantNet=10000 + n, reinsurerNet=9500 + n))
    return O.create(uid=uuid.uuid4(), number=f'VM-{tag}-{n}', original_serial=f'VM-{tag}-{n}', reference=data['reference'], currency='TWD',
                    revenue_month='2026-03', status='confirmed', historical=False, batch=batch, first_confirmed_at=timezone.now(), data=data, fx_snapshot=dict(rate=1))


legacy(1)
calls = [0]
compute = LD._compute_inputs


def counted():
    calls[0] += 1
    return compute()


LD._compute_inputs = counted
path = LD._inputs_file()


def fresh():
    LD._MEMO.clear()
    path.unlink(missing_ok=True)


try:
    fresh()
    first = LD.dashboard_inputs(); second = LD.dashboard_inputs()
    check('the legacy inputs are computed once for repeated Dashboard reads', calls[0] == 1 and first == second, calls)
    check('the cached inputs equal a direct computation', first == compute())
    first['policies'].append({'expiry': 'x', 'items': []})
    check('each caller gets its own copy (changing one result does not change the cache)', LD.dashboard_inputs() == second and calls[0] == 1)
    check('the shared file lives in its own folder (it never replaces the legacy history snapshots)', path.exists() and path.parent.name == 'dashboard' and path.parent.parent == L._snapshot_dir())
    LD._MEMO.clear()
    check('another worker (empty memory) reads the shared file instead of recomputing', LD.dashboard_inputs() == second and calls[0] == 1, calls)
    row = legacy(2)
    third = LD.dashboard_inputs()
    check('a new legacy row is picked up at once', calls[0] == 2 and third != second and len(third['trend']) == len(second['trend']) + 1, calls)
    O.filter(pk=row.pk).update(version=row.version + 1, data={**row.data, 'amounts': {**row.data['amounts'], 'premium': 99}})
    LD.dashboard_inputs()
    check('an edited legacy row (version change) is picked up at once', calls[0] == 3, calls)
    FxRate.objects.create(year_month='2026-03', currency='USD', rate=31, created_by='qa', updated_by='qa')
    LD.dashboard_inputs()
    check('an FX Rates change is picked up at once', calls[0] == 4, calls)
    today = L._today
    L._today = lambda: '2099-01-01'
    try:
        LD.dashboard_inputs()
        check('a new Taipei date recomputes', calls[0] == 5, calls)
    finally:
        L._today = today
    logic = L._LOGIC
    L._LOGIC = 'other-code-version'
    try:
        LD.dashboard_inputs()
        check('a new program version recomputes', calls[0] == 6, calls)
    finally:
        L._LOGIC = logic
    LD.dashboard_inputs()
    settings.RESULT_CACHE_TTL_SECONDS = 0
    LD.dashboard_inputs(); LD.dashboard_inputs()
    check('the insurance limit (RI_RESULT_CACHE_TTL) applies to memory and file', calls[0] == 9, calls)
    settings.RESULT_CACHE_TTL_SECONDS = 3600
    settings.RESULT_CACHE_ENABLED = False
    fresh(); LD.dashboard_inputs(); LD.dashboard_inputs()
    check('with the result cache switched off every read computes and no file is written', calls[0] == 11 and not path.exists(), calls)
    settings.RESULT_CACHE_ENABLED = True
    result_cache.clear(); fresh()
    cached_body = admin.get('/api/dashboard').content
    settings.RESULT_CACHE_ENABLED = False
    plain_body = admin.get('/api/dashboard').content
    settings.RESULT_CACHE_ENABLED = True
    check('the Dashboard response is byte-identical with and without the cache', cached_body == plain_body and b'"ok":true' in cached_body.replace(b' ', b''), cached_body[:200])
finally:
    LD._compute_inputs = compute
    settings.RESULT_CACHE_ENABLED = False
    fresh()

# ---- Accounting pages: the filtered, sorted history of a query is kept in the history part ----
random.seed(1124)
NAMES, CEDANTS, DATES = ['Re A', 'Re B', 'Re C', 'Re D', ''], ['Cedant X', 'Cedant Y', ''], ['', '2026-01-01', '2026-06-30', '2026-11-24', '2027-01-01']


def synthetic(n, prefix):
    rows = []
    for i in range(n):
        rows.append({'key': f'{prefix}{i}', 'txNo': random.choice([f'TX{i % 17}', '']), 'settlement': random.choice(['settled', 'open', 'partial']),
                     'legType': random.choice(['Leg 1', 'Leg 2', 'Leg 3', 'Claim Leg 2', '']), 'partyName': random.choice(NAMES),
                     'reinsured': random.choice(CEDANTS), 'currency': random.choice(['TWD', 'USD']), 'dueDate': random.choice(DATES),
                     'contractDueDate': random.choice(DATES), 'twRef': random.choice(['TWA', 'TWB', 'twa', '']), 'originalInsured': random.choice(['Alpha', 'Beta', '']),
                     'paymentDirection': random.choice(['receivable', 'payable']), 'source': random.choice(['premium', 'claim']),
                     'cashTracking': random.choice(['cash', 'cash', 'derived']), 'overseaBusiness': random.random() < .1,
                     'origin': random.choice(['native', 'legacy']), 'reversed': random.random() < .05, 'schedules': []})
    return rows


hist, opened = synthetic(600, 'h'), synthetic(40, 'o')


def old_order(open_rows, part, tab, filters, text, now):
    listed = P.filter_rows(open_rows + part['rows'], tab, filters, text)
    keys = P._history_keys(part, tab, now)
    listed.sort(key=lambda r: keys.get(id(r)) or P.sort_key(r, tab, now))
    return [id(r) for r in listed]


def new_order(open_rows, part, tab, filters, text, now):
    listed = P.filter_rows(open_rows, tab, filters, text) + P._history_listed(part, tab, filters, text, now)
    keys = P._history_keys(part, tab, now)
    listed.sort(key=lambda r: keys.get(id(r)) or P.sort_key(r, tab, now))
    return [id(r) for r in listed]


def old_parties(rows):
    cedants, reinsurers = {}, {}
    for r in rows:
        if P.is_derived_brokerage(r):
            continue
        party = P.transaction_party(r)
        if P.js_truthy(party):
            (cedants if P.is_cedant_account(r) else reinsurers).setdefault(party, None)
    return {'cedants': sorted(cedants, key=P._code_units), 'reinsurers': sorted(reinsurers, key=P._code_units)}


blank = {k: '' for k in ('cedant', 'reinsurer', 'currency', 'direction', 'source', 'origin', 'due')}
queries = [({**blank, 'settlement': []}, {'reference': '', 'insured': ''})]
queries += [({**blank, 'settlement': s}, {'reference': '', 'insured': ''}) for s in (['settled'], ['open'], ['open', 'settled'])]
queries += [({**blank, k: v, 'settlement': []}, {'reference': '', 'insured': ''}) for k, v in
            (('cedant', 'Cedant X'), ('reinsurer', 'Re B'), ('currency', 'USD'), ('direction', 'payable'), ('source', 'claim'), ('origin', 'legacy'), ('due', '2026-06-30'))]
queries += [({**blank, 'settlement': []}, t) for t in ({'reference': 'twa', 'insured': ''}, {'reference': '', 'insured': ' ALPHA '})]
same = 0
for date_free in (False, True):
    part = {'rows': hist, 'dateFree': date_free, 'sortKeys': {}}
    for now in ('2026-06-30', '2026-11-24'):
        for tab in ('all', 'settled', 'brokerage'):
            for filters, text in queries:
                same += old_order(opened, part, tab, filters, text, now) == new_order(opened, part, tab, filters, text, now)
check('page order with the kept history equals sorting every row at once (ties included)', same == 2 * 2 * 3 * len(queries), same)
part = {'rows': hist, 'dateFree': False, 'sortKeys': {}}
check('dropdown names with the kept history parties equal the former computation',
      P.party_options(opened, P._history_parties(part)) == old_parties(opened + hist) and P.party_options(opened) == old_parties(opened))
filtered = [0]
real_filter = P.filter_rows


def counting(rows, *args):
    if len(rows) == len(hist):   # a history part's rows (the open rows are fewer)
        filtered[0] += 1
    return real_filter(rows, *args)


P.filter_rows = counting
try:
    f, t = queries[0]
    P._history_listed(part, 'all', f, t, '2026-11-24'); P._history_listed(part, 'all', f, t, '2026-11-24')
    check('the same query filters the history once', filtered[0] == 1, filtered)
    P._history_listed(part, 'settled', f, t, '2026-11-24'); P._history_listed(part, 'all', queries[4][0], t, '2026-11-24')
    check('another tab or filter is computed separately', filtered[0] == 3, filtered)
    P._history_listed(part, 'all', f, t, '2026-11-25')
    check('a history with unsettled rows is recomputed on a new date', filtered[0] == 4, filtered)
    free = {'rows': hist, 'dateFree': True, 'sortKeys': {}}
    P._history_listed(free, 'all', f, t, '2026-11-24'); P._history_listed(free, 'all', f, t, '2026-11-25')
    check('an all-settled history keeps one list for every day', filtered[0] == 5, filtered)
    newer = {'rows': list(hist), 'dateFree': False, 'sortKeys': {}}
    P._history_listed(newer, 'all', f, t, '2026-11-24')
    check('a rebuilt history part starts with its own lists', filtered[0] == 6 and 'pageLists' in newer, filtered)
    for n in range(P.PAGE_LISTS_MAX + 8):
        P._history_listed(part, 'all', {**blank, 'due': f'2026-01-{n % 28 + 1:02d}', 'settlement': [str(n)]}, t, '2026-11-24')
    check('at most PAGE_LISTS_MAX query lists are kept per part', len(part['pageLists']) <= P.PAGE_LISTS_MAX, len(part['pageLists']))
finally:
    P.filter_rows = real_filter

print(f'{len(checks)} passed VM optimization 2026-11-24 checks; disposable database')
