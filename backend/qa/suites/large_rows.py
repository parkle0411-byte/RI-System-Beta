from qa.accounting_full import accounting_get   # 2026-11-17: retired Accounting reads are internal in tests
"""Oversized rows never break a page (owner decision 2026-11-16). Disposable MySQL only.

MySQL refuses to sort a row larger than sort_buffer_size ("Out of sort memory"). One very large case,
review batch, Audit entry, legacy row, import batch, recycle-bin entry or Placing Slip version used to make
Accounting / Account List / Production Report / Dashboard / Legacy / Audit Log fail for everyone.
Each kind is made larger than this server's sort buffer in turn; every page and the main actions must
still answer, and ri_system.sorted_fetch must return exactly what the plain ordered query returns.
Also: settled legacy claim (cash) rows report paymentStatus 'settled'.
"""
import copy, json, os, uuid
from pathlib import Path
from django.db import connection, connections, transaction
from django.db.models import F
from django.test import Client
from django.utils import timezone
from django.contrib.auth import get_user_model
from audit.models import AuditLog, EntitySnapshot
from audit.services import record_audit
from cases.models import Case, DraftRecycleBin, FinanceReconciliationBatch, PlacingSlipVersion
from legacy.models import ImportBatch, LegacyAudit, LegacyTransaction
from personnel.models import Personnel
from production.models import ProductionReport
from ri_system.sorted_fetch import sorted_rows, sorted_values

assert os.environ.get('RI_DISPOSABLE_QA') == 'true'
checks = []
def check(name, ok, detail=''):
    assert ok, (name, detail)
    checks.append(name); print('PASS ' + name, flush=True)

with connection.cursor() as cur:
    cur.execute('SELECT @@sort_buffer_size'); buffer = int(cur.fetchone()[0])
PAD = 'x' * (buffer + 64 * 1024)
tag = uuid.uuid4().hex[:5]
def account(role, dept):
    u = get_user_model().objects.create_user(username=f'lr{tag}.{role}', password='Lr-Test-Pass-1')
    p = Personnel.objects.create(name=f'LR{tag} {role}', department=dept, role_code=role, auth_user_id=str(u.pk), account_status='active',
                                 email=f'{role}{tag}@example.test', created_by='qa', updated_by='qa')
    c = Client(HTTP_HOST='localhost', raise_request_exception=False); c.force_login(u); return c, p
R = {role: account(role, dept) for role, dept in (('admin', 'admin'), ('sales', 'reinsurance'), ('general_manager', 'reinsurance'),
     ('accounting_manager', 'finance'), ('accounting', 'finance'), ('viewer', 'reinsurance'))}
sales, sp = R['sales']; finm = R['accounting_manager'][0]; fin = R['accounting'][0]; admin = R['admin'][0]
def body(name, **over):
    b = dict(classOfBusiness='Property', classCode='PF', typePrefix='Property', reinsuranceStructure='QS', currency='TWD', originalInsured=name,
        originalInsuredCn='大資料測試', reinsured='LR Cedant', newOrRenew='New', policyFrom='2026-11-01', policyTo='2027-11-01', interest='Stock',
        situations=[{'address': 'Taipei', 'postcode': '100'}], sumInsured=[{'category': 'Building', 'amount': 1000000}], basisOfValuation='Actual Cash Value',
        originalPremium=100000, riCommPct=0, taxPct=1, paymentTermsDays=90, deductibles='TWD 1,000', originalConditions='A', reinsuredRetention='Waived',
        lossAdvisedDate='2026-01-01', lossRecordYears=5, ae=sp.name, ownerPersonnelId=sp.pk, ownerPersonnelName=sp.name,
        reinsurers=[{'name': 'LR Re A', 'sharePct': 60, 'premium': 100000, 'riCommPct': 10, 'taxPct': 1, 'paymentTermsDays': 90},
                    {'name': 'LR Re B', 'sharePct': 40, 'premium': 100000, 'riCommPct': 10, 'taxPct': 1, 'paymentTermsDays': 90}])
    b.update(over); return b
