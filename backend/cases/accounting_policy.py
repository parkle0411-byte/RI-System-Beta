"""Shared A–G accounting decisions, approved 2026-10-22.

Pure policy functions. Actual receipts/payments remain accountant entries.
Property-only underwriting validation stays in property_original.scope.
"""
import re
from functools import lru_cache

VERSION = 'accounting-ag-20261022'
FACILITIES = (
    "Lloyd's Underwriter Syndicate No. 0609 AUW (Facility)",
    'Allianz Global Corporate & Specialty SE, Hong Kong Branch (Facility)',
    'Great American Insurance Company, Singapore Branch (Facility)',
    'QBE Hongkong & Shanghai Insurance Limited (Facility)',
    'Swiss Re Asia Pte. Ltd., Hong Kong Branch (Facility)',
)
@lru_cache(maxsize=4096)
def _normalized_text(text):
    return ' '.join(text.split()).casefold()

def normalized(name):
    # 2026-10-29 效能：同一個名稱只整理一次（純字串函式，結果不變）
    return _normalized_text(str(name or ''))

_FACILITY_KEYS = frozenset(_normalized_text(n) for n in FACILITIES)
_FACILITY_OR_PWS = re.compile(r'facility|\bpws\b', re.I)

def facility(name):
    return normalized(name) in _FACILITY_KEYS

def rows(value):
    return [r for r in value if isinstance(r,dict)] if isinstance(value,list) else []

def scope(p):
    if not isinstance(p,dict) or p.get('_legacyCalculation'):
        return False
    names=[r.get('name') for r in rows(p.get('reinsurers')) if r.get('name')]
    if p.get('endorsementRules') == 'facultative-v1' and p.get('reinsuranceStructure') in ('QS', 'XOL'):
        return bool(names)
    return bool(names) and all(facility(n) or not _FACILITY_OR_PWS.search(str(n)) for n in names)

def fixed_cedant(p):
    return scope(p) and any(facility(r.get('name')) for r in rows(p.get('reinsurers')))

def legacy_math(p):
    return bool(isinstance(p,dict) and (p.get('accountingLegacyMath') or
        p.get('premiumRounding')=='legacy-cents' or p.get('propertyOriginalRules')=='historical'))

def adopt(p,old=None):
    if not scope(p):
        return
    p['accountingRules']=VERSION
    # No client may turn historical precision on or off.
    if old:
        from .accounting_rules import premium_activity
        protected=legacy_math(old) or (old.get('accountingRules')!=VERSION and
            old.get('propertyOriginalRules')!='property-original-v1' and
            bool(old.get('confirmedProductionKeys') or old.get('productionHistory') or premium_activity(old)
                 or any(t.get('settlement')=='settled' for t in rows(old.get('transactions')))))
        p['accountingLegacyMath']=bool(protected)
    else:
        p['accountingLegacyMath']=False

def claim_dates(payload,tx):
    from .payment_policy import claim_source,claim_created_at
    from .calc.swiss_facility import local_date,quarter,is_swiss_facility
    from .calc.payment_terms import add_calendar_days
    source,name=claim_source(payload,tx)
    stamp=claim_created_at(payload,tx)
    base=local_date(stamp)
    if not scope({**payload,**source}) or not base:
        return None
    from .swiss_cgl import target as swiss_cgl
    swiss=is_swiss_facility(name) and not swiss_cgl({**payload, **source}, name)
    due=quarter(base) if swiss else add_calendar_days(base,15)
    return dict(baseDate=base,claimCreatedAt=stamp,dueDate=due,contractDueDate=due,
                reminderDate=add_calendar_days(due,-7),paymentRule='claim_swiss_quarterly' if swiss else 'claim_created_15')

def apply_claim_details(payload,details,now):
    from .calc.payment_terms import taipei_date,_status_for,add_calendar_days,days_between_dates
    today=taipei_date(now)
    for d in details.values():
        if d['_source']!='claim' or d['_historic']:
            continue
        dates=claim_dates(payload,d['_tx'])
        if not dates:
            continue
        d.update(dates)
        due=dates['contractDueDate'];remaining=abs(d['outstanding'])>.004
        elapsed=days_between_dates(due,today)
        first=dates['reminderDate']
        next_day=first if today<=first else due if today<=due else add_calendar_days(due,7*max(1,((elapsed or 0)+6)//7))
        d.update(paymentStatus=_status_for(due,abs(d['outstanding']),abs(d['paid']),today,now),
            nextTrackingDate=next_day if remaining else '',
            trackingDue=remaining and (today in (first,due) or elapsed is not None and elapsed>0 and elapsed%7==0),
            allianzClaim=False,greatAmericanClaim=False,qbeClaim=False)
        if d['paymentStatus']=='upcoming' and today>=first:
            d['paymentStatus']='reminder'

def fx_for_transaction(payload,tx,rates,latest):
    """Return (rate, month, estimated); no fallback for a formally posted month."""
    currency=str(payload.get('currency') or 'TWD').upper()
    if not scope(payload):
        month=tx.get('postedMonth') or str(tx.get('createdAt') or '')[:7]
        return (1 if currency=='TWD' else rates.get((month,currency)),month,False)
    claim=tx.get('source')=='claim'
    month=tx.get('postedMonth') if not claim else tx.get('postedMonth') or str(tx.get('createdAt') or '')[:7]
    if month:
        rate=1 if currency=='TWD' else tx.get('postingFxRate') or rates.get((month,currency))
        return rate,month,False
    if currency=='TWD':
        return 1,'',True
    current=latest.get(currency)
    return (current[1],current[0],True) if current else (None,'',True)


def stored_all_settled(p):
    """2026-10-29 業主：帳款上記錄的結清標記顯示「整件都已銷帳」（不含已沖回／沖回分錄）。
    Dashboard 據此跳過不重算；Accounting 每次會核對標記與實際收付款是否一致（不一致列入警告）。"""
    txs = [t for t in rows(p.get('transactions'))
           if not t.get('reversed') and not t.get('isReversalEntry')] if isinstance(p, dict) else []
    return bool(txs) and all(t.get('settlement') == 'settled' for t in txs)


SETTLED_FLAG_WARNING = ('Settlement flags say this case is fully settled, but its payments still leave an outstanding balance. '
                        'The Dashboard skips fully settled cases, so this balance is missing there. Contact the System Administrator.')


def settled_flag_mismatch(p, details):
    """用和 Dashboard 未結清金額相同的條件（略過已沖回、沖回分錄、推算的經紀費），看實際是否還有欠款。"""
    stored = {t.get('txNo'): t for t in rows(p.get('transactions'))}
    for no, detail in (details or {}).items():
        tx = stored.get(no, {})
        if tx.get('reversed') or tx.get('isReversalEntry') or detail.get('cashTracking') == 'derived':
            continue
        if abs(float(detail.get('outstanding') or 0)) >= .005:
            return True
    return False

