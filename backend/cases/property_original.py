"""Shared premium ledgers and Property-only underwriting validation.

The server owns the accounting version. Protected historical calculations and
recognized Production facts retain their original amounts and precision.
"""
import copy
import re
from decimal import Decimal, ROUND_HALF_UP

VERSION = 'property-original-v1'
VERSION_KEY = 'propertyOriginalRules'
POSTCODE = re.compile(r'(?=.*[A-Za-z0-9])[A-Za-z0-9 -]+\Z')
DESCRIPTION_FIELDS = frozenset(('occupation', 'construction', 'specialAgreement', 'interest',
    'deductibles', 'originalConditions', 'basisOfValuation', 'basisOfValuationOther',
    'reinsuredRetention', 'expressWarranties', 'conditionsPrecedent', 'subjectivities',
    'originalExclusions', 'reinstatementProvisions', 'indemnityPeriod', 'lossRecordText',
    'constructionSelections','constructionLegacyText','constructionLegacyConfirmed','constructionSelectionVersion',
    'notices', 'coReinsuranceWarranty', 'selfInsuredRetention', 'lossPayee', 'remark', 'clauseDetails', 'clauses', 'autoClauses', 'manualClauses',
    'originalInsured', 'originalInsuredCn', 'newOrRenew', 'type', 'typePrefix', 'situations',
    'sumInsured', 'limitOfLiability', 'aggregateLimit', 'subLimits', 'lossAdvisedDate',
    'lossRecordYears', 'lossRecord', 'ownerPersonnelId', 'ownerPersonnelName'))
SERVER_FIELDS = (VERSION_KEY, 'propertyEditHistory', 'productionHistory', 'productionReversals',
                 'propertyReversalHistory', 'propertyDateOverrides', 'accountingRules', 'accountingLegacyMath', 'premiumLedgerLayout', 'accountingLayoutHistory')


def rows(value):
    return [r for r in value if isinstance(r, dict)] if isinstance(value, list) else []


def scope(p):
    return (isinstance(p, dict) and str(p.get('reinsuranceStructure') or '').upper() == 'QS'
            and (str(p.get('classCode') or '').upper() == 'PD' or p.get('classOfBusiness') == 'Property')
            and not p.get('parentTwRef'))


def ordinary(p):
    from .payment_policy import kind
    named = [r for r in rows(p.get('reinsurers')) if r.get('name')]
    return all(kind(p, r['name']) == 'ordinary' for r in named)


def enabled(p):
    from .accounting_policy import scope as accounting_scope
    return accounting_scope(p)


def eligible(p):
    from .accounting_rules import premium_activity
    return not (p.get('confirmedProductionKeys') or p.get('productionHistory') or premium_activity(p)
                or p.get('pendingReversalOffset') or any(t.get('settlement') == 'settled' or t.get('reversed') or t.get('isReversalEntry') for t in rows(p.get('transactions'))))


def adopt(p, old=None):
    from .accounting_policy import adopt as adopt_accounting
    adopt_accounting(p,old)
    if old and old.get(VERSION_KEY):
        p[VERSION_KEY] = VERSION if scope(p) and ordinary(p) and not ordinary(old) and eligible(old) else old[VERSION_KEY]
    elif scope(p) and ordinary(p):
        p[VERSION_KEY] = VERSION if eligible(old or p) else 'historical'
    from .premium_ledger import adopt_layout
    adopt_layout(p, old)
    for key in SERVER_FIELDS[1:]:
        if old and key in old:
            p[key] = copy.deepcopy(old[key])


def num(value):
    try:
        from .calc.jsnum import js_trim
        n = Decimal(js_trim(str(value or 0)).replace(',', ''))
        return n if n.is_finite() else Decimal(0)
    except Exception:
        return Decimal(0)


def money(value, p):
    precision = Decimal('1') if p.get('currency') == 'TWD' and p.get('premiumRounding') != 'legacy-cents' else Decimal('.01')
    return float(num(value).quantize(precision, rounding=ROUND_HALF_UP))


def allocate(total, weights, p):
    weights = [max(Decimal(0), num(w)) for w in weights]
    denominator = sum(weights)
    if not denominator:
        return [0.0] * len(weights)
    values = [money(num(total) * w / denominator, p) for w in weights]
    unit = Decimal(1) if p.get('currency') == 'TWD' and p.get('premiumRounding') != 'legacy-cents' else Decimal('.01')
    remainder = int((num(total) - sum(map(num, values))) / unit)
    order = sorted((i for i,w in enumerate(weights) if w), key=lambda i: (-weights[i], i))
    # Highest share absorbs the tail first; tied shares retain Case order.
    for i in order:
        if not remainder:
            break
        delta = remainder
        if total >= 0 and delta < 0:
            delta = max(delta, -int(num(values[i]) / unit))
        values[i] = money(num(values[i]) + delta * unit, p)
        remainder -= delta
    return values


