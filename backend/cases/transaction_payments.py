"""Atomic cash allocations to immutable, existing transactions."""
import copy
import uuid
from .cash_ledger import amount, cents, objects, proportions, transaction_details
from .models import Case
from .calc.payment_terms import taipei_date, build_payment_schedule
from .calc.swiss_facility import payment_error, case_payload


def edit_payment(view, request, body):
    from .accounting_views import _can_edit, _error, _iso_now
    from .accounting_rules import entry_locked, claim_balance_error
    from ri_system.authz import actor_from
    if not _can_edit(request.ri_principal):
        return _error(403, 'permission_denied', 'Accounting write access is required.')
    case = view._load_case_for_update(str(body.get('caseUid') or ''))
    if not case:
        return _error(404, 'case_not_found', 'Case not found.')
    locked = view._status_error(case, 'edited')
    if locked:
        raw_entry = next((e for e in objects(case.payload.get('paymentEntries')) if e.get('id') == body.get('entryId')), {})
        raw_tx = next((t for t in objects(case.payload.get('transactions')) if t.get('txNo') == raw_entry.get('transactionNo')), {})
        if case.status != 'reversed' or raw_tx.get('source') != 'claim':
            return locked
    if case.row_version != body.get('rowVersion'):
        return _error(409, 'version_conflict', 'Reload Accounting before editing this record.')
    reason = str(body.get('reason') or '').strip()[:1000]
    if not reason:
        return _error(400, 'correction_reason_required', 'Enter the reason for changing the recorded amount.')
    payload = case_payload(case)
    entries = objects(payload.get('paymentEntries'))
    entry = next((e for e in entries if e.get('id') == body.get('entryId')), None)
    if (not entry or entry.get('entryType') != 'payment' or entry.get('nonCash') or
            any(e.get('reversalOf') == entry.get('id') for e in entries)):
        return _error(400, 'payment_not_editable', 'Select an active receipt/payment record.')
    if entry_locked(payload, entry):
        return _error(409, 'settled_amount_locked', 'Previously settled amounts remain locked even after cancelling settlement.')
    detail = transaction_details(payload).get(entry.get('transactionNo'))
    if not detail:
        return _error(409, 'individual_transaction_required', 'Review the transaction mapping before editing a legacy payment.')
    try:
        value = cents(body.get('amount'))
        before_amount = abs(cents(entry['amount']))
        capacity = before_amount + abs(cents(detail['outstanding']))
        if value <= 0 or value > capacity:
            raise ValueError()
    except (ValueError, TypeError):
        return _error(400, 'invalid_payment', 'Enter a positive amount within the original obligation balance.')
    if detail.get('fullPaymentRequired') and value != capacity:
        return _error(400, 'full_premium_required', 'Premium receipts/payments must cover the complete balance.')
    before = copy.deepcopy(entry)
    entry['amount'] = amount(value * (-1 if cents(entry['amount']) < 0 else 1))
    from .allianz_accounting import collection_change_error
    problem = collection_change_error(case.payload,payload) or claim_balance_error(payload)
    if problem:
        return _error(409, 'claim_collection_limit', problem)
    actor = actor_from(request.ri_principal)
    payload.setdefault('paymentEditHistory', []).append({
        'entryId': entry['id'], 'transactionNo': entry.get('transactionNo'),
        'before': before, 'after': copy.deepcopy(entry), 'reason': reason,
        'changedAt': _iso_now(), 'changedBy': actor['id'], 'changedByName': actor['name'],
    })
    return view._save(request, body, case, payload, 'payment_amount_edited', {'entryId': entry['id'], 'reason': reason})


