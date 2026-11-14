"""Loss history derived from a policy-period Claim, without rewriting its books."""
from .calc.accounting import number_or_zero
from .calc.jsnum import money
from .claim_currency import claim_currency


def claim_loss_rows(payload, tw_ref='', case_uid=''):
    rows = []
    for claim in payload.get('claims') or []:
        if not isinstance(claim, dict):
            continue
        obligations = claim.get('payments') if isinstance(claim.get('payments'), list) else []
        total = number_or_zero(claim.get('outstandingReserve')) + sum(number_or_zero(row.get('amount')) for row in obligations if isinstance(row, dict))
        rows.append({
            'source': 'claim', 'sourceCaseUid': str(case_uid), 'sourceTwRef': str(tw_ref or ''),
            'claimId': claim.get('id'), 'date': claim.get('dateOfLoss') or '',
            'cause': claim.get('causeOfLoss') or '', 'currency': claim_currency(payload, claim),
            'lossPaid': max(0, money(total)),
        })
    return rows


def renewal_claim_snapshots(root_payload, root_tw_ref, root_case_uid):
    """Take independent renewal snapshots of the source policy's current claims."""
    return [{**row, 'source': 'claimSnapshot', 'snapshotModified': False,
             'sourceBaseline': {'date': row['date'], 'cause': row['cause']}, 'sync': {}}
            for row in claim_loss_rows(root_payload, root_tw_ref, root_case_uid)]


def plan_snapshot_sync(snapshot, updates, source_claim, *, reason=''):
    """Plan edits without overwriting a concurrently changed source Claim.

    The caller persists the snapshot and the returned source patch under row locks.
    A missing source or a field-level conflict leaves the edited snapshot pending.
    """
    import copy
    result = copy.deepcopy(snapshot)
    patch = {}
    baseline = result.setdefault('sourceBaseline', {})
    sync = result.setdefault('sync', {})
    for field, target in (('date', 'dateOfLoss'), ('cause', 'causeOfLoss')):
        if field not in updates or updates[field] == result.get(field):
            continue
        desired = str(updates[field] or '').strip()
        if field == 'date' and not str(reason or '').strip():
            raise ValueError('Enter the reason for changing the Date of Loss.')
        base = baseline.get(field, result.get(field) or '')
        result[field] = desired
        result['snapshotModified'] = True
        if not isinstance(source_claim, dict):
            sync[field] = {'state': 'pending', 'desired': desired, 'base': base, 'message': 'The source Claim is unavailable.', 'reason': reason if field == 'date' else ''}
        elif str(source_claim.get(target) or '') != str(base or ''):
            sync[field] = {'state': 'conflict', 'desired': desired, 'base': base,
                           'observed': str(source_claim.get(target) or ''), 'reason': reason if field == 'date' else ''}
        else:
            patch[target] = desired
            baseline[field] = desired
            sync[field] = {'state': 'synced'}
    for field in ('lossPaid', 'currency'):
        if field in updates and updates[field] != result.get(field):
            result[field] = updates[field]
            result['snapshotModified'] = True
    return result, patch


def retry_snapshot_sync(snapshot, source_claim, *, decisions=None):
    """Retry pending fields or resolve conflicts using the value the user saw."""
    import copy
    result = copy.deepcopy(snapshot)
    patch = {}
    decisions = decisions if isinstance(decisions, dict) else {}
    baseline, sync = result.setdefault('sourceBaseline', {}), result.setdefault('sync', {})
    for field, target in (('date', 'dateOfLoss'), ('cause', 'causeOfLoss')):
        pending = sync.get(field)
        if not isinstance(pending, dict) or pending.get('state') not in ('pending', 'conflict'):
            continue
        decision = decisions.get(field) if isinstance(decisions.get(field), dict) else {}
        if decision.get('choice') == 'keep_source':
            sync[field] = {**pending, 'state': 'cancelled'}
            continue
        if not isinstance(source_claim, dict):
            sync[field] = {**pending, 'state': 'pending', 'message': 'The source Claim is unavailable.'}
            continue
        current = str(source_claim.get(target) or '')
        base = str(pending.get('base') or '')
        force = decision.get('choice') == 'use_renewal' and 'observed' in decision and str(decision.get('observed') or '') == current
        if current != base and not force:
            sync[field] = {**pending, 'state': 'conflict', 'observed': current}
            continue
        desired = str(pending.get('desired') or '')
        patch[target] = desired
        baseline[field] = desired
        sync[field] = {'state': 'synced'}
    return result, patch
