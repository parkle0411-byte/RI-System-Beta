"""Legacy Data inputs for the Dashboard (owner decisions 2026-11-13/14).

- Problem 5-1 / 2026-11-15: brokerage trend includes legacy premium and endorsement rows
  (imported and new) by Revenue Month; closed months come from the formal Production
  report, historical months (before the start month) show the legacy rows as recognized.
- Problem 5-2 / confirmation 3: receivable / payable include every unsettled legacy
  account. The 5-year window uses the original Effective Date (claims: DOL) for
  imported rows and the confirmation date for new endorsements / claims.
- Follow-up D: Gross Premium, In-Force Policies and Expected Renewals include legacy
  policies still in force. One policy = one Cedant's Policy No. (fallback: Old
  Reference), because each legacy TW Ref is a single reinsurer's share.

Read-only: nothing here writes legacy or Case data.
"""
from .models import LegacyTransaction

CLASS_NAMES = {'PD': 'Property', 'GL': 'Commercial General Liability'}


def _taipei_day(stamp):
    from cases.calc.swiss_facility import local_date
    return local_date(stamp.isoformat()) if stamp else ''


def _policy_key(data, reference):
    number = ' '.join(str(data.get('statementNo') or '').split()).casefold()
    return ('policy', number) if number else ('reference', str(reference or ''))


def dashboard_inputs():
    """Plain dicts for dashboard.calc.build_dashboard(legacy=...)."""
    from .ledger import accounting_data
    from .services import rate_for
    records = list(LegacyTransaction.objects.filter(status='confirmed').order_by('reference', 'uid'))
    policies, trend = {}, []
    by_uid = {}
    for t in records:
        d = t.data if isinstance(t.data, dict) else {}
        by_uid[str(t.uid)] = t
        kind = d.get('kind')
        if kind in ('premium', 'endorsement'):
            key = _policy_key(d, t.reference)
            policy = policies.setdefault(key, {'expiry': '', 'items': []})
            expiry = str(d.get('expiryDate') or '')
            if expiry > policy['expiry']:
                policy['expiry'] = expiry
            amounts = d.get('amounts') if isinstance(d.get('amounts'), dict) else {}
            policy['items'].append({'currency': t.currency, 'premium': amounts.get('premium') or 0,
                                    'className': CLASS_NAMES.get(str(d.get('classCode') or ''), 'Property'),
                                    'party': str(d.get('party') or '')})
        if kind in ('premium', 'endorsement') and t.revenue_month:
            # 2026-11-15: imported and new legacy premium/endorsement rows are Production by
            # Revenue Month (historical months show them as recognized).
            fx = rate_for(t) or {}
            trend.append({'month': t.revenue_month, 'incomeTwd': fx.get('incomeTwd')})
    outstanding = []
    _, rows = accounting_data('open')
    for row in rows:
        if row.get('cashTracking') == 'derived' or abs(float(row.get('outstanding') or 0)) < .005:
            continue
        t = by_uid.get(str(row.get('legacyTransactionId') or row.get('caseUid') or ''))
        if t is None:
            continue
        d = t.data if isinstance(t.data, dict) else {}
        if t.batch_id is not None:
            age = str((d.get('lossDate') if d.get('kind') == 'claim' else d.get('effectiveDate')) or '')
        else:
            age = _taipei_day(t.first_confirmed_at)
        snapshot = t.fx_snapshot if isinstance(t.fx_snapshot, dict) else {}
        outstanding.append({'txNo': row.get('txNo'), 'currency': str(row.get('currency') or t.currency or 'TWD').upper(),
                            'outstanding': abs(float(row['outstanding'])), 'paymentDirection': row.get('paymentDirection'),
                            'ageDate': age[:10], 'postedRate': snapshot.get('rate'),
                            'postedMonth': t.revenue_month or _taipei_day(t.first_confirmed_at)[:7]})
    return {'policies': list(policies.values()), 'trend': trend, 'outstanding': outstanding}
