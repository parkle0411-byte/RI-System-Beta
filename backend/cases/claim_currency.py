"""Currency selection and precision for the approved multi-currency Claim scopes."""
from decimal import Decimal, InvalidOperation
import math

CURRENCIES = ('TWD', 'USD', 'EUR', 'JPY', 'GBP', 'HKD', 'MYR')


def multi_currency_scope(payload):
    if not isinstance(payload, dict):
        return False
    klass = str(payload.get('classOfBusiness') or '').strip().casefold()
    structure = str(payload.get('reinsuranceStructure') or '').strip().upper()
    if klass == 'stock throughput':
        return True
    if klass == 'product recall':
        return structure in ('QS', 'FACULTATIVE')
    if klass == 'commercial general liability' and structure in ('QS', 'FACULTATIVE'):
        from .cgl_information import is_standard_cgl
        return is_standard_cgl(payload)
    return False


def claim_currency(payload, claim):
    """Pre-existing Claims without a currency retain the original Case currency."""
    value = claim.get('currency') if isinstance(claim, dict) else None
    return str(value or payload.get('currency') or '').strip().upper()


def original_currency_claim(payload, transaction):
    """These Claim transactions are displayed and totalled without FX conversion."""
    return isinstance(transaction, dict) and transaction.get('source') == 'claim' and multi_currency_scope(payload)


def valid_amount(value, currency):
    """Reject, rather than round, amounts that exceed the approved precision."""
    try:
        amount = Decimal(str(value).replace(',', ''))
        if not amount.is_finite():
            return False
        digits = 0 if str(currency).upper() == 'TWD' else 2
        return amount.normalize().as_tuple().exponent >= -digits
    except (InvalidOperation, ValueError, TypeError):
        return False


def allocate_claim_shares(amount, shares, currency):
    """Allocate rounded minor units so the lines sum to the rounded total share."""
    from .calc.jsnum import js_round
    factor = 1 if str(currency or '').upper() == 'TWD' else 100
    raw = [float(amount) * float(share or 0) / 100 * factor for share in shares]
    units = [math.floor(value) for value in raw]
    remainder = int(js_round(sum(raw))) - sum(units)
    order = sorted(range(len(raw)), key=lambda i: (-(raw[i] - units[i]), i))
    for i in order[:max(0, remainder)]:
        units[i] += 1
    return [value / factor for value in units]
