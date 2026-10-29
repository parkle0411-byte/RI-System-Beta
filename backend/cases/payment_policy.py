"""Owner-confirmed cash/settlement rules, 2026-10-20; pure read calculations."""
import re
from .allianz_accounting import target as allianz_target, objects
from .great_american_accounting import target as ga_target
from .qbe_accounting import target as qbe_target
from .manual_reference import is_auw_reinsurer


def kind(payload, name):
    if is_auw_reinsurer(name):
        return 'auw'
    if allianz_target(payload, name):
        return 'allianz'
    if qbe_target(payload, name):
        return 'qbe'
    if ga_target(payload, name):
        return 'great_american'
    # Preserve Swiss, other Facility and PWS rules outside the reviewed scope.
    if str(name or '').strip() and not re.search(r'facility|\bpws\b', str(name), re.I):
        return 'ordinary'
    return ''


def case_scope(payload):
    return any(kind(payload, r.get('name')) for r in objects(payload.get('reinsurers')))


def row_kind(payload, row):
    if row.get('partyType') == 'cedant':
        return 'cedant' if case_scope(payload) else ''
    match = re.fullmatch(r'r([1-9][0-9]*)', str(row.get('partyKey') or ''))
    rows = objects(payload.get('reinsurers'))
    index = int(match[1])-1 if match else -1
    return kind(payload, rows[index].get('name')) if 0 <= index < len(rows) else ''


def actual_cash(payload, row):
    from .calc.accounting import number_or_zero
    paid = sum(number_or_zero(e.get('amount')) * (-1 if e.get('entryType') == 'reversal' else 1)
               for e in objects(payload.get('paymentEntries'))
               if e.get('scheduleKey') == row['scheduleKey'] and e.get('entryType') in ('payment', 'reversal')
               and not e.get('nonCash'))
    return paid * (-1 if row['amount'] < 0 else 1) + .004 >= abs(row['amount'])


def cleared_receipt(payload, row):
    return abs(row['outstanding']) < .005 and actual_cash(payload, row) and bool(row.get('manualSettlementConfirmed'))


def payment_status(due, reminder, confirmed, outstanding, today):
    if confirmed:
        return 'settled'
    if not due:
        return 'pending_review'
    if today > due:
        return 'overdue'
    if today == due:
        return 'due_today'
    if reminder and today >= reminder:
        return 'reminder'
    return 'pending_confirmation' if abs(outstanding) < .005 else 'upcoming'


def apply_schedules(payload, items, now):
    from .calc.payment_terms import taipei_date
    from .calc.swiss_facility import applies as swiss_case
    today = taipei_date(now)
    refund_scope = case_scope(payload) and not swiss_case(payload)
    refunds = [r for r in items if r['partyType'] == 'reinsurer' and r['amount'] < 0]
    refunds_ready = all(cleared_receipt(payload, r) for r in refunds)
    for item in items:
        scope = row_kind(payload, item)
        if not scope:
            continue
        item['fullPaymentRequired'] = True
        if scope in ('ordinary', 'auw', 'allianz', 'great_american', 'qbe') and item['amount'] > 0:
            cedants = [r for r in items if r['partyType'] == 'cedant' and r['installmentId'] == item['installmentId']]
            ready = bool(cedants) and all(r['amount'] >= 0 and cleared_receipt(payload, r) for r in cedants)
            item.update(cedantReceiptConfirmed=ready, paymentAllowed=ready,
                        paymentBlockedReason='' if ready else 'Receive the entire Cedant installment, including every reinsurer share, and individually settle its transactions before recording this premium payment.')
        if item['partyType'] == 'reinsurer' and item['amount'] < 0:
            item['offsetAllowed'] = False
        if refund_scope and item['partyType'] == 'cedant' and item['amount'] < 0:
            item.update(paymentAllowed=refunds_ready, paymentBlockedReason='' if refunds_ready else
                        'Record full receipts and individually settle every reinsurer refund before refunding the entire Cedant endorsement.')
        payable = (item['partyType'] == 'reinsurer' and item['amount'] > 0) or (item['partyType'] == 'cedant' and item['amount'] < 0)
        if payable:
            item['status'] = payment_status(item.get('contractDueDate'), item.get('dueDate'),
                                             item.get('manualSettlementConfirmed'), item['outstanding'], today)
    return items


def claim_source(payload, tx):
    source = tx.get('splitSource')
    source = source if isinstance(source, dict) else payload
    match = re.search(r'-R([1-9][0-9]*)-T[12]$', str(tx.get('txNo') or '')) if source is not payload else None
    index = int(match[1])-1 if match else tx.get('reinsurerIdx')
    rows = objects(source.get('reinsurers'))
    return source, rows[int(index)].get('name') if isinstance(index, (int, float)) and not isinstance(index, bool) and int(index) == index and 0 <= index < len(rows) else tx.get('reinsurer')


