"""Complete missing contract days without reopening or changing booked amounts."""
import copy
from .calc.payment_terms import valid_terms
from .calc.swiss_facility import case_payload, is_swiss_facility
from .manual_reference import is_auw_reinsurer
from .allianz_accounting import is_allianz
from .great_american_accounting import target as ga_target


def complete_payment_terms(view, request, body):
    from .accounting_views import _error, _iso_now
    from ri_system.authz import has_permission, actor_from
    if not has_permission(request.ri_principal, 'cases.write'):
        return _error(403, 'permission_denied', 'Case editing access is required to complete contract days.')
    case = view._load_case_for_update(str(body.get('caseUid') or ''))
    if not case:
        return _error(404, 'case_not_found', 'Case not found.')
    error = view._status_error(case, 'updated')
    if error:
        return error
    if case.row_version != body.get('rowVersion'):
        return _error(409, 'version_conflict', 'Reload the current case before completing days.')
    days = valid_terms(body.get('days'))
    reason = str(body.get('reason') or '').strip()[:1000]
    if days is None or not reason:
        return _error(400, 'payment_terms_required', 'Enter independent days (integer >=15) and the completion reason.')
    payload = case_payload(case)
    party = str(body.get('partyKey') or '')
    installment = None
    if payload.get('installmentEnabled'):
        installment = next((i for i in payload.get('performanceInstallments', []) if i.get('id') == body.get('installmentId')), None)
        if installment is None:
            return _error(400, 'schedule_not_found', 'Select an existing installment.')
    if party == 'cedant':
        from .calc.swiss_facility import applies
        if applies(payload):
            return _error(409, 'fixed_terms_locked', 'Swiss Cedant terms are fixed at 90 days.')
        target, field = (installment if installment is not None else payload), 'paymentTermsDays'
    else:
        try:
            index = int(party[1:]) - 1
            row = payload['reinsurers'][index]
            if not party.startswith('r') or index < 0:
                raise ValueError()
        except (ValueError, KeyError, IndexError, TypeError):
            return _error(400, 'party_not_found', 'Select an existing reinsurer.')
        if ga_target(payload, row.get('name')):
            return _error(409, 'fixed_terms_locked', 'Great American Property uses fixed quarterly 90/75-day rules.')
        if is_auw_reinsurer(row.get('name')) or is_allianz(row.get('name')) or is_swiss_facility(row.get('name')):
            return _error(409, 'fixed_terms_locked', 'AUW, Allianz and Swiss fixed terms cannot be changed here.')
        target, field = ((installment.setdefault('reinsurerPaymentTerms', {}), party)
                         if installment is not None else (row, 'paymentTermsDays'))
    before = target.get(field)
    if valid_terms(before) is not None:
        return _error(409, 'existing_terms_locked', 'Only missing contract days may be completed; existing valid terms remain locked.')
    target[field] = days
    actor = actor_from(request.ri_principal)
    payload.setdefault('paymentTermsHistory', []).append({'installmentId': body.get('installmentId'),
        'partyKey': party, 'before': before, 'after': days, 'reason': reason,
        'changedAt': _iso_now(), 'changedBy': actor['id']})
    payload.setdefault('paymentEntries', [])
    return view._save(request, body, case, payload, 'payment_terms_completed', {'partyKey': party, 'reason': reason})
