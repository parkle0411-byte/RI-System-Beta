"""Cash-only multi-currency receipts/payments with independent item outcomes.

The Accounting view owns PRODUCTION_SOURCES and an outer transaction. Each
allocation has a savepoint; accepted allocations in one currency/direction share
one immutable registration. A retry creates registrations only for new successes.
JSON entry keys provide idempotency without rewriting old entries or schema.
"""
import hashlib
import json
import uuid

from django.db import IntegrityError, transaction
from rest_framework.response import Response

from .cash_ledger import amount, cents, objects, transaction_details


def _uuid(value):
    return isinstance(value, str) and str(uuid.UUID(value)) == value


def _signature(actor, body, row, value):
    fields = [str(actor['id']), row['caseUid'], row['txNo'], value, body['paymentDate'],
              str(body.get('reference') or '').strip(), str(body.get('note') or '').strip(),
              str(body.get('replacementOfBatchId') or '')]
    return hashlib.sha256(json.dumps(fields, ensure_ascii=False, separators=(',', ':')).encode()).hexdigest()


def register_accounts(view, request, body):
    from .accounting_views import _can_edit, _real_date
    from .finance_workflow import counterparty, fail, register_cash_group
    from .models import Case
    from legacy.models import LegacyTransaction
    from legacy.ledger import locked_facades, FinanceFacade
    from ri_system.authz import actor_from

    if not _can_edit(request.ri_principal):
        return fail('permission_denied', 'Finance access is required.', 403)
    reference = str(body.get('reference') or '').strip()
    note = str(body.get('note') or '').strip()
    if not _real_date(body.get('paymentDate')) or not (reference or note) or len(reference) > 200 or len(note) > 1000:
        return fail('payment_details_required', 'Enter a valid date and an Accounting Dept. Ref. or note.', 400)
    allocations = body.get('allocations')
    try:
        if not _uuid(body.get('cashSubmissionId')) or not isinstance(allocations, list) or not 1 <= len(allocations) <= 2000:
            raise ValueError()
        if any(not isinstance(row, dict) or not _uuid(row.get('cashItemId')) or not isinstance(row.get('caseUid'), str) or not isinstance(row.get('txNo'), str) for row in allocations):
            raise ValueError()
        if len({row['cashItemId'] for row in allocations}) != len(allocations):
            raise ValueError()
        keys = [(str(row.get('caseUid')), str(row.get('txNo'))) for row in allocations]
        if len(set(keys)) != len(keys):
            raise ValueError()
    except (ValueError, TypeError, AttributeError):
        return fail('invalid_cash_request', 'Select each account once with valid submission and item identifiers (maximum 2000 accounts).', 400)

    actor = actor_from(request.ri_principal)
    submission_id = body['cashSubmissionId']
    # One read covers retries even when the caller no longer sends successful rows.
    prior = {}
    previous = [(str(case.case_uid), case.payload.get('paymentEntries')) for case in
                Case.objects.filter(payload__paymentEntries__contains=[{'cashSubmissionId': submission_id}]).only('case_uid', 'payload')]
    previous.extend((str(record.uid), record.financial.get('paymentEntries')) for record in
                    LegacyTransaction.objects.filter(historical=False, financial__paymentEntries__contains=[{'cashSubmissionId': submission_id}]).only('uid', 'financial'))
    for uid, entries in previous:
        for entry in objects(entries):
            if entry.get('entryType') == 'payment' and entry.get('cashSubmissionId') == submission_id:
                key = entry.get('cashItemId')
                if key:
                    prior.setdefault(key, (uid, entry))
    valid_uids = set()
    for row in allocations:
        try:
            if _uuid(row.get('caseUid')):
                valid_uids.add(row['caseUid'])
        except (ValueError, TypeError, AttributeError):
            pass
    cases = {str(case.case_uid): case for case in Case.objects.select_for_update().filter(case_uid__in=valid_uids).order_by('id')}
    cases.update(locked_facades(valid_uids - set(cases)))
    initial_versions = {uid: case.row_version for uid, case in cases.items()}

    def refresh_case(case):
        if getattr(case, 'legacy', False):
            case.record.refresh_from_db()
            refreshed = FinanceFacade(case.record)
            cases[str(refreshed.case_uid)] = refreshed
            return refreshed
        case.refresh_from_db()
        return case
    # Failed-only retries must stay with the original submission counterparty,
    # even though successful allocations are deliberately omitted by the UI.
    scope = next((' '.join(str(entry.get('partyName') or '').split()).casefold()
                  for _, entry in prior.values() if entry.get('partyName')), None)
    batches = {}; outcomes = []
    # Receipts are checked before payments. Independent failures never roll back valid receipts.
    def safe_detail(case, no):
        if case is None:
            return {}
        from .data_integrity import financial_issues
        if not getattr(case, 'legacy', False) and financial_issues(case.payload):
            return {}
        try:
            return transaction_details(case.payload).get(no, {})
        except (ValueError, TypeError, KeyError, OverflowError):
            return {}

    pending = []
    for index, row in enumerate(allocations):
        case = cases.get(row.get('caseUid'))
        d = safe_detail(case, row.get('txNo'))
        existing = prior.get(row['cashItemId'])
        party_name = existing[1].get('partyName') if existing else d.get('partyName')
        party_key = ' '.join(str(party_name or '').split()).casefold()
        if scope is None and party_key:
            scope = party_key
        side = existing[1].get('paymentDirection') if existing else d.get('paymentDirection')
        pending.append((side == 'payable', index, row, party_key))
    for _, index, row, party_key in sorted(pending, key=lambda item: (item[0], item[1])):
        uid, no = row.get('caseUid'), row.get('txNo')
        result = {'index': index, 'cashItemId': row['cashItemId'], 'caseUid': uid, 'txNo': no, 'status': 'failed'}
        outcomes.append(result)
        try:
            value = cents(row.get('cashAmount'))
            if value <= 0:
                raise ValueError()
            if cents(row.get('offsetAmount', 0)) != 0:
                result.update(error='offsets_disabled', message='New offsets are disabled. Enter actual cash only.')
                continue
        except (ValueError, TypeError, OverflowError):
            result.update(error='invalid_cash_amount', message='Cash Amount must be greater than zero and within the outstanding balance.')
            continue
        signature = _signature(actor, body, row, value)
        existing = prior.get(row['cashItemId'])
        if existing:
            original_uid, entry = existing
            if original_uid != uid or entry.get('transactionNo') != no or entry.get('cashItemSignature') != signature:
                result.update(error='cash_item_conflict', message='This item was already recorded with different details. View its registration before creating another.')
                continue
            result.update(status='recorded', replayed=True, batchId=entry['batchId'], currency=entry['currency'],
                          paymentDirection=entry['paymentDirection'], cashAmount=amount(value),
                          paymentDate=entry['paymentDate'], reference=entry.get('reference', ''), note=entry.get('note', ''))
            continue
        if not scope or party_key != scope:
            result.update(error='incompatible_counterparty', message='Use one actual counterparty per submission.')
            continue
        case = cases.get(uid)
        if case is None or not isinstance(no, str) or not no:
            result.update(error='account_unavailable', message='This account is unavailable. Refresh Accounting.')
            continue
        if type(row.get('rowVersion')) is not int or row['rowVersion'] != initial_versions[uid]:
            result.update(error='version_conflict', message='This case changed. Refresh the failed account before retrying.')
            continue
        case = refresh_case(case)
        from .data_integrity import financial_issues
        if not getattr(case, 'legacy', False) and financial_issues(case.payload):
            result.update(error='case_data_invalid', message='Correct the case financial data before recording this account.')
            continue
        d = safe_detail(case, no)
        currency, actual_party = counterparty(case.payload, d)
        result.update(currency=currency, paymentDirection=d.get('paymentDirection'), cashAmount=amount(value))
        if not currency or actual_party != scope or d.get('paymentDirection') not in ('receivable', 'payable'):
            result.update(error='account_unavailable', message='Select an active cash account for the chosen counterparty.')
            continue
        key = (currency, d['paymentDirection'])
        bid = batches.setdefault(key, str(uuid.uuid4()))
        single = {**body, 'allocations': [{**row, 'rowVersion': case.row_version, 'offsetAmount': 0}],
                  'amount': amount(value if d['paymentDirection'] == 'receivable' else -value)}
        context = {'batchId': bid, 'submissionId': submission_id, 'itemId': row['cashItemId'], 'signature': signature}
        try:
            with transaction.atomic():
                response = register_cash_group(view, request, single, context=context)
                if response.status_code != 200:
                    transaction.set_rollback(True)
            if response.status_code != 200:
                result.update(error=response.data.get('error', 'cash_record_failed'), message=response.data.get('message', 'This account could not be recorded.'))
                continue
        except IntegrityError:
            result.update(error='payment_conflict', message='This account changed while saving. Refresh and retry the failed item.')
            continue
        result.update(status='recorded', replayed=False, batchId=bid, paymentDate=body['paymentDate'], reference=reference, note=note)
        refresh_case(case)
    outcomes.sort(key=lambda item: item['index'])
    succeeded = sum(row['status'] == 'recorded' for row in outcomes)
    return Response({'ok': True, 'cashSubmissionId': submission_id, 'results': outcomes,
                     'succeeded': succeeded, 'failed': len(outcomes) - succeeded,
                     'newlyRecorded': sum(row['status'] == 'recorded' and not row.get('replayed') for row in outcomes)})
