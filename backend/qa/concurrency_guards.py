"""Real MySQL connections and overlapping writes. Run in a DISPOSABLE DB only.

Fixtures commit so other connections can see them. The QA runner destroys the
database afterwards; this suite must never run against the VM database.
"""
import json
import threading
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest import mock
from uuid import uuid4

from django.contrib.auth import get_user_model
from django.db import connections, transaction
from django.test import override_settings
from rest_framework.test import APIRequestFactory, force_authenticate

from audit.models import AuditLog, EntitySnapshot
from cases.draft import normalize_draft
from cases.models import Case
from fxrates.models import CURRENCIES, FxRate
from fxrates.views import FxRatesView
from personnel import accounts
from personnel.models import Personnel
from personnel.views import PersonnelView
from production.models import ProductionExclusion, ProductionReport
from production import views as production

assert 'review' in connections['default'].settings_dict['HOST'] or __import__('os').environ.get('RI_DISPOSABLE_QA') == 'true', 'Disposable database required'
User = get_user_model()
tag = uuid4().hex[:10]
results = []
actor = {'id': 'qa-concurrency', 'name': 'QA', 'role': 'admin'}

def check(name, ok, detail=''):
    results.append((name, bool(ok)))
    print(('PASS ' if ok else 'FAIL ')+name+(' '+str(detail) if not ok else ''), flush=True)

def person(label, role='admin'):
    user = User.objects.create_user(username=f'zz.conc.{tag}.{label}')
    obj = Personnel.objects.create(name=f'ZZ Conc {tag} {label}', department='admin', role_code=role,
        is_active=True, auth_user_id=str(user.pk), account_status='active', created_by='qa', updated_by='qa')
    return user, obj

user, principal = person('operator')
factory = APIRequestFactory()

def api(view, body):
    request = factory.post('/', body, format='json')
    force_authenticate(request, user=User.objects.get(pk=user.pk))
    return view.as_view()(request)

def production_api(action, month, **extra):
    return api(production.ProductionReportView, {'action': action, 'month': month, **extra})

def fx_api(month, usd=31):
    current = {r.currency: r for r in FxRate.objects.filter(year_month=month)}
    return api(FxRatesView, {'yearMonth': month, 'rates': [dict(currency=c, rate=usd if c=='USD' else 1,
        rowVersion=current[c].row_version if c in current else None) for c in CURRENCIES]})

def setup(month, currency='USD'):
    helpers = {}
    exec(open('qa/suites/production_api.py').read().split('\ntry:\n')[0], helpers)
    payload = normalize_draft(helpers['ready'](policyFrom=month+'-01', policyTo=str(int(month[:4])+1)+month[4:]+'-01', currency=currency))['value']
    case = Case.objects.create(tw_ref=f'ZZ-CONC-{tag}-{month}', status='posted', payload=payload,
        currency=currency, reinsurance_structure='QS', announced_at=datetime(2026,1,1,tzinfo=timezone.utc), created_by='qa', updated_by='qa')
    if currency=='USD':
        for c in CURRENCIES:
            FxRate.objects.create(year_month=month, currency=c, rate=30 if c=='USD' else 1, created_by='qa', updated_by='qa')
    state = production.load_month(month)
    response = production_api('generate', month, sourceSignature=state['preview']['sourceSignature'])
    assert response.status_code==201, response.data
    report = response.data['report']
    return case, report, dict(reportUid=report['reportUid'], rowVersion=report['rowVersion'], sourceSignature=report['sourceSignature'])

def thread_call(fn):
    try:
        return fn()
    finally:
        connections.close_all()

def overlap(first, second, patch_target, read_original):
    """Hold first after a real read/write; let second attempt and then release.

    The new locks make the second wait; the original code lets it proceed using
    outdated data. The short done wait distinguishes these without deadlocking
    corrected code. Barriers surround real business calls, never substitute data.
    """
    held, release, attempted = threading.Event(), threading.Event(), threading.Event()
    ident = []
    def hooked(*args, **kwargs):
        value = read_original(*args, **kwargs)
        if threading.get_ident()==ident[0] and not held.is_set():
            held.set()
            assert release.wait(15), 'release timed out'
        return value
    def run_first():
        ident.append(threading.get_ident())
        return thread_call(first)
    def run_second():
        attempted.set()
        return thread_call(second)
    with mock.patch(patch_target, side_effect=hooked), ThreadPoolExecutor(max_workers=2) as pool:
        one = pool.submit(run_first)
        assert held.wait(15), 'first operation never reached hook'
        two = pool.submit(run_second)
        assert attempted.wait(5)
        try:
            two.result(timeout=0.4)
        except TimeoutError:
            pass
        finally:
            release.set()
        return one.result(timeout=20), two.result(timeout=20)

