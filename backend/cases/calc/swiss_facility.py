"""Swiss Facility Property dates and manual clearance; no database side effects."""
import copy
import hashlib
import json
from datetime import date, datetime, timedelta, timezone
from zoneinfo import ZoneInfo

SWISS_NAME = 'Swiss Re Asia Pte. Ltd., Hong Kong Branch (Facility)'
TAIPEI = ZoneInfo('Asia/Taipei')
CONFIRMATION_FIELDS = ('requiresCollectionConfirmation', 'collectionConfirmed', 'collectionConfirmedAt',
                       'collectionConfirmationSource', 'canConfirmCollection', 'latestReceiptDate')
DISPLAY_FIELDS = (*CONFIRMATION_FIELDS, 'swissCgl', 'swissFacility', 'swissCase', 'originalDueDate', 'projectedDueDate',
                  'confirmationCutoff', 'fullPaymentRequired', 'paymentAllowed', 'paymentBlockedReason',
                  'reminderDate', 'statementNeedsRevision', 'statementDueDate', 'statementReference')


def objects(value):
    return [r for r in value if isinstance(r, dict)] if isinstance(value, list) else []


def is_swiss_facility(name):
    return ' '.join(str(name or '').split()).casefold() == SWISS_NAME.casefold()


def applies(payload):
    return (isinstance(payload, dict) and any(is_swiss_facility(r.get('name')) for r in objects(payload.get('reinsurers'))))


def case_payload(case, copy_payload=True):
    """Read the persisted Announce event; never infer a legacy endorsement from today.

    copy_payload=False（只讀的 Accounting GET）：只複製最上層，省掉整份 deepcopy；呼叫端不得修改巢狀內容。"""
    payload = (copy.deepcopy(case.payload) if copy_payload else dict(case.payload)) if isinstance(case.payload, dict) else {}
    if case.case_kind == 'endorsement':
        if case.announced_at:
            payload['endorsementAnnouncedAt'] = case.announced_at.isoformat()
        if case.parent_case_id:
            payload['parentTwRef'] = case.parent_case.tw_ref or payload.get('parentTwRef') or ''
    return payload


def real_date(value):
    try:
        return date.fromisoformat(value) if isinstance(value, str) and len(value) == 10 else None
    except ValueError:
        return None


def local_date(value):
    try:
        stamp = datetime.fromisoformat(value.replace('Z', '+00:00')) if isinstance(value, str) else value
        return stamp.astimezone(TAIPEI).date().isoformat() if isinstance(stamp, datetime) and stamp.tzinfo else ''
    except (ValueError, TypeError, OverflowError):
        return ''


def add_days(value, days):
    parsed = real_date(value)
    return (parsed + timedelta(days=days)).isoformat() if parsed else ''


def quarter(value):
    """Quarter-end cutoff -> next fixed 14th; November through January crosses years."""
    parsed = real_date(value)
    if not parsed:
        return ''
    year, month = parsed.year, parsed.month
    if month == 1:
        target = 2
    elif month <= 4:
        target = 5
    elif month <= 7:
        target = 8
    elif month <= 10:
        target = 11
    else:
        year, target = year + 1, 2
    return date(year, target, 14).isoformat()


def previous_quarter(value):
    parsed = real_date(value)
    if not parsed:
        return ''
    month = parsed.month - 3
    return date(parsed.year if month > 0 else parsed.year - 1, month if month > 0 else month + 12, 14).isoformat()


def cutoff(value):
    parsed = real_date(value)
    return (parsed.replace(day=1) - timedelta(days=1)).isoformat() if parsed else ''


def incoming_entries(payload, key):
    return [e for e in objects(payload.get('paymentEntries')) if e.get('scheduleKey') == key]


def fingerprint(payload, key):
    # Includes notes, dates, added records and reversals: every change requires re-confirmation.
    entries = incoming_entries(payload, key)
    facts = {'entries': entries, 'originalPremium': payload.get('originalPremium'),
             'reinsurers': [{k: v for k, v in r.items() if k not in ('settlementRef', 'clientKey')} for r in objects(payload.get('reinsurers'))], 'installments': payload.get('performanceInstallments')}
    return hashlib.sha256(json.dumps(facts, sort_keys=True, ensure_ascii=False, default=str).encode()).hexdigest()