def totals(p):
    from .accounting_policy import legacy_math
    if legacy_math(p):
        from .calc.accounting import calc_legs_for_reinsurer
        source={**p,'_legacyCalculation':True}
        legs=[calc_legs_for_reinsurer(source,r) for r in rows(p.get('reinsurers'))]
        names={'cedantPremium':'cp','cedantCommission':'ri','cedantTax':'tax','leg1':'leg1','reinsurerPremium':'reinsurerCp','reinsurerDeductions':'reinsurerRi','reinsurerTax':'reinsurerTax','leg2':'leg2','leg3':'leg3','brokerage':'brokerage'}
        result={key:money(sum(num(r[field]) for r in legs),p) for key,field in names.items()}
        result.update(t2s=[r['leg2'] for r in legs],components=[dict(premium=r['reinsurerCp'],deduction=r['reinsurerRi'],tax=r['reinsurerTax'],t2=r['leg2']) for r in legs])
        return result
    reinsurers = rows(p.get('reinsurers'))
    percent = sum(num(r.get('sharePct')) for r in reinsurers) / 100
    cp = money(num(money(p.get('originalPremium'),p)) * percent,p)
    commission = money(num(cp) * num(p.get('riCommPct')) / 100,p)
    tax = money(num(cp) * num(p.get('taxPct')) / 100,p)
    t1 = money(num(cp)-num(commission)-num(tax),p)
    t2s, rcp, deductions, rtax = [], [], [], []
    for r in reinsurers:
        base = money(num(money(r.get('premium'),p)) * num(r.get('sharePct')) / 100,p)
        deduction = money(num(base)*num(r.get('riCommPct'))/100,p)
        tax_ri = money(num(base)*num(r.get('taxPct'))/100,p)
        rcp.append(base); deductions.append(deduction); rtax.append(tax_ri)
        t2s.append(money(num(base)-num(deduction)-num(tax_ri),p))
    t2 = money(sum(map(num,t2s)),p)
    t3 = money(num(t1)-num(t2),p)
    return dict(cedantPremium=cp,cedantCommission=commission,cedantTax=tax,leg1=t1,
        reinsurerPremium=money(sum(map(num,rcp)),p),reinsurerDeductions=money(sum(map(num,deductions)),p),
        reinsurerTax=money(sum(map(num,rtax)),p),leg2=t2,leg3=t3,brokerage=t3,t2s=t2s,components=[dict(premium=a,deduction=b,tax=c,t2=d) for a,b,c,d in zip(rcp,deductions,rtax,t2s)])


def periods(p):
    from .calc.payment_terms import payment_installments, allocate as allocate_periods
    from .accounting_policy import legacy_math
    installments = payment_installments(p)
    full = totals(p)
    legacy_legs=[]
    if legacy_math(p):
        from .calc.accounting import calc_legs_for_reinsurer
        legacy_legs=[calc_legs_for_reinsurer({**p,'_legacyCalculation':True},r) for r in rows(p.get('reinsurers'))]
    from .premium_ledger import per_reinsurer
    allocated = allocate(full['leg1'], [r.get('sharePct') for r in rows(p.get('reinsurers'))], p)
    split_t1s = [allocate_periods(value, installments, p) for value in allocated] if per_reinsurer(p) else []
    old_t1s=[allocate_periods(r['leg1'],installments,p) for r in legacy_legs]
    t1s = [money(sum(num(v[i]) for v in old_t1s),p) for i in range(len(installments))] if legacy_legs else allocate_periods(full['leg1'],installments,p)
    t2s = [allocate_periods(t,installments,p) for t in full['t2s']]
    result=[]
    for i,r in enumerate(installments):
        amounts=[v[i] for v in t2s]
        shares=[v[i] for v in split_t1s] if split_t1s else [v[i] for v in old_t1s] if legacy_legs else allocate(t1s[i],[r.get('sharePct') for r in rows(p.get('reinsurers'))],p)
        if split_t1s: t1s[i] = money(sum(map(num, shares)), p)
        result.append({**r,'number':i+1,'t1':t1s[i],'t2s':amounts,
                       't1shares':shares,'t3':money(num(t1s[i])-sum(map(num,amounts)),p)})
    return result