with override_settings(AUDIT_LOG_PAUSED=True):
    before_audit = AuditLog.objects.count()
    case, report, close_body = setup('2087-01')
    one, two = overlap(lambda: production_api('close','2087-01',**close_body),
        lambda: production_api('generate','2087-01',sourceSignature=report['sourceSignature']),
        'production.views.load_month', production.load_month)
    check('close first: concurrent generate immediately reports busy', one.status_code==200 and two.status_code==409 and two.data.get('error')=='operation_busy', (one.data,two.data))
    check('closed month has no valid/new report', list(ProductionReport.objects.filter(year_month='2087-01').values_list('version','status'))==[(1,'closed')])

    case, report, close_body = setup('2087-02')
    one, two = overlap(lambda: production_api('close','2087-02',**close_body), lambda: fx_api('2087-02'),
        'production.views.load_month', production.load_month)
    stored = FxRate.objects.get(year_month='2087-02',currency='USD')
    check('close first: concurrent FX edit immediately reports busy', one.status_code==200 and two.status_code==409 and two.data.get('error')=='operation_busy', (one.data,two.data))
    check('closed report and locked USD rate agree', stored.is_locked and float(stored.rate)==30 and all(r['rate']==30 for r in ProductionReport.objects.get(report_uid=report['reportUid']).rows))

    case, report, close_body = setup('2087-03')
    original_snapshot = __import__('fxrates.views', fromlist=['record_snapshot']).record_snapshot
    one, two = overlap(lambda: fx_api('2087-03'), lambda: production_api('close','2087-03',**close_body),
        'fxrates.views.record_snapshot', original_snapshot)
    case.refresh_from_db()
    check('FX edit first: concurrent close immediately reports busy', one.status_code==200 and two.status_code==409 and two.data.get('error')=='operation_busy', (one.data,two.data))
    retry = production_api('close','2087-03',**close_body)
    check('retry close rejects changed source until report regenerated', retry.status_code==409 and retry.data.get('error')=='source_changed', retry.data)
    check('failed close leaves report, cases and FX unlocked', ProductionReport.objects.get(report_uid=report['reportUid']).status=='valid' and case.status=='posted' and not FxRate.objects.filter(year_month='2087-03',is_locked=True).exists())
    refreshed = production.load_month('2087-03')['preview']['sourceSignature']
    generated = production_api('generate','2087-03',sourceSignature=refreshed)
    latest = generated.data.get('report')
    if latest:
        response = production_api('close','2087-03',reportUid=latest['reportUid'],rowVersion=latest['rowVersion'],sourceSignature=refreshed)
        check('regenerate with current FX then close succeeds', response.status_code==200, response.data)
    else:
        check('regenerate with current FX then close succeeds', False, generated.data)

    case, report, close_body = setup('2087-05')
    one, two = overlap(lambda: production_api('generate','2087-05',sourceSignature=report['sourceSignature']),
        lambda: production_api('close','2087-05',**close_body), 'production.views.load_month', production.load_month)
    states = list(ProductionReport.objects.filter(year_month='2087-05').values_list('status',flat=True))
    check('generate reads first: concurrent close cannot leave closed and valid versions', one.status_code==201 and two.status_code==409 and 'closed' not in states and states.count('valid')==1, (one.status_code,two.status_code,states))

    # First-ever generation rejects conflicts even without any month rows.
    month = '2087-09'
    signature = production.load_month(month)['preview']['sourceSignature']
    one, two = overlap(lambda: production_api('generate',month,sourceSignature=signature),
        lambda: production_api('generate',month,sourceSignature=signature), 'production.views.load_month', production.load_month)
    check('empty month: concurrent first generation immediately reports busy', one.status_code==201 and two.status_code==409 and two.data.get('error')=='operation_busy' and ProductionReport.objects.filter(year_month=month).count()==1, (one.data,two.data))

    # Defensive comparison catches stale FX even when a non-API writer bypasses
    # month coordination. This executes inside a rollback-only outer transaction.
    with transaction.atomic():
        case, report, close_body = setup('2087-04')
        state = production.load_month('2087-04')
        FxRate.objects.filter(year_month='2087-04',currency='USD').update(rate=31)
        with mock.patch('production.views.load_month', return_value=state):
            response = production_api('close','2087-04',**close_body)
        check('stale FX set rejected before any close write', response.status_code==409 and response.data.get('error')=='close_conflict' and ProductionReport.objects.get(report_uid=report['reportUid']).status=='valid', response.data)
        transaction.set_rollback(True)

    # Excluding from the previous month modifies the next month's source too.
    case, report, close_body = setup('2087-06', currency='TWD')
    key = production.load_month('2087-06')['preview']['rows'][0]['key']
    ProductionExclusion.objects.create(case=case,year_month='2087-06',deferred_to='2087-07',scope='case',installment_key=key,reason='qa',created_by='qa')
    state = production.load_month('2087-07')
    deferred_report = production_api('generate','2087-07',sourceSignature=state['preview']['sourceSignature']).data['report']
    response = production_api('close','2087-07',reportUid=deferred_report['reportUid'],rowVersion=deferred_report['rowVersion'],sourceSignature=deferred_report['sourceSignature'])
    case.refresh_from_db()
    check('deferred next-month rows can close normally', response.status_code==200 and len(deferred_report['rows'])==2 and case.status=='closed', response.data)

    # The chosen policy skips all intervening closed months, across year-end.
    case, report, _ = setup('2087-10', currency='TWD')
    for closed_month in ['2087-11','2087-12']:
        signature = production.load_month(closed_month)['preview']['sourceSignature']
        empty_report = production_api('generate',closed_month,sourceSignature=signature).data['report']
        closed = production_api('close',closed_month,reportUid=empty_report['reportUid'],rowVersion=empty_report['rowVersion'],sourceSignature=signature)
        assert closed.status_code==200, closed.data
    row = production.load_month('2087-10')['preview']['rows'][0]
    response = production_api('exclude','2087-10',rowId=row['id'],scope='case',reason='skip closed months')
    check('exclusion skips consecutive closed months and crosses year-end', response.status_code==201 and response.data['exclusion']['deferred_to']=='2088-01', response.data)
    rows = production.load_month('2088-01')['preview']['rows']
    check('deferred rows appear only in the selected open month', len([r for r in rows if r['caseUid']==str(case.case_uid)])==2 and all(not production.load_month(m)['preview']['rows'] for m in ['2087-11','2087-12']))

    # A busy destination aborts the whole exclusion, and releases source locks.
    from coordination.services import monthly_operation
    case, _, _ = setup('2088-02',currency='TWD')
    row = production.load_month('2088-02')['preview']['rows'][0]
    held, release = threading.Event(), threading.Event()
    def hold_destination():
        try:
            with monthly_operation('2088-03'):
                held.set()
                assert release.wait(15)
        finally:
            connections.close_all()
    with ThreadPoolExecutor(max_workers=1) as pool:
        future = pool.submit(hold_destination)
        assert held.wait(15)
        response = production_api('exclude','2088-02',rowId=row['id'],scope='case',reason='busy destination')
        release.set()
        future.result(timeout=15)
    check('busy destination rejects exclusion with no partial write', response.status_code==409 and response.data.get('error')=='operation_busy' and not ProductionExclusion.objects.filter(case=case).exists(), response.data)
    retry = production_api('exclude','2088-02',rowId=row['id'],scope='case',reason='retry after release')
    check('all partial locks released; exclusion retry succeeds', retry.status_code==201 and retry.data['exclusion']['deferred_to']=='2088-03', retry.data)

    # Remove all other active admins in this disposable DB, retaining operator
    # as a non-admin permission context for direct business-handler tests.
    Personnel.objects.filter(role_code='admin',account_status='active').update(role_code='viewer')
    def remove(kind, person):
        if kind=='disable':
            try:
                accounts.disable_account(personnel_id=person.pk,actor=actor,source='cli')
                return 'ok'
            except accounts.AccountError as exc:
                return exc.code
        body = dict(id=person.pk,rowVersion=person.row_version,name=person.name,email=person.email or '',department=person.department,
            roleCode='viewer' if kind=='demote' else 'admin',isActive=kind!='deactivate',isSplitEligible=False,supervisorName='')
        response = PersonnelView().put(SimpleNamespace(data=body,ri_principal=principal,headers={}))
        return 'ok' if response.status_code==200 else response.data.get('error')

    for index, (left,right) in enumerate([('disable','disable'),('demote','demote'),('deactivate','deactivate'),('disable','demote'),('disable','deactivate'),('demote','deactivate')]):
        Personnel.objects.filter(role_code='admin',account_status='active').update(role_code='viewer')
        _, first = person(f'pair{index}a')
        _, second = person(f'pair{index}b')
        original_count = accounts.active_admin_count
        held, release = threading.Event(), threading.Event()
        counts = []
        def paused_count():
            count = original_count()
            counts.append(count)
            if len(counts)==1:
                held.set()
                assert release.wait(15)
            return count
        with mock.patch('personnel.accounts.active_admin_count',side_effect=paused_count), mock.patch('personnel.views.active_admin_count',side_effect=paused_count), ThreadPoolExecutor(max_workers=2) as pool:
            one = pool.submit(thread_call,lambda: remove(left,first))
            assert held.wait(15)
            attempted = threading.Event()
            def later():
                attempted.set()
                return thread_call(lambda: remove(right,second))
            two = pool.submit(later)
            assert attempted.wait(5)
            try:
                two.result(timeout=0.4)
            except TimeoutError:
                pass
            finally:
                release.set()
            values = [one.result(timeout=20),two.result(timeout=20)]
        check(f'last-admin race {left}/{right}: first succeeds, second rejected', values==['ok','last_active_admin'] and original_count()==1 and counts==[2,1], (values,counts,original_count()))
    check('Audit remains paused through all concurrent operations', AuditLog.objects.count()==before_audit)

fails = [name for name,ok in results if not ok]
print(f'{len(results)-len(fails)}/{len(results)} passed; committed fixtures confined to disposable QA database',flush=True)
assert not fails, fails
