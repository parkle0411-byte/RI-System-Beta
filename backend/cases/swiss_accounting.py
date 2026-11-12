"""Manual Swiss statement references (same-policy premium offsets were retired; removed 2026-11-12)."""
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
    if action != 'mark_swiss_statement':   # 2026-11-12：其餘 Swiss 動作已退役（Accounting 回 410），這裡只處理結算清單參考號
        return _error(400, 'unsupported_action', 'Unsupported Accounting action.')
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
        return _error(400, 'swiss_scope_required', 'This action requires a Swiss Facility case.')
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
        state['statements'][key] = {'dueDate': item.get('contractDueDate') if item.get('swissCgl') else item['dueDate'], 'reference': reference, 'confirmedAt': now, 'confirmedBy': actor['id']}
    return view._save(request, body, case, payload, action, metadata)