def transactions(p, now, old=()):
    refs = str(p.get('twRef') or '')
    cycle = int(p.get('reversalCycle') or 0)
    previous={t.get('txNo'):t for t in rows(list(old))}
    result=[]
    for period in periods(p):
        suffix = f"-I{period['number']}" if p.get('installmentEnabled') else ''
        suffix += f'-C{cycle}' if cycle else ''
        common={'installmentId':period['id'],'installmentLabel':period['label'], 'source':'premium',
                'createdAt':now,'postedMonth':'','productionRecognized':False, 'settlement':'open'}
        entries=[dict(txNo=f'{refs}-T1{suffix}',legType='Leg 1',label='Receivable from Cedant',
                      amount=period['t1'],reinsurer='',reinsurerIdx=None,caseAggregate=True),
                 dict(txNo=f'{refs}-T3{suffix}',legType='Leg 3',label='Brokerage retained',
                      amount=period['t3'],reinsurer='',reinsurerIdx=None,caseAggregate=True)]
        for index,(r,value) in enumerate(zip(rows(p.get('reinsurers')),period['t2s'])):
            from .calc.accounting import strip_facility_tag
            name=r.get('foreignBroker') or strip_facility_tag(r.get('name')) or ''
            entries.append(dict(txNo=f'{refs}-R{index+1}-T2{suffix}',legType='Leg 2',
                label='Payable to '+name,amount=value,reinsurer=name,reinsurerIdx=index,
                viaForeignBroker=bool(r.get('foreignBroker'))))
        from .premium_ledger import per_reinsurer
        if per_reinsurer(p):
            entries=[]
            for index, r in enumerate(rows(p.get('reinsurers'))):
                if num(r.get('sharePct')) <= 0: continue
                from .calc.accounting import strip_facility_tag
                name=r.get('foreignBroker') or strip_facility_tag(r.get('name')) or ''
                t1, t2=period['t1shares'][index], period['t2s'][index]
                for leg, value, label in [(1,t1,'Receivable from Cedant'),(2,t2,'Payable to '+name),(3,money(num(t1)-num(t2),p),'Brokerage retained')]:
                    entries.append(dict(txNo=f'{refs}-R{index+1}-T{leg}{suffix}', legType=f'Leg {leg}',
                        label=label, amount=value, reinsurer=name, reinsurerName=strip_facility_tag(r.get('name')), reinsurerIdx=index,
                        viaForeignBroker=bool(r.get('foreignBroker')), perReinsurer=True))
        for entry in entries:
            tx={**common,**entry}
            prior=previous.get(tx['txNo'])
            if prior and prior.get('amount') == tx['amount'] and prior.get('reinsurer') == tx['reinsurer']:
                tx={**tx,**prior}
            if entry.get('perReinsurer'):tx['reinsurerName']=entry['reinsurerName']
            result.append(tx)
    return result


def refresh_transactions(p, now):
    live=rows(p.get('transactions'))
    historical=[t for t in live if t.get('source')=='claim' or t.get('reversed') or t.get('isReversalEntry')]
    p['transactions']=[*historical,*transactions(p,now,old=[t for t in live if t not in historical])]


def apply_schedules(p, items):
    if not enabled(p):
        return items
    from .payment_policy import actual_cash
    for item in items:
        cleared=abs(item['outstanding']) < .005
        item.update(manualSettlementRequired=False,manualSettlementConfirmed=cleared,
            canConfirmSettlement=False,canCancelSettlement=False,settlement='settled' if cleared else 'open')
        if cleared:item['status']='settled'
    refunds=[r for r in items if r['partyType']=='reinsurer' and r['amount']<0]
    refunds_ready=bool(refunds) and all(r['settlement']=='settled' and actual_cash(p,r) for r in refunds)
    for item in items:
        if item['partyType']=='reinsurer' and item['amount']>0:
            cedants=[r for r in items if r['partyType']=='cedant' and r['installmentId']==item['installmentId']]
            ready=bool(cedants) and all(r.get('settlement')=='settled' and actual_cash(p,r) for r in cedants)
            reason='' if ready else 'Receive the full Cedant installment, including every reinsurer share, before recording the premium payment.'
            if ready and item.get('swissFacility') and not item.get('statementReference'):
                ready=False;reason='Enter the Swiss settlement statement reference after the full Cedant receipt before recording payment.'
            item.update(paymentAllowed=ready,paymentBlockedReason=reason)
        if item['partyType']=='cedant' and item['amount']<0:
            item.update(paymentAllowed=refunds_ready,paymentBlockedReason='' if refunds_ready else
                'Record the full cash receipts of every reinsurer refund before refunding the entire Cedant endorsement.')
        item['offsetAllowed']=False
    return items


