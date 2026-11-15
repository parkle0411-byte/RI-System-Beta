"""Historical manual-settlement records (2026-10-14 rule, retired).

Since 2026-11-03 settlement is automatic after full cash (finance_workflow). This module only
keeps the stored historical confirmations readable (QBE legacy completion, History dialog).
"""
import copy
import hashlib
import json
import re


def objects(value):
    return [row for row in value if isinstance(row, dict)] if isinstance(value, list) else []


def manual_case(payload):
    """2026-10-14 owner decision: settlement is always manual, for every case."""
    return True


def schedule_scope(payload, item):
    return manual_case(payload)


def tx_scope(payload, tx):
    leg = str(tx.get('legType') or '')
    return manual_case(payload) and (leg.startswith('Leg ') or leg.startswith('Claim Leg '))


def signature(facts):
    return hashlib.sha256(json.dumps(facts, sort_keys=True, ensure_ascii=False, default=str).encode()).hexdigest()


def schedule_signature(payload, item):
    return signature({'amount': item['amount'], 'party': item['partyName'], 'currency': item['currency'],
                      'entries': [e for e in objects(payload.get('paymentEntries')) if e.get('scheduleKey') == item['scheduleKey']]})


def tx_signature(detail):
    return signature({'amount': detail['amount'], 'party': detail['partyName'], 'group': detail['paymentGroup'],
                      'paid': detail['paid'], 'entries': detail.get('entries', []),
                      'dependencies': detail.get('settlementDependencies', [])})


def state_for(payload, key):
    state = payload.get('facilityAccounting')
    return (state.get('confirmations') or {}).get(key, {}) if isinstance(state, dict) else {}


def is_confirmed(payload, key, fingerprint):
    state = state_for(payload, key)
    return bool(state.get('confirmed') is True and state.get('fingerprint') == fingerprint and state.get('confirmedAt'))


def attach_schedule_history(payload, items):
    """Past manual settlement events of a schedule entry (shown by schedule-only History rows)."""
    state = payload.get('facilityAccounting') if isinstance(payload.get('facilityAccounting'), dict) else {}
    history = objects(state.get('history'))
    for item in items:
        item['settlementHistory'] = [e for e in history if e.get('key') == 'schedule:' + item['scheduleKey']]
    return items


def attach_history(payload, details):
    """Problem 8 partial cleanup (2026-11-15): automatic settlement (finance_workflow) owns
    every settlement field. Only the historical records still shown in the Accounting
    History dialog are attached here: past manual settlement events and past amount edits.
    The retired manual-confirmation calculation (always overwritten later) is removed."""
    state = payload.get('facilityAccounting') if isinstance(payload.get('facilityAccounting'), dict) else {}
    history = objects(state.get('history'))
    edits = objects(payload.get('paymentEditHistory'))
    transactions = {str(t.get('txNo') or ''): t for t in objects(payload.get('transactions'))}
    for no, detail in details.items():
        tx = transactions.get(no, {})
        if not tx_scope(payload, tx) or tx.get('reversed') or tx.get('isReversalEntry'):
            continue
        detail['settlementHistory'] = [e for e in history if e.get('key') == 'tx:' + no]
        detail['paymentEditHistory'] = [h for h in edits if h.get('transactionNo') == no]
    return details
