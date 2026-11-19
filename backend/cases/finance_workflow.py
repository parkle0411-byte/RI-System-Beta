"""Finance-reviewed accounts and cash-only registrations.

All write callers hold PRODUCTION_SOURCES and one database transaction. Reading
does not populate reconciliation or rewrite existing receipts.
"""
import copy
import hashlib
import json
import uuid
from django.core.exceptions import ValidationError

from django.db import transaction
from rest_framework.response import Response

from .cash_ledger import amount, cents, direction, family, objects, transaction_details



class StaleCaseError(ValueError):
    pass


class FinancialDataError(ValueError):
    pass


def fail(code, message, status=409, **extra):
    return Response({'ok': False, 'error': code, 'message': message, **extra}, status=status)


# 2026-11-19 業主決定：與這兩家 Facility 的往來帳由 Reinsurance Staff 對帳。
# Reinsurance Staff 只能 Mark reviewed「對象是這兩家」的帳款（應付與應收：保費、退保保費、理賠款；
# 同日稍晚業主擴大到應收），且只能取消自己做的審核；登錄收付款與其他 Finance 操作仍只有 Finance。
FACILITY_REVIEW_PERMISSION = 'accounting.review.facility_accounts'
FACILITY_REVIEW_REINSURERS = ('Swiss Re Asia Pte. Ltd., Hong Kong Branch (Facility)',
                           'Allianz Global Corporate & Specialty SE, Hong Kong Branch (Facility)')


def facility_account(payload, no, detail):
    """帳款的收付對象是否為上述兩家（應付或應收；新系統與舊資料都適用）。
    再保人依帳款自己的再保人序號判斷（畫面上的對象名稱已去掉 "(Facility)"，不能用來比對）。"""
    from .accounting_policy import normalized, rows
    from .payment_policy import claim_source
    if detail.get('paymentDirection') not in ('payable', 'receivable') or detail.get('partyType') != 'reinsurer' or detail.get('cashTracking') == 'derived':
        return False
    tx = next((t for t in objects(payload.get('transactions')) if t.get('txNo') == no), None)
    if tx is None or tx.get('reversed') or tx.get('isReversalEntry'):
        return False
    if tx.get('source') == 'claim':
        name = claim_source(payload, tx)[1]
    else:
        index = tx.get('reinsurerIdx'); names = [r.get('name') for r in rows(payload.get('reinsurers'))]
        name = names[index] if isinstance(index, int) and not isinstance(index, bool) and 0 <= index < len(names) else ''
    return normalized(name) in {normalized(n) for n in FACILITY_REVIEW_REINSURERS}


def review_rights(person):
    """回傳 (finance, allowed)：Finance 可審核／取消任何帳款；Reinsurance Staff 只限對象是這兩家的帳款與自己的審核。"""
    from .accounting_views import _can_edit
    from ri_system.authz import has_permission
    finance = _can_edit(person)
    return finance, finance or has_permission(person, FACILITY_REVIEW_PERMISSION)


def counterparty(payload, detail):
    return (str(detail.get('currency') or payload.get('currency') or '').upper(), ' '.join(str(detail.get('partyName') or '').split()).casefold())


def signature(payload, detail):
    data = [*counterparty(payload, detail), detail.get('amount'), detail.get('paymentDirection')]
    if detail.get('overseaBusiness'):
        data.append(detail.get('actualPaymentDate'))
    return hashlib.sha256(json.dumps(data, ensure_ascii=False, separators=(',', ':')).encode()).hexdigest()


