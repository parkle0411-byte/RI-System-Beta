"""2026-11-10 weekly debug fixes. Synthetic data in disposable MySQL only.

1. Legacy list: huge page numbers return an empty page instead of a database error.
2. Great American reinsurer tax on posted cases is matched by reinsurer name, not list position.
3. Legacy URLs are unchanged after removing the leading-slash routes (no urls.W002 warning).
"""
import json, os
from django.contrib.auth import get_user_model
from django.core.checks import run_checks
from django.test import Client
from django.urls import resolve
from personnel.models import Personnel
from legacy.models import LegacyTransaction
from cases.facility_rules import legacy_ga_tax_error

assert os.environ.get('RI_DISPOSABLE_QA') == 'true'
checks = []
def check(name, ok, detail=''):
    assert ok, (name, detail)
    checks.append(name); print('PASS ' + name, flush=True)

# ---- 1. Legacy list pagination ----
u = get_user_model().objects.create_user(username='qa-debug-1110', password='Qa-Debug-9!')
Personnel.objects.create(name='QA Debug 1110', department='reinsurance', role_code='sales',
                         auth_user_id=str(u.pk), account_status='active', created_by='qa', updated_by='qa')
c = Client(HTTP_HOST='localhost'); c.force_login(u)
for n in range(3):
    LegacyTransaction.objects.create(number=f'QA-DBG-{n}', original_serial=f'QA-DBG-{n}', reference=f'QA-DBG-{n}',
        status='confirmed', historical=True, currency='TWD', data=dict(reference=f'QA-DBG-{n}', kind='premium'))
def page(q):
    r = c.get('/api/legacy' + q)
    return r.status_code, (r.json() if r.status_code < 500 and r['Content-Type'].startswith('application/json') else r.content[:200])
s, d = page('?page=1&size=25')
check('normal first page lists the transactions', s == 200 and d['count'] == 3 and len(d['rows']) == 3, d)
s, d = page('?page=2&size=2')
check('second page keeps the remaining row', s == 200 and len(d['rows']) == 1 and d['page'] == 2, d)
for huge in ('99999999999999999999', '1000001', '9' * 400):
    s, d = page(f'?page={huge}&size=99999999')
    check(f'huge page {huge[:22]} returns an empty page, not a server error', s == 200 and d['rows'] == [] and d['count'] == 3, d)
s, d = page('?page=1000000&size=100')
check('the largest allowed page is accepted and empty', s == 200 and d['page'] == 1000000 and d['rows'] == [], d)
for bad in ('abc', '1.5', '', '-5'):
    s, d = page(f'?page={bad}')
    check(f'odd page value {bad!r} never causes a server error', s in (200, 400), (s, d))
s, d = page('?page=' + '9' * 5000)
check('page value longer than Python int limit is rejected cleanly', s == 400, (s, d))

# ---- 2. Great American tax on posted cases ----
GA = 'Great American Insurance Company, Singapore Branch (Facility)'
base = {'classOfBusiness': 'Property'}
def case(*rows): return {**base, 'reinsurers': [dict(name=n, taxPct=t) for n, t in rows]}
before = case(('Other Re', 2), (GA, 5))
check('unchanged original rate is kept', legacy_ga_tax_error(before, before) == '')
check('reordering reinsurers keeps the original rate', legacy_ga_tax_error(before, case((GA, 5), ('Other Re', 2))) == '')
check('removing another reinsurer keeps the original rate', legacy_ga_tax_error(before, case((GA, 5))) == '')
check('same rate written as text or decimal is kept',
      legacy_ga_tax_error(before, case(('Other Re', 2), (GA, '5'))) == '' and legacy_ga_tax_error(before, case(('Other Re', 2), (GA, 5.0))) == '')
check('Great American may be lowered to 0%', legacy_ga_tax_error(before, case(('Other Re', 2), (GA, 0))) == '')
msg = 'Great American Facility Reinsurer Tax must be 0%.'
check('a new nonzero rate is still rejected', legacy_ga_tax_error(before, case(('Other Re', 2), (GA, 7))) == msg)
check('another reinsurer rate cannot be copied onto Great American', legacy_ga_tax_error(before, case(('Other Re', 2), (GA, 2))) == msg)
check('a case that had no Great American cannot add a nonzero rate',
      legacy_ga_tax_error(case(('Other Re', 2)), case(('Other Re', 2), (GA, 5))) == msg)
check('original zero rate cannot become nonzero', legacy_ga_tax_error(case((GA, 0)), case((GA, 5))) == msg)
check('non-Property classes are not restricted',
      legacy_ga_tax_error({'classOfBusiness': 'Commercial General Liability', 'reinsurers': [dict(name=GA, taxPct=0)]},
                          {'classOfBusiness': 'Commercial General Liability', 'reinsurers': [dict(name=GA, taxPct=5)]}) == '')
check('odd payloads never raise', legacy_ga_tax_error({}, case((GA, 5))) == msg and legacy_ga_tax_error(None, {'reinsurers': None}) == '')

# ---- 3. Legacy URLs ----
for path, view in (('/api/legacy', 'TransactionsView'), ('/api/legacy/imports', 'ImportView'), ('/api/legacy/options', 'OptionsView')):
    check(f'{path} still resolves to {view}', resolve(path).func.view_class.__name__ == view)
for path in ('/api/legacyimports', '/api/legacy/', '/api/imports', '/api/options'):
    try:
        resolve(path); ok = False
    except Exception:
        ok = True
    check(f'{path} is not a route', ok)
check('no leading-slash URL warnings', not [m for m in run_checks() if m.id == 'urls.W002'], [str(m) for m in run_checks() if m.id == 'urls.W002'])
check('other API routes are unaffected', resolve('/api/accounting').func.view_class.__name__ == 'AccountingView'
      and resolve('/api/system-reference').func.view_class.__name__ == 'SystemReferenceView')
print(f'{len(checks)}/{len(checks)} passed')
