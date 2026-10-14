"""Atomic cash allocations to immutable, existing transactions."""
import copy
import uuid
from .cash_ledger import amount, cents, objects, proportions, transaction_details
from .models import Case
from .calc.payment_terms import taipei_date, build_payment_schedule
from .calc.swiss_facility import payment_error, case_payload


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
        if case.status not in ('posted','closed'):
            return _error(409,'accounting_status_locked','Only posted transactions can receive payments.')
        if case.row_version!=row['rowVersion']:
            return _error(409,'version_conflict','A selected case changed. Refresh Accounting and try again.')
        if row['caseUid'] not in details:
            details[row['caseUid']]=transaction_details({**case_payload(case),'currency':case.payload.get('currency') or case.currency,'reinsured':case.payload.get('reinsured') or case.reinsured_name_snapshot})
        detail=details[row['caseUid']].get(row['txNo'])
        if not detail or not detail['canRecord']:
            return _error(400,'transaction_not_payable','This transaction cannot receive a cash allocation.')
        blocked = payment_error(detail, amount(row['value']))
        if blocked:
            return _error(400, 'swiss_payment_blocked', blocked)
        if row['value']>abs(cents(detail['outstanding'])):
            return _error(400,'overpayment','Allocation cannot exceed the transaction balance.')
        if payment_group is not None and detail['paymentGroup']!=payment_group:
            return _error(400,'incompatible_allocations','Use the same currency, cash direction and counterparty in one remittance.')
        payment_group=detail['paymentGroup']
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
    results=[]
    for uid,case in cases.items():
        view._save(request,{'rowVersion':case.row_version},case,payloads[uid],'record_payment',
                   {'operation':'record_transaction_payments','batchId':batch_id,'batchAmount':amount(total)})
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
        if case.is_archived or case.recycled_at or case.status not in ('posted','closed'):
            return _error(409,'accounting_status_locked','All affected cases must be active and posted.')
        if expected[str(case.case_uid)]!=case.row_version:
            return _error(409,'version_conflict','An affected case changed. Refresh and try again.')
        entries=objects(case.payload.get('paymentEntries'))
        payments=[e for e in entries if e.get('batchId')==bid and e.get('entryType')=='payment']
        ids={e['id'] for e in payments}
        if any(e.get('entryType')=='reversal' and e.get('reversalOf') in ids for e in entries):
            return _error(409,'already_reversed','This remittance has already been reversed.')
        originals.extend(payments)
    if sum(abs(cents(e['amount'])) for e in originals)!=cents(originals[0]['batchAmount']):
        return _error(409,'incomplete_batch','The complete remittance is required for reversal.')
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
        view._save(request,{'rowVersion':case.row_version},case,payload,'reverse_payment',{'batchId':bid,'reversalBatchId':reversal_batch})
    from rest_framework.response import Response
    return Response({'ok':True,'batchId':bid,'reversalBatchId':reversal_batch})
