"""Great American Singapore Facility Property: owner-confirmed quarterly/manual rules."""
import re
from datetime import date
from .allianz_accounting import objects

NAME = 'Great American Insurance Company, Singapore Branch (Facility)'
FIELDS = ('greatAmericanFacility', 'greatAmericanCase', 'offsetAllowed', 'cedantReceiptConfirmed',
          'paymentAllowed', 'paymentBlockedReason', 'sourceBaseDate', 'accountingLeadDays')


def is_great_american(name):
    return ' '.join(str(name or '').split()).casefold() == NAME.casefold()


def target(payload, name):
    return str(payload.get('classOfBusiness') or '').strip().casefold() == 'property' and is_great_american(name)


def applies(payload):
    return any(target(payload, r.get('name')) for r in objects(payload.get('reinsurers')))


def payment_dates(payload, installment):
    from .calc.payment_terms import endorsement_base_date, add_calendar_days
    source = installment.get('baseDate', '')
    if payload.get('parentTwRef'):
        source = endorsement_base_date(payload)
    try:
        value = date.fromisoformat(source)
        month = ((value.month - 1) // 3 + 1) * 3
        base = date(value.year, month, 31 if month in (3, 12) else 30).isoformat()
    except (ValueError, TypeError):
        base = ''
    return source, base, add_calendar_days(base, 90) if base else '', add_calendar_days(base, 80) if base else ''


def status(due, reminder, confirmed, cash_remaining, today):
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
    return 'pending_confirmation' if not cash_remaining else 'upcoming'


def apply_schedules(payload, items, now):
    if applies(payload):
        for item in items:
            item.update(greatAmericanCase=True, offsetAllowed=False)
    return items


def claim_is_great_american(payload, tx):
    if tx.get('source') != 'claim':
        return False
    split = tx.get('splitSource')
    source = split if isinstance(split, dict) else payload
    # A claim can use a historical endorsement's security; never infer identity
    # from a broker/payee name or a client-supplied claim marker.
    class_name = source.get('classOfBusiness', payload.get('classOfBusiness'))
    if str(class_name or '').strip().casefold() != 'property':
        return False
    rows = objects(source.get('reinsurers'))
    match = re.search(r'-R([1-9][0-9]*)-T[12]$', str(tx.get('txNo') or '')) if isinstance(split, dict) else None
    index = int(match[1]) - 1 if match else tx.get('reinsurerIdx')
    return (isinstance(index, (int, float)) and not isinstance(index, bool) and index >= 0
            and int(index) == index and index < len(rows) and is_great_american(rows[int(index)].get('name')))


def apply_details(payload, details, schedule, now):
    by_key = {r['scheduleKey']: r for r in schedule}
    for no, detail in details.items():
        if detail['_source'] == 'premium':
            rows = [by_key[p['scheduleKey']] for p in detail.get('cashParts', []) if p['scheduleKey'] in by_key]
            target = [r for r in rows if r.get('greatAmericanFacility')]
            if target or (applies(payload) and detail['partyType'] == 'cedant'):
                detail.update(greatAmericanCase=True, offsetAllowed=False)
            if target:
                detail['greatAmericanFacility'] = True
                if detail['amount'] > 0:
                    detail['canCancelSettlement'] = False
        else:
            if applies(payload):
                detail['greatAmericanCase'] = True
            if not claim_is_great_american(payload, detail['_tx']):
                continue
            detail['greatAmericanCaseClaim'] = True
            if detail['partyType'] == 'reinsurer' and detail['paymentDirection'] == 'receivable':
                detail.update(greatAmericanClaim=True, trackingHistory=[h for h in objects(payload.get('greatAmericanClaimTracking')) if h.get('txNo') == no])
    return details


def collection_change_error(before, after):
    from .payment_policy import collection_change_error as check
    return check(before, after)


def registration_scope(payload, tx, detail):
    """One business case/period; underlying split legs keep individual records."""
    if tx.get('source') == 'claim':
        if tx.get('claimId') is None or tx.get('paymentId') is None:
            return None
        return ('claim', str(tx.get('claimId')), str(tx.get('paymentId')))
    if detail['partyType'] == 'cedant' and detail['amount'] < 0:
        # The confirmed full-endorsement refund rule remains one obligation.
        return ('return-endorsement',)
    from .calc.payment_terms import build_payment_schedule
    periods = {i['scheduleKey']: i['installmentId'] for i in build_payment_schedule(payload)['items']}
    matched = {periods[p['scheduleKey']] for p in detail.get('cashParts', []) if p['scheduleKey'] in periods}
    return ('premium', next(iter(matched))) if len(matched) == 1 else None


def allocation_error(chosen, parsed, cases, details):
    from .calc.swiss_facility import case_payload
    payloads = {uid: case_payload(cases[uid]) for uid in {r['caseUid'] for r in parsed}}
    if not (any(applies(p) for p in payloads.values()) or
            any(d.get('greatAmericanFacility') or d.get('greatAmericanCase') or d.get('greatAmericanCaseClaim') for d in chosen)):
        return ''
    if len(payloads) != 1:
        return 'Record Great American receipts/payments one case at a time. The external system reference may be reused.'
    scopes = set()
    for row, detail in zip(parsed, chosen):
        payload = payloads[row['caseUid']]
        tx = next(t for t in objects(payload.get('transactions')) if t.get('txNo') == row['txNo'])
        scopes.add(registration_scope(payload, tx, detail))
    if None in scopes or len(scopes) != 1:
        return 'Record one installment or claim request at a time; review any legacy transaction covering several periods.'
    sources = {next(t.get('source', 'premium') for t in objects(cases[r['caseUid']].payload.get('transactions')) if t.get('txNo') == r['txNo']) for r in parsed}
    if len(sources) > 1:
        return 'Record Great American claims separately from premiums and refunds.'
    # Each return endorsement is recorded as one full Cedant refund,
    # even when its stored T1 obligation consists of several reinsurer/split legs.
    for uid in {r['caseUid'] for r, d in zip(parsed, chosen) if d.get('greatAmericanCase') and d['partyType'] == 'cedant' and d['amount'] < 0}:
        expected = {no: abs(d['outstanding']) for no, d in details[uid].items()
                    if d.get('greatAmericanCase') and d['partyType'] == 'cedant' and d['amount'] < 0 and abs(d['outstanding']) > .004}
        selected = {r['txNo']: r['value'] / 100 for r in parsed if r['caseUid'] == uid}
        if any(abs(selected.get(no, 0) - value) > .004 for no, value in expected.items()):
            return 'Record the entire Cedant return endorsement as one full refund; partial refunds are not allowed.'
    return ''


def record_followup(view, request, body):
    from .accounting_views import _can_edit, _error, _iso_now
    from .calc.swiss_facility import case_payload
    from .cash_ledger import transaction_details
    from ri_system.authz import actor_from
    if not _can_edit(request.ri_principal):
        return _error(403, 'permission_denied', 'Accounting write access is required.')
    case = view._load_case_for_update(str(body.get('caseUid') or ''))
    if not case:
        return _error(404, 'case_not_found', 'Case not found.')
    if case.status not in ('posted', 'closed', 'reversed') or case.is_archived or case.recycled_at:
        return _error(409, 'accounting_status_locked', 'Select an active announced claim obligation.')
    if case.row_version != body.get('rowVersion'):
        return _error(409, 'version_conflict', 'Refresh Accounting before recording follow-up.')
    no = body.get('txNo')
    if not isinstance(no, str):
        return _error(400, 'invalid_transaction', 'Select one claim receivable.')
    payload = case_payload(case)
    detail = transaction_details(payload).get(no, {})
    tx = next((t for t in objects(payload.get('transactions')) if t.get('txNo') == no), {})
    if not detail.get('greatAmericanClaim') or tx.get('reversed') or tx.get('isReversalEntry') or abs(detail.get('outstanding', 0)) < .005:
        return _error(400, 'claim_followup_not_allowed', 'Select an outstanding Great American claim receivable.')
    note = str(body.get('note') or '').strip()[:1000]
    if not note:
        return _error(400, 'followup_note_required', 'Enter the follow-up record.')
    actor = actor_from(request.ri_principal)
    payload.setdefault('greatAmericanClaimTracking', []).append({'txNo': no, 'recordedAt': _iso_now(),
        'recordedBy': actor['id'], 'recordedByName': actor['name'], 'note': note})
    payload.setdefault('paymentEntries', [])
    return view._save(request, body, case, payload, 'record_great_american_claim_followup', {'txNo': no})
