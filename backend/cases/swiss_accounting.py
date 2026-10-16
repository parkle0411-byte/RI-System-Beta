"""Manual Swiss statement references and same-policy premium offsets."""
import copy
import uuid

from .calc.payment_terms import build_payment_schedule, taipei_date
from .calc.swiss_facility import applies, fingerprint, is_swiss_facility, objects, case_payload
from .cash_ledger import cents, amount
from .models import Case


def swiss_action(view, request, body):
    from .accounting_views import _can_edit, _error, _iso_now, _real_date
    from ri_system.authz import actor_from
    if not _can_edit(request.ri_principal):
        return _error(403, 'permission_denied', 'Accounting write access is required.')
    action = body['action']
    if action in ('confirm_swiss_collection', 'unconfirm_swiss_collection', 'record_swiss_clearance'):
        return _error(400, 'manual_transaction_workflow', 'Use individual transaction settlement. Bank fees and shortfalls are handled outside this system.')
    if action in ('record_swiss_offset', 'record_premium_offset'):
        return _offset(view, request, body)
    case = view._load_case_for_update(str(body.get('caseUid') or ''))
    if not case:
        return _error(404, 'case_not_found', 'Case not found.')
    locked = view._status_error(case, 'updated')
    if locked:
        return locked
    if case.row_version != body.get('rowVersion'):
        return _error(409, 'version_conflict', 'This case changed. Refresh Accounting and try again.')
    payload = case_payload(case)
    if not applies(payload):
        return _error(400, 'swiss_scope_required', 'This action requires Swiss Facility Property.')
    item = next((i for i in build_payment_schedule(payload)['items'] if i['scheduleKey'] == body.get('scheduleKey')), None)
    if not item:
        return _error(400, 'schedule_not_found', 'The selected installment and party no longer exist.')
    actor = actor_from(request.ri_principal)
    now = _iso_now()
    payload.setdefault('paymentEntries', [])
    state = payload.get('swissAccounting')
    if not isinstance(state, dict):
        state = {}; payload['swissAccounting'] = state
    key = item['scheduleKey']
    metadata = {'operation': action, 'scheduleKey': key}
    if action == 'mark_swiss_statement':
        if not item.get('swissFacility') or item['amount'] <= 0 or not item.get('dueDate'):
            return _error(400, 'statement_not_allowed', 'Select a Swiss premium payable with a settlement date.')
        if not item.get('collectionConfirmed'):
            return _error(409, 'cedant_settlement_required', 'Settle the entire Cedant installment before entering the Swiss statement reference.')
        reference = str(body.get('reference') or '').strip()[:200]
        if not reference:
            return _error(400, 'statement_reference_required', 'Enter the settlement statement reference.')
        state.setdefault('statementHistory', []).append({'scheduleKey': key, **state.setdefault('statements', {}).get(key, {}), 'changedAt': now})
        state['statements'][key] = {'dueDate': item['dueDate'], 'reference': reference, 'confirmedAt': now, 'confirmedBy': actor['id']}
    return view._save(request, body, case, payload, action, metadata)


def _entry(item, value, payment_date, now, actor, kind, note):
    return {'id': str(uuid.uuid4()), 'entryType': 'payment', 'entryKind': kind, 'nonCash': True,
            'scheduleKey': item['scheduleKey'], 'installmentId': item['installmentId'], 'installmentLabel': item['installmentLabel'],
            'partyType': item['partyType'], 'partyName': item['partyName'],
            'amount': amount(value * (-1 if item['amount'] < 0 else 1)), 'paymentDate': payment_date,
            'note': note, 'createdAt': now, 'createdBy': actor['id'], 'createdByName': actor['name']}


