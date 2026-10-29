"""Server-owned layout version; handled historical premiums never change shape."""
import copy
from .accounting_policy import rows
VERSION='per-reinsurer-v1'
KEY='premiumLedgerLayout'

def untreated(p):
    from .accounting_rules import premium_activity
    live=[t for t in rows(p.get('transactions')) if t.get('source')!='claim']
    return not (premium_activity(p) or p.get('confirmedProductionKeys') or p.get('productionHistory')
        or p.get('productionReversals') or p.get('pendingReversalOffset')
        or any(t.get('settlement')=='settled' or t.get('productionRecognized') or t.get('reversed') or t.get('isReversalEntry') for t in live)
        or (p.get('swissAccounting') or {}).get('offsets'))

def per_reinsurer(p):
    if p.get(KEY): return p[KEY]==VERSION
    from .accounting_policy import scope,legacy_math
    if not scope(p) or legacy_math(p):return False
    return not any(t.get('source')!='claim' and not t.get('reversed') and not t.get('isReversalEntry') for t in rows(p.get('transactions')))

def adopt_layout(p,old=None):
    p[KEY]=(old or {}).get(KEY) or (VERSION if untreated(old or {}) else 'preserved')

def convert(p,now,actor):
    from .property_original import enabled,refresh_transactions,persist_settlements
    if not enabled(p) or p.get(KEY)==VERSION or not untreated(p): return None
    before=copy.deepcopy(p)
    p=copy.deepcopy(p);p[KEY]=VERSION
    if p.get('twRef'): refresh_transactions(p,now);persist_settlements(p,now,actor)
    p.setdefault('accountingLayoutHistory',[]).append(dict(at=now,by=actor.get('id'),byName=actor.get('name'),operation='per_reinsurer_conversion',before=before.get('transactions',[]),after=copy.deepcopy(p.get('transactions',[]))))
    return p