def record_transaction_payments(view, request, body):
    from .accounting_views import _can_edit, _error, _real_date, _iso_now
    from ri_system.authz import actor_from
    if not _can_edit(request.ri_principal):
        return _error(403,'permission_denied','Accounting write access is required.')
    allocations=body.get('allocations')
    try:
        total=cents(body.get('amount'))
        if total<=0 or not _real_date(body.get('paymentDate')) or not isinstance(allocations,list) or not 1<=len(allocations)<=200:
            raise ValueError()
        parsed=[]
        for row in allocations:
            uid=str(uuid.UUID(row['caseUid']))
            if uid!=row['caseUid'] or not isinstance(row.get('txNo'),str) or not row['txNo']:
                raise ValueError()
            value=cents(row.get('amount'))
            if value<=0 or isinstance(row.get('rowVersion'),bool) or not isinstance(row.get('rowVersion'),int):
                raise ValueError()
            parsed.append({**row,'value':value})
        if len({(r['caseUid'],r['txNo']) for r in parsed})!=len(parsed):
            return _error(400,'duplicate_allocation','Select each transaction only once.')
        if sum(r['value'] for r in parsed)!=total:
            return _error(400,'allocation_mismatch','Allocation amounts must equal the remittance amount.')
    except (ValueError,TypeError,KeyError,AttributeError):
        return _error(400,'invalid_payment','A valid date, positive amount, transaction allocations and case versions are required.')
    cases={str(c.case_uid):c for c in Case.objects.select_for_update().filter(case_uid__in={r['caseUid'] for r in parsed}).order_by('id')}
    details={}
    payment_group=None
    for row in parsed:
        case=cases.get(row['caseUid'])
        if not case or case.recycled_at or case.is_archived:
            return _error(404,'case_not_found','Case not found.')
        is_claim = any(t.get('txNo') == row['txNo'] and t.get('source') == 'claim' for t in objects(case.payload.get('transactions')))
        if case.status not in ('posted','closed') and not (case.status == 'reversed' and is_claim):
            return _error(409,'accounting_status_locked','Only posted transactions can receive payments.')
        if case.row_version!=row['rowVersion']:
            return _error(409,'version_conflict','A selected case changed. Refresh Accounting and try again.')
        if row['caseUid'] not in details:
            details[row['caseUid']]=transaction_details({**case_payload(case),'currency':case.payload.get('currency') or case.currency,'reinsured':case.payload.get('reinsured') or case.reinsured_name_snapshot})
        detail=details[row['caseUid']].get(row['txNo'])
        if not detail or not detail['canRecord']:
            return _error(400,'transaction_not_payable','This transaction cannot receive a cash allocation.')
        if (detail.get('greatAmericanFacility') or detail.get('greatAmericanCase')) and detail.get('paymentAllowed') is False:
            return _error(400, 'great_american_collection_required', detail['paymentBlockedReason'])
        if detail.get("allianzFacility") and detail.get("paymentAllowed") is False:
            return _error(400,"allianz_collection_required",detail["paymentBlockedReason"])
        blocked = payment_error(detail, amount(row['value']))
        if blocked:
            return _error(400, 'swiss_payment_blocked', blocked)
        if row['value']>abs(cents(detail['outstanding'])):
            return _error(400,'overpayment','Allocation cannot exceed the transaction balance.')
        if payment_group is not None and detail['paymentGroup']!=payment_group:
            return _error(400,'incompatible_allocations','Use the same currency, cash direction and counterparty in one receipt/payment record.')
        payment_group=detail['paymentGroup']
    chosen=[details[r['caseUid']][r['txNo']] for r in parsed]
    if any(d.get('allianzFacility') or d.get('allianzCaseClaim') for d in chosen):
        sources={next(t.get('source','premium') for t in objects(cases[r['caseUid']].payload.get('transactions')) if t.get('txNo')==r['txNo']) for r in parsed}
        if len(sources)>1:return _error(400,'allianz_separate_claim_payment','Record Allianz claims separately from premiums and refunds.')
        if 'claim' not in sources and len({d.get('contractDueDate') for d in chosen})>1:
            return _error(400,'allianz_separate_due_dates','Record Allianz premiums with different contract due dates in separate remittances.')
    from .great_american_accounting import allocation_error
    ga_problem = allocation_error(chosen, parsed, cases, details)
    if ga_problem:return _error(400, 'great_american_payment_rule', ga_problem)
    from .payment_policy import allocation_error
    problem = allocation_error(parsed, chosen, details)
    if problem:return _error(400, 'whole_refund_required', problem)
    batch_id=str(uuid.uuid4())
    actor=actor_from(request.ri_principal)
    timestamp=_iso_now()
    payloads={uid:case_payload(c) for uid,c in cases.items()}
    for row in parsed:
        payload=payloads[row['caseUid']]
        detail=details[row['caseUid']][row['txNo']]
        parts=detail['cashParts']
        schedule_dates = {i['scheduleKey']: i for i in build_payment_schedule(payload)['items']}
        shares=proportions(row['value'],[cents(p['outstanding']) for p in parts])
        if sum(shares)!=row['value']:
            return _error(409,'payment_conflict','Transaction balance changed. Nothing was saved.')
        tx=next(t for t in objects(payload.get('transactions')) if t.get('txNo')==row['txNo'])
        entries=payload.setdefault('paymentEntries',[])
        if not isinstance(entries,list):
            entries=[];payload['paymentEntries']=entries
        for part,share in zip(parts,shares):
            if not share:continue
            entries.append({'id':str(uuid.uuid4()),'entryType':'payment','transactionNo':row['txNo'],
                'scheduleKey':part['scheduleKey'],'installmentId':tx.get('installmentId'),
                'installmentLabel':tx.get('installmentLabel'),'partyType':detail['partyType'],
                'partyName':detail['partyName'],'paymentDirection':detail['paymentDirection'],
                'currency':payload.get('currency') or cases[row['caseUid']].currency,
                'amount':amount(share*(-1 if detail['amount']<0 else 1)),
                'batchId':batch_id,'batchAmount':amount(total),'paymentDate':body['paymentDate'],
                'reference':str(body.get('reference') or '').strip()[:200], 'note':str(body.get('note') or '').strip()[:1000],
                'createdAt':timestamp,'createdBy':actor['id'],'createdByName':actor['name'],
                **({'settlementDueDate':schedule_dates[part['scheduleKey']]['dueDate']}
                   if schedule_dates.get(part['scheduleKey'],{}).get('swissFacility') and detail['amount'] > 0 else {})})
    from .accounting_rules import claim_balance_error
    from .payment_policy import collection_change_error
    for uid, payload in payloads.items():
        problem = collection_change_error(case_payload(cases[uid]), payload) or claim_balance_error(payload)
        if problem:return _error(400, 'collection_settlement_required', problem)
    results=[]
    for uid,case in cases.items():
        saved = view._save(request,{'rowVersion':case.row_version},case,payloads[uid],'record_payment',
                   {'operation':'record_transaction_payments','batchId':batch_id,'batchAmount':amount(total)})
        if saved.status_code != 200:
            from django.db import transaction
            transaction.set_rollback(True)
            return saved
        results.append({'caseUid':uid,'rowVersion':case.row_version})
    from rest_framework.response import Response
    return Response({'ok':True,'batchId':batch_id,'amount':amount(total),'cases':results})


