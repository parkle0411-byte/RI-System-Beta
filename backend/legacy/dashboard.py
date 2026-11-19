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
- 2026-11-19 owner: Total Bound YTD, Renewals Bound MTD and New Business MTD include legacy
  premium rows by Revenue Month and the Register's New / Renew. One bound policy = one
  Cedant's Policy No. (fallback: Old Reference) and Effective Date, so the reinsurers' shares of
  one policy count once and a policy renewed under the same number counts every year; the
  earliest Revenue Month among its premium rows is the month it was bound.
- 2026-11-19 owner: Active Endorsements include legacy endorsements whose Expiry Date has not
  passed. One endorsement = policy (as above) + Endorsement No. + Effective Date, so the
  reinsurers' shares of one endorsement count once.

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
    from ri_system.sorted_fetch import sorted_rows   # 2026-11-16：先排序編號再讀整筆
    records = sorted_rows(LegacyTransaction.objects.filter(status='confirmed'), 'reference', 'uid')
    policies, trend, bound, endorsements = {}, [], {}, {}
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
                                    'className': d.get('classOfBusiness') or CLASS_NAMES.get(str(d.get('classCode') or ''), 'Property'),
                                    'party': str(d.get('party') or '')})
        if kind == 'endorsement':
            slot = (_policy_key(d, t.reference), ' '.join(str(d.get('endorsementNo') or '').split()).casefold(), str(d.get('effectiveDate') or ''))
            expiry = str(d.get('expiryDate') or '')
            if expiry > endorsements.get(slot, ''):
                endorsements[slot] = expiry
            else:
                endorsements.setdefault(slot, expiry)
        if kind == 'premium' and t.revenue_month:
            slot = (_policy_key(d, t.reference), str(d.get('effectiveDate') or ''))
            if slot not in bound or t.revenue_month < bound[slot]['month']:
                bound[slot] = {'month': str(t.revenue_month), 'newOrRenew': str(d.get('newRenew') or '')}
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
    return {'policies': list(policies.values()), 'trend': trend, 'outstanding': outstanding, 'bound': list(bound.values()),
            'endorsements': [{'expiry': expiry} for expiry in endorsements.values()]}
