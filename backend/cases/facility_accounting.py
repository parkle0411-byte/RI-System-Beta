"""Settlement is an accountant action, separate from cash balance calculation.

2026-10-14 owner decision: no automatic settlement. Every premium leg (T1/T2/T3), every claim
transaction and every payment-schedule entry is settled only by an explicit accountant
confirmation, for all cases (not only Facility). Names keep the original "facility" wording.
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


def apply_schedules(payload, items):
    for item in items:
        if not schedule_scope(payload, item):
            continue
        cleared = abs(item['outstanding']) < .005
        fingerprint = schedule_signature(payload, item)
        confirmed = cleared and is_confirmed(payload, 'schedule:' + item['scheduleKey'], fingerprint)
        item.update(manualSettlementRequired=True, manualSettlementConfirmed=confirmed,
                    canConfirmSettlement=cleared and not confirmed,
                    settlement='settled' if confirmed else 'pending_confirmation' if cleared else 'partial' if abs(item['paid']) > .004 else 'open')
        state = state_for(payload, 'schedule:' + item['scheduleKey'])
        item['settlementHistory'] = [e for e in (payload.get('facilityAccounting') or {}).get('history', []) if e.get('key') == 'schedule:' + item['scheduleKey']]
        item['settlementConfirmedAt'] = state.get('confirmedAt', '') if confirmed else ''
        item['settlementConfirmedBy'] = state.get('confirmedByName', '') if confirmed else ''
        if cleared:
            item['status'] = 'settled' if confirmed else 'pending_confirmation'
    return items


def apply_transactions(payload, details, schedule_items=None):
    from .calc.payment_terms import build_payment_schedule
    # schedule_items：呼叫端（transaction_details）已算好的付款排程項目，同一份 payload，不必再算一次
    schedule = {i['scheduleKey']: i for i in (build_payment_schedule(payload)['items'] if schedule_items is None else schedule_items)}
    transactions = {str(t.get('txNo') or ''): t for t in objects(payload.get('transactions'))}
    # Cash legs first: brokerage eligibility must use the manual settlement of its dependencies.
    ordered = sorted(details.items(), key=lambda pair: pair[1]['cashTracking'] == 'derived')
    for no, detail in ordered:
        tx = transactions.get(no, {})
        if not tx_scope(payload, tx) or tx.get('reversed') or tx.get('isReversalEntry'):
            continue
        derived = detail['cashTracking'] == 'derived'
        if derived:
            dependencies = detail.get('settlementDependencies', [])
            for dep in dependencies:
                other = details.get(dep['txNo'], {})
                dep.update(settlement=other.get('settlement', 'open'),
                           confirmation=other.get('settlementConfirmedAt', ''),
                           balanceSignature=other.get('settlementFingerprint', ''))
            cleared = (bool(dependencies) and {str(transactions.get(d['txNo'], {}).get('legType', ''))[4:5] for d in dependencies} == {'1', '2'}
                       and all(d['settlement'] == 'settled' for d in dependencies))
            # T3 is retained income; a confirmation never creates a bank cash entry.
            detail['paid'] = 0
            detail['outstanding'] = detail['amount']
        else:
            cleared = abs(detail['outstanding']) < .005
        fingerprint = tx_signature(detail)
        schedule_keys = [p['scheduleKey'] for p in detail.get('cashParts', [])]
        confirmed = cleared and is_confirmed(payload, 'tx:' + no, fingerprint)
        state = state_for(payload, 'tx:' + no)
        detail.update(manualSettlementRequired=True, manualSettlementConfirmed=confirmed,
                      canConfirmSettlement=cleared and not confirmed, settlementFingerprint=fingerprint,
                      settlementConfirmedAt=(state.get('confirmedAt', '') or max((state_for(payload, 'schedule:' + key).get('confirmedAt', '') or schedule.get(key, {}).get('collectionConfirmedAt', '') for key in schedule_keys), default='')) if confirmed else '',
                      settlementConfirmedBy=state.get('confirmedByName', '') if confirmed else '',
                      settlementHistory=(payload.get('facilityAccounting') or {}).get('history', []))
        from .accounting_rules import finalized, settled_once
        detail['canCancelSettlement'] = confirmed and not finalized(payload, no)
        detail['amountEditLocked'] = settled_once(payload, no)
        detail['settlementFinalized'] = finalized(payload, no)
        detail['paymentEditHistory'] = [h for h in objects(payload.get('paymentEditHistory')) if h.get('transactionNo') == no]
        detail['settlementHistory'] = [e for e in detail['settlementHistory'] if e.get('key') == 'tx:' + no]
        detail['settlement'] = 'settled' if confirmed else 'pending_confirmation' if cleared else 'partial' if abs(detail['paid']) > .004 else 'open'
        if confirmed and derived:
            detail['paid'], detail['outstanding'] = detail['amount'], 0
        if cleared or derived:
            detail['paymentStatus'] = detail['settlement']
    return details