def review_batches():
    """One logical active batch per counterparty across currencies; retain original review events.

    Group on read so existing review records need no migration or destructive rewrite.
    Writers hold the shared Accounting source lock.
    2026-11-19：取消可以是整個對象批次、取消者自己的審核，或單筆帳款；單筆取消記在該次審核的
    cancelled_members，這些帳款不再屬於有效批次（原始審核內容保留不動）。
    """
    from .models import FinanceReconciliationBatch
    groups = {}; history = []
    from ri_system.sorted_fetch import sorted_rows   # 2026-11-16：先排序編號再讀整筆，很大的審核批次不會讓排序記憶體不足
    for original in sorted_rows(FinanceReconciliationBatch.objects.all(), 'created_at', 'id'):
        if original.status != 'active':
            history.append(original)
            continue
        key = ' '.join(original.party_name.split()).casefold()
        if key not in groups:
            batch = copy.copy(original)
            batch.members = []
            batch.currencies = []
            batch.cancelled = []
            groups[key] = batch
        batch = groups[key]
        if original.currency.upper() not in batch.currencies:
            batch.currencies.append(original.currency.upper())
        gone = {(m.get('caseUid'), m.get('txNo')) for m in objects(original.cancelled_members)}
        batch.cancelled.extend({**m, 'reviewEventId': str(original.pk)} for m in objects(original.cancelled_members))
        batch.members.extend({**member, 'reviewEventId': str(original.pk),
            'reviewDate': str(original.review_date), 'reviewReference': original.reference,
            'reviewNote': original.note, 'reviewedBy': original.created_by, 'reviewedByName': original.created_by_name,
            'reviewedAt': original.created_at.isoformat(), 'currency': original.currency.upper()}
            for member in original.members if (member.get('caseUid'), member.get('txNo')) not in gone)
    return [*groups.values(), *history]


def active_reviews(case_uids=None):
    from .models import Case, FinanceReconciliationBatch
    # One query per list/write, independent of account count. No inferred legacy approval.
    result = {}
    for batch in review_batches():
        if batch.status != 'active':
            continue
        for member in batch.members:
            if case_uids is None or member['caseUid'] in case_uids:
                result[(member['caseUid'], member['txNo'])] = (batch, member)
    return result


def review_fields(uid, no, payload, detail, reviews):
    pair = reviews.get((uid, no))
    valid = bool(pair and pair[1]['signature'] == signature(payload, detail))
    batch = pair[0] if valid else None
    return {'financeReviewed': valid, 'reviewBatchId': str(batch.pk) if batch else '',
            'reviewDate': pair[1]['reviewDate'] if valid else '',
            'reviewReference': pair[1]['reviewReference'] if valid else '',
            'reviewNote': pair[1]['reviewNote'] if valid else '',
            'reviewedByName': pair[1]['reviewedByName'] if valid else '',
            'reviewedBy': pair[1].get('reviewedBy', '') if valid else '',
            'reviewCurrencies': batch.currencies if valid else []}


def writable_case(case, no):
    tx = next((t for t in objects(case.payload.get('transactions')) if t.get('txNo') == no), {})
    return (not case.is_archived and not case.recycled_at and
            (case.status in ('posted', 'closed') or case.status == 'reversed' and tx.get('source') == 'claim'))


def locked_cases(members, max_accounts=2000):
    from .models import Case, FinanceReconciliationBatch
    if not isinstance(members, list) or not members or max_accounts is not None and len(members) > max_accounts:
        raise ValueError('Select valid accounts within the operation limit.')
    expected = {}
    seen = set()
    for m in members:
        uid = m.get('caseUid'); no = m.get('txNo'); version = m.get('rowVersion')
        if str(uuid.UUID(uid)) != uid or not isinstance(no, str) or not no or type(version) is not int:
            raise ValueError('Valid account identifiers and current case versions are required.')
        if (uid, no) in seen:
            raise ValueError('Select each account once with consistent case versions.')
        if uid in expected and expected[uid] != version:
            raise StaleCaseError('An affected case changed. Refresh Accounting and try again.')
        seen.add((uid, no)); expected[uid] = version
    cases = {str(c.case_uid): c for c in Case.objects.select_for_update().filter(case_uid__in=expected).order_by('id')}
    from legacy.ledger import locked_facades
    cases.update(locked_facades(set(expected)-set(cases)))
    if set(cases) != set(expected):
        raise ValueError('An affected case is unavailable.')
    for uid, case in cases.items():
        if case.row_version != expected[uid]:
            raise StaleCaseError('An affected case changed. Refresh Accounting and try again.')
        from .data_integrity import financial_issues
        if not getattr(case,'legacy',False) and financial_issues(case.payload):
            raise FinancialDataError('An affected case has invalid financial data. Correct it before continuing.')
    return cases


