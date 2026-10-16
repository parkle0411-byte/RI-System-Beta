"""Review-92 legacy repair: preview first, preserve handled money and closed reports."""
import copy,re
from collections import defaultdict
from .accounting_rules import objects,settled_once
from .calc.accounting import build_premium_transactions,build_claim_payment_transactions
from .calc.payment_terms import premium_installment_plan,taipei_date,add_calendar_days
from production import calc


def identity(tx):
    return (str(tx.get('installmentId') or 'FULL'),tx.get('legType'),tx.get('reinsurerIdx'))


def group(tx):
    no=str(tx.get('txNo') or '')
    normalized=re.sub(r'-(?:TX|T)[123]([ab]?)(?=-|$)',r'-T*\1',no)
    return normalized if normalized != no else str((tx.get('source'),tx.get('claimId'),tx.get('paymentId'),tx.get('installmentId'),tx.get('reinsurerIdx')))


def repair_payload(case, chain, reports, closed_months, fx, snapshots):
    from .claims_views import _split_source
    from production.closing import confirm_case
    from production.views import case_source
    from .calc.swiss_facility import case_payload
    original=case_payload(case);p=copy.deepcopy(original);changes=[];pending=[];next_status=case.status
    txs=objects(p.get('transactions'));by_no={t.get('txNo'):t for t in txs}
    entries=objects(p.get('paymentEntries'))
    locked={group(t) for t in txs if settled_once(p,t.get('txNo',''))}
    from .cash_ledger import _matches
    from .calc.payment_terms import build_payment_schedule
    schedule=build_payment_schedule(p)['items']
    for entry in entries:
        if entry.get('transactionNo') in by_no:locked.add(group(by_no[entry['transactionNo']]))
        else:
            item=next((i for i in schedule if i['scheduleKey']==entry.get('scheduleKey')),None)
            if item:
                locked.update(group(t) for t in txs if t.get('source')!='claim' and _matches(item,t))
    # Reallocating the rounding remainder across installments must preserve the
    # original total. Once any installment for a reinsurer has been handled,
    # leave that reinsurer's whole allocation unchanged for manual review.
    handled_reinsurers={t.get('reinsurerIdx') for t in txs if t.get('source')!='claim' and group(t) in locked}
    if handled_reinsurers and premium_installment_plan(p):
        for tx in txs:
            if tx.get('source')!='claim' and tx.get('reinsurerIdx') in handled_reinsurers:
                locked.add(group(tx))
        pending.append({'kind':'handled_installment_allocation','reinsurerIndexes':sorted(handled_reinsurers,key=str)})
    # Posting metadata comes only from an existing report / recorded timestamp.
    for tx in txs:
        if tx.get('source')=='claim':continue
        matches=[r for r in reports if any(str(row.get('caseId'))==str(case.pk) and
                 str(row.get('installmentId') or 'FULL')==str(tx.get('installmentId') or 'FULL') for row in r['rows'])]
        if matches:
            report=min(matches,key=lambda r:r['closed_at'])
            for key,value in [('postedMonth',report['year_month']),('createdAt',report['closed_at'].isoformat())]:
                if not tx.get(key):tx[key]=value;changes.append({'kind':'posting_metadata','txNo':tx.get('txNo'),'field':key,'after':value})
    candidates=build_premium_transactions(p)
    for installment in premium_installment_plan(p):candidates.extend(build_premium_transactions(p,installment))
    amounts={identity(t):t for t in candidates}
    for tx in txs:
        if tx.get('source')=='claim' or tx.get('reversed') or tx.get('isReversalEntry') or group(tx) in locked:continue
        target=amounts.get(identity(tx))
        if target and tx.get('amount')!=target.get('amount'):
            changes.append({'kind':'unprocessed_premium_amount','txNo':tx['txNo'],'before':tx.get('amount'),'after':target['amount']})
            tx['amount']=target['amount']
    # Recover claim creation time from one actual, consecutive payment snapshot.
    created={};previous=set();previous_version=None
    for snap in snapshots:
        data=snap['snapshot_data'];data=data.get('payload') or {}
        found={(str(c.get('id')),str(pay.get('id'))) for c in objects(data.get('claims')) for pay in objects(c.get('payments'))}
        added=found-previous
        if snap['snapshot_reason']=='claim_payment_recorded' and previous_version is not None and snap['entity_version']==previous_version+1 and len(added)==1:
            created[next(iter(added))]=snap['created_at'].isoformat()
        previous=found;previous_version=snap['entity_version']
    root=next((c for c in chain if not c.parent_case_id),case)
    for claim in objects(p.get('claims')):
        for payment in objects(claim.get('payments')):
            current=[t for t in txs if t.get('source')=='claim' and t.get('claimId')==claim.get('id') and t.get('paymentId')==payment.get('id')]
            stamp=payment.get('createdAt') or next((t.get('createdAt') for t in current if t.get('createdAt')),None) or created.get((str(claim.get('id')),str(payment.get('id'))))
            if not stamp:
                pending.append({'kind':'claim_creation_date','claimId':claim.get('id'),'paymentId':payment.get('id')});continue
            try:day=taipei_date(stamp)
            except (ValueError,TypeError,OverflowError):
                pending.append({'kind':'claim_creation_date','claimId':claim.get('id'),'paymentId':payment.get('id')});continue
            if not payment.get('createdAt'):payment['createdAt']=stamp;changes.append({'kind':'claim_creation_metadata','paymentId':payment.get('id')})
            for tx in current:
                for field,value in [('createdAt',stamp),('postedMonth',day[:7]),('dueDate',add_calendar_days(day,15))]:
                    if not tx.get(field):tx[field]=value;changes.append({'kind':'claim_metadata','txNo':tx.get('txNo'),'field':field,'after':value})
            if any(group(t) in locked for t in current):continue
            try:split=_split_source(root,chain,claim.get('dateOfLoss'))
            except ValueError:
                pending.append({'kind':'claim_split','claimId':claim.get('id'),'paymentId':payment.get('id')});continue
            desired=build_claim_payment_transactions({**p,'twRef':case.tw_ref},split.payload,claim,payment)
            # Do not guess a mapping if the set of parties/legs changed.
            lookup={(t.get('legType'),t.get('reinsurer')):t for t in desired}
            if {(t.get('legType'),t.get('reinsurer')) for t in current} != set(lookup):
                pending.append({'kind':'claim_party_mapping','claimId':claim.get('id'),'paymentId':payment.get('id')});continue
            basis={'caseUid':str(split.case_uid),'twRef':split.tw_ref,'reinsurers':copy.deepcopy(split.payload.get('reinsurers') or [])}
            if payment.get('splitSource') != basis:
                payment['splitSource']=basis;changes.append({'kind':'claim_split_metadata','paymentId':payment.get('id')})
            for tx in current:
                target=lookup[(tx.get('legType'),tx.get('reinsurer'))]
                if tx.get('amount')!=target['amount']:
                    changes.append({'kind':'unprocessed_claim_amount','txNo':tx['txNo'],'before':tx.get('amount'),'after':target['amount']});tx['amount']=target['amount']
    p['transactions']=txs
    # Backfill only zero-income installments whose original month is already closed.
    source=case_source(case);source['payload']=p
    for allocation in calc.installment_allocations(calc.normalize_source(source)):
        month=allocation['performanceMonth']
        if month not in closed_months:continue
        preview=calc.build_production_preview([source],month,{})
        rows=[row for row in preview.get('accountingRows',[]) if row['installmentId']==allocation['id']]
        if not rows:continue
        if any(t.get('source')!='claim' and not t.get('reversed') and not t.get('isReversalEntry') and (not t.get('installmentId') or t['installmentId']==allocation['id']) for t in txs):continue
        target=month
        while target in closed_months:target=calc.next_production_month(target)
        currency=str(p.get('currency') or case.currency or 'TWD').upper()
        if currency!='TWD' and (target,currency) not in fx:
            pending.append({'kind':'backfill_fx','month':target,'currency':currency});continue
        result=confirm_case(source,rows,posting_month=target)
        before=len(txs);p=result['payload'];txs=objects(p.get('transactions'));next_status=result['nextStatus'];source['payload']=p
        if len(txs)>before:changes.append({'kind':'zero_income_backfill','installmentId':allocation['id'],'originalMonth':month,'postedMonth':target,'transactionCount':len(txs)-before})
    return p,next_status,changes,pending