def apply_details(p, details, now=None):
    if not enabled(p):
        return details
    from .accounting_policy import apply_claim_details
    from .accounting_rules import settled_once
    apply_claim_details(p,details,now)
    from .swiss_cgl import target as swiss_cgl, preserve_completed_dates
    if swiss_cgl(p):
        preserve_completed_dates(p,details,now)
    for d in details.values():
        if d['_historic'] or d['_source'] not in ('premium','claim') or d['_leg']=='3':continue
        if d['_tx'].get('settledDates'):d.update(d['_tx']['settledDates'])
        cleared=abs(d['outstanding'])<.005
        locked=settled_once(p,d['_tx']['txNo']) or cleared
        d.update(settlement='settled' if cleared else 'partial' if abs(d['paid'])>.004 else 'open',manualSettlementRequired=False,
            manualSettlementConfirmed=cleared,canConfirmSettlement=False,canCancelSettlement=False,
            amountEditLocked=locked,settlementFinalized=locked,canRecord=d['canRecord'] and not locked,offsetAllowed=False)
        if cleared:d['paymentStatus']='settled'
        if d['_source']=='premium' and d['partyType']=='cedant' and d['amount']<0:
            d['refundWholeEndorsement']=True
    for d in details.values():
        if d['_source']!='premium' or d['_historic'] or d['_leg']!='3':continue
        dependencies=[v for v in details.values() if v['_source']=='premium' and not v['_historic']
            and v['_leg'] in ('1','2') and v['_tx'].get('installmentId')==d['_tx'].get('installmentId')
            and (not d['_tx'].get('perReinsurer') or v['_tx'].get('reinsurerIdx')==d['_tx'].get('reinsurerIdx'))]
        cleared=(not d['_tx'].get('perReinsurer') and abs(d['amount'])<.005) or bool(dependencies) and all(v['settlement']=='settled' for v in dependencies)
        d.update(settlementDependencies=[{'txNo':v['_tx']['txNo'],'settlement':v['settlement']} for v in dependencies],
            settlement='settled' if cleared else 'open',manualSettlementRequired=False,
            manualSettlementConfirmed=cleared,canConfirmSettlement=False,canCancelSettlement=False,
            amountEditLocked=cleared,settlementFinalized=cleared,paid=d['amount'] if cleared else 0,
            outstanding=0 if cleared else d['amount'],paymentStatus='settled' if cleared else 'open')
    locked_periods={d['_tx'].get('installmentId') for d in details.values()
        if d['_source']=='premium' and not d['_historic'] and d['_leg']=='3'
        and d['_tx'].get('perReinsurer') and d['settlement']=='settled'}
    for d in details.values():
        if d['_source']=='premium' and not d['_historic'] and d['_leg'] in ('2','3') and d['_tx'].get('installmentId') in locked_periods:
            d['amountEditLocked']=True
            d['periodAmountLocked']=True
    return details


def persist_settlements(p, now, actor=None):
    if not enabled(p):return
    from .cash_ledger import transaction_details
    from .calc.payment_terms import build_payment_schedule
    from .calc.swiss_facility import fingerprint
    details=transaction_details(p,now)
    for tx in rows(p.get('transactions')):
        d=details.get(tx.get('txNo'),{})
        if d.get('settlement')=='settled' and tx.get('settlement')!='settled' and not tx.get('reversed') and not tx.get('isReversalEntry'):
            tx.update(settlement='settled',settledAt=now,settledBy=(actor or {}).get('id'),settlementSource='automatic',
                settledDates={k:d.get(k) for k in ('baseDate','dueDate','contractDueDate','termsDays','reminderDate','paymentRule') if d.get(k) is not None})
    for item in build_payment_schedule(p,now)['items']:
        if not item.get('requiresCollectionConfirmation') or abs(item['outstanding'])>.004:continue
        matching=[tx for tx in rows(p.get('transactions')) if not tx.get('reversed') and not tx.get('isReversalEntry')
            and tx.get('source')!='claim' and any(part['scheduleKey']==item['scheduleKey'] for part in details.get(tx.get('txNo'),{}).get('cashParts',[]))]
        if not matching or not all(tx.get('settlement')=='settled' for tx in matching):continue
        confirmations=p.setdefault('swissAccounting',{}).setdefault('confirmations',{})
        prior=confirmations.get(item['scheduleKey'],{})
        mark=fingerprint(p,item['scheduleKey'])
        if prior.get('confirmed') and prior.get('fingerprint')==mark:continue
        stamp=max((tx.get('settledAt') or now for tx in matching),default=now)
        confirmations[item['scheduleKey']]={'confirmed':True,'confirmedAt':stamp,'confirmedBy':(actor or {}).get('id'),
            'source':'automatic settlement','fingerprint':mark}