def post(c, url, data): return c.post(url, json.dumps(data), content_type='application/json')

# ---- data through the API (Announce is replaced by its state change; documents are not the subject here) ----
cases = []
for n in range(3):
    r = post(sales, '/api/cases', {'case': body(f'LR{tag} Insured {n}')}); assert r.status_code == 201, r.content[:300]
    c = Case.objects.get(case_uid=r.json()['case']['caseUid'])
    Case.objects.filter(pk=c.pk).update(status='posted', tw_ref=f'LR{tag}{n:03d}', announced_at=timezone.now())
    cases.append(Case.objects.get(pk=c.pk))
A, B, C = cases
draft = Case.objects.get(case_uid=post(sales, '/api/cases', {'case': body(f'LR{tag} Draft')}).json()['case']['caseUid'])
recycled = Case.objects.get(case_uid=post(sales, '/api/cases', {'case': body(f'LR{tag} Recycled')}).json()['case']['caseUid'])
r = post(admin, '/api/draft-recycle-bin', {'action': 'recycle', 'caseUid': str(recycled.case_uid), 'rowVersion': recycled.row_version})
check('a draft is in the recycle bin', r.status_code in (200, 201), (r.status_code, r.content[:300]))
def claim(case, data):
    case.refresh_from_db(); data.update(caseUid=str(case.case_uid), rowVersion=case.row_version); return post(sales, '/api/claims', data)
for case in (A, B):
    check(f'{case.tw_ref}: claim created', claim(case, {'action': 'create_claim', 'claim': {'dateOfLoss': '2026-11-05', 'outstandingReserve': 50000}}).status_code == 200)
    for _ in range(2):
        check(f'{case.tw_ref}: claim payment recorded', claim(case, {'action': 'record_payment', 'claimId': 1, 'payment': {'amount': 1000, 'date': '2026-11-10'}}).status_code == 200)
mine = [x for x in accounting_get(fin, '?view=list').json()['transactionRows'] if x.get('caseUid') in {str(c.case_uid) for c in cases}]
def member(x): return dict(caseUid=x['caseUid'], rowVersion=Case.objects.get(case_uid=x['caseUid']).row_version, txNo=x['txNo'])
rA = [x for x in mine if x['caseUid'] == str(A.case_uid)]; rB = [x for x in mine if x['caseUid'] == str(B.case_uid)]
check('review batch recorded', post(fin, '/api/accounting', dict(action='review_accounts', date='2026-11-16', members=[member(rA[0])])).status_code == 200)
cashable = next(x for x in rA[1:] if x.get('canRecord'))
check('cash recorded', post(fin, '/api/accounting', dict(action='record_transaction_payments', cashSubmissionId=str(uuid.uuid4()), paymentDate='2026-11-16', reference='LR',
      allocations=[dict(cashItemId=str(uuid.uuid4()), caseUid=cashable['caseUid'], txNo=cashable['txNo'], cashAmount=10, rowVersion=Case.objects.get(case_uid=cashable['caseUid']).row_version)])).status_code == 200)
preview = finm.get('/api/production-report?month=2026-11').json()
check('production report generated', post(finm, '/api/production-report', {'action': 'generate', 'month': '2026-11', 'sourceSignature': preview.get('sourceSignature')}).status_code == 201)
PlacingSlipVersion.objects.create(id=uuid.uuid4(), case=draft, version=1, source='generated', filename='qa.docx', content_type='application/octet-stream', byte_size=1,
    sha256='0' * 64, storage_key='qa/none', description='qa', case_version=1, signature='0' * 64, snapshot={'qa': True}, uploaded_by='qa')

