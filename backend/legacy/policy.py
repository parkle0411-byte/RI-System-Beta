"""Shared Legacy policy rules (owner decisions 2026-11-11/12).

"Same policy" is the same Old Reference (TW Ref): each TW Ref is one reinsurer's share.
- Latest period: earliest start + latest expiry among confirmed premium/endorsement rows.
- Latest Insured: the newest confirmed endorsement's Insured, else the premium row's.
- Payment rule: detected from the settlement party (Facility names), otherwise ordinary.
- Endorsement Revenue Month: the later of the effective month and the confirmation month;
  a closed Production month rolls to the first open month (native rule, VM-RULES §9).
- Money precision: TWD whole numbers, other currencies at most two decimals; never rounded silently.
- Insured master: Chinese-name identity shared with Case; legacy rows link and mark it official.
"""
import copy
from datetime import date
from decimal import Decimal, InvalidOperation
from django.utils import timezone
from .models import LegacyTransaction

POLICY_KINDS = ('premium', 'endorsement')


def _day(value):
    try:
        return date.fromisoformat(value) if isinstance(value, str) and len(value) == 10 else None
    except ValueError:
        return None


def policy_rows(reference, exclude=None):
    qs = LegacyTransaction.objects.filter(reference=reference, status='confirmed', data__kind__in=POLICY_KINDS)
    return qs.exclude(pk=exclude) if exclude else qs


def latest_period(reference, exclude=None):
    starts, ends = [], []
    for data in policy_rows(reference, exclude).values_list('data', flat=True):
        start, end = _day((data or {}).get('effectiveDate')), _day((data or {}).get('expiryDate'))
        if start: starts.append(start)
        if end: ends.append(end)
    return (min(starts) if starts else None, max(ends) if ends else None)


def previous_endorsement_date(reference, exclude=None):
    days = [_day((d or {}).get('effectiveDate')) for d in policy_rows(reference, exclude).filter(data__kind='endorsement').values_list('data', flat=True)]
    days = [d for d in days if d]
    return max(days) if days else None


def latest_insured(source):
    rows = list(policy_rows(source.reference).filter(data__kind='endorsement'))
    rows.sort(key=lambda t: (t.first_confirmed_at or t.created_at, (t.data or {}).get('effectiveDate', ''), str(t.uid)))
    for t in reversed(rows):
        if (t.data or {}).get('insured') or (t.data or {}).get('insuredCn'):
            return t.data.get('insured', ''), t.data.get('insuredCn', '')
    return source.data.get('insured', ''), source.data.get('insuredCn', '')


def detected_rule(party):
    from .ledger import detect_rule
    rule = detect_rule(party)
    return rule if rule and rule != 'ordinary' else 'ordinary'


def next_month(month):
    year, mon = int(month[:4]), int(month[5:7])
    return f'{year + (mon == 12):04d}-{1 if mon == 12 else mon + 1:02d}'


def revenue_month(effective, now=None):
    from production.models import ProductionReport
    from cases.calc.payment_terms import taipei_date
    month = max(str(effective or '')[:7], taipei_date(now)[:7])
    closed = set(ProductionReport.objects.filter(status='closed').values_list('year_month', flat=True))
    while month in closed:
        month = next_month(month)
    return month


def money_error(value, label, currency):
    try:
        amount = Decimal(str(value).replace(',', '').strip())
    except (InvalidOperation, ValueError):
        return f'{label} must be a number.'
    places = 0 if currency == 'TWD' else 2
    if amount != amount.quantize(Decimal(1).scaleb(-places)):
        return (f'{label} must be a whole number for TWD; decimals are not allowed.' if places == 0
                else f'{label} must have at most two decimal places for {currency}.')
    return ''


def link_insured(name, actor, transaction_uid):
    """Find (same rules as Case) or create the Insured master for a Chinese name; mark it official."""
    from cases import insured_master as im
    from masterdata.models import MasterRecord
    name = str(name or '').strip()[:240]
    if not name:
        return None
    try:
        record = im.equivalent(name)
    except Exception:  # an unusual combination never blocks the transaction
        return None
    if record is None:
        record = MasterRecord.objects.create(entity_type='insured', name=name,
            payload={'aliases': [], 'history': [dict(at=timezone.now().isoformat(), by=actor['id'], byName=actor.get('name'),
                     action='created', name=name, legacyTransaction=transaction_uid)]},
            created_by=actor['id'], updated_by=actor['id'])
    if not (record.payload or {}).get(im.OFFICIAL_KEY):
        data = copy.deepcopy(record.payload or {})
        data.setdefault('history', []).append(dict(at=timezone.now().isoformat(), by=actor['id'], byName=actor.get('name'),
                                                   action='activated_by_legacy', legacyTransaction=transaction_uid))
        data[im.OFFICIAL_KEY] = timezone.now().isoformat()
        record.payload = data; record.updated_by = actor['id']; record.row_version += 1
        record.save()
    return record.pk
