"""Swiss Re CGL Facility QS policy; dates are independent of actual cash dates."""
from copy import deepcopy

SWISS_NAME = 'Swiss Re Asia Pte. Ltd., Hong Kong Branch (Facility)'


def target(payload, name=None):
    if not isinstance(payload, dict):
        return False
    if str(payload.get('reinsuranceStructure') or '').strip().upper() != 'QS':
        return False
    if str(payload.get('classOfBusiness') or '').strip().casefold() != 'commercial general liability':
        return False
    normalized = lambda value: ' '.join(str(value or '').split()).casefold()
    names = [name] if name is not None else [r.get('name') for r in payload.get('reinsurers') or [] if isinstance(r, dict)]
    return any(normalized(value) == normalized(SWISS_NAME) for value in names)


def apply_schedule(payload, items, now):
    from .calc.payment_terms import endorsement_base_date, month_end_date, add_calendar_days
    from .payment_policy import actual_cash
    state = payload.get('swissAccounting') or {}
    for item in items:
        item.update(swissCase=True, swissCgl=True)
        swiss = item['partyType'] == 'reinsurer' and target(payload, (payload.get('reinsurers') or [])[int(item['partyKey'][1:])-1].get('name'))
        base = endorsement_base_date(payload) if payload.get('parentTwRef') else item['baseDate']
        if item['partyType'] == 'cedant' or swiss:
            anchor = month_end_date(base) if swiss else base
            due = add_calendar_days(anchor, 90) if anchor else ''
            reminder = add_calendar_days(due, -10 if swiss else -15) if due else ''
            item.update(baseDate=anchor, sourceBaseDate=base, termsDays=90, dueDate=reminder,
                        contractDueDate=due, reminderDate=reminder, dueTime='',
                        accountingLeadDays=10 if swiss else 15,
                        paymentRule='swiss_cgl_month_end_90' if swiss else 'swiss_cgl_cedant_90')
        if swiss:
            cedants = [r for r in items if r['partyType'] == 'cedant' and r['installmentId'] == item['installmentId']]
            ready = bool(cedants) and all(abs(r['outstanding']) < .005 and actual_cash(payload, r) for r in cedants)
            statement = state.get('statements', {}).get(item['scheduleKey'], {})
            item.update(swissFacility=True, collectionConfirmed=ready,
                        statementReference=statement.get('reference') or '',
                        statementDueDate=statement.get('dueDate') or '', statementNeedsRevision=False)
        item.update(fullPaymentRequired=True, offsetAllowed=False)
    return items


def preserve_completed_dates(payload, details, now):
    """Unsettled dates adopt this policy; completed rows retain their prior dates.

    Current automatic settlements already store settledDates. Older completed
    rows use their explicit dates or the prior Swiss calculation as a fallback.
    This function does not mutate transactions or actual cash history.
    """
    from .accounting_rules import settled_once
    from .calc.payment_terms import build_payment_schedule, add_calendar_days
    from .calc.swiss_facility import quarter, local_date
    from .payment_policy import claim_source, claim_created_at
    legacy = None
    fields = ('baseDate', 'dueDate', 'contractDueDate', 'termsDays', 'reminderDate', 'paymentRule')
    for no, detail in details.items():
        if detail['_historic'] or detail['_leg'] == '3':
            continue
        tx = detail['_tx']
        if not settled_once(payload, no):
            continue
        dates = tx.get('settledDates') or {key: tx[key] for key in fields if tx.get(key) is not None}
        if not dates and detail['_source'] == 'claim':
            source, name = claim_source(payload, tx)
            if not target({**payload, **source}, name):
                continue
            base = local_date(claim_created_at(payload, tx))
            due = quarter(base)
            dates = dict(baseDate=base, dueDate=due, contractDueDate=due,
                         reminderDate=add_calendar_days(due, -7), paymentRule='claim_swiss_quarterly')
        elif not dates and detail['_source'] == 'premium':
            if legacy is None:
                legacy = {r['scheduleKey']: r for r in build_payment_schedule(payload, now, legacy_swiss_cgl=True)['items']}
            rows = [legacy[p['scheduleKey']] for p in detail.get('cashParts', []) if p['scheduleKey'] in legacy]
            dates = {key: min(r[key] for r in rows if r.get(key) is not None) for key in fields if any(r.get(key) is not None for r in rows)}
        detail.update(deepcopy(dates))