def save_all(view, request, cases, payloads, action, metadata):
    for uid, case in cases.items():
        payloads[uid].setdefault('paymentEntries', [])
        result = view._save(request, {'rowVersion': case.row_version}, case, payloads[uid], action, metadata)
        if result.status_code != 200:
            transaction.set_rollback(True)
            return result
    return None


def reconcile(view, request, body):
    from .models import Case, FinanceReconciliationBatch
    from .accounting_views import _real_date
    from ri_system.authz import actor_from
    finance, allowed = review_rights(request.ri_principal)
    if not allowed:
        return fail('permission_denied', 'Finance access is required.', 403)
    reference = str(body.get('reference') or '').strip(); note = str(body.get('note') or '').strip()
    if not _real_date(body.get('date')) or len(reference) > 200 or len(note) > 1000:
        return fail('review_details_required', 'Enter a valid review date; reference and explanation are optional (maximum 200 and 1000 characters).', 400)
    members = body.get('members')
    try:
        cases = locked_cases(members)
    except FinancialDataError:
        return fail('case_data_invalid', 'An affected case has invalid financial data. Correct it before continuing.')
    except StaleCaseError:
        return fail('version_conflict', 'An affected case changed. Refresh Accounting and try again.')
    except (ValueError, TypeError, AttributeError):
        return fail('version_conflict', 'Refresh and select valid accounts with their current versions.')
    reviews = active_reviews(set(cases)); details = {uid: transaction_details(c.payload) for uid, c in cases.items()}
    scope = None; stored = {}; party_name = ''
    for m in members:
        uid, no = m['caseUid'], m['txNo']; p = cases[uid].payload; d = details[uid].get(no)
        if not d or not writable_case(cases[uid], no) or d.get('cashTracking') == 'derived' or any(
                t.get('txNo') == no and (t.get('reversed') or t.get('isReversalEntry')) for t in objects(p.get('transactions'))):
            return fail('review_not_allowed', 'Select active T1/T2 or claim accounts.')
        if (uid, no) in reviews:
            return fail('already_reviewed', 'Cancel the existing whole review batch before reviewing this account again.')
        if not finance and not facility_account(p, no, d):   # Reinsurance Staff：只限對象是這兩家的帳款
            return fail('permission_denied', 'Reinsurance Staff can review only accounts with Swiss Re Asia or Allianz (Facility).', 403)
        group = counterparty(p, d)
        if not all(group) or scope is not None and group[1] != scope:
            return fail('review_scope', 'Review accounts for one counterparty per batch.', 400)
        scope = group[1]; party_name = d['partyName']
        stored.setdefault(group[0], []).append({'caseUid': uid, 'txNo': no, 'signature': signature(p, d)})
    actor = actor_from(request.ri_principal)
    events = [FinanceReconciliationBatch.objects.create(id=uuid.uuid4(), review_date=body['date'], reference=reference,
        note=note, currency=currency, party_name=party_name, members=items,
        created_by=str(actor['id']), created_by_name=actor['name']) for currency, items in stored.items()]
    payloads = {uid: copy.deepcopy(c.payload) for uid, c in cases.items()}
    group_id = str(active_reviews(set(cases))[(members[0]['caseUid'], members[0]['txNo'])][0].pk)
    error = save_all(view, request, cases, payloads, 'finance_accounts_reviewed',
                     {'reviewBatchId': group_id, 'reviewEventId': str(events[0].pk),
                      'reviewEventIds': [str(event.pk) for event in events]})
    return error or Response({'ok': True, 'reviewBatchId': group_id})


