"""Accounting review decisions, 2026-10-16. Pure guards shared by every write path."""
from .calc.accounting import number_or_zero


def objects(value):
    return [x for x in value if isinstance(x, dict)] if isinstance(value, list) else []


def settled_once(payload, no):
    state = payload.get('facilityAccounting') or {}
    key = 'tx:' + no
    return (no in state.get('finalizedTransactions', []) or
            any(h.get('key') == key and h.get('confirmed') for h in objects(state.get('history'))) or
            bool((state.get('confirmations') or {}).get(key, {}).get('confirmed')) or
            any(t.get('txNo') == no and t.get('settlement') == 'settled' for t in objects(payload.get('transactions'))))


def finalized(payload, no):
    import re
    state = payload.get('facilityAccounting') or {}
    if no in state.get('finalizedTransactions', []):
        return True
    normalize = lambda value: re.sub(r'-(?:TX|T)[123]([ab]?)(?=-|$)', r'-T*\1', value)
    for tx in objects(payload.get('transactions')):
        if str(tx.get('legType') or '').startswith('Leg 3') and (state.get('confirmations') or {}).get('tx:' + tx.get('txNo', ''), {}).get('confirmed'):
            if no == tx.get('txNo') or normalize(no) == normalize(tx.get('txNo', '')):
                return True
    return False


def entry_locked(payload, entry):
    no = entry.get('transactionNo')
    if no:
        return settled_once(payload, no)
    key = 'schedule:' + str(entry.get('scheduleKey') or '')
    state = payload.get('facilityAccounting') or {}
    return any(h.get('key') == key and h.get('confirmed') for h in objects(state.get('history')))


def premium_activity(payload):
    """Even a reversed receipt/offset remains historical accounting activity."""
    txs = {t.get('txNo'): t for t in objects(payload.get('transactions'))}
    for entry in objects(payload.get('paymentEntries')):
        if txs.get(entry.get('transactionNo'), {}).get('source') != 'claim':
            return True
    state = payload.get('facilityAccounting') or {}
    return any(h.get('confirmed') and not str(h.get('key', '')).startswith('tx:claim:')
               and txs.get(str(h.get('key', ''))[3:], {}).get('source') != 'claim'
               for h in objects(state.get('history')))


def claim_balance_error(payload):
    """Within one recorded claim obligation, reported outgoing <= reported incoming."""
    from .cash_ledger import cents, direction
    txs = {t.get('txNo'): t for t in objects(payload.get('transactions')) if t.get('source') == 'claim'}
    groups = {}
    for entry in objects(payload.get('paymentEntries')):
        tx = txs.get(entry.get('transactionNo'))
        if not tx:
            continue
        group = (str(tx.get('claimId')), str(tx.get('paymentId')))
        sums = groups.setdefault(group, {'receivable': 0, 'payable': 0})
        value = abs(cents(entry.get('amount'))) * (-1 if entry.get('entryType') == 'reversal' else 1)
        sums[direction(tx)] += value
    if any(s['payable'] > s['receivable'] for s in groups.values()):
        return 'Claim payments cannot exceed the receipts recorded for the same claim obligation.'
    return ''


def period_terms(case_data, installment):
    from .calc.payment_terms import valid_terms
    return valid_terms(installment.get('paymentTermsDays') if case_data.get('installmentEnabled') is True
                       else case_data.get('paymentTermsDays'))
