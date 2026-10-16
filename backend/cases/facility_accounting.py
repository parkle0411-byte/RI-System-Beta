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


def facility_indices(payload):
    return {i for i, row in enumerate(objects(payload.get('reinsurers')))
            if re.search(r'\(Facility\)\s*$', str(row.get('name') or ''), re.I)}


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


def settlement_action(view, request, body):
    from .accounting_views import _can_edit, _error, _iso_now
    from .calc.payment_terms import build_payment_schedule
    from .calc.swiss_facility import case_payload
    from .cash_ledger import transaction_details
    from ri_system.authz import actor_from
    if not _can_edit(request.ri_principal):
        return _error(403, 'permission_denied', 'Accounting write access is required.')
    case = view._load_case_for_update(str(body.get('caseUid') or ''))
    if not case:
        return _error(404, 'case_not_found', 'Case not found.')
    locked = view._status_error(case, 'confirmed')
    if locked:
        raw = next((t for t in objects(case.payload.get('transactions')) if t.get('txNo') == body.get('txNo')), {})
        if case.status != 'reversed' or raw.get('source') != 'claim':
            return locked
    if case.row_version != body.get('rowVersion'):
        return _error(409, 'version_conflict', 'This case changed. Refresh Accounting and try again.')
    payload = case_payload(case)
    no, schedule_key = body.get('txNo'), body.get('scheduleKey')
    # 2026-10-14：非文字的編號（陣列、數字…）回 400，不讓查表時出錯
    if any(value is not None and not isinstance(value, str) for value in (no, schedule_key)):
        return _error(400, 'invalid_settlement_target', 'Select one transaction or schedule entry.')
    if schedule_key:
        return _error(400, 'individual_transaction_required', 'Settle each posted transaction individually; no separate Swiss collection action is required.')
    if bool(no) == bool(schedule_key):
        return _error(400, 'invalid_settlement_target', 'Select one transaction or schedule entry.')
    if no:
        detail = transaction_details(payload).get(no)
        key = 'tx:' + str(no)
        fingerprint = detail.get('settlementFingerprint') if detail else None
    else:
        detail = next((i for i in build_payment_schedule(payload)['items'] if i['scheduleKey'] == schedule_key), None)
        key = 'schedule:' + str(schedule_key)
        fingerprint = schedule_signature(payload, detail) if detail else None
    if not detail or not detail.get('manualSettlementRequired'):
        return _error(400, 'facility_scope_required', 'Select a current premium, claim or schedule entry.')
    if 'confirmedAt' in body or 'confirmationDate' in body:
        return _error(400, 'confirmation_date_locked', 'Settlement confirmation uses the actual operation time in Taiwan.')
    confirm = body['action'] == 'confirm_facility_settlement'
    if confirm and detail.get('cashTracking') != 'derived' and not detail.get('contractDueDate'):
        return _error(400, 'terms_pending_review', 'Confirm the contract days and due date before settlement.')
    if confirm and not detail.get('canConfirmSettlement'):
        return _error(400, 'settlement_not_ready', 'Clear the balance first; brokerage requires manually settled T1 and T2.')
    from .accounting_rules import finalized
    if not confirm and no and finalized(payload, no):
        return _error(409, 'final_settlement_locked', 'T3 is final: the matching T1, T2 and T3 settlements cannot be cancelled.')
    if not confirm and not detail.get('manualSettlementConfirmed'):
        return _error(400, 'settlement_not_confirmed', 'This entry has no current settlement confirmation.')
    if not confirm and not no and detail.get('requiresCollectionConfirmation'):
        return _error(400, 'collection_confirmation_action_required', 'Use Cancel confirmation to cancel Swiss collection confirmation.')
    note = str(body.get('note') or '').strip()[:1000]
    if not note:
        return _error(400, 'settlement_reason_required', 'Enter a reconciliation reference or reason.')
    actor, now = actor_from(request.ri_principal), _iso_now()
    state = payload.setdefault('facilityAccounting', {})
    entry = {'key': key, 'confirmed': confirm, 'fingerprint': fingerprint,
             'confirmedAt': now, 'confirmedBy': actor['id'], 'confirmedByName': actor['name'], 'note': note}
    state.setdefault('confirmations', {})[key] = entry
    state.setdefault('history', []).append(copy.deepcopy(entry))
    if confirm and detail.get('cashTracking') == 'derived':
        finalized = set(state.get('finalizedTransactions', []))
        finalized.add(no)
        finalized.update(d['txNo'] for d in detail.get('settlementDependencies', []))
        state['finalizedTransactions'] = sorted(finalized)
    # A schedule/Swiss collection is confirmed only when EVERY corresponding
    # transaction was explicitly settled. One checkbox never settles another row.
    if no and detail.get('cashTracking') != 'derived':
        from .cash_ledger import _matches
        live = [t for t in objects(payload.get('transactions')) if t.get('source') != 'claim'
                and not t.get('reversed') and not t.get('isReversalEntry')]
        for item in build_payment_schedule(payload)['items']:
            if item['scheduleKey'] not in {p['scheduleKey'] for p in detail.get('cashParts', [])}:
                continue
            matched = [t for t in live if _matches(item, t)]
            complete = (abs(item['outstanding']) < .005 and bool(matched) and
                        all(state_for(payload, 'tx:' + t['txNo']).get('confirmed') for t in matched))
            aggregate = {**entry, 'key': 'schedule:' + item['scheduleKey'], 'confirmed': complete,
                         'fingerprint': schedule_signature(payload, item)}
            state['confirmations'][aggregate['key']] = aggregate
            state['history'].append(copy.deepcopy(aggregate))
            if item.get('requiresCollectionConfirmation'):
                from .calc.swiss_facility import fingerprint as swiss_fingerprint
                collection = payload.setdefault('swissAccounting', {}).setdefault('confirmations', {})
                collection[item['scheduleKey']] = {'confirmed': complete, 'confirmedAt': now,
                                                   'confirmedBy': actor['id'], 'source': 'manual settlement',
                                                   'fingerprint': swiss_fingerprint(payload, item['scheduleKey'])}
    payload.setdefault('paymentEntries', [])
    return view._save(request, body, case, payload, body['action'], {'settlementKey': key, 'note': note})