owner = copy.deepcopy(connections.databases['default']); owner.update(USER='ri_app', PASSWORD=Path('/run/secrets/mysql_app_password').read_text().strip())
connections.databases['lr_owner'] = owner
batch = ImportBatch.objects.using('lr_owner').create(filename='lr.xlsx', sha256='f' * 64, storage_key='qa/lr.xlsx', status='imported', created_by='qa')
def legacy(n, historical, kind='premium', **extra):
    number = f'LR-{tag}-{n}'
    data = dict(reference=f'LR-REF-{n}', currency='TWD', insured=f'LR Legacy {n}', insuredCn='舊', cedant='LR Cedant', party='LR Re A', ae=sp.name, statementNo=f'ST{n}',
        gross=10000, share=100, rule='ordinary', kind=kind, classCode='PD', classOfBusiness='Property', effectiveDate='2026-01-01', expiryDate='2026-12-31',
        receiveReminder='2026-12-15', payReminder='2026-12-30', amounts=dict(premium=10000, commission=0, tax=0, brokerage=500, claim=0, cedantNet=10000, reinsurerNet=9500), **extra)
    return LegacyTransaction.objects.using('lr_owner').create(uid=uuid.uuid4(), number=number, original_serial=number, reference=f'LR-REF-{n}', currency='TWD',
        revenue_month='2026-11', status='confirmed', historical=historical, batch=batch, first_confirmed_at=timezone.now(), data=data, fx_snapshot=dict(rate=1), financial={})
L_open, L_hist = legacy(1, False), legacy(2, True)
LegacyAudit.objects.using('lr_owner').create(entity=str(L_open.uid), action='qa', actor_name='qa', before={}, after={'qa': 1})

U = [str(c.case_uid) for c in cases] + [str(draft.case_uid)]
GETS = ['/api/accounting?view=list', '/api/accounting?view=list&legacy=open', '/api/accounting?view=list&legacy=history', '/api/accounting', '/api/cases',
        '/api/dashboard', '/api/production-report?month=2026-11', '/api/production-report?month=2026-12', '/api/legacy', f'/api/legacy?id={L_open.uid}',
        f'/api/legacy?id={L_hist.uid}', '/api/legacy/imports', '/api/audit-log', '/api/draft-recycle-bin', '/api/system-reference']
for u in U:
    GETS += [f'/api/cases?caseUid={u}', f'/api/case-workflow?caseUid={u}', f'/api/claims?caseUid={u}', f'/api/placing-slips?caseUid={u}', f'/api/case-reminders?caseUid={u}']
def answers():
    failed = []
    for role, (c, _) in R.items():
        for g in GETS:
            s = c.get(g).status_code
            if s >= 500: failed.append((role, g, s))
    for label, fn in (
        ('claim on another case', lambda: claim(C, {'action': 'create_claim', 'claim': {'dateOfLoss': '2026-11-05', 'outstandingReserve': 100}})),
        ('draft save', lambda: sales.put('/api/cases', json.dumps({'caseUid': str(draft.case_uid), 'rowVersion': Case.objects.get(pk=draft.pk).row_version,
                                                                     'case': body(f'LR{tag} Draft')}), content_type='application/json')),
        ('new draft', lambda: post(sales, '/api/cases', {'case': body(f'LR{tag} New {uuid.uuid4().hex[:4]}')})),
        ('review on another case', lambda: post(fin, '/api/accounting', dict(action='review_accounts', date='2026-11-16', members=[member(rB[0])]))),
        ('cancel the other review', lambda: post(fin, '/api/accounting', dict(action='cancel_review_batch', reviewBatchId=str(FinanceReconciliationBatch.objects.filter(status='active').order_by('-created_at').values_list('pk', flat=True).first()), reason='qa')))):
        s = fn().status_code
        if s >= 500: failed.append(('write', label, s))
    return failed
check('baseline: every page and action answers', not answers(), answers())

