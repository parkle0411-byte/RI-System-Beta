"""Stock Throughput underwriting data and review validation.

Drafts may be incomplete; validation of required fields is applied on review.
This module is intentionally scoped to STP and does not change other classes.
"""
import math
import re

CURRENCIES = {'TWD', 'USD', 'EUR', 'JPY', 'GBP', 'HKD', 'MYR'}
DEFAULT_WARRANTY = 'None - other than as may exist in this document or in the wording that forms part of this contract.'


def scope(payload):
    return isinstance(payload, dict) and (str(payload.get('classCode') or '').strip().upper() == 'ST' or str(payload.get('classOfBusiness') or '').strip().casefold() == 'stock throughput')


def _filled(value):
    return isinstance(value, str) and bool(value.strip())


def _positive(value):
    if value is None or isinstance(value, bool) or value == '':
        return False
    try:
        amount = float(value)
        return math.isfinite(amount) and amount > 0
    except (TypeError, ValueError):
        return False


def issues(payload):
    if not scope(payload):
        return []
    out = []
    def add(field, label):
        out.append({'field': field, 'label': label})
    if str(payload.get('reinsuranceStructure') or '').upper() not in ('QS', 'FACULTATIVE'):
        add('reinsuranceStructure', 'Stock Throughput requires Quota Share')
    for key, label in (('conveyance', 'Conveyance'), ('voyage', 'Voyage'),
                       ('limitOfLiability', 'Limit of Liability'), ('reinsuredRetention', 'Reinsured’s Retention'),
                       ('expressWarranties', 'Express Warranties'), ('conditionsPrecedent', 'Conditions Precedent'),
                       ('subjectivities', 'Subjectivities')):
        if not _filled(payload.get(key)):
            add(key, label)
    for key, label in (('riCommPct', 'Ceding Commission'), ('taxPct', 'Cedant Tax')):
        if payload.get(key) is None or payload.get(key) == '':
            add(key, label)
    for i, row in enumerate(payload.get('reinsurers') or []):
        if isinstance(row, dict) and re.search(r'\bfacility\b', str(row.get('name') or ''), re.I):
            add(f'reinsurers.{i}.name', 'Facility is not available for Stock Throughput')
    hubs = payload.get('stpHubs')
    if not isinstance(hubs, list) or not hubs:
        add('stpHubs', 'At least one HUB is required')
    else:
        for i, row in enumerate(hubs):
            row = row if isinstance(row, dict) else {}
            for key, label in (('name', 'Location name'), ('address', 'Address')):
                if not _filled(row.get(key)):
                    add(f'stpHubs.{i}.{key}', f'HUB {i + 1} {label}')
            if str(row.get('currency') or '').upper() not in CURRENCIES:
                add(f'stpHubs.{i}.currency', f'HUB {i + 1} Currency')
            if not _positive(row.get('amount')):
                add(f'stpHubs.{i}.amount', f'HUB {i + 1} Insured Amount must be greater than 0')
    mode = payload.get('stpTurnoverMode')
    if mode not in ('combined', 'companies'):
        add('stpTurnoverMode', 'Choose an Estimated Turnover mode')
    turnover = payload.get('stpTurnover')
    if not isinstance(turnover, list) or not turnover:
        add('stpTurnover', 'At least one Estimated Turnover entry is required')
    else:
        names = set()
        for i, row in enumerate(turnover):
            row = row if isinstance(row, dict) else {}
            name = str(row.get('company') or '').strip()
            currency = str(row.get('currency') or '').strip().upper()
            if mode == 'companies':
                if not name:
                    add(f'stpTurnover.{i}.company', f'Turnover {i + 1} Company')
                elif name.lower() in names:
                    add(f'stpTurnover.{i}.company', f'Turnover {i + 1} Company must be unique')
                names.add(name.lower())
            if currency not in CURRENCIES:
                add(f'stpTurnover.{i}.currency', f'Turnover {i + 1} Currency')
            if not _positive(row.get('amount')):
                add(f'stpTurnover.{i}.amount', f'Turnover {i + 1} Amount must be greater than 0')
    return out