def cancel_review(view, request, body):
    from .models import Case, FinanceReconciliationBatch
    from ri_system.authz import actor_from
    from django.utils import timezone
    finance, allowed = review_rights(request.ri_principal)
    if not allowed:
        return fail('permission_denied', 'Finance access is required.', 403)
    note = str(body.get('reason') or '').strip()
    if not note or len(note) > 1000:
        return fail('reason_required', 'Enter the reason for cancelling this entire review batch.', 400)
    # 2026-11-19 業主決定：scope='batch'（取消整批；未指定時與原本相同）或 'account'（只取消這一筆）。
    #   Finance：整批＝整個對象批次；單筆可取消任何人審的帳款。
    #   Reinsurance Staff：整批＝本人在這個對象審過的全部帳款；單筆只限本人審的。其他人審的不動。
    scope = body.get('scope') or 'batch'
    if scope not in ('batch', 'account'):
        return fail('invalid_scope', 'Choose to cancel this account only or the whole batch.', 400)
    actor = actor_from(request.ri_principal); me = str(actor['id'])
    try:
        # Lock every event, including events created by later reviews for this group.
        from ri_system.sorted_fetch import sorted_rows   # 2026-11-16：先排序並鎖定編號，再讀整筆
        events = sorted_rows(FinanceReconciliationBatch.objects.select_for_update().filter(status='active'), 'created_at', 'id')
        original = next(b for b in events if str(b.pk) == str(body.get('reviewBatchId')))
        party = ' '.join(original.party_name.split()).casefold()
        events = [b for b in events if ' '.join(b.party_name.split()).casefold() == party]
        batch = next(b for b in review_batches() if b.status == 'active' and str(b.pk) == str(events[0].pk))
        supplied = body.get('members')
        keys = {(m['caseUid'], m['txNo']) for m in supplied}
        if scope == 'account':
            targets = [m for m in batch.members if (m['caseUid'], m['txNo']) in keys]
            if len(supplied) != 1 or len(targets) != 1:
                raise ValueError()
            if not finance and targets[0].get('reviewedBy') != me:
                return fail('own_reviews_only', 'Reinsurance Staff can cancel only the reviews they made.', 403)
        else:
            targets = batch.members if finance else [m for m in batch.members if m.get('reviewedBy') == me]
            if not targets:
                return fail('own_reviews_only', 'Reinsurance Staff can cancel only the reviews they made.', 403)
            if keys != {(m['caseUid'], m['txNo']) for m in targets}:
                raise ValueError()
        cases = locked_cases(supplied, max_accounts=None)
    except (StopIteration, FinanceReconciliationBatch.DoesNotExist, ValidationError, ValueError, TypeError, KeyError, AttributeError):
        return fail('whole_review_required', 'Reload and cancel every account in the original review batch together.')
    for uid, case in cases.items():
        details = transaction_details(case.payload)
        for member in targets:
            if member['caseUid'] != uid:
                continue
            d = details.get(member['txNo'], {})
            if any(abs(cents(e.get('appliedAmount', 0))) for e in effective_entries(d.get('entries', []))):
                return fail('review_payment_locked', 'Reverse active receipt/payment and offset registrations before cancelling the whole review batch.')
    stamp = timezone.now()
    def close(event):
        event.status = 'cancelled'; event.cancelled_at = stamp; event.cancelled_by = me
        event.cancelled_by_name = actor['name']; event.cancel_reason = note
    if finance and scope == 'batch':
        for event in events:   # 原本的做法：整個對象批次一起取消
            close(event)
            event.save(update_fields=['status', 'cancelled_at', 'cancelled_by', 'cancelled_by_name', 'cancel_reason'])
    else:
        # 只把指定帳款記為已取消；該次審核的帳款全部取消時，整次審核改為已取消。
        by_event = {}
        for m in targets:
            by_event.setdefault(m['reviewEventId'], []).append(m)
        for event in events:
            chosen = by_event.get(str(event.pk))
            if not chosen:
                continue
            event.cancelled_members = [*objects(event.cancelled_members), *({'caseUid': m['caseUid'], 'txNo': m['txNo'],
                'cancelledAt': stamp.isoformat(), 'cancelledBy': me, 'cancelledByName': actor['name'], 'reason': note} for m in chosen)]
            fields = ['cancelled_members']
            gone = {(m.get('caseUid'), m.get('txNo')) for m in event.cancelled_members}
            if all((m.get('caseUid'), m.get('txNo')) in gone for m in objects(event.members)):
                close(event); fields += ['status', 'cancelled_at', 'cancelled_by', 'cancelled_by_name', 'cancel_reason']
            event.save(update_fields=fields)
    error = save_all(view, request, cases, {uid: copy.deepcopy(c.payload) for uid, c in cases.items()},
                     'finance_review_cancelled', {'reviewBatchId': str(batch.pk), 'reason': note, 'scope': scope,
                                                  'accounts': [m['txNo'] for m in targets]})
    return error or Response({'ok': True, 'reviewBatchId': str(batch.pk)})