def field_issues(p):
    if not scope(p):
        return []
    from .payment_policy import kind
    result=[]
    def add(field,label):result.append({'field':field,'label':label})
    def filled(value):return value is not None and str(value).strip()!=''
    for key,label in [('originalInsuredCn','Original insured (CN)'),('reinsuredRetention',"Reinsured's Retention"),
                      ('riCommPct','Cedant Commission'),('taxPct','Cedant Tax'),('paymentTermsDays','Cedant Payment Terms (Days)')]:
        if not filled(p.get(key)):add(key,label)
    if p.get('policyFrom') and p.get('policyTo') and p['policyTo']<=p['policyFrom']:
        add('policyTo','Expiration date must be later than Effective date')
    if sum(num(r.get('sharePct')) for r in rows(p.get('reinsurers'))) > 100:
        add('reinsurers','Total Order Hereon must not exceed 100%')
    if not filled(p.get('typePrefix')):add('type','Type')
    if num(p.get('originalPremium'))<=0:add('originalPremium','100% Premium must be greater than 0')
    for i,r in enumerate(rows(p.get('reinsurers'))):
        if num(r.get('premium'))<=0:add(f'reinsurers.{i}.premium',f'Reinsurer {i+1} Premium must be greater than 0')
        if kind(p,r.get('name'))=='ordinary' and not filled(r.get('paymentTermsDays')):add(f'reinsurers.{i}.paymentTermsDays',f'Reinsurer {i+1} Payment Terms (Days)')
    if filled(p.get('aggregateLimit')) and num(p['aggregateLimit'])<=0:
        add('aggregateLimit','Aggregate Limit must be greater than 0')
    if p.get('splitEnabled'):
        parties=rows(p.get('splitParties'))
        if len(parties)!=2 or (num(parties[0].get('pct')),num(parties[1].get('pct'))) not in ((40,60),(70,30)):
            add('splitParties','Reinsurance Staff / Other Staff split must be 40% / 60% or 70% / 30%')
    if p.get('installmentEnabled'):
        for i,r in enumerate(rows(p.get('performanceInstallments'))):
            if num(r.get('premium'))<=0:add(f'performanceInstallments.{i}.premium',f'Installment {i+1} Premium must be greater than 0')
            if not filled(r.get('paymentTermsDays')):add(f'performanceInstallments.{i}.paymentTermsDays',f'Installment {i+1} Cedant Payment Terms (Days)')
            for j,ri in enumerate(rows(p.get('reinsurers'))):
                from .payment_policy import kind
                if kind(p,ri.get('name'))=='ordinary' and not filled((r.get('reinsurerPaymentTerms') or {}).get(f'r{j+1}')):
                    add(f'performanceInstallments.{i}.reinsurerPaymentTerms.r{j+1}',f'Installment {i+1} Reinsurer {j+1} Payment Terms (Days)')
    return result


def report_values(p, period):
    from .accounting_policy import legacy_math
    if legacy_math(p):
        from .calc.accounting import calc_legs_for_reinsurer
        from .calc.payment_terms import allocate as installment_allocate, payment_installments
        old=[calc_legs_for_reinsurer({**p,'_legacyCalculation':True},r) for r in rows(p.get('reinsurers'))]
        index=period['number']-1
        premiums=[installment_allocate(r['cp'],payment_installments(p),p)[index] for r in old]
        return premiums,[money(num(a)-num(b),p) for a,b in zip(period['t1shares'],period['t2s'])]
    premium = totals(p)['cedantPremium']
    weights=[r['weight'] for r in periods(p)]
    from .calc.payment_terms import allocate as installment_allocate
    premium_periods=installment_allocate(premium,periods(p),p)
    index=period['number']-1
    premiums=allocate(premium_periods[index],[r.get('sharePct') for r in rows(p.get('reinsurers'))],p)
    incomes=[money(num(t1)-num(t2),p) for t1,t2 in zip(period['t1shares'],period['t2s'])]
    return premiums,incomes


def confirmed_facts(p, key):
    try:
        period_key,index=str(key).rsplit(':R',1)
        period_key=period_key.split(':',1)[1]
        period=next(r for r in periods(p) if (r['id'] if p.get('installmentEnabled') else 'FULL')==period_key)
        i=int(index);r=rows(p.get('reinsurers'))[i]
        premiums,incomes=report_values(p,period)
        return (p.get('currency'),premiums[i],incomes[i],r.get('name'),r.get('foreignBroker'),
            p.get('policyFrom'),p.get('policyTo'),
            period.get('performanceMonth') if p.get('installmentEnabled') else None,
            [(r.get('personnelId'),r.get('name'),r.get('pct')) for r in rows(p.get('splitParties'))]
                if p.get('splitEnabled') else p.get('ae'))
    except (ValueError,IndexError,KeyError,StopIteration):
        return None


