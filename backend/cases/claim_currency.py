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
    """Owner decision 2026-11-15 (same as premium allocation): each reinsurer share is
    rounded to the currency unit (TWD whole numbers, others two decimals, .5 away from
    zero), and the tail goes to the largest share (ties in Case order), so the lines
    sum to the rounded total share. E.g. TWD 1,005 at 50/30/20 -> 502 / 302 / 201."""
    from decimal import ROUND_HALF_UP
    unit = Decimal('1') if str(currency or '').upper() == 'TWD' else Decimal('0.01')
    def number(value):
        try:
            result = Decimal(str(value).replace(',', ''))
            return result if result.is_finite() else Decimal(0)
        except (InvalidOperation, ValueError, TypeError):
            return Decimal(0)
    total = number(amount)
    weights = [max(Decimal(0), number(share)) for share in shares]
    values = [(total * w / 100).quantize(unit, rounding=ROUND_HALF_UP) for w in weights]
    target = (total * sum(weights) / 100).quantize(unit, rounding=ROUND_HALF_UP)
    order = sorted((i for i, w in enumerate(weights) if w), key=lambda i: (-weights[i], i))
    if order:
        values[order[0]] += target - sum(values)
    return [float(v) for v in values]
