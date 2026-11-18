"""Supported currencies (owner decision 2026-11-18). Disposable MySQL only; writes rolled back.

- 15 foreign currencies in the owner's order (RMB = CNY); TWD is the base currency and comes first in menus.
- FX Rates: every month must contain all 15 rates; rates keep six decimals (IDR / VND accepted).
- Every validation that lists currencies (Claims, Loss Record, Product Recall, CGL / STP turnover,
  Legacy Data entry and import) uses the same list.
"""
import os
from decimal import Decimal
from django.db import transaction
from django.contrib.auth import get_user_model
from rest_framework.test import APIRequestFactory, force_authenticate
from fxrates import currencies
from fxrates.models import FxRate, CURRENCIES, CURRENCY_CHOICES
from fxrates.views import FxRatesView
from personnel.models import Personnel
assert os.environ.get('RI_DISPOSABLE_QA') == 'true'
checks = []
def check(label, ok, detail=''):
    assert ok, (label, detail)
    checks.append(label); print('PASS ' + label, flush=True)

ORDER = ['USD', 'THB', 'CNY', 'AUD', 'HKD', 'EUR', 'JPY', 'GBP', 'CAD', 'IDR', 'VND', 'CHF', 'SGD', 'MYR', 'INR']
check('15 foreign currencies in the owner order (RMB uses CNY)', list(currencies.FOREIGN) == ORDER and 'RMB' not in currencies.ALL)
check('TWD is the base currency and comes first', currencies.ALL == ('TWD', *ORDER))
check('FX model uses the same list', CURRENCIES == ORDER and [c for c, _ in CURRENCY_CHOICES] == ORDER)
from cases import claim_currency, cgl_information, stp
from legacy import importer, entries
for name, values in [('Claims / Loss Record / Product Recall', claim_currency.CURRENCIES), ('CGL turnover', cgl_information.CURRENCIES),
                     ('STP', stp.CURRENCIES), ('Legacy import', importer.CURRENCIES), ('Legacy entry', entries.CURRENCIES)]:
    check(name + ' validation accepts TWD and all 15', set(values) == set(currencies.ALL), sorted(values))
check('Claim precision: TWD whole numbers, every other currency two decimals',
      claim_currency.valid_amount(1000, 'TWD') and not claim_currency.valid_amount(1000.5, 'TWD')
      and all(claim_currency.valid_amount(10.25, c) and not claim_currency.valid_amount(10.255, c) for c in ORDER))

class Rollback(Exception): pass
try:
    with transaction.atomic():
        u = get_user_model().objects.create_user(username='qa.currency.fm', password='Synthetic-Only-9!')
        Personnel.objects.create(name='QA Currency FM', email='qa-currency-fm@example.test', department='finance', role_code='accounting_manager',
                                 auth_user_id=str(u.pk), account_status='active', created_by='qa', updated_by='qa')
        factory = APIRequestFactory()
        def api(method, body=None):
            req = getattr(factory, method)('/', body, format='json'); force_authenticate(req, user=u); return FxRatesView.as_view()(req)
        rates = {'USD': 30.5, 'THB': 0.9, 'CNY': 4.3, 'AUD': 20.1, 'HKD': 3.9, 'EUR': 33.1, 'JPY': 0.21, 'GBP': 38.9,
                 'CAD': 22.4, 'IDR': 0.0019503, 'VND': 0.0012149, 'CHF': 36.2, 'SGD': 23.5, 'MYR': 6.8, 'INR': 0.37}
        old_six = [dict(currency=c, rate=rates[c], rowVersion=None) for c in ('USD', 'EUR', 'JPY', 'GBP', 'HKD', 'MYR')]
        r = api('post', dict(yearMonth='2099-02', rates=old_six))
        check('saving only the original six currencies is refused (all 15 required)', r.status_code == 400 and r.data.get('error') == 'incomplete_rates' and '15' in r.data.get('message', ''), r.data)
        r = api('post', dict(yearMonth='2099-02', rates=[dict(currency='RMB', rate=4.3, rowVersion=None)] + [dict(currency=c, rate=rates[c], rowVersion=None) for c in ORDER[1:]]))
        check('RMB is not a currency code (use CNY)', r.status_code == 400 and r.data.get('error') == 'invalid_currency', r.data)
        r = api('post', dict(yearMonth='2099-02', rates=[dict(currency=c, rate=rates[c], rowVersion=None) for c in reversed(ORDER)]))
        check('all 15 rates save together (any input order)', r.status_code == 200, r.data)
        stored = {f.currency: f.rate for f in FxRate.objects.filter(year_month='2099-02')}
        check('15 rows stored', sorted(stored) == sorted(ORDER), sorted(stored))
        check('IDR / VND rates keep six decimals', stored['IDR'] == Decimal('0.001950') and stored['VND'] == Decimal('0.001215'), (stored['IDR'], stored['VND']))
        r = api('get')
        month = [x['currency'] for x in r.data['rates'] if x['yearMonth'] == '2099-02']
        check('FX list returns each month in the owner order', r.status_code == 200 and month == ORDER, month)
        policy = r.data.get('policy') or {}
        check('FX policy: maintained currencies in the owner order, complete month required', list(policy.get('maintainedCurrencies') or []) == ORDER and policy.get('completeMonthRequired') is True, policy)
        raise Rollback()
except Rollback:
    pass
print(f'{len(checks)}/{len(checks)} currency-list checks passed; database changes rolled back')