def edit_guard(case, p, body, actor, now):
    """Return an error message, or update the candidate with audited, guarded ledger changes."""
    old=case.payload
    if not enabled(old):
        return ''
    adopt(p,old)
    p['confirmedProductionKeys']=copy.deepcopy(old.get('confirmedProductionKeys') or [])
    for key in ('productionPartiallyConfirmed','announcedAt','twRef','postedAt'):
        if key in old:p[key]=copy.deepcopy(old[key])
    if case.status=='draft':
        return ''
    # Editing a reversed case creates a fresh Draft; Review / Announce is repeated.
    if case.status=='reversed':
        reason=str(body.get('reason') or '').strip()[:2000]
        if not reason:return 'Enter a reason for correcting the reversed Case.'
        p.setdefault('propertyEditHistory',[]).append({'at':now,'by':actor.get('id'),'byName':actor.get('name'),'reason':reason,'operation':'reverse_correction'})
        p['transactions']=copy.deepcopy(old.get('transactions') or [])
        p['confirmedProductionKeys']=[]
        return ''
    mutable=set(DESCRIPTION_FIELDS)|{'ae','originalPremium','riCommPct','taxPct','currency','reinsurers',
        'policyFrom','policyTo','performanceInstallments','installmentEnabled','paymentTermsDays','splitParties','splitEnabled','endoEffectiveDate'}
    ignored=set(SERVER_FIELDS)|{'transactions','paymentEntries','claims','facilityAccounting','swissAccounting',
        'status','confirmedProductionKeys','productionPartiallyConfirmed','premiumRounding','cedantTermsBasis',
        'paymentTermsHistory','paymentEditHistory','claimCorrectionHistory','accountingAdjustmentHistory','accountingRules','accountingLegacyMath','insuredDirectoryEnabled','accountingLayoutHistory'}
    changed={k for k in set(old)|set(p) if k not in ignored and old.get(k)!=p.get(k)}
    # Normalization may add empty compatibility fields; they are not business changes.
    changed={k for k in changed if old.get(k) not in (None,'',[],{}) or p.get(k) not in (None,'',[],{})}
    if not changed:
        return ''
    financial_fields={'ae','originalPremium','riCommPct','taxPct','currency','reinsurers',
        'policyFrom','policyTo','performanceInstallments','installmentEnabled','paymentTermsDays',
        'splitParties','splitEnabled','endoEffectiveDate','reinsured','classOfBusiness','classCode',
        'reinsuranceStructure','parentTwRef'}
    if not (scope(old) and ordinary(old)) and not changed & financial_fields:
        # Other classes keep their existing wording/coverage edit workflow.
        # Their ledger, cash and Production data were restored by the caller.
        return ''
    if changed-mutable:
        return 'After Announce, change only the approved financial or document description fields.'
    reason=str(body.get('reason') or '').strip()[:2000]
    if not reason:
        return 'Enter a reason for changing an Announced or Confirmed case.'
    if p.get('currency') != old.get('currency') and old.get('paymentEntries'):
        return 'Currency is locked after any receipt or payment record, including claims.'
    from .draft import validate_announce_ready
    prior_issues={r['field'] for r in validate_announce_ready(old,allow_zero_loss_years=True)}
    new_issues=[r for r in validate_announce_ready(p,allow_zero_loss_years=True) if r['field'] not in prior_issues]
    if new_issues:return 'Keep all required Announced fields valid: '+new_issues[0]['label']
    if not enabled(p):
        if not eligible(old):return 'Changing the accounting scheme is locked by accounting or Production history.'
        p[VERSION_KEY]='historical'
        p['transactions']=[t for t in rows(old.get('transactions')) if t.get('source')=='claim' or t.get('reversed') or t.get('isReversalEntry')]
        p.setdefault('propertyEditHistory',[]).append({'at':now,'by':actor.get('id'),'reason':reason,'operation':'facility_rules_selected','reinsurersBefore':old.get('reinsurers'),'reinsurersAfter':p.get('reinsurers')})
        return ''
    # Keep automatic installment defaults in step with their sources until manually overridden.
    prior_periods={r.get('id'):r for r in rows(old.get('performanceInstallments'))}
    for i,r in enumerate(rows(p.get('performanceInstallments'))):
        before=prior_periods.get(r.get('id'),{})
        recognized=any(str(key).split(':',1)[-1].rsplit(':R',1)[0]==r.get('id') for key in old.get('confirmedProductionKeys') or [])
        if recognized:
            if r.get('performanceMonth')!=before.get('performanceMonth') and r.get('performanceMonthManual'):
                return 'Performance Month is locked after Production confirmation.'
            r['performanceMonth']=before.get('performanceMonth')
        if i==0 and p.get('policyFrom')!=old.get('policyFrom') and not before.get('paymentBaseDateManual'):
            r['paymentBaseDate']=p.get('policyFrom') or ''
        elif r.get('paymentBaseDate')!=before.get('paymentBaseDate'):
            r['paymentBaseDateManual']=True
        if not recognized and r.get('paymentBaseDate')!=before.get('paymentBaseDate') and not before.get('performanceMonthManual'):
            r['performanceMonth']=str(r.get('paymentBaseDate') or '')[:7]
        elif not recognized and r.get('performanceMonth')!=before.get('performanceMonth'):
            r['performanceMonthManual']=True
    old_live=[t for t in rows(old.get('transactions')) if t.get('source')!='claim' and not t.get('reversed') and not t.get('isReversalEntry')]
    expected=transactions({**p,'twRef':case.tw_ref},now,old=old_live)
    expected_by_no={t['txNo']:t for t in expected}
    old_by_no={t['txNo']:t for t in old_live}
    from .cash_ledger import transaction_details
    old_details=transaction_details(old)
    fresh_expected=[{k:v for k,v in t.items() if k!='settledDates'} for t in expected]
    new_details=transaction_details({**p,'transactions':fresh_expected})
    for tx in old_live:
        no=tx['txNo'];replacement=expected_by_no.get(no)
        money_change=(not replacement or replacement['amount']!=tx['amount'] or replacement.get('reinsurer')!=tx.get('reinsurer') or replacement.get('reinsurerName')!=tx.get('reinsurerName') or p.get('currency')!=old.get('currency'))
        activity=any(e.get('transactionNo')==no for e in rows(old.get('paymentEntries')))
        settled=tx.get('settlement')=='settled' or old_details.get(no,{}).get('settlement')=='settled'
        period_locked=any(t.get('perReinsurer') and t.get('legType')=='Leg 3'
            and t.get('installmentId')==tx.get('installmentId')
            and old_details.get(t['txNo'],{}).get('settlement')=='settled' for t in old_live)
        if money_change and period_locked and tx.get('legType') in ('Leg 2','Leg 3'):
            return 'T2 and T3 amounts for this installment are locked after any reinsurer T3 settles.'
        if money_change and (activity or settled):
            return 'This change would affect a transaction with receipt/payment or Settlement history.'
        if settled:
            before=old_details.get(no,{})
            after=new_details.get(no,{})
            if any(before.get(k)!=after.get(k) for k in ('baseDate','dueDate','contractDueDate','termsDays')):
                return 'Payment Terms and the shared Payment Base Date are locked once the corresponding transaction settles.'
    # A shared base date locks as soon as any cash leg in that period settles.
    for tx in old_live:
        if str(tx.get('legType')) not in ('Leg 1','Leg 2') or old_details.get(tx['txNo'],{}).get('settlement')!='settled':continue
        pid=tx.get('installmentId')
        before=next((r for r in periods(old) if r['id']==pid),None)
        after=next((r for r in periods(p) if r['id']==pid),None)
        if not after or before and before.get('baseDate')!=after.get('baseDate'):
            return 'This installment Payment Base Date is locked by a settled T1 or T2.'
    if changed & {'splitParties','splitEnabled','ae'}:
        if old.get('confirmedProductionKeys') or any(t.get('legType')=='Leg 3' and old_details.get(t['txNo'],{}).get('settlement')=='settled' for t in old_live):
            return 'Account Executive and Performance Split are locked after any Production confirmation or affected T3 Settlement.'
    for key in old.get('confirmedProductionKeys') or []:
        if confirmed_facts(old,key)!=confirmed_facts(p,key):
            return 'This change would alter a reinsurer already confirmed in Production.'
    for history in rows(old.get('productionHistory')):
        row=history.get('row') or {}
        if history.get('cycle',0)!=int(old.get('reversalCycle') or 0) or not row.get('reinsurerKey'):continue
        try:
            prefix,index=row['reinsurerKey'].rsplit(':R',1)
            pid=prefix.split(':',1)[1]
            pi=int(row['id'].rsplit(':P',1)[1])
            premiums,incomes=report_amounts(p,pid,row['rate'])[int(index)]
            if (premiums[pi],incomes[pi])!=(row['premium'],row['income']):
                return 'This change would alter rounded staff amounts already confirmed in Production.'
        except (KeyError,ValueError,IndexError,StopIteration):
            return 'Keep the original confirmed Production allocation unchanged.'
    # Confirmed periods retain their performance month even when their common dates change.
    p['transactions']=[*[t for t in rows(old.get('transactions')) if t.get('source')=='claim' or t.get('reversed') or t.get('isReversalEntry')],*expected]
    changes={k:{'before':copy.deepcopy(old.get(k)),'after':copy.deepcopy(p.get(k))} for k in sorted(changed)}
    p.setdefault('propertyEditHistory',[]).append({'at':now,'by':actor.get('id'),'byName':actor.get('name'),
        'reason':reason,'changes':changes,'amountsBefore':totals(old),'amountsAfter':totals(p)})
    persist_settlements(p,now,actor)
    return ''


