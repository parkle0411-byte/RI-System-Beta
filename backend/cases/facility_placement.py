"""Rules for Facility Placement declarations.

This module is deliberately independent of posting and accounting persistence;
callers must serialize and lock a Facility while validating and saving a draft.
"""
from datetime import date, timedelta
from decimal import Decimal, InvalidOperation

from .claim_currency import allocate_claim_shares, valid_amount
from .property_original import allocate, money, num, totals

MAX_PREMIUM = Decimal('999999999999')
SUFFIX = 'Personal Accident Facultative Facility Reinsurance'
from fxrates.currencies import ALL as CURRENCIES
TEXT_FIELDS = ('facilityName', 'classOfBusiness', 'classCode', 'facilityTypePrefix', 'reinsured',
               'reinsuredLocation', 'originalAssuredDescription', 'periodConditions', 'interest', 'coverageLimits',
               'eventLimit', 'reinsuredRetention', 'territorialScope', 'conditions', 'exclusions',
               'expressWarranties', 'conditionsPrecedent', 'subjectivities', 'choiceOfLaw', 'premiumRates',
               'premiumPaymentTerms', 'bordereaux', 'accounts', 'cashLossLimit', 'taxesText', 'recordingText',
               'facilityInformation', 'newOrRenew', 'ownerPersonnelName', 'ae', 'renewedFromTwRef')


def _date(value, label):
    try:
        if not isinstance(value, str) or len(value) != 10:
            raise ValueError()
        result = date.fromisoformat(value)
        if result.isoformat() != value:
            raise ValueError()
        return result
    except (TypeError, ValueError):
        raise ValueError(f'{label} must be a valid date in YYYY-MM-DD format.')


def _number(value, label):
    try:
        if isinstance(value, bool):
            raise ValueError()
        number = Decimal(str(value).replace(',', '').strip())
        if not number.is_finite():
            raise ValueError()
        return number
    except (InvalidOperation, TypeError, ValueError):
        raise ValueError(f'{label} must be a finite number.')


def normalize_facility_draft(source):
    """Whitelist user-entered fields; never accept posting or accounting state."""
    if not isinstance(source, dict):
        raise ValueError('Facility data is required.')
    value = {'reinsuranceStructure': 'FACILITY', 'originalInsured': '', 'originalInsuredCn': '',
             'transactions': [], 'paymentEntries': [], 'claims': [], 'confirmedProductionKeys': [],
             'splitEnabled': False, 'splitParties': [], 'performanceInstallments': [], 'installmentEnabled': False}
    for key in TEXT_FIELDS:
        item = source.get(key) or ''
        if not isinstance(item, str) or len(item) > (50000 if key not in ('facilityName', 'classOfBusiness', 'classCode', 'reinsured', 'ownerPersonnelName', 'ae', 'renewedFromTwRef', 'newOrRenew', 'facilityTypePrefix') else 240):
            raise ValueError(f'{key} has an invalid format or exceeds its size limit.')
        value[key] = item.strip()
    if value['classOfBusiness'] not in ('', 'Personal Accident'):
        raise ValueError('Facility Placement currently supports Personal Accident only.')
    for key in ('ownerPersonnelId', 'aePersonnelId'):
        item = source.get(key)
        if item not in (None, ''):
            number = _number(item, key)
            if number < 1 or number != number.to_integral_value():
                raise ValueError(f'{key} must be a positive whole number.')
            value[key] = int(number)
        else:
            value[key] = None
    for key in ('riCommPct', 'taxPct', 'ppwDays'):
        item = source.get(key)
        if item is None or item == '':
            value[key] = None
            continue
        number = _number(item, key)
        if number < 0 or (key != 'ppwDays' and number > 100) or (key == 'ppwDays' and (number != number.to_integral_value() or number > 36500)):
            raise ValueError(f'{key} is out of range.')
        value[key] = float(number)
    currency = str(source.get('currency') or '').strip().upper()
    if currency and currency not in CURRENCIES:
        raise ValueError('Unsupported currency.')
    value['currency'] = currency
    for key in ('policyFrom', 'policyTo'):
        item = source.get(key) or ''
        value[key] = _date(item, key).isoformat() if item else ''
    if value['policyFrom'] and value['policyTo'] and value['policyTo'] < value['policyFrom']:
        raise ValueError('Facility end must not precede its start.')
    value['policyFromTime'] = value['policyToTime'] = '00:00'
    rows = source.get('reinsurers') or []
    if not isinstance(rows, list) or len(rows) > 50:
        raise ValueError('Reinsurers must be a list of at most 50 entries.')
    value['reinsurers'] = []
    for row in rows:
        if not isinstance(row, dict):
            raise ValueError('Invalid Reinsurer entry.')
        clean = {}
        for key in ('name', 'facilityReference'):
            item = row.get(key) or ''
            if not isinstance(item, str) or len(item) > 240:
                raise ValueError(f'{key} has an invalid format or exceeds 240 characters.')
            clean[key] = item.strip()
        for key in ('sharePct', 'deductionPct', 'taxPct'):
            item = row.get(key)
            if item is None or item == '':
                clean[key] = None
                continue
            number = _number(item, key)
            if not 0 <= number <= 100:
                raise ValueError(f'{key} is out of range.')
            clean[key] = float(number)
        value['reinsurers'].append(clean)
    if sum(Decimal(str(row['sharePct'] or 0)) for row in value['reinsurers']) > 100:
        raise ValueError('Reinsurer shares must not exceed 100%.')
    value['type'] = f"{value['facilityTypePrefix']} {SUFFIX}".strip()
    return value


