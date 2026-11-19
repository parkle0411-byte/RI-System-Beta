"""Dashboard bound counts include legacy policies (2026-11-19 owner decision). Synthetic data in disposable MySQL only.

Total Bound YTD, Renewals Bound MTD and New Business MTD add legacy premium rows by Revenue Month and the Register's
New / Renew; one bound policy = Cedant's Policy No. (fallback Old Reference) + Effective Date, counted in the earliest
Revenue Month of its premium rows. Endorsements, claims, drafts and withdrawn rows are not counted. The personal
Dashboard (no legacy input) is unchanged.
"""
import copy, os, uuid
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo
from django.db import connections
from django.utils import timezone
assert os.environ.get('RI_DISPOSABLE_QA') == 'true'
from dashboard.calc import build_dashboard
from legacy.dashboard import dashboard_inputs
from legacy.models import ImportBatch, LegacyTransaction
checks = []
def check(name, ok, detail=''):
    checks.append(name)
    assert ok, (name, detail)

# ---- the calculation ----
now = datetime(2026, 11, 19, 10, tzinfo=ZoneInfo('Asia/Taipei'))
case = lambda i, kind, posted: {'id': i, 'status': 'announced', 'announced_at': posted, 'payload': {'newOrRenew': kind, 'postedAt': posted, 'policyTo': '2027-11-01'}}
rows = [case(1, 'Renew', '2026-11-03T02:00:00Z'), case(2, 'New', '2026-11-04T02:00:00Z'), case(3, 'Renew', '2026-03-04T02:00:00Z'), case(4, 'New', '2025-06-04T02:00:00Z')]
base = build_dashboard(rows, [], [], now)['metrics']
bound = [{'month': '2026-11', 'newOrRenew': 'Renew'}, {'month': '2026-11', 'newOrRenew': 'Renew'}, {'month': '2026-11', 'newOrRenew': 'New'},
         {'month': '2026-02', 'newOrRenew': 'Renew'}, {'month': '2026-12', 'newOrRenew': 'Renew'},
         {'month': '2025-11', 'newOrRenew': 'New'}, {'month': '2025-12', 'newOrRenew': 'Renew'}, {'month': '2025-01', 'newOrRenew': ''}]
m = build_dashboard(rows, [], [], now, legacy={'policies': [], 'trend': [], 'outstanding': [], 'bound': bound})['metrics']
check('Renewals Bound MTD adds legacy renewals bound this month', m['renewalsMtd'] == base['renewalsMtd'] + 2, (m['renewalsMtd'], base['renewalsMtd']))
check('New Business MTD adds legacy new policies bound this month', m['newBusinessMtd'] == base['newBusinessMtd'] + 1, (m['newBusinessMtd'], base['newBusinessMtd']))
check('Total Bound YTD adds this year up to this month (later months excluded)', m['ytdCurrent'] == base['ytdCurrent'] + 4, (m['ytdCurrent'], base['ytdCurrent']))
check('Prior-Year YTD adds the same months of last year (December excluded, blank New / Renew included)', m['ytdPrior'] == base['ytdPrior'] + 2, (m['ytdPrior'], base['ytdPrior']))
only = build_dashboard([], [], [], now, legacy={'policies': [], 'trend': [], 'outstanding': [], 'bound': bound})['metrics']
check('legacy alone: 2 renewals and 1 new this month, 4 bound this year, 2 last year', (only['renewalsMtd'], only['newBusinessMtd'], only['ytdCurrent'], only['ytdPrior']) == (2, 1, 4, 2), only)
check('Retention Ratio uses the legacy renewals (3 this year / 2 last year)', abs(only['retentionRatio'] - 150) < 1e-9, only['retentionRatio'])
check('Expected Renewals and In-Force are not changed by bound counts', m['expectedRenewalsMtd'] == base['expectedRenewalsMtd'] and m['inForcePolicies'] == base['inForcePolicies'])
check('without legacy input (personal Dashboard) nothing changes', build_dashboard(rows, [], [], now, legacy=None)['metrics'] == base)
check('legacy input without bound counts behaves as before', build_dashboard(rows, [], [], now, legacy={'policies': [], 'trend': [], 'outstanding': []})['metrics'] == base)

# ---- legacy inputs from the database ----
owner = copy.deepcopy(connections.databases['default'])
owner.update(USER='ri_app', PASSWORD=Path('/run/secrets/mysql_app_password').read_text().strip())
connections.databases['dlb_owner'] = owner
O = LegacyTransaction.objects.using('dlb_owner')
batch = ImportBatch.objects.using('dlb_owner').create(filename='dlb.xlsx', sha256='d' * 64, storage_key='qa/dlb.xlsx', status='imported', created_by='qa')
def make(n, kind='premium', month='2026-05', renew='Renew', statement='', effective='2026-05-01', status='confirmed', reference=None):
    reference = reference or f'DLB-{n:03d}'
    data = dict(reference=reference, currency='TWD', insured=f'DLB {n}', cedant='DLB Cedant', party=f'DLB Re {n}', statementNo=statement, kind=kind, newRenew=renew,
                effectiveDate=effective, expiryDate='2027-04-30', amounts=dict(premium=1000, commission=0, tax=0, brokerage=100, claim=0, cedantNet=1000, reinsurerNet=900))
    return O.create(uid=uuid.uuid4(), number=f'DLB-{n:03d}', original_serial=f'DLB-{n:03d}', reference=reference, currency='TWD', revenue_month=month,
                    status=status, historical=True, batch=batch, first_confirmed_at=timezone.now(), data=data, fx_snapshot=dict(rate=1))
make(1, month='2026-06', statement='POL-A'); make(2, month='2026-05', statement=' pol-a ')                 # two shares of one policy: once, earliest month
make(3, month='2025-05', statement='POL-A', effective='2025-05-01', renew='New')                          # same number, earlier year: its own policy
make(4, month='2026-07', reference='DLB-REF-X'); make(5, month='2026-08', reference='DLB-REF-X')          # no policy number: Old Reference
make(6, kind='endorsement', month='2026-05', statement='POL-E'); make(7, kind='claim', month='2026-05', statement='POL-C')
make(8, month='', statement='POL-NOMONTH'); make(9, month='2026-05', statement='POL-DRAFT', status='draft'); make(10, month='2026-05', statement='POL-W', status='withdrawn')
got = sorted((b['month'], b['newOrRenew']) for b in dashboard_inputs()['bound'])
check('one policy = policy number + Effective Date, counted in its earliest Revenue Month', got.count(('2026-05', 'Renew')) == 1 and ('2026-06', 'Renew') not in got, got)
check('the same policy number in another year is another bound policy, with its own New / Renew', ('2025-05', 'New') in got, got)
check('without a policy number the Old Reference identifies the policy', got.count(('2026-07', 'Renew')) == 1 and ('2026-08', 'Renew') not in got, got)
check('endorsements, claims, rows without Revenue Month, drafts and withdrawn rows are not bound policies', len(got) == 3, got)
print(f'{len(checks)}/{len(checks)} legacy bound-count checks passed')