def effective_entries(entries):
    reversed_ids = {e.get('reversalOf') for e in entries if e.get('entryType') == 'reversal'}
    return [e for e in entries if e.get('entryType') == 'payment' and e.get('id') not in reversed_ids]


def apply_details(payload, details, now):
    """Automatic settlement, per-reinsurer locks, preserved dates and claim notes."""
    from .calc.payment_terms import taipei_date
    today = taipei_date(now)
    for no, d in details.items():
        tx = d['_tx']
        if d['_historic']:
            d.update(canRecord=False, manualSettlementRequired=False, canConfirmSettlement=False, canCancelSettlement=False)
            continue
        d.update(tx.get('financeDates') or {})
        if d['cashTracking'] != 'derived':
            cleared = abs(d['outstanding']) < .005
            d.update(settlement='settled' if cleared else 'partial' if abs(d['paid']) > .004 else 'open',
                     manualSettlementRequired=False, manualSettlementConfirmed=cleared,
                     canConfirmSettlement=False, canCancelSettlement=False,
                     amountEditLocked=abs(d['paid']) > .004, settlementFinalized=cleared,
                     fullPaymentRequired=False, refundWholeEndorsement=False, offsetAllowed=False)
            if cleared:
                d['canRecord'] = False
            deadline = d.get('contractDueDate') or d.get('dueDate')
            if cleared:
                d['paymentStatus'] = 'settled'
            elif deadline and deadline < today:
                d['paymentStatus'] = 'overdue'
            if d['_source'] == 'claim':
                old_notes = [x for key in ('allianzClaimTracking', 'greatAmericanClaimTracking', 'qbeClaimTracking', 'financeClaimTracking')
                             for x in objects(payload.get(key)) if x.get('txNo') == no]
                d['trackingHistory'] = sorted(old_notes, key=lambda x: x.get('recordedAt', ''))
    for no, d in details.items():
        if d['_historic'] or d['cashTracking'] != 'derived':
            continue
        tx = d['_tx']
        peers = [x for x in details.values() if not x['_historic'] and x['_source'] == 'premium' and x['_leg'] in ('1', '2')
                 and x['_tx'].get('installmentId') == tx.get('installmentId')
                 and (not tx.get('perReinsurer') or x['_tx'].get('reinsurerIdx') == tx.get('reinsurerIdx'))]
        cleared = bool(peers) and all(x['settlement'] == 'settled' for x in peers)
        d.update(settlement='settled' if cleared else 'open',
                 paid=d['amount'] if cleared else 0, outstanding=0 if cleared else d['amount'],
                 settlementDependencies=[{'txNo': x['_tx']['txNo'], 'settlement': x['settlement']} for x in peers],
                 manualSettlementRequired=False, canConfirmSettlement=False, canCancelSettlement=False,
                 settlementFinalized=cleared, amountEditLocked=cleared, periodAmountLocked=False)


def register(view, request, body):
    if 'cashSubmissionId' in body:
        from .cash_registration import register_accounts
        return register_accounts(view, request, body)
    return register_cash_group(view, request, body)