def report_amounts(p, period_id, rate):
    """Balanced NTD rows. Other Staff first; Reinsurance Staff keeps the remainder."""
    period=next(r for r in periods(p) if (r['id'] if p.get('installmentEnabled') else 'FULL')==period_id)
    premiums,incomes=report_values(p,period)
    weights=[num(r.get('sharePct')) for r in rows(p.get('reinsurers'))]
    ntd={**p,'currency':'TWD'}
    def convert(values):
        converted=[money(num(v)*num(rate),ntd) for v in values]
        target=money(sum(map(num,values))*num(rate),ntd)
        order=sorted((i for i,w in enumerate(weights) if w),key=lambda i:(-weights[i],i))
        if order:converted[order[0]]=money(num(converted[order[0]])+num(target)-sum(map(num,converted)),ntd)
        return converted
    pp,ii=convert(premiums),convert(incomes)
    if not p.get('splitEnabled'):
        return [( [x],[y] ) for x,y in zip(pp,ii)]
    pct=num(rows(p.get('splitParties'))[1].get('pct'))/100
    def split(values):
        others=[money(num(v)*pct,ntd) for v in values]
        target=money(sum(map(num,values))*pct,ntd)
        order=sorted((i for i,w in enumerate(weights) if w),key=lambda i:(-weights[i],i))
        if order:others[order[0]]=money(num(others[order[0]])+num(target)-sum(map(num,others)),ntd)
        return [[money(num(v)-num(other),ntd),other] for v,other in zip(values,others)]
    return list(zip(split(pp),split(ii)))