def inflate(table, column, where, params, shape):
    """Make one row larger than the sort buffer; return a function that restores it by a full rewrite."""
    with connections['lr_owner'].cursor() as cur:
        cur.execute(f'SELECT `{column}` FROM {table} WHERE {where}', params); original = cur.fetchone()[0]
        expr = f"JSON_SET(`{column}`,'$.zzPad',%s)" if shape == 'object' else f"JSON_SET(`{column}`,'$[0].zzPad',%s)"   # array: enlarge its first element
        cur.execute(f'UPDATE {table} SET `{column}`={expr} WHERE {where}', [PAD, *params])
    def restore():
        with connections['lr_owner'].cursor() as cur:
            cur.execute(f'UPDATE {table} SET `{column}`=%s WHERE {where}', [original, *params])
    return restore
first = lambda model: str(model.objects.order_by('pk').values_list('pk', flat=True).first()).replace('-', '')
kinds = [('an announced case', 'ri_cases', 'payload', 'id=%s', [A.pk], 'object'),
         ('a draft case', 'ri_cases', 'payload', 'id=%s', [draft.pk], 'object'),
         ('a saved production report', 'ri_production_reports', 'rows', 'id=%s', [ProductionReport.objects.values_list('pk', flat=True).first()], 'array'),
         ('a finance review batch', 'ri_finance_reconciliation_batches', 'members', 'id=%s', [first(FinanceReconciliationBatch)], 'array'),
         ('an unsettled legacy row', 'ri_legacy_transactions', 'data', 'uid=%s', [L_open.uid.hex], 'object'),
         ('a settled legacy row', 'ri_legacy_transactions', 'data', 'uid=%s', [L_hist.uid.hex], 'object'),
         ('a legacy import batch', 'ri_legacy_import_batches', 'manifest', 'id=%s', [batch.pk.hex], 'object')]
if DraftRecycleBin.objects.exists():
    kinds.append(('a recycle-bin entry', 'ri_draft_recycle_bin', 'case_snapshot', 'id=%s', [DraftRecycleBin.objects.values_list('pk', flat=True).first()], 'object'))
if PlacingSlipVersion.objects.exists():
    kinds.append(('a Placing Slip version', 'ri_placing_slip_versions', 'snapshot', 'id=%s', [PlacingSlipVersion.objects.values_list('pk', flat=True).first().hex], 'object'))
for label, *args in kinds:
    restore = inflate(*args)
    failed = answers()
    check(f'one oversized row ({label}, {len(PAD) // 1024} KB): every page and action still answers', not failed, failed)
    restore()
LegacyAudit.objects.using('lr_owner').create(entity=str(L_open.uid), action='qa_oversized', actor_name='qa', before={}, after={'zzPad': PAD})
failed = answers()
check('one oversized legacy audit entry (append-only, stays): every page and action still answers', not failed, failed)
check('the legacy transaction still lists its audit entries in order', [e['action'] for e in admin.get(f'/api/legacy?id={L_open.uid}').json()['audit']][-1] == 'qa_oversized')
with transaction.atomic():
    record_audit(entity_type='case', entity_id=str(A.case_uid), action='qa_oversized', actor={'id': 'qa', 'name': 'qa', 'role': 'admin'}, after={'zzPad': PAD})
failed = answers()
check('one oversized Audit entry (append-only, stays): every page and action still answers', not failed, failed)
events = admin.get('/api/audit-log?limit=250').json()['events']
check('Audit Log lists the oversized entry, newest first, in database order', 'qa_oversized' in [e['action'] for e in events]
      and [e['id'] for e in events] == list(AuditLog.objects.order_by('-occurred_at', '-id').values_list('id', flat=True)[:250]))