def register_cash_group(view, request, body, context=None):
    from .models import Case, FinanceReconciliationBatch
    from .accounting_views import _can_edit, _real_date, _iso_now
    from ri_system.authz import actor_from
    if not _can_edit(request.ri_principal):
        return fail('permission_denied', 'Finance access is required.', 403)
    reference = str(body.get('reference') or '').strip(); note = str(body.get('note') or '').strip()
    if not _real_date(body.get('paymentDate')) or not (reference or note) or len(reference) > 200 or len(note) > 1000:
        return fail('payment_details_required', 'Enter a valid date and an Accounting Dept. Ref. or note.', 400)
    allocations = body.get('allocations')
    try:
        cases = locked_cases(allocations)
        net = cents(body.get('amount'))  # signed: positive receipt, negative payment
    except FinancialDataError:
        return fail('case_data_invalid', 'An affected case has invalid financial data. Correct it before continuing.')
    except StaleCaseError:
        return fail('version_conflict', 'An affected case changed. Refresh Accounting and try again.')
    except (ValueError, TypeError, AttributeError):
        return fail('invalid_payment', 'Refresh and enter valid allocations and a signed net amount.', 400)
    details = {uid: transaction_details(c.payload) for uid, c in cases.items()}; reviews = active_reviews(set(cases))
    group = None; totals = {'receivable': 0, 'payable': 0}
    parsed = []
    for row in allocations:
        uid, no = row['caseUid'], row['txNo']; p = cases[uid].payload; d = details[uid].get(no)
        if not d or not writable_case(cases[uid], no) or not d.get('canRecord'):
            return fail('transaction_not_payable', 'Select active reviewed accounts with outstanding balances.', 400)
        pair = reviews.get((uid, no))
        if not pair or pair[1]['signature'] != signature(p, d):
            return fail('finance_review_required', 'Finance must review every selected account before recording receipts or payments.')
        current = counterparty(p, d)
        if not all(current) or group is not None and current != group:
            return fail('incompatible_allocations', 'Use one currency and one counterparty per registration.', 400)
        group = current
        if d.get('paymentAllowed') is False or d.get('statementNeedsRevision'):
            return fail('payment_prerequisite', d.get('paymentBlockedReason') or 'Revise the Swiss statement before recording payment.')
        try:
            cash = cents(row.get('cashAmount', row.get('amount', 0))); offset = cents(row.get('offsetAmount', 0)); total = cash
            if offset:
                return fail('offsets_disabled', 'New offsets are disabled. Record actual receipts and payments separately.', 400)
            if current[0] == 'TWD' and cash % 100:
                return fail('twd_whole_number', 'TWD Cash Amount must be a whole number.', 400)
            if cash < 0 or offset < 0 or total <= 0 or total > abs(cents(d['outstanding'])):
                raise ValueError()
        except (ValueError, TypeError):
            return fail('invalid_allocation', 'Enter positive cash amounts within each outstanding balance.', 400)
        side = d['paymentDirection']; totals[side] += total
        parsed.append((row, d, cash, offset))
    if totals['receivable'] - totals['payable'] != net:
        return fail('net_mismatch', 'The signed net cash must equal receivable allocations minus payable allocations.', 400)
    # One real bank movement: cash cannot be fabricated on both sides of a net remittance.
    cash_in = totals['receivable']; cash_out = totals['payable']
    if cash_in and cash_out:
        return fail('cash_direction_mismatch', 'Record receipts and payments separately; use the multi-account cash form for both directions.', 400)
    actor = actor_from(request.ri_principal); stamp = _iso_now(); bid = context['batchId'] if context else str(uuid.uuid4())
    payloads = {uid: copy.deepcopy(c.payload) for uid, c in cases.items()}
    from .calc.payment_terms import build_payment_schedule
    from .cash_ledger import proportions
    for row, d, cash, offset in parsed:
        p = payloads[row['caseUid']]; parts = d['cashParts']; capacities = [abs(cents(x['outstanding'])) for x in parts]
        schedules = {x['scheduleKey']: x for x in build_payment_schedule(p)['items']}
        shares = proportions(cash, capacities)
        if sum(shares) != cash:
            return fail('payment_conflict', 'An allocation no longer fits the account balance.')
        for part, share in zip(parts, shares):
            if not share:
                continue
            schedule = schedules.get(part['scheduleKey'], {})
            p.setdefault('paymentEntries', []).append({
                'id': str(uuid.uuid4()), 'entryType': 'payment', 'transactionNo': row['txNo'],
                'scheduleKey': part['scheduleKey'], 'partyType': d['partyType'], 'partyName': d['partyName'],
                'paymentDirection': d['paymentDirection'], 'currency': group[0],
                'amount': amount(share * (-1 if d['amount'] < 0 else 1)), 'nonCash': False,
                'entryKind': 'finance-cash', 'batchId': bid,
                **({'cashSubmissionId': context['submissionId'], 'cashItemId': context['itemId'],
                    'cashItemSignature': context['signature']} if context else
                   {'batchAmount': amount(net), 'batchReceivable': amount(totals['receivable']), 'batchPayable': amount(totals['payable'])}),
                'paymentDate': body['paymentDate'], 'reference': reference, 'note': note,
                'createdAt': stamp, 'createdBy': actor['id'], 'createdByName': actor['name'],
                'replacementOfBatchId': body.get('replacementOfBatchId') or '',
                **({'settlementDueDate': schedule.get('contractDueDate') if schedule.get('swissCgl') else schedule.get('dueDate')}
                   if schedule.get('swissFacility') else {})})
    for uid, p in payloads.items():
        problem = dependency_error(cases[uid].payload, p)
        if problem:
            return fail('payment_dependency', problem)
    replacement = body.get('replacementOfBatchId')
    if replacement:
        # Validate linkage to a fully reversed historical registration for this counterparty/currency.
        from legacy.ledger import all_payment_payloads
        payloads_for_link=[c.payload for c in Case.objects.all().only('payload')]+list(all_payment_payloads())
        prior = [e for p in payloads_for_link for e in objects(p.get('paymentEntries'))
                 if e.get('entryType') == 'payment' and e.get('batchId') == replacement]
        revs = {e.get('reversalOf') for p in payloads_for_link for e in objects(p.get('paymentEntries')) if e.get('entryType') == 'reversal'}
        if not prior or any(e['id'] not in revs or counterparty({'currency': e.get('currency')}, e) != group for e in prior):
            return fail('invalid_replacement', 'Select a fully reversed registration for the same currency and counterparty.')
    error = save_all(view, request, cases, payloads, 'record_payment', {'batchId': bid, 'netCash': amount(net)})
    return error or Response({'ok': True, 'batchId': bid, 'amount': amount(net)})


