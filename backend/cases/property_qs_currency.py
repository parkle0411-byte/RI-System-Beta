"""Currency restriction for Property Quota Share cases, including endorsements."""

MESSAGE = 'Property QS Currency must be TWD or USD.'
ALLOWED = frozenset(('TWD', 'USD'))


def scope(payload):
    return (isinstance(payload, dict)
            and str(payload.get('classOfBusiness') or '').strip().casefold() == 'property'
            and str(payload.get('reinsuranceStructure') or '').strip().upper() in ('QS', 'FACULTATIVE'))


def invalid(payload, existing=None):
    if not scope(payload):
        return False
    currency = str(payload.get('currency') or '').strip().upper()
    prior = str((existing or {}).get('currency') or '').strip().upper()
    return (bool(currency) and currency not in ALLOWED) or (not currency and scope(existing) and bool(prior) and prior not in ALLOWED)