# ---- the helper returns exactly what the ordered query returns ----
for label, qs, order in (('cases by tw_ref', Case.objects.all(), ('tw_ref', 'id')), ('cases by -updated_at', Case.objects.select_related('ae_personnel'), ('-updated_at', '-id')),
        ('cases with nulls last', Case.objects.all(), (F('announced_at').asc(nulls_last=True), F('created_at').asc(nulls_last=True), 'id')),
        ('Production cases (filter reads the JSON payload)', __import__('production.views', fromlist=['_live_cases'])._live_cases(), (F('announced_at').asc(nulls_last=True), F('created_at').asc(nulls_last=True), 'id')),
        ('legacy claims (filter reads the JSON data)', LegacyTransaction.objects.filter(data__kind__in=('premium', 'claim')), ('reference', 'uid')),
        ('legacy', LegacyTransaction.objects.all(), ('reference', 'uid')), ('legacy newest first', LegacyTransaction.objects.all(), ('-created_at', 'uid')),
        ('audit newest first', AuditLog.objects.all(), ('-occurred_at', '-id')), ('snapshots', EntitySnapshot.objects.all(), ('-created_at', '-id'))):
    plain = [x.pk for x in qs.order_by(*order)] if label not in ('audit newest first',) else list(qs.order_by(*order).values_list('pk', flat=True))
    check(f'sorted_rows equals the ordered query: {label}', [x.pk for x in sorted_rows(qs, *order)] == plain and len(plain) > 1)
    check(f'sorted_rows slices like the ordered query: {label}', [x.pk for x in sorted_rows(qs, *order, start=1, stop=3)] == plain[1:3])
fields = ('id', 'entity_type', 'action', 'occurred_at')
check('sorted_values equals the ordered values query', sorted_values(AuditLog.objects.all(), ('-occurred_at', '-id'), fields, stop=5) == list(AuditLog.objects.order_by('-occurred_at', '-id').values(*fields)[:5]))
check('sorted_values without id keeps the same keys', sorted_values(AuditLog.objects.all(), ('-occurred_at', '-id'), ('action',), stop=3) == list(AuditLog.objects.order_by('-occurred_at', '-id').values('action')[:3]))
check('sorted_rows of an empty queryset is empty', sorted_rows(Case.objects.none(), 'tw_ref') == [])
with transaction.atomic():
    locked = sorted_rows(FinanceReconciliationBatch.objects.select_for_update().filter(status__in=('active', 'cancelled')), 'created_at', 'id')
    check('locking query keeps its rows and order', [b.pk for b in locked] == list(FinanceReconciliationBatch.objects.filter(status__in=('active', 'cancelled')).order_by('created_at', 'id').values_list('pk', flat=True)))
row = sorted_rows(Case.objects.select_related('ae_personnel').filter(pk=A.pk), 'id')[0]
check('select_related is kept', 'ae_personnel' in row._state.fields_cache)

# ---- settled legacy claim rows report settled ----
claim_tx = legacy(3, True, kind='claim', lossNo='LR-L1', lossDate='2026-02-01')
LegacyTransaction.objects.using('lr_owner').filter(pk=claim_tx.pk).update(data={**claim_tx.data, 'receiveReminder': '', 'payReminder': '', 'claim': 5000,   # imported claims carry no reminder dates
    'amounts': dict(premium=0, commission=0, tax=0, brokerage=0, claim=5000, cedantNet=5000, reinsurerNet=5000)})
import legacy.ledger as ledger
ledger._CACHE.clear()
rows = [x for x in accounting_get(fin, '?view=list').json()['transactionRows'] if x.get('legacyTransactionId') == str(claim_tx.uid)]
cash = [x for x in rows if x.get('cashTracking') == 'cash']
check('settled legacy claim rows exist', bool(cash) and all(x['settlement'] == 'settled' for x in cash), rows)
check('settled legacy claim cash rows report paymentStatus settled', all(x['paymentStatus'] == 'settled' for x in cash), [(x['txNo'], x['paymentStatus']) for x in cash])
derived = [x for x in accounting_get(fin, '?view=list').json()['transactionRows'] if x.get('legacyTransactionId') == str(L_hist.uid) and x.get('cashTracking') == 'derived']
check('derived T3 rows keep their previous status', all(x['paymentStatus'] == 'pending_review' for x in derived) and bool(derived), [(x['txNo'], x['paymentStatus']) for x in derived])
print(f'{len(checks)}/{len(checks)} passed')
