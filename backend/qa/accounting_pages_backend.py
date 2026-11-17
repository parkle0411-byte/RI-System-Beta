"""Accounting server paging parity, backend half (2026-11-17). Read-only: every request runs in a rolled-back transaction.

Prints, between ACCOUNTING-PAGES-BEGIN / -END, the two list responses the browser used to merge
(?view=list&legacy=open and ?view=list&legacy=history), the Taipei date, the options response and the server
pages for many tab / filter / page combinations. qa/accounting_pages_frontend.mjs recomputes every page with
the browser's own code and compares (scripts/run_qa.sh pages).
"""
import json, os
from urllib.parse import urlencode
from django.contrib.auth import get_user_model
from django.contrib.sessions.backends.signed_cookies import SessionStore
from django.db import transaction
from django.test import RequestFactory
from django.urls import resolve
from personnel.models import Personnel
from cases.calc.payment_terms import taipei_date

person = (Personnel.objects.filter(role_code__in=('accounting_manager', 'accounting', 'admin'), is_active=True, account_status='active', must_change_password=False)
          .exclude(auth_user_id=None).order_by('id').first())
assert person is not None, 'no Finance / administrator account available'
user = get_user_model().objects.get(pk=person.auth_user_id)
factory = RequestFactory(HTTP_HOST='localhost')


def fetch(url):
    request = factory.get(url); request.user = user; request.session = SessionStore()
    with transaction.atomic():
        response = resolve('/api/accounting').func(request); response.render(); transaction.set_rollback(True)
    assert response.status_code == 200, (url, response.status_code, response.content[:300])
    return json.loads(response.content)


now = taipei_date(None)
open_body = fetch('/api/accounting?view=list&legacy=open')
from qa.accounting_full import accounting_get   # the history read is internal since 2026-11-17


class _ReadOnlyCaller:
    """Identifies the user without logging in (no session row, no last-login update on production data)."""
    session = {'_auth_user_id': str(user.pk)}


with transaction.atomic():
    history = accounting_get(_ReadOnlyCaller(), '?view=list&legacy=history').json(); transaction.set_rollback(True)
options = fetch('/api/accounting?view=options')['options']
MAX_PAGES = int(os.environ.get('PAGES_MAX', '6'))


def page_url(tab, page, filters, text):
    query = {'view': 'page', 'tab': tab, 'page': page}
    for key, value in {**filters, **text}.items():
        if key == 'settlement':
            if value: query[key] = ','.join(value)
        elif value: query[key] = value
    return '/api/accounting?' + urlencode(query)


defaults = {'all': [], 'settled': ['settled'], 'brokerage': []}
blank = {'cedant': '', 'reinsurer': '', 'currency': '', 'direction': '', 'settlement': [], 'source': '', 'origin': '', 'due': ''}
some_ref = next((r.get('twRef') for r in [*open_body.get('transactionRows', []), *history.get('transactionRows', [])] if r.get('twRef')), 'TW')
some_cn = next((r.get('originalInsuredCn') for r in [*open_body.get('transactionRows', []), *history.get('transactionRows', [])] if r.get('originalInsuredCn')), '')
variants = [({}, {}), ({'settlement': ['open']}, {}), ({'settlement': ['settled']}, {}), ({'settlement': ['open', 'settled']}, {}),
            ({'origin': 'legacy'}, {}), ({'origin': 'native'}, {}), ({'source': 'premium'}, {}), ({'source': 'claim'}, {}), ({'source': 'brokerage'}, {}),
            ({'direction': 'payable'}, {}), ({'direction': 'receivable'}, {}), ({'due': now}, {}), ({'due': '2000-01-01'}, {}),
            ({}, {'reference': some_ref[:6]}), ({}, {'reference': ' ' + some_ref[:6].lower() + ' '}), ({}, {'reference': 'zz-no-match'}),
            ({}, {'insured': some_cn[:2]}), ({}, {'insured': '   '}), ({'settlement': ['settled'], 'origin': 'legacy'}, {'reference': some_ref[:4]})]
variants += [({'currency': c}, {}) for c in options['currencies'][:3]]
variants += [({'cedant': c}, {}) for c in options['cedants'][:2]] + [({'reinsurer': c}, {}) for c in options['reinsurers'][:2]]
variants += [({'cedant': 'No such cedant'}, {})]
checks = []
for tab in ('all', 'settled', 'brokerage'):
    for filters, text in variants:
        f = {**blank, 'settlement': defaults[tab], **filters}
        t = {'reference': '', 'insured': '', **text}
        first = fetch(page_url(tab, 1, f, t))
        last = max(1, -(-first['total'] // first['pageSize']))
        everything = tab == 'all' and not filters and not text
        numbers = range(1, last + 1) if everything else sorted({*range(1, min(last, MAX_PAGES) + 1), last, last + 1})
        pages = {n: (first if n == 1 else fetch(page_url(tab, n, f, t))) for n in numbers}
        checks.append({'tab': tab, 'filters': f, 'text': t, 'pages': pages})
print('ACCOUNTING-PAGES-BEGIN')
print(json.dumps({'now': now, 'open': open_body, 'history': history, 'options': options, 'checks': checks}, ensure_ascii=False))
print('ACCOUNTING-PAGES-END')
