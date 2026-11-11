"""Production rows from formal standalone transactions, never historical imports."""
import copy
import hashlib
import json
from .models import LegacyTransaction
from .services import rate_for, audit, fail


def report_sources(month):
    # Imported Register rows (batch set) never feed Production (owner 2026-11-11: Revenue Month is data only).
    return LegacyTransaction.objects.filter(status='confirmed',historical=False,batch__isnull=True,revenue_month=month,data__kind='endorsement').select_related('corrects').order_by('uid')


def append_preview(preview,month):
    from production.calc import month_end
    transactions=list(report_sources(month))
    if not transactions:return preview  # Keep native no-legacy signatures intact.
    result=copy.deepcopy(preview); signatures=[]
    missing=set(result['missingRateCurrencies'])
    for t in transactions:
        d=t.data;fx=rate_for(t);signatures.append([str(t.uid),t.version,d,fx])
        pending=fx.get('rate') is None
        if pending:missing.add(t.currency)
        people=fx.get('people') or [dict(name=d.get('ae',''),income=None,premium=None)]
        for i,person in enumerate(people):
            uid=str(t.uid);key=f'legacy:{uid}'
            result['rows'].append(dict(id=f'{key}:{i}',key=key,reinsurerKey='legacy-party',caseId=key,
                caseUid=uid,caseRowVersion=t.version,legacyTransactionId=uid,installmentId='FULL',month=month,
                originalInsured=d.get('insured',''),reinsured=d.get('cedant',''),reinsurer=d.get('party',''),
                classCode='PD',type=d.get('newRenew',''),currency=t.currency,rate=fx.get('rate'),missingRate=pending,
                ae=person['name'],effDate=d.get('effectiveDate',''),expDate=d.get('expiryDate',''),
                comm=d.get('commissionRate',0),premium=person.get('premium'),income=person.get('income'),
                policyNo=d.get('policyNo',''),firstPolicyNo=t.reference,endorseNo=d.get('endorsementNo',''),
                remark='Fac',tranxDate=month_end(month),installment=d.get('installmentNo','')))
    result['missingRateCurrencies']=sorted(missing)
    # Source and inherited FX are both part of the signature. An original-currency
    # posting remains valid while this signature prevents stale report closes.
    extra=json.dumps(signatures,sort_keys=True,separators=(',',':'),ensure_ascii=False)
    result['sourceSignature'] += '|legacy:'+hashlib.sha256(extra.encode()).hexdigest()
    return result


def freeze_report(person,rows):
    ids={r['legacyTransactionId'] for r in rows if r.get('legacyTransactionId')}
    records=list(LegacyTransaction.objects.select_for_update().filter(pk__in=ids).select_related('corrects'))
    if len(records)!=len(ids):fail('A legacy Production source is no longer available.',409)
    for t in records:
        if t.status!='confirmed' or t.historical:fail('A legacy Production source changed.',409)
        snapshot=rate_for(t)
        if snapshot.get('rate') is None:fail('Resolve missing FX before closing Production.',409)
        before=copy.deepcopy(t.fx_snapshot)
        t.fx_snapshot=snapshot;t.save(update_fields=['fx_snapshot'])
        audit(person,t.uid,'production_fx_frozen',before,copy.deepcopy(snapshot))
