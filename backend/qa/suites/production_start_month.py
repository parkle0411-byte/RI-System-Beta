"""Production start month and historical months (owner decisions 2026-11-15).

- Months before the start month are historical: treated as closed, never generated, closed
  or excluded; their FX is locked; the page lists imported Legacy Data rows read-only.
- New-system production that would fall in a historical month is recognized in the start month.
- Imported Legacy premium and endorsement rows are Production by Revenue Month; claims never.
- The Dashboard trend shows historical months as closed with Legacy income; native income
  of historical months is drawn in the start month.
The suite uses a synthetic start month (2050-11) so no real month is involved.
"""
import copy, json, os, uuid
from pathlib import Path
from datetime import datetime, timezone as dtz
from types import SimpleNamespace
from unittest.mock import patch
from django.conf import settings
from django.db import transaction, connections
from django.test import override_settings
from django.contrib.auth import get_user_model
from django.utils import timezone
from rest_framework.test import APIRequestFactory, force_authenticate
from cases.models import Case, CaseDocument
from cases.views import CasesView
from cases.workflow_views import AnnounceView
from personnel.models import Personnel
from fxrates.models import FxRate, CURRENCIES
from fxrates.views import FxRatesView
from production import calc
from production.views import ProductionReportView
from legacy.models import ImportBatch, LegacyTransaction
from dashboard.calc import build_dashboard
assert os.environ.get('RI_DISPOSABLE_QA') == 'true'
ns = {}; exec(Path('/app/qa/suites/cgl_qs.py').read_text().split('class Rollback')[0], ns)
checks = []
def check(label, ok, detail=''):
    assert ok, (label, detail)
    checks.append(label)

check('default Production start month is 2026-11', settings.PRODUCTION_START_MONTH == '2026-11' and calc.start_month() == '2026-11')
check('2026-10 is historical, 2026-11 is not', calc.is_historical('2026-10') and not calc.is_historical('2026-11'))
check('a historical month is recognized in the start month', calc.effective_month('2026-03') == '2026-11' and calc.effective_month('2026-12') == '2026-12')

owner = copy.deepcopy(connections.databases['default'])
owner.update(USER='ri_app', PASSWORD=Path('/run/secrets/mysql_app_password').read_text().strip())
connections.databases['start_month_owner'] = owner
with transaction.atomic(using='start_month_owner'):
    batch = ImportBatch.objects.using('start_month_owner').create(filename='synthetic.xlsx', sha256='b' * 64,
        storage_key='qa/start-month.xlsx', status='imported', created_by='isolated-qa')
    def legacy_row(serial, month, kind, income):
        return LegacyTransaction.objects.using('start_month_owner').create(number=serial, original_serial=serial,
            reference='QA-SM-' + serial, currency='TWD', revenue_month=month if kind != 'claim' else '', status='confirmed',
            historical=True, batch=batch, first_confirmed_at=timezone.now(),
            data=dict(reference='QA-SM-' + serial, currency='TWD', revenueMonth=month, insured='Synthetic Start Insured',
                      cedant='Synthetic Cedant', party='Synthetic Reinsurer', ae='Synthetic AE', statementNo='SM-' + serial,
                      gross=10000, share=100, rule='ordinary', kind=kind, effectiveDate='2050-01-01', expiryDate='2051-01-01',
                      amounts=dict(premium=10000, commission=0, tax=0, brokerage=income, claim=0, cedantNet=10000, reinsurerNet=10000 - income)),
            fx_snapshot=dict(rate=1, incomeTwd=income, premiumTwd=10000, people=[dict(name='Synthetic AE', income=income, premium=10000)]))
    hist_premium = legacy_row('QASM1', '2050-09', 'premium', 700)
    open_premium = legacy_row('QASM2', '2050-11', 'premium', 900)
    open_endorsement = legacy_row('QASM3', '2050-11', 'endorsement', 50)
    claim = legacy_row('QASM4', '2050-11', 'claim', 0)