def validate_facility(facility):
    """Check a Facility before review/announcement, without creating ledger entries."""
    for key, label in (('facilityName', 'Facility name'), ('reinsured', 'Reinsured'),
                       ('classOfBusiness', 'Insurance type')):
        if not str(facility.get(key) or '').strip():
            raise ValueError(f'{label} is required.')
    if facility.get('classOfBusiness') != 'Personal Accident':
        raise ValueError('Facility Placement currently supports Personal Accident only.')
    if str(facility.get('currency') or '').upper() not in CURRENCIES:
        raise ValueError('A supported Facility currency is required.')
    start = _date(facility.get('policyFrom'), 'Facility start')
    end = _date(facility.get('policyTo'), 'Facility end')
    if end < start:
        raise ValueError('Facility end must not precede its start.')
    validate_declaration(facility, {'periodFrom': start.isoformat(), 'periodTo': start.isoformat(),
                                  'statementNo': '_readiness_check_', 'premium': 1, 'claim': 0})
    prefix = str(facility.get('facilityTypePrefix') or '').strip()
    return {'type': f'{prefix} {SUFFIX}'.strip(), 'policyFrom': start.isoformat(), 'policyTo': end.isoformat()}


def validate_declaration(facility, declaration, others=(), exclude_id=None):
    """Validate a complete declaration against active draft/announced siblings.

    ``others`` must include drafts and posted declarations, excluding cancelled
    and recycled records. A caller editing a record supplies its stable ID.
    """
    start = _date(declaration.get('periodFrom'), 'Declaration period start')
    end = _date(declaration.get('periodTo'), 'Declaration period end')
    if end < start:
        raise ValueError('Declaration period end must not precede its start.')
    ref = str(declaration.get('statementNo') or '').strip()
    if not ref:
        raise ValueError('Cedant statement number is required.')
    if len(ref) > 160:
        raise ValueError('Cedant statement number cannot exceed 160 characters.')
    premium = _number(declaration.get('premium') or 0, 'Premium')
    claim = _number(declaration.get('claim') or 0, 'Claim')
    if premium == 0 and claim == 0:
        raise ValueError('Premium or Claim must be non-zero.')
    currency = str(facility.get('currency') or '').upper()
    if currency not in CURRENCIES:
        raise ValueError('A supported Facility currency is required.')
    if abs(premium) > MAX_PREMIUM:
        raise ValueError('Premium exceeds the supported amount.')
    if abs(claim) > MAX_PREMIUM:
        raise ValueError('Claim exceeds the supported amount.')
    if not valid_amount(premium, currency) or not valid_amount(claim, currency):
        raise ValueError('Premium and Claim must use the permitted currency precision.')
    active = [x for x in others if exclude_id is None or x.get('id') != exclude_id]
    for other in active:
        if str(other.get('statementNo') or '').strip().casefold() == ref.casefold():
            raise ValueError('Cedant statement number is already used for this Facility.')
        other_start = _date(other.get('periodFrom'), 'Existing period start')
        other_end = _date(other.get('periodTo'), 'Existing period end')
        if start <= other_end and other_start <= end:
            raise ValueError('Declaration periods must not overlap.')
    if exclude_id is None and active and start <= max(_date(x.get('periodTo'), 'Existing period end') for x in active):
        raise ValueError('A new Declaration must start after the latest Declaration ends.')
    first = min([start] + [_date(x.get('periodFrom'), 'Existing period start') for x in active])
    if first != _date(facility.get('policyFrom'), 'Facility start'):
        raise ValueError('The first Declaration must start on the Facility start date.')
    shares = []
    for row in facility.get('reinsurers') or []:
        if not isinstance(row, dict):
            raise ValueError('Invalid Reinsurer entry.')
        if not str(row.get('name') or '').strip():
            raise ValueError('Reinsurer name is required.')
        if not str(row.get('facilityReference') or '').strip():
            raise ValueError('Each Reinsurer requires a reference number.')
        share = _number(row.get('sharePct'), 'Reinsurer share')
        deduction = _number(row.get('deductionPct'), 'Reinsurer deduction')
        if not 0 < share <= 100 or not 0 <= deduction <= 100:
            raise ValueError('Reinsurer share or deduction is out of range.')
        shares.append(share)
    if not shares or sum(shares) > 100:
        raise ValueError('Reinsurer shares must total more than zero and no more than 100%.')
    commission = _number(facility.get('riCommPct'), 'Cedant commission')
    if not 0 <= commission <= 100:
        raise ValueError('Cedant commission is out of range.')
    ppw = _number(facility.get('ppwDays'), 'PPW')
    if ppw < 0 or ppw != ppw.to_integral_value():
        raise ValueError('PPW must be a non-negative whole number of days.')
    try:
        due = end + timedelta(days=int(ppw))
    except (OverflowError, ValueError):
        raise ValueError('PPW produces an invalid due date.')
    return {'periodFrom': start.isoformat(), 'periodTo': end.isoformat(), 'dueDate': due.isoformat()}