def receipt_date(payload, key):
    entries = incoming_entries(payload, key)
    reversed_ids = {e.get('reversalOf') for e in entries if e.get('entryType') == 'reversal'}
    return max((e['paymentDate'] for e in entries if e.get('entryType') == 'payment'
                and not e.get('nonCash') and e.get('id') not in reversed_ids and real_date(e.get('paymentDate'))), default='')


def confirmation(payload, item):
    key = item['scheduleKey']
    state = (payload.get('swissAccounting') or {}).get('confirmations', {}).get(key)
    closed = abs(float(item.get('outstanding') or 0)) < .005
    if isinstance(state, dict):
        valid = (closed and state.get('confirmed') is True and state.get('fingerprint') == fingerprint(payload, key)
                 and bool(local_date(state.get('confirmedAt'))))
        return (local_date(state['confirmedAt']), state.get('source') or 'manual') if valid else ('', '')
    # An explicit historical reconciliation timestamp is evidence. Neither a receipt date
    # nor automatic cash totals alone substitute for historical confirmation.
    if closed:
        matches = [t for t in objects(payload.get('transactions')) if not t.get('reversed') and not t.get('isReversalEntry')
                   and str(t.get('legType') or '').startswith('Leg ' + ('1' if item['partyType'] == 'cedant' else '2'))
                   and (not t.get('installmentId') or t['installmentId'] == item['installmentId'])
                   and (item['partyType'] == 'cedant' or item['partyKey'] == 'r' + str(int(t.get('reinsurerIdx', -1)) + 1))]
        if matches and all(t.get('settlement') == 'settled' and local_date(t.get('settledAt')) for t in matches):
            latest = max(local_date(t['settledAt']) for t in matches)
            return latest, 'historical transaction reconciliation: ' + ', '.join(str(t.get('txNo')) for t in matches)
    return '', ''


def _state(payload):
    value = payload.get('swissAccounting')
    return value if isinstance(value, dict) else {}


def locked_due(payload, item):
    # Failed remittances retain their original period, including after bank reversal.
    return next((e['settlementDueDate'] for e in incoming_entries(payload, item['scheduleKey'])
                 if real_date(e.get('settlementDueDate')) and (not e.get('nonCash') or abs(item.get('outstanding', 0)) < .005)), '')


def apply_schedule(payload, items, now):
    from ..swiss_cgl import target, apply_schedule as cgl_schedule
    return cgl_schedule(payload, items, now) if target(payload) else apply_legacy_schedule(payload, items, now)