def claim_created_at(payload, tx):
    from .calc.swiss_facility import local_date
    payment = next((p for c in objects(payload.get('claims')) if c.get('id') == tx.get('claimId')
                    for p in objects(c.get('payments')) if p.get('id') == tx.get('paymentId')), {})
    for value in (tx.get('createdAt'), payment.get('createdAt')):
        if local_date(value):
            return value
    return ''


def apply_details(payload, details, schedule, now):
    from .calc.payment_terms import taipei_date, add_calendar_days, days_between_dates, _status_for
    from .calc.swiss_facility import local_date
    today = taipei_date(now)
    by_key = {r['scheduleKey']: r for r in schedule}
    for no, detail in details.items():
        if detail['_historic']:
            continue
        tx = detail['_tx']
        if detail['_source'] == 'premium':
            rows = [by_key[p['scheduleKey']] for p in detail.get('cashParts', []) if p['scheduleKey'] in by_key]
            covered = [r for r in rows if row_kind(payload, r)]
            if not covered:
                continue
            detail['fullPaymentRequired'] = True
            if detail['partyType'] == 'cedant' and detail['amount'] < 0:
                detail['refundWholeEndorsement'] = True
            detail.update(paymentAllowed=all(r.get('paymentAllowed', True) for r in covered),
                          paymentBlockedReason=next((r['paymentBlockedReason'] for r in covered if r.get('paymentBlockedReason')), ''))
            if detail['paymentDirection'] == 'payable':
                detail['paymentStatus'] = payment_status(detail.get('contractDueDate'), detail.get('dueDate'),
                    detail.get('manualSettlementConfirmed'), detail['outstanding'], today)
                detail['paymentCompletionRequired'] = True
            continue
        if detail.get('qbeLegacyCompleted'):
            continue
        source, name = claim_source(payload, tx)
        if not kind({**payload, **source}, name):
            continue
        stamp = claim_created_at(payload, tx)
        base = local_date(stamp)
        due = add_calendar_days(base, 15) if base else tx.get('dueDate', '')
        first = add_calendar_days(due, -7) if due else ''
        remaining = abs(detail['outstanding']) > .004
        elapsed = days_between_dates(due, today) if due else None
        next_day = first if first and today <= first else due if due and today <= due else add_calendar_days(due, 7 * max(1, ((elapsed or 0)+6)//7)) if due else ''
        tracking = remaining and bool(due) and (today == first or today == due or (elapsed is not None and elapsed > 0 and elapsed % 7 == 0))
        status = _status_for(due, abs(detail['outstanding']), abs(detail['paid']), today, now)
        if status == 'upcoming' and first and today >= first:
            status = 'reminder'
        if not remaining:
            status = 'settled' if detail.get('manualSettlementConfirmed') else 'pending_confirmation'
        detail.update(paymentRule='claim_created_15', claimCreatedAt=stamp, baseDate=base,
                      dueDate=due, contractDueDate=due, reminderDate=first, nextTrackingDate=next_day if remaining else '',
                      trackingDue=bool(tracking), paymentStatus=status)
        if not due:
            detail['canRecord'] = False
    return details


def collection_change_error(before, after):
    from .calc.payment_terms import build_payment_schedule
    prior = {r['scheduleKey']: r for r in build_payment_schedule(before)['items']}
    for item in build_payment_schedule(after)['items']:
        scope = row_kind(after, item)
        guarded = scope in ('ordinary', 'auw', 'allianz', 'great_american', 'qbe') and item['amount'] > 0 or scope == 'cedant' and item['amount'] < 0
        if guarded and abs(item['paid']) > .004 and item.get('paymentAllowed') is False:
            old = prior.get(item['scheduleKey'], {})
            if old.get('paymentAllowed') or abs(item['paid']) > abs(old.get('paid', 0)) + .004:
                # 2026-10-21：優先顯示具體原因（例如「先收齊並銷帳所有再保人退款」），沒有才用通用說明
                return item.get('paymentBlockedReason') or 'Full cash receipts and individual manual settlement must remain valid while the corresponding premium payment or Cedant refund is recorded.'
    return ''


def allocation_error(parsed, chosen, details):
    for uid in {r['caseUid'] for r, d in zip(parsed, chosen) if d.get('refundWholeEndorsement')}:
        expected = {no: abs(d['outstanding']) for no, d in details[uid].items()
                    if d.get('refundWholeEndorsement') and abs(d['outstanding']) > .004}
        selected = {r['txNo']: r['value']/100 for r in parsed if r['caseUid'] == uid}
        if any(abs(selected.get(no, 0)-value) > .004 for no, value in expected.items()):
            return 'Select every Cedant refund transaction and record this endorsement refund in full in one remittance.'
    return ''