class Rollback(Exception): pass
try:
    with transaction.atomic(), override_settings(PRODUCTION_START_MONTH='2050-11'):
        users = {}
        for role, dept in [('sales', 'reinsurance'), ('accounting_manager', 'finance')]:
            u = get_user_model().objects.create_user(username='qa.startmonth.' + role, password='Synthetic-Only-9!')
            p = Personnel.objects.create(name='QA StartMonth ' + role, email='qa-startmonth-' + role + '@example.test', department=dept,
                                         role_code=role, auth_user_id=str(u.pk), account_status='active', is_split_eligible=True,
                                         created_by='qa', updated_by='qa')
            users[role] = (u, p)
        factory = APIRequestFactory()
        def api(view, method, body, role='sales'):
            req = getattr(factory, method)('/', body, format='json'); force_authenticate(req, user=users[role][0]); return view.as_view()(req)
        payload = ns['ready'](users['sales'][1]); payload.update(policyFrom='2050-10-01', policyTo='2051-10-01', originalInsuredCn='合成起始月')
        r = api(CasesView, 'post', dict(case=payload, incompleteDraft=True)); check('save draft', r.status_code == 201, r.data)
        c = Case.objects.get(case_uid=r.data['case']['caseUid'])
        for kind in ['offer', 'signed']:
            CaseDocument.objects.create(case=c, kind=kind, reinsurers=[x['name'] for x in c.payload['reinsurers']], filename='qa-' + kind + '.pdf',
                                        content_type='application/pdf', byte_size=1, sha256='a' * 64, storage_key=uuid.uuid4().hex, is_selected=True, uploaded_by='qa')
        ids = [str(d.pk) for d in CaseDocument.objects.filter(case=c)]
        with patch('cases.workflow_views.timezone', SimpleNamespace(now=lambda: datetime(2050, 10, 5, 3, tzinfo=dtz.utc))):
            r = api(AnnounceView, 'post', dict(caseUid=str(c.case_uid), rowVersion=c.row_version, confirmed=True, documentIds=ids))
        check('Announce a 2050-10 original', r.status_code == 200, r.data); c.refresh_from_db()
        FxRate.objects.create(year_month='2050-11', currency='USD', rate=32, created_by='qa', updated_by='qa')
        def preview(month):
            r = api(ProductionReportView, 'get', dict(month=month), 'accounting_manager'); check('read preview ' + month, r.status_code == 200, r.data); return r.data
        hist = preview('2050-10')
        check('historical month: closed, historical, cannot generate', hist['scope']['historicalMonth'] and hist['scope']['monthClosed']
              and not hist['scope']['canGenerate'] and not hist['scope']['canCloseLatest'] and hist['scope']['productionStartMonth'] == '2050-11', hist['scope'])
        check('historical month: the new-system case is not listed there', not [x for x in hist['rows'] if x.get('caseUid') == str(c.case_uid)])
        for action in ('generate', 'close', 'exclude'):
            r = api(ProductionReportView, 'post', dict(action=action, month='2050-10', sourceSignature=hist['sourceSignature']), 'accounting_manager')
            check('historical month refuses ' + action, r.status_code == 409 and r.data.get('error') == 'historical_month', r.data)
        start = preview('2050-11')
        mine = [x for x in start['rows'] if x.get('caseUid') == str(c.case_uid)]
        check('new-system production of a historical month is recognized in the start month', bool(mine) and all(x['month'] == '2050-11' and x['tranxDate'] == '2050-11-30' for x in mine), mine[:1])
        legacy_ids = {x.get('legacyTransactionId') for x in start['rows'] if x.get('legacyTransactionId')}
        check('imported premium and endorsement rows of the start month are Production; claims never',
              {str(open_premium.uid), str(open_endorsement.uid)} <= legacy_ids and str(claim.uid) not in legacy_ids, legacy_ids)
        past = preview('2050-09')
        check('historical month lists its imported row read-only as recognized Production',
              [x.get('legacyTransactionId') for x in past['rows']] == [str(hist_premium.uid)] and past['scope']['historicalMonth'], past['rows'][:1])
        # 2026-11-19 owner: a historical month can be filled in once (while it has no rates); the rates are then locked.
        r = api(FxRatesView, 'post', dict(yearMonth='2050-10', rates=[dict(currency=cur, rate=30, rowVersion=None) for cur in CURRENCIES]), 'accounting_manager')
        check('historical month without rates: the first FX entry is accepted', r.status_code == 200, r.data)
        saved = list(FxRate.objects.filter(year_month='2050-10'))
        check('historical month FX is locked as soon as it is saved', len(saved) == len(CURRENCIES) and all(x.is_locked and 'entered once' in (x.lock_reason or '') for x in saved), [(x.currency, x.is_locked, x.lock_reason) for x in saved])
        r = api(FxRatesView, 'post', dict(yearMonth='2050-10', rates=[dict(currency=x.currency, rate=31, rowVersion=x.row_version) for x in saved]), 'accounting_manager')
        check('historical month FX cannot be changed after the one entry', r.status_code == 409 and r.data.get('error') == 'month_locked' and 'entered once' in r.data.get('message', ''), r.data)
        check('the refused change leaves the saved rates as they were', sorted(float(x.rate) for x in FxRate.objects.filter(year_month='2050-10')) == [30.0] * len(CURRENCIES))
        r = api(FxRatesView, 'get', {}, 'accounting_manager')
        listed = [x for x in r.data['rates'] if x['yearMonth'] == '2050-10']
        check('FX list shows the historical month as Locked', len(listed) == len(CURRENCIES) and all(x['isLocked'] for x in listed), listed[:1])
        # Dashboard: historical months are closed and show Legacy income; native income moves to the start month.
        rows = [{'id': c.pk, 'parent_case_id': None, 'status': c.status, 'payload': c.payload, 'announced_at': '2050-10-05T11:00:00+08:00', 'created_at': '2050-10-01T00:00:00+08:00'}]
        legacy = {'policies': [], 'outstanding': [], 'trend': [{'month': '2050-09', 'incomeTwd': 700}, {'month': '2050-11', 'incomeTwd': 950}]}
        fx = [{'year_month': '2050-11', 'currency': 'USD', 'rate': 32.0}]
        board = build_dashboard(rows, [], fx, datetime(2050, 12, 15, 4, tzinfo=dtz.utc), tz=dtz.utc, production_rules=True, closed_reports=[], brokerage_year=2050, legacy=legacy)['brokerage']
        native = sum(a['income'] for a in calc.installment_allocations(calc.normalize_source({**rows[0], 'payload': c.payload}))) * 32
        check('Dashboard: historical months are closed', board['currentStatus'][8] == 'closed' and board['currentStatus'][9] == 'closed' and board['currentStatus'][10] == 'estimated', board['currentStatus'])
        check('Dashboard: historical September shows its Legacy income', round(board['current'][8], 2) == 700, board['current'])
        check('Dashboard: native October income is drawn in the November start month', round(board['current'][9], 2) == 0 and round(board['current'][10], 2) == round(native + 950, 2), board['current'])
        raise Rollback()
except Rollback:
    pass
print(f"{len(checks)}/{len(checks)} passed Production start-month checks; database changes rolled back")