def reverse_batch_payment(view, request, body):
    from .accounting_views import _can_edit, _error, _real_date, _iso_now
    from ri_system.authz import actor_from
    if not _can_edit(request.ri_principal):
        return _error(403,'permission_denied','Accounting write access is required.')
    bid=body.get('batchId')
    payment_date=body.get('paymentDate') or taipei_date()
    if not isinstance(bid,str) or not bid or not _real_date(payment_date):
        return _error(400,'invalid_payment','A batch and valid reversal date are required.')
    versions=body.get('cases')
    if not isinstance(versions,list) or not 1<=len(versions)<=200 or any(not isinstance(r,dict) or not isinstance(r.get('caseUid'),str) or isinstance(r.get('rowVersion'),bool) or not isinstance(r.get('rowVersion'),int) for r in versions):
        return _error(400,'invalid_payment','All affected case versions are required.')
    expected={r.get('caseUid'):r['rowVersion'] for r in versions}
    # The production source guard serializes all payment writes; locks below protect case saves.
    matches=[c.pk for c in Case.objects.all() if any(e.get('batchId')==bid and e.get('entryType')=='payment' for e in objects((c.payload or {}).get('paymentEntries')))]
    cases=list(Case.objects.select_for_update().filter(pk__in=matches).order_by('id'))
    if not cases:return _error(404,'batch_not_found','Remittance not found.')
    if set(expected)!={str(c.case_uid) for c in cases} or len(expected)!=len(versions):
        return _error(400,'incomplete_batch','Provide all affected case versions to reverse the whole remittance.')
    originals=[]
    for case in cases:
        batch_entries = [e for e in objects(case.payload.get('paymentEntries')) if e.get('batchId') == bid and e.get('entryType') == 'payment']
        claims = {t['txNo'] for t in objects(case.payload.get('transactions')) if t.get('source') == 'claim'}
        claim_only = bool(batch_entries) and all(e.get('transactionNo') in claims for e in batch_entries)
        if case.is_archived or case.recycled_at or (case.status not in ('posted','closed') and not (case.status == 'reversed' and claim_only)):
            return _error(409,'accounting_status_locked','All affected cases must be active and posted.')
        if expected[str(case.case_uid)]!=case.row_version:
            return _error(409,'version_conflict','An affected case changed. Refresh and try again.')
        entries=objects(case.payload.get('paymentEntries'))
        payments=[e for e in entries if e.get('batchId')==bid and e.get('entryType')=='payment']
        ids={e['id'] for e in payments}
        if any(e.get('entryType')=='reversal' and e.get('reversalOf') in ids for e in entries):
            return _error(409,'already_reversed','This remittance has already been reversed.')
        from .accounting_rules import entry_locked
        if any(entry_locked(case.payload, p) for p in payments):
            return _error(409, 'settled_amount_locked', 'Previously settled receipt/payment amounts cannot be edited or reversed.')
        probe = copy.deepcopy(case.payload)
        probe.setdefault('paymentEntries', []).extend({**p, 'entryType': 'reversal'} for p in payments)
        from .accounting_rules import claim_balance_error
        from .allianz_accounting import collection_change_error
        problem = collection_change_error(case.payload,probe) or claim_balance_error(probe)
        if problem:
            return _error(409, 'claim_collection_limit', problem)
        originals.extend(payments)
    if not str(body.get('note') or '').strip():
        return _error(400, 'correction_reason_required', 'Enter the reason for reversing these receipt/payment records.')
    actor=actor_from(request.ri_principal);timestamp=_iso_now();reversal_batch=str(uuid.uuid4())
    for case in cases:
        payload=copy.deepcopy(case.payload)
        entries=objects(payload.get('paymentEntries'))
        reversals=[]
        for original in entries:
            if original.get('entryType')!='payment' or original.get('batchId')!=bid:continue
            reversals.append({**original,'id':str(uuid.uuid4()),'entryType':'reversal',
                'reversalOf':original['id'],'reversalOfBatchId':bid,'batchId':reversal_batch,
                'paymentDate':payment_date,'note':str(body.get('note') or 'Correction reversal').strip()[:1000],
                'createdAt':timestamp,'createdBy':actor['id'],'createdByName':actor['name']})
        payload['paymentEntries']=[*entries,*reversals]
        saved = view._save(request,{'rowVersion':case.row_version},case,payload,'reverse_payment',{'batchId':bid,'reversalBatchId':reversal_batch})
        if saved.status_code != 200:
            from django.db import transaction
            transaction.set_rollback(True)
            return saved
    from rest_framework.response import Response
    return Response({'ok':True,'batchId':bid,'reversalBatchId':reversal_batch})