def apply_legacy_schedule(payload, items, now):
    if not applies(payload):
        return items
    today = local_date(now)
    by_key = {i['scheduleKey']: i for i in items}
    refund = bool(payload.get('parentTwRef') and float(payload.get('originalPremium') or 0) < 0)
    for item in items:
        item['swissCase'] = True
        is_swiss = item['partyType'] == 'reinsurer' and is_swiss_facility(
            objects(payload.get('reinsurers'))[int(item['partyKey'][1:]) - 1].get('name'))
        needs_confirmation = (not refund and item['partyType'] == 'cedant') or (refund and item['partyType'] == 'reinsurer')
        if needs_confirmation:
            confirmed, source = confirmation(payload, item)
            item.update(requiresCollectionConfirmation=True, collectionConfirmed=bool(confirmed),
                        collectionConfirmedAt=confirmed, collectionConfirmationSource=source,
                        canConfirmCollection=abs(item['outstanding']) < .005 and not confirmed,
                        latestReceiptDate=receipt_date(payload, item['scheduleKey']))
        if item['partyType'] == 'cedant':
            contract = add_days(item['baseDate'], 90)
            accounting = add_days(item['baseDate'], 80)
            item.update(partyName=str(payload.get('reinsured') or payload.get('reinsuredName') or payload.get('cedantName') or 'Cedant'), termsDays=90, dueDate=accounting, dueTime='', contractDueDate=contract,
                        accountingLeadDays=10, paymentRule='swiss_cedant_80_90', reminderDate=accounting)
        if is_swiss:
            cedant = by_key.get(item['installmentId'] + ':cedant', {})
            accounting = add_days(cedant.get('baseDate', ''), 90)
            original = quarter(accounting)
            if refund:
                original = max(previous_quarter(original), quarter(local_date(payload.get('endorsementAnnouncedAt'))))
                chosen = locked_due(payload, item) or original
            else:
                collected, _ = confirmation(payload, cedant) if cedant else ('', '')
                chosen = locked_due(payload, item) or max(original, quarter(receipt_date(payload, cedant.get('scheduleKey'))),
                                                         quarter(collected or today)) if original else ''
                item.update(collectionConfirmed=bool(collected), collectionConfirmedAt=collected,
                            paymentAllowed=bool(collected), paymentBlockedReason='' if collected else 'Confirm the entire Cedant installment as collected.')
            # Completed legacy payments keep their displayed dates and recorded periods.
            has_old_payment = not refund and abs(item['outstanding']) < .005 and abs(item['paid']) > .004 and not locked_due(payload, item)
            if not has_old_payment:
                item.update(dueDate=chosen, dueTime='', contractDueDate=chosen, termsDays=90,
                            paymentRule='swiss_quarterly_refund' if refund else 'swiss_quarterly_premium')
            item.update(swissFacility=True, originalDueDate=original, confirmationCutoff=cutoff(chosen),
                        projectedDueDate=chosen if not refund and not item.get('collectionConfirmed') else '',
                        fullPaymentRequired=not refund)
            statement = _state(payload).get('statements', {}).get(item['scheduleKey'], {})
            item.update(statementDueDate=statement.get('dueDate') or '', statementReference=statement.get('reference') or '',
                        statementNeedsRevision=False)
    if refund:
        required = [i for i in items if i['partyType'] == 'reinsurer' and i['amount'] < 0]
        ready = bool(required) and all(i.get('collectionConfirmed') for i in required)
        for item in items:
            if item['partyType'] == 'cedant' and item['amount'] < 0:
                item.update(paymentAllowed=ready, paymentBlockedReason='' if ready else 'Await collection and confirmation of every Reinsurer refund.',
                            fullPaymentRequired=True)
    for item in items:
        if item['partyType'] != 'cedant' and not item.get('swissFacility'):
            continue
        overdue_due = item['contractDueDate'] if item['partyType'] == 'cedant' else item['dueDate']
        item['status'] = ('settled' if abs(item['outstanding']) < .005 else 'pending_review' if not overdue_due
                          else 'overdue' if today > overdue_due else 'due_today' if today == overdue_due
                          else 'reminder' if item['partyType'] == 'cedant' and item['dueDate'] and today >= item['dueDate'] else 'upcoming')
    return items


def reset_after_changes(before, after, now):
    from ..property_original import enabled
    if enabled(after):return  # Automatic confirmations are persisted with the actual operation timestamp.
    if not applies(after):
        return
    state = after.setdefault('swissAccounting', {})
    confirmations = state.setdefault('confirmations', {})
    keys = {e.get('scheduleKey') for e in objects(before.get('paymentEntries')) + objects(after.get('paymentEntries'))}
    for key in keys:
        if key and fingerprint(before, key) != fingerprint(after, key):
            # Preserve confirmation behind completed Swiss payments; pending obligations
            # always require a fresh confirmation after receipt/clearance changes.
            old = confirmations.get(key) or {}
            confirmations[key] = {'confirmed': False, 'invalidatedAt': now, 'priorConfirmedAt': old.get('confirmedAt') or old.get('priorConfirmedAt')}


def payment_error(item, amount):
    if item.get('fullPaymentRequired') and abs(amount - abs(item['outstanding'])) >= .005:
        return 'Premium receipts and payments must cover the entire outstanding balance.'
    if not item.get('swissCase'):
        return ''
    if item.get('paymentAllowed') is False:
        return item.get('paymentBlockedReason') or 'Collection confirmation is required.'
    if item.get('fullPaymentRequired') and abs(amount - abs(item['outstanding'])) >= .005:
        return 'Pay the entire Swiss installment or Cedant refund in one allocation.'
    if item.get('swissFacility') and item.get('paymentDirection', 'payable') != 'receivable' and item.get('amount', 0) > 0 and not item.get('statementReference'):
        return 'Enter the Swiss settlement statement reference after Cedant settlement before recording payment.'
    return ''