def dependency_error(before, after):
    from .accounting_rules import claim_balance_error
    error = claim_balance_error(after)
    if error:
        return error
    prior = transaction_details(before); current = transaction_details(after)
    for no, d in current.items():
        if d.get('paymentDirection') == 'payable' and abs(d.get('paid', 0)) > .004 and d.get('paymentAllowed') is False:
            old = prior.get(no, {})
            if old.get('paymentAllowed') or abs(d['paid']) > abs(old.get('paid', 0)) + .004:
                return d.get('paymentBlockedReason') or 'A downstream payment requires the original receipt or offset to remain valid.'
    return ''


def reverse_registration(view, request, body):
    from .models import Case, FinanceReconciliationBatch
    from .accounting_views import _can_edit, _iso_now, _real_date
    from ri_system.authz import actor_from
    if not _can_edit(request.ri_principal):
        return fail('permission_denied', 'Finance access is required.', 403)
    bid = body.get('batchId'); reason = str(body.get('note') or '').strip()
    if not isinstance(bid, str) or not bid or not reason or not _real_date(body.get('paymentDate')):
        return fail('reversal_details_required', 'Enter the registration, reversal date and correction reason.', 400)
    # Legacy records without a batch are grouped by original id/offset id, never silently dropped.
    matches = [c.pk for c in Case.objects.all().only('pk', 'payload') if any(
        e.get('entryType') == 'payment' and (e.get('batchId') or e.get('offsetId') or 'legacy:' + str(e.get('id'))) == bid
        for e in objects(c.payload.get('paymentEntries')))]
    cases = {str(c.case_uid): c for c in Case.objects.select_for_update().filter(pk__in=matches).order_by('id')}
    from legacy.models import LegacyTransaction
    from legacy.ledger import locked_facades
    legacy_matches=[str(t.uid) for t in LegacyTransaction.objects.filter(status='confirmed',historical=False).only('uid','financial')
        if any(e.get('entryType')=='payment' and (e.get('batchId') or e.get('offsetId') or 'legacy:'+str(e.get('id')))==bid
               for e in objects(t.financial.get('paymentEntries')))]
    cases.update(locked_facades(legacy_matches))
    try:
        versions = body.get('cases')
        expected = {m['caseUid']: m['rowVersion'] for m in versions}
        if not cases or len(expected) != len(versions) or set(expected) != set(cases) or any(type(expected[u]) is not int or c.row_version != expected[u] for u, c in cases.items()):
            raise ValueError()
    except (ValueError, TypeError, KeyError):
        return fail('whole_registration_required', 'Refresh and provide every affected case version to reverse the whole registration.')
    actor = actor_from(request.ri_principal); stamp = _iso_now(); reversal_id = str(uuid.uuid4()); payloads = {}
    for uid, c in cases.items():
        from .data_integrity import financial_issues
        if not getattr(c,'legacy',False) and financial_issues(c.payload):
            return fail('case_data_invalid', 'Correct the affected case financial data first.')
        p = copy.deepcopy(c.payload); entries = objects(p.get('paymentEntries')); reversed_ids = {e.get('reversalOf') for e in entries}
        originals = [e for e in entries if e.get('entryType') == 'payment' and
                     (e.get('batchId') or e.get('offsetId') or 'legacy:' + str(e.get('id'))) == bid]
        if any(e.get('id') in reversed_ids or not writable_case(c, e.get('transactionNo', '')) for e in originals):
            return fail('registration_locked', 'This registration is already reversed or an affected case is inactive.')
        if any(e.get('entryKind') == 'legacy-import' for e in originals):
            return fail('registration_locked', 'Receipts and payments settled before import are read-only.')
        p.setdefault('paymentEntries', []).extend({**e, 'id': str(uuid.uuid4()), 'entryType': 'reversal',
            'reversalOf': e['id'], 'reversalOfBatchId': bid, 'batchId': reversal_id,
            'paymentDate': body['paymentDate'], 'note': reason[:1000],
            'createdAt': stamp, 'createdBy': actor['id'], 'createdByName': actor['name']} for e in originals)
        # Frozen dates remain, but a stale persisted settled flag must not masquerade as an active receipt.
        original_ids = {e.get('id') for e in originals}
        affected = {no for no,d in transaction_details(c.payload).items() if any(e.get('id') in original_ids for e in d.get('entries', []))}
        for tx in objects(p.get('transactions')):
            if tx.get('txNo') in affected and not tx.get('reversed') and not tx.get('isReversalEntry'):
                tx['settlement'] = 'open'; tx['financeReopened'] = True
        error = dependency_error(c.payload, p)
        if error:
            return fail('downstream_payment_locked', error)
        payloads[uid] = p
    error = save_all(view, request, cases, payloads, 'reverse_payment', {'batchId': bid, 'reversalBatchId': reversal_id, 'reason': reason})
    return error or Response({'ok': True, 'batchId': bid, 'reversalBatchId': reversal_id})