def reverse_payload(p, month, now, actor, reason):
    from .cash_ledger import transaction_details
    from .accounting_rules import premium_activity
    details=transaction_details(p)
    if premium_activity(p) or any(t.get('source')!='claim' and not t.get('reversed') and not t.get('isReversalEntry')
        and details.get(t.get('txNo'),{}).get('settlement')=='settled' for t in rows(p.get('transactions'))):
        raise ValueError('A settled T1/T2, receipt/payment or offset history prohibits whole Case Reverse.')
    result=copy.deepcopy(p)
    cycle=int(p.get('reversalCycle') or 0)
    history=[h for h in rows(p.get('productionHistory')) if h.get('cycle',0)==cycle and not h.get('isReversal')]
    new_cycle=cycle+1
    live=[t for t in rows(p.get('transactions')) if t.get('source')!='claim' and not t.get('reversed') and not t.get('isReversalEntry')]
    retained=[t for t in rows(p.get('transactions')) if t not in live]
    if history or p.get('confirmedProductionKeys'):
        retained.extend([{**t,'reversed':True} for t in live])
        retained.extend([{**t,'txNo':t['txNo']+f'-RVS{new_cycle}','amount':-t['amount'],
            'isReversalEntry':True,'reversed':False,'settlement':'open','createdAt':now,'postedMonth':month} for t in live])
        negative=[]
        for h in history:
            row=copy.deepcopy(h['row'])
            row.update(id=row['id']+f':REV{new_cycle}',key=row['key']+f':REV{new_cycle}',
                reinsurerKey=row['reinsurerKey']+f':REV{new_cycle}',premium=-row['premium'],income=-row['income'],
                isProductionReversal=True,reversalCycle=new_cycle)
            negative.append(row)
        result.setdefault('productionReversals',[]).append({'cycle':new_cycle,'month':month,'rows':negative,'confirmedKeys':[]})
    result.update(transactions=retained,reversalCycle=new_cycle,pendingReversalOffset=False,
                  confirmedProductionKeys=[],productionPartiallyConfirmed=False)
    result.setdefault('propertyReversalHistory',[]).append({'at':now,'month':month,'by':actor.get('id'),
        'reason':reason,'cycle':new_cycle,'recognizedRows':len(history)})
    return result


def confirm_production(source, report_rows, month):
    from .calc.jsnum import get
    from production.calc import production_keys_for_case
    p=copy.deepcopy(get(source,'payload') or {})
    current=[r for r in report_rows if not r.get('isProductionReversal')]
    negative=[r for r in report_rows if r.get('isProductionReversal')]
    confirmed=list(p.get('confirmedProductionKeys') or [])
    for row in current:
        if row['reinsurerKey'] not in confirmed:confirmed.append(row['reinsurerKey'])
        if 'premium' in row and 'income' in row:
            p.setdefault('productionHistory',[]).append({'cycle':int(p.get('reversalCycle') or 0),'month':month,'row':copy.deepcopy(row)})
    p['confirmedProductionKeys']=confirmed
    # Recognition fixes FX per completed period; creation at Announce never duplicates cash legs.
    from .calc.payment_terms import premium_installment_plan
    groups=__import__('production.calc',fromlist=['production_key_groups_for_case']).production_key_groups_for_case(source)
    for group in groups:
        if not group['keys'] or not all(k in confirmed for k in group['keys']):continue
        key=group.get('key') or group['keys'][0].rsplit(':R',1)[0]
        pid=str(key).split(':',1)[1]
        for tx in rows(p.get('transactions')):
            if tx.get('source')=='claim' or tx.get('reversed') or tx.get('isReversalEntry'):continue
            tx_pid=tx.get('installmentId') if p.get('installmentEnabled') else 'FULL'
            if tx_pid!=pid or tx.get('productionRecognized'):continue
            tx.update(postedMonth=month,productionRecognized=True)
            rate=next((r.get('rate') for r in current if r.get('rate') is not None),None)
            if rate is not None:tx['postingFxRate']=rate
    for batch in rows(p.get('productionReversals')):
        keys=batch.setdefault('confirmedKeys',[])
        for row in negative:
            if row.get('reversalCycle')==batch['cycle'] and row['id'] not in keys:keys.append(row['id'])
    status=get(source,'status')
    remaining=any(k not in confirmed for k in production_keys_for_case(source))
    if current:
        p['productionPartiallyConfirmed']=remaining
        next_status='posted' if remaining else 'closed'
    else:
        next_status=status
    return dict(payload=p,nextStatus=next_status,remaining=remaining,
                closedCases=int(bool(current) and status!='closed' and not remaining))
