"""Product Recall QS risk details and validation.

The row IDs identify coverage selections and survive reordering/renewal.
They are data identifiers, not labels displayed on the cover note.
"""
from decimal import Decimal, InvalidOperation

EVENTS = ('Defect', 'Malicious Product Tampering', 'Product Extortion', 'Government Recall')
LOSSES = ('First Party Recall Costs', 'Third Party Recall Costs', 'Consultant and Advisor Costs', 'Extortion Costs')
CHOICE_OF_LAW = 'This (re)insurance shall be governed by and construed in according with the law of Republic of China, Taiwan and the each party agrees to submit to the exclusive jurisdiction of the Courts of the Republic of China, Taiwan.'


def ordered_rows(rows, group):
    """Put standard rows in template order; preserve the relative custom order."""
    prefix = 'event' if group == 'events' else 'loss'
    ranks = {f'{prefix}-{i}': i for i in range(1, 5)}
    return sorted(rows or [], key=lambda row: ranks.get(row.get('id'), 5) if isinstance(row, dict) else 5)


def scope(payload):
    return isinstance(payload, dict) and str(payload.get('classOfBusiness') or '').strip().casefold() == 'product recall' and str(payload.get('reinsuranceStructure') or '').upper() in ('QS', 'FACULTATIVE')


def initial():
    return {
        'choiceOfLaw': CHOICE_OF_LAW,
        'events': [{'id': f'event-{i}', 'name': name, 'selected': True, 'fixed': True} for i, name in enumerate(EVENTS, 1)],
        'losses': [{'id': f'loss-{i}', 'name': name, 'selected': True, 'fixed': True, 'amount': None} for i, name in enumerate(LOSSES, 1)],
        'additionalSublimits': [],
    }


def _number(value):
    try:
        number = Decimal(str(value).replace(',', ''))
        return number if number.is_finite() else None
    except (InvalidOperation, ValueError, TypeError):
        return None


def _text(value):
    return str(value or '').strip()


def issues(payload, *, ready=False):
    if not scope(payload):
        return []
    risk = payload.get('productRecall') or {}
    if not isinstance(risk, dict):
        return [{'field': 'productRecall', 'label': 'Product Recall risk details must be an object'}]
    result = []
    def add(field, message):
        result.append({'field': field, 'label': message})
    groups = [('events', 'Covered Event'), ('losses', 'Covered Loss'), ('additionalSublimits', 'Additional Sub-limit')]
    for key, label in groups:
        entries = risk.get(key, [])
        if not isinstance(entries, list):
            add('productRecall.' + key, label + ' must be a list')
            continue
        names, ids = set(), set()
        fixed_names = {f'{"event" if key == "events" else "loss"}-{i}': name for i, name in enumerate(EVENTS if key == 'events' else LOSSES, 1)} if key != 'additionalSublimits' else {}
        for i, row in enumerate(entries):
            if not isinstance(row, dict):
                add(f'productRecall.{key}.{i}', label + ' must be an object')
                continue
            name = _text(row.get('name'))
            row_id = _text(row.get('id'))
            if not row_id or row_id in ids:
                add(f'productRecall.{key}.{i}.id', label + ' must have a unique identifier')
            ids.add(row_id)
            if row_id in fixed_names and (name != fixed_names[row_id] or row.get('fixed') is not True):
                add(f'productRecall.{key}.{i}.name', 'Standard items cannot be renamed')
            if row.get('fixed') is True and row_id not in fixed_names:
                add(f'productRecall.{key}.{i}.name', 'Unknown standard item')
            if not name and ready:
                add(f'productRecall.{key}.{i}.name', label + ' name is required')
            normalized = name.casefold()
            if normalized and normalized in names:
                add(f'productRecall.{key}.{i}.name', label + ' names must be unique')
            if normalized:
                names.add(normalized)
        if ready and key != 'additionalSublimits' and not any(isinstance(r, dict) and r.get('selected') and _text(r.get('name')) for r in entries):
            add('productRecall.' + key, 'Select at least one ' + label)
    losses = risk.get('losses') if isinstance(risk.get('losses'), list) else []
    additional = risk.get('additionalSublimits') if isinstance(risk.get('additionalSublimits'), list) else []
    loss_names = {_text(row.get('name')).casefold() for row in losses if isinstance(row, dict) and _text(row.get('name'))}
    for i, row in enumerate(additional):
        if isinstance(row, dict) and _text(row.get('name')).casefold() in loss_names:
            add(f'productRecall.additionalSublimits.{i}.name', 'Use the existing Covered Loss sub-limit')
    limit = _number(payload.get('limitOfLiability'))
    currency = str(payload.get('currency') or '').upper()
    if ready and (limit is None or limit <= 0):
        add('limitOfLiability', 'Limit of Indemnity must be greater than 0')
    if ready:
        if currency not in ('TWD', 'USD'):
            add('currency', 'Product Recall currency must be TWD or USD')
        for key, label in (('originalExclusions', 'Original Exclusions'), ('originalConditions', 'Original Conditions'),
                           ('reinsuredRetention', 'Reinsured’s Retention'), ('expressWarranties', 'Express Warranties'),
                           ('conditionsPrecedent', 'Conditions Precedent'), ('subjectivities', 'Subjectivities')):
            if not _text(payload.get(key)):
                add(key, label + ' is required')
    def amount_issue(field, raw, *, required=False, cap=True):
        if raw is None or str(raw).strip() == '':
            if required:
                add(field, 'Enter an amount greater than 0')
            return
        value = _number(raw)
        if value is None or value <= 0:
            add(field, 'Amount must be greater than 0')
            return
        if currency == 'TWD' and value != value.to_integral_value() or currency == 'USD' and value.normalize().as_tuple().exponent < -2:
            add(field, 'Amount has too many decimal places for the currency')
        if ready and cap and limit is not None and value > limit:
            add(field, 'Amount must not exceed the Limit of Indemnity')
    amount_issue('limitOfLiability', payload.get('limitOfLiability'), cap=False)
    for key, rows in (('losses', losses), ('additionalSublimits', additional)):
        for i, row in enumerate(rows):
            if not isinstance(row, dict) or key == 'losses' and not row.get('selected'):
                continue
            amount_issue(f'productRecall.{key}.{i}.amount', row.get('amount'), required=ready)
    deductible = payload.get('deductibles')
    if ready and not _text(deductible) and not _text(payload.get('selfInsuredRetention')):
        add('deductibles', 'Enter Deductibles or Self-Insured Retention')
    amount_issue('deductibles', deductible)
    from .claim_currency import CURRENCIES, valid_amount
    for i, row in enumerate(payload.get('lossRecord') or []):
        if not isinstance(row, dict):
            continue
        row_currency = _text(row.get('currency')).upper()
        if ready and row_currency not in CURRENCIES:
            add(f'lossRecord.{i}.currency', f'Loss {i + 1} Currency')
        amount = row.get('lossPaid')
        if amount is not None and str(amount).strip() and (_number(amount) is None or _number(amount) <= 0 or row_currency and not valid_amount(amount, row_currency)):
            add(f'lossRecord.{i}.lossPaid', f'Loss {i + 1} Amount must be positive and use the currency precision')
    return result