def _offset(view, request, body):
    from .accounting_views import _error, _iso_now, _real_date
    from ri_system.authz import actor_from
    try:
        original_uid = str(uuid.UUID(body['originalCaseUid']))
        refund_uid = str(uuid.UUID(body['refundCaseUid']))
        value = cents(body['amount'])
        if value <= 0 or not _real_date(body.get('paymentDate')) or original_uid == refund_uid:
            raise ValueError()
    except (ValueError, TypeError, KeyError, AttributeError):
        return _error(400, 'invalid_offset', 'Select the original policy, refund endorsement, date and a positive amount.')
    cases = {str(c.case_uid): c for c in Case.objects.select_for_update().filter(case_uid__in=[original_uid, refund_uid]).order_by('id')}
    original, refund = cases.get(original_uid), cases.get(refund_uid)
    if not original or not refund or any(c.recycled_at or c.is_archived for c in cases.values()):
        return _error(404, 'case_not_found', 'Case not found.')
    if any(c.status not in ('posted', 'closed') for c in cases.values()):
        return _error(409, 'accounting_status_locked', 'Only announced or confirmed policies can be offset.')
    if original.row_version != body.get('originalRowVersion') or refund.row_version != body.get('refundRowVersion'):
        return _error(409, 'version_conflict', 'A selected case changed. Refresh Accounting and try again.')
    if original.parent_case_id or refund.parent_case_id != original.pk or refund.case_kind != 'endorsement':
        return _error(400, 'same_policy_required', 'Offset only the original policy and its own refund endorsement.')
    if original.currency != refund.currency:
        return _error(400, 'offset_scope_required', 'Both cases must use the same currency.')
    schedules = [build_payment_schedule(case_payload(c))['items'] for c in [original, refund]]
    selected = [next((i for i in items if i['scheduleKey'] == key), None) for items, key in zip(schedules, [body.get('originalKey'), body.get('refundKey')])]
    if not all(selected):
        return _error(400, 'schedule_not_found', 'Select an existing premium and corresponding refund.')
    premium, returned = selected
    from .cash_ledger import _matches
    for case, item in zip([original, refund], selected):
        posted = [t for t in objects(case.payload.get('transactions'))
                  if t.get('source') != 'claim' and not t.get('reversed') and not t.get('isReversalEntry')]
        if not any(_matches(item, t) for t in posted):
            return _error(400, 'posted_obligation_required', 'Close Production and create both premium obligations before offsetting.')
    if (premium['amount'] <= 0 or returned['amount'] >= 0 or premium['partyType'] != returned['partyType']
            or premium['partyName'].strip().casefold() != returned['partyName'].strip().casefold()):
        return _error(400, 'invalid_offset_pair', 'Select matching Cedant entries or matching reinsurer entries.')
    swiss_dates = []
    if applies(original.payload) or applies(refund.payload):
        if not (applies(original.payload) and applies(refund.payload)):
            return _error(400, 'offset_scope_required', 'Swiss offsets require two Swiss policies.')
        for items, item in zip(schedules, selected):
            dates = {i['dueDate'] for i in items if i.get('swissFacility') and i['installmentId'] == item['installmentId']}
            if len(dates) != 1 or not next(iter(dates)):
                return _error(400, 'swiss_period_required', 'Both entries require one identifiable Swiss settlement period.')
            swiss_dates.append(next(iter(dates)))
        if swiss_dates[0] != swiss_dates[1]:
            return _error(400, 'cross_period_offset', 'Receive and pay cross-period premiums and refunds separately.')
    else:
        swiss_dates = ['', '']
    if not premium.get('contractDueDate') or not returned.get('contractDueDate'):
        return _error(400, 'terms_pending_review', 'Complete the independent payment terms before offsetting.')
    # Both-ended Swiss netting must never bypass the collection prerequisites.
    if value != abs(cents(returned['outstanding'])) or value > abs(cents(premium['outstanding'])):
        return _error(400, 'invalid_offset_amount', 'Offset the entire refund balance without exceeding the original premium balance.')
    if premium['partyType'] == 'reinsurer' and premium.get('paymentAllowed') is False:
        return _error(400, 'collection_confirmation_required', premium['paymentBlockedReason'])
    # A Cedant refund is released only after every Reinsurer refund is confirmed collected;
    # netting it against the original premium must not bypass that gate.
    if returned.get('paymentAllowed') is False:
        return _error(400, 'refund_collection_required', returned.get('paymentBlockedReason') or
                      'Await collection and confirmation of every Reinsurer refund.')
    if premium.get('statementNeedsRevision'):
        return _error(400, 'statement_revision_required', 'Revise the settlement statement before offsetting.')
    actor = actor_from(request.ri_principal)
    now, offset_id = _iso_now(), str(uuid.uuid4())
    for case, item, other in zip([original, refund], selected, [refund, original]):
        payload = case_payload(case)
        entry = _entry(item, value, body['paymentDate'], now, actor, 'offset', str(body.get('note') or 'Same-policy premium/refund offset')[:1000])
        entry.update(offsetId=offset_id, offsetCaseUid=str(other.case_uid), settlementDueDate=swiss_dates[0])
        payload.setdefault('paymentEntries', []).append(entry)
        view._save(request, {'rowVersion': case.row_version}, case, payload, 'record_swiss_offset', {'offsetId': offset_id})
    from rest_framework.response import Response
    return Response({'ok': True, 'offsetId': offset_id, 'cases': [{'caseUid': str(c.case_uid), 'rowVersion': c.row_version} for c in [original, refund]]})