def followup(view, request, body):
    from .accounting_views import _can_edit, _iso_now
    from ri_system.authz import actor_from
    if not _can_edit(request.ri_principal):
        return fail('permission_denied', 'Finance access is required.', 403)
    case = view._load_case_for_update(str(body.get('caseUid') or ''))
    if not case or case.row_version != body.get('rowVersion'):
        return fail('version_conflict', 'Refresh the current account before recording follow-up.')
    d = transaction_details(case.payload).get(body.get('txNo'), {})
    note = str(body.get('note') or '').strip()
    if not writable_case(case, body.get('txNo')) or not str(body.get('txNo') or '') or d.get('cashTracking') == 'derived' or abs(d.get('outstanding', 0)) < .005 or not any(
            t.get('source') == 'claim' and t.get('txNo') == body.get('txNo') and not t.get('reversed') and not t.get('isReversalEntry') for t in objects(case.payload.get('transactions'))):
        return fail('claim_followup_not_allowed', 'Select an active outstanding claim account.')
    if not note or len(note) > 1000:
        return fail('followup_note_required', 'Enter the claim follow-up record.', 400)
    actor = actor_from(request.ri_principal); p = copy.deepcopy(case.payload)
    p.setdefault('financeClaimTracking', []).append({'txNo': body['txNo'], 'note': note,
        'recordedAt': _iso_now(), 'recordedBy': actor['id'], 'recordedByName': actor['name']})
    return view._save(request, body, case, p, 'record_claim_followup', {'txNo': body['txNo']})
