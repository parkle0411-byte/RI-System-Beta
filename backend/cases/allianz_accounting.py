"""Allianz Facility settlement rules confirmed by the owner, 2026-10-19.

Cash records and manual settlement remain separate. The shared payment policy
requires both for the whole Cedant installment before a premium payment.
"""
import re

NAME='Allianz Global Corporate & Specialty SE, Hong Kong Branch (Facility)'
TERMS_DAYS=90
ACCOUNTING_LEAD_DAYS=10
FIELDS=('allianzFacility','allianzCase','offsetAllowed','cedantReceiptConfirmed',
        'paymentAllowed','paymentBlockedReason','sourceBaseDate','accountingLeadDays')


def objects(value):
    return [r for r in value if isinstance(r,dict)] if isinstance(value,list) else []


def is_allianz(name):
    return ' '.join(str(name or '').split()).casefold()==NAME.casefold()


def target(payload, name):
    return (isinstance(payload, dict)
            and str(payload.get('classOfBusiness') or '').strip().casefold() == 'property'
            and is_allianz(name))


def applies(payload):
    return any(target(payload, r.get('name')) for r in objects(payload.get('reinsurers')))


def selection_issues(payload):
    from .facility_selection import selection_issues as facility_issues
    return [issue for issue in facility_issues(payload)
            if issue["field"].startswith("reinsurers.")
            and is_allianz(payload["reinsurers"][int(issue["field"].split(".")[1])].get("name"))]


def payment_dates(payload,installment):
    from .calc.payment_terms import endorsement_base_date,month_end_date,add_calendar_days
    source=installment.get('baseDate','')
    if payload.get('parentTwRef') and payload.get('installmentEnabled') is not True:
        source=endorsement_base_date(payload)
    base=month_end_date(source)
    return source,base,add_calendar_days(base,90) if base else '',add_calendar_days(base,80) if base else ''


def apply_schedules(payload, items):
    if applies(payload):
        for item in items:
            if item['partyType'] == 'cedant' or item.get('allianzFacility'):
                item.update(allianzCase=True, offsetAllowed=False)
    return items


def claim_is_allianz(payload,tx):
    if tx.get('source')!='claim':return False
    source=tx.get('splitSource')
    source=source if isinstance(source,dict) else {}
    if not target({**payload,**source},NAME):return False
    if tx.get('allianzFacility') is True:return True
    split=tx.get('splitSource')
    if isinstance(split,dict):
        rows=objects(split.get('reinsurers'))
        match=re.search(r'-R([1-9][0-9]*)-T[12]$',str(tx.get('txNo') or ''))
        if match:
            index=int(match[1])-1
            return index<len(rows) and is_allianz(rows[index].get('name'))
    index=tx.get('reinsurerIdx')
    rows=objects(payload.get('reinsurers'))
    return (isinstance(index,(int,float)) and not isinstance(index,bool) and index>=0
            and int(index)==index and index<len(rows) and is_allianz(rows[int(index)].get('name')))


def collection_change_error(before, after):
    from .payment_policy import collection_change_error as check
    return check(before, after)


def claim_announced_at(payload,tx):
    from .calc.swiss_facility import local_date
    payment=next((p for c in objects(payload.get('claims')) if c.get('id')==tx.get('claimId')
                  for p in objects(c.get('payments')) if p.get('id')==tx.get('paymentId')), {})
    # Before this rule, successful obligation recording was already the posting
    # operation. Its server-createdAt is valid legacy evidence; payment.date,
    # policy Announce, Date of Loss and today's date are never substitutes.
    for value in (tx.get('claimAnnouncedAt'),payment.get('claimAnnouncedAt'),tx.get('createdAt'),payment.get('createdAt')):
        if local_date(value):return value
    return ''


def apply_details(payload, details, schedule, now):
    by_key = {r['scheduleKey']: r for r in schedule}
    for no, detail in details.items():
        if detail['_source'] == 'premium':
            rows = [by_key[p['scheduleKey']] for p in detail.get('cashParts', []) if p['scheduleKey'] in by_key]
            target = [r for r in rows if r.get('allianzFacility')]
            if target:
                detail.update(allianzFacility=True, allianzCase=True, offsetAllowed=False)
            elif applies(payload) and detail['partyType'] == 'cedant':
                detail.update(allianzCase=True, offsetAllowed=False)
        elif claim_is_allianz(payload, detail['_tx']):
            detail['allianzCaseClaim'] = True
            if detail['partyType'] == 'reinsurer':
                detail.update(allianzClaim=True, trackingHistory=[h for h in objects(payload.get('allianzClaimTracking')) if h.get('txNo') == no])
    return details


def record_followup(view,request,body):
    from .accounting_views import _can_edit,_error,_iso_now
    from .calc.swiss_facility import case_payload
    from .cash_ledger import transaction_details
    from ri_system.authz import actor_from
    if not _can_edit(request.ri_principal):return _error(403,'permission_denied','Accounting write access is required.')
    case=view._load_case_for_update(str(body.get('caseUid') or ''))
    if not case:return _error(404,'case_not_found','Case not found.')
    if case.status not in ('posted','closed','reversed'):
        return _error(409,'accounting_status_locked','Select an announced claim obligation.')
    if case.row_version!=body.get('rowVersion'):return _error(409,'version_conflict','Refresh Accounting before recording follow-up.')
    no=body.get('txNo')
    if not isinstance(no,str):return _error(400,'invalid_transaction','Select one claim receivable.')
    payload=case_payload(case);detail=transaction_details(payload).get(no,{})
    tx=next((t for t in objects(payload.get('transactions')) if t.get('txNo')==no),{})
    if not detail.get('allianzClaim') or tx.get('reversed') or tx.get('isReversalEntry') or abs(detail.get('outstanding',0))<=.004:
        return _error(400,'claim_followup_not_allowed','Select an outstanding Allianz claim receivable.')
    note=str(body.get('note') or '').strip()[:1000]
    if not note:return _error(400,'followup_note_required','Enter the follow-up record.')
    actor=actor_from(request.ri_principal)
    payload.setdefault('allianzClaimTracking',[]).append({'txNo':no,'recordedAt':_iso_now(),
        'recordedBy':actor['id'],'recordedByName':actor['name'],'note':note})
    payload.setdefault('paymentEntries',[])
    return view._save(request,body,case,payload,'record_allianz_claim_followup',{'txNo':no})