def calculate(facility, premium, claim):
    """Preview existing per-reinsurer premium legs and claim allocation.

    Tax and rounding use existing case calculation rules. Posting, ledger
    direction, production month and historical correction are handled elsewhere.
    """
    rows = facility.get('reinsurers') or []
    claims = allocate_claim_shares(claim, [r.get('sharePct') for r in rows], facility.get('currency'))
    amount = float(_number(premium, 'Premium'))
    normalized = [{**r, 'premium': amount, 'riCommPct': r.get('deductionPct')} for r in rows]
    case = {**facility, 'originalPremium': amount, 'reinsurers': normalized,
            'accountingLegacyMath': False, 'premiumRounding': 'currency-stepwise-v1'}
    summary = totals(case)
    weights = [r.get('sharePct') for r in rows]
    allocated_premium = allocate(summary['cedantPremium'], weights, case)
    allocated_commission = allocate(summary['cedantCommission'], weights, case)
    allocated_tax = allocate(summary['cedantTax'], weights, case)
    allocated_cedant = allocate(summary['leg1'], weights, case)
    result = []
    for i, (row, allocated_claim) in enumerate(zip(rows, claims)):
        component = summary['components'][i]
        cedant = num(allocated_cedant[i])
        reinsurer = num(component['t2'])
        result.append({'name': row.get('name'), 'reference': row.get('facilityReference'),
                       'premium': allocated_premium[i], 'cedantCommission': allocated_commission[i],
                       'cedantTax': allocated_tax[i], 'deduction': component['deduction'],
                       'reinsurerTax': component['tax'], 'brokerage': money(cedant - reinsurer, case),
                       'claim': allocated_claim, 'cedantNet': money(cedant - num(allocated_claim), case),
                       'reinsurerNet': money(reinsurer - num(allocated_claim), case)})
    return result


def revenue_month(announced_day, closed_months):
    """Use previous calendar month when it is still open at announcement time.

    Caller provides a Taipei-local date and must serialize this decision with
    production close so that the closed-month set cannot change concurrently.
    """
    if not isinstance(announced_day, date):
        raise ValueError('The local announcement date is required.')
    first = announced_day.replace(day=1)
    previous = (first - timedelta(days=1)).strftime('%Y-%m')
    current = first.strftime('%Y-%m')
    if previous not in set(closed_months):
        return previous
    if current in set(closed_months):
        raise ValueError('The announcement month is already closed.')
    return current


def correction_delta(original, corrected):
    """Full corrected amounts are entered; return signed changes for reconciliation.

    Creating the actual reversal and replacement records is the responsibility of
    the posting workflow, which must retain the original and both accounting legs.
    """
    result = {}
    for key, label in (('premium', 'Premium'), ('claim', 'Claim')):
        old = _number(original.get(key) or 0, label)
        new = _number(corrected.get(key) or 0, label)
        result[key] = new - old
    return result
