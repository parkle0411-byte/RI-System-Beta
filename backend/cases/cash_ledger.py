"""Cash balances of stored transactions; reading never rewrites historical entries.

New receipts carry the raw transaction number. Legacy schedule receipts are allocated
to the remaining capacities of matching transactions, so their cash is counted once.
Brokerage is retained and has no cash of its own. Nothing settles automatically (2026-10-14): this module
only computes cash balances; facility_accounting.apply_transactions turns a cleared balance into
"Awaiting confirmation" and Accounting's manual confirmation into "Settled".
"""
import copy
from .accounting_rules import entry_locked
import re
from collections import Counter, defaultdict
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP

from .calc.accounting import number_or_zero
from .calc.payment_terms import build_payment_schedule, _as_utc, _status_for, taipei_date
from .calc.swiss_facility import DISPLAY_FIELDS


def cents(value):
    if isinstance(value, bool) or value is None:
        raise ValueError('A finite amount is required.')
    try:
        amount = Decimal(str(value).replace(',', ''))
        if not amount.is_finite():
            raise ValueError('A finite amount is required.')
        return int(amount.quantize(Decimal('0.01'), rounding=ROUND_HALF_UP) * 100)
    except (InvalidOperation, TypeError, OverflowError):
        raise ValueError('A finite amount is required.')


def amount(value):
    return float(Decimal(value) / 100)


def objects(value):
    return [r for r in value if isinstance(r, dict)] if isinstance(value, list) else []


def proportions(total, weights):
    """Allocate integer cents without exceeding integer capacities; preserve the sum."""
    denominator = sum(max(0, w) for w in weights)
    if not denominator:
        return [0] * len(weights)
    total = min(max(0, total), denominator)
    result = [total * max(0, w) // denominator for w in weights]
    remainder = total - sum(result)
    for i in sorted(range(len(weights)), key=lambda i: (-(total * weights[i] % denominator), i)):
        if remainder and result[i] < weights[i]:
            result[i] += 1
            remainder -= 1
    return result


def family(tx):
    leg = str(tx.get('legType') or '')
    match = re.match(r'^(Claim )?Leg ([123])([ab]?)$', leg)
    if not match:
        return '', '', ''
    return ('claim' if match[1] or tx.get('source') == 'claim' else 'premium'), match[2], match[3]


def party(payload, tx):
    source, leg, _ = family(tx)
    cedant = (source == 'premium' and leg == '1') or (source == 'claim' and leg == '2')
    if source == 'premium' and leg == '3':
        return 'broker', 'Broker'
    if cedant:
        return 'cedant', str(payload.get('reinsured') or payload.get('reinsuredName') or payload.get('cedantName') or '').strip()
    return 'reinsurer', str(tx.get('partyName') or tx.get('reinsurer') or '').strip()


def direction(tx):
    source, leg, _ = family(tx)
    incoming = (source == 'premium' and leg == '1') or (source == 'claim' and leg == '1')
    return 'receivable' if incoming != (number_or_zero(tx.get('amount')) < 0) else 'payable'


def group(currency, direction_, party_type, party_name):
    return '|'.join([str(currency or '').strip().upper(), direction_, party_type, ' '.join(party_name.split()).casefold()])


def _matches(item, tx):
    if tx.get('installmentId') and item['installmentId'] != tx['installmentId']:
        return False
    _, leg, _ = family(tx)
    if leg == '1':
        return item['partyType'] == 'cedant'
    idx = tx.get('reinsurerIdx')
    return (leg == '2' and isinstance(idx, (int, float)) and not isinstance(idx, bool)
            and idx >= 0 and int(idx) == idx and item['partyKey'] == 'r' + str(int(idx) + 1))


def transaction_details(payload, now=None, schedule_result=None):
    """schedule_result：呼叫端已用同一份 payload 與同一個 now 算好的 build_payment_schedule 結果（Accounting 列表共用，省掉重算）。"""
    now = _as_utc(now)
    today = taipei_date(now)
    transactions = objects(payload.get('transactions'))
    counts = Counter(str(t.get('txNo') or '') for t in transactions)
    schedule = (build_payment_schedule(payload, now) if schedule_result is None else schedule_result)['items']
    entries = objects(payload.get('paymentEntries'))
    details, parts, legacy_targets = {}, {}, defaultdict(list)
    for tx in transactions:
        no = str(tx.get('txNo') or '')
        if not no or counts[no] != 1:
            continue
        source, leg, suffix = family(tx)
        value = cents(number_or_zero(tx.get('amount')))
        sign = -1 if value < 0 else 1
        derived = source == 'premium' and leg == '3'
        historic = bool(tx.get('reversed') or tx.get('isReversalEntry'))
        party_type, party_name = party(payload, tx)
        cash_direction = 'retained' if derived else direction(tx)
        matching = [i for i in schedule if source == 'premium' and _matches(i, tx)]
        date_rows = matching
        weights = [abs(cents(i['amount'])) for i in matching]
        if matching:
            # Scale schedule proportions to the stored transaction (including split legs).
            denominator = sum(weights)
            scaled = [abs(value) * w // denominator for w in weights] if denominator else [abs(value) // len(weights)] * len(weights)
            for i in range(abs(value) - sum(scaled)):
                scaled[i % len(scaled)] += 1
            for item, capacity in zip(matching, scaled):
                parts[(no, item['scheduleKey'])] = {'capacity':capacity,'paid':0,'entries':[]}
                if not historic and not derived:
                    legacy_targets[item['scheduleKey']].append((no, item['scheduleKey']))
        elif not derived:
            parts[(no, 'transaction:' + no)] = {'capacity':abs(value),'paid':0,'entries':[]}
        dates = [i['dueDate'] for i in date_rows if i.get('dueDate')]
        if source == 'claim' and tx.get('dueDate'):
            dates = [tx['dueDate']]
        base_dates = [i['baseDate'] for i in date_rows if i.get('baseDate')]
        contract_dates = [i.get('contractDueDate') for i in date_rows if i.get('contractDueDate')]
        if source == 'claim' and tx.get('dueDate'):
            contract_dates = [tx['dueDate']]
        swiss_fields = {}
        for field in DISPLAY_FIELDS:
            values = [i[field] for i in matching if field in i]
            if values:
                swiss_fields[field] = all(values) if field in ('collectionConfirmed', 'paymentAllowed', 'canConfirmCollection') else any(values) if isinstance(values[0], bool) else min(values)
        details[no] = {
            **swiss_fields,
            'amount':amount(value),'paid':0,'outstanding':amount(value),'entries':[],
            'partyType':party_type,'partyName':party_name,'paymentDirection':cash_direction,
            'paymentGroup':group(payload.get('currency'),cash_direction,party_type,party_name),
            'cashTracking':'derived' if derived else 'cash','dueDate':min(dates) if dates else '',
            'baseDate':min(base_dates) if base_dates else '', 'dueTime':'',
            'contractDueDate':min(contract_dates) if contract_dates else '',
            'paymentRule':next((i.get('paymentRule') for i in matching if i.get('paymentRule')),''),
            'termsDays':min((i['termsDays'] for i in matching if i['termsDays'] is not None),default=None),
            'cashDescription':('Brokerage retained from premium receipts and payments' if derived else
                               ('Receivable from ' if cash_direction == 'receivable' else 'Payable to ') + party_name),
            'fullPaymentRequired':source == 'premium',
            'postedMonth':tx.get('postedMonth') or str(tx.get('createdAt') or '')[:7],
            'canRecord':bool(source and (source != 'claim' or leg in ('1','2')) and leg and not derived and not historic and value and party_name
                             and (source == 'claim' or (matching and len(dates) == len(matching)))),
            '_sign':sign,'_historic':historic,'_source':source,'_leg':leg,'_suffix':suffix,'_tx':tx,
        }
    pending = defaultdict(list)
    for entry in entries:
        if entry.get('entryType') not in ('payment','reversal'):
            continue
        try:
            value = cents(entry.get('amount'))
        except ValueError:
            continue
        reverse = -1 if entry.get('entryType') == 'reversal' else 1
        no = str(entry.get('transactionNo') or '')
        direct = details.get(no)
        if direct:
            keys = [key for key in parts if key[0] == no]
            matching = [key for key in keys if key[1] == entry.get('scheduleKey')]
            keys = matching or keys
            shares = proportions(abs(value), [parts[k]['capacity'] for k in keys])
            for key, share in zip(keys, shares):
                parts[key]['paid'] += share * reverse
                parts[key]['entries'].append({**entry,'appliedAmount':amount(share * direct['_sign'] * reverse)})
            if not direct['_historic']:
                continue
        # Carry legacy schedule cash forward after case Reverse/reclose without rewriting it.
        key = str(entry.get('scheduleKey') or '')
        candidates = [k for k in legacy_targets.get(key,[]) if details[k[0]]['_sign'] == (-1 if value < 0 else 1)]
        if candidates:
            pending[key].append((entry,abs(value)*reverse,candidates))
    for key, records in pending.items():
        candidates = records[0][2]
        capacities = [max(0,parts[k]['capacity']-max(0,parts[k]['paid'])) for k in candidates]
        running = 0
        previous = [0] * len(candidates)
        for entry, value, targets in records:
            # Normally all rows under a schedule key have the same premium sign.
            if targets != candidates:
                continue
            running += value
            allocated = proportions(running, capacities)
            for i, target in enumerate(candidates):
                delta = allocated[i]-previous[i]
                parts[target]['entries'].append({**entry,'legacyAllocation':True,
                    'appliedAmount':amount(delta*details[target[0]]['_sign'])})
            previous = allocated
        for target, share in zip(candidates, previous):
            parts[target]['paid'] += share
    for no, detail in details.items():
        if detail['cashTracking'] == 'derived':
            continue
        allocated = [(key,p) for key,p in parts.items() if key[0] == no]
        # Historical explicitly settled claim flags retain their meaning.
        legacy_settled = (detail['_source']=='claim' and detail['_tx'].get('settlement')=='settled'
                          and not any(e.get('transactionNo')==no for e in entries))
        paid = sum(p['capacity'] if legacy_settled else min(p['capacity'],max(0,p['paid'])) for _,p in allocated)
        total = abs(cents(detail['amount']))
        detail['paid']=amount(paid*detail['_sign'])
        detail['outstanding']=amount((total-paid)*detail['_sign'])
        detail['settlement']='settled' if total==paid else 'partial' if paid else 'open'
        detail['paymentStatus']=_status_for(detail['contractDueDate'] or detail['dueDate'],amount(total-paid),amount(paid),today,now)
        if detail['paymentStatus'] == 'upcoming' and detail['_source'] == 'premium' and detail['dueDate'] and today >= detail['dueDate']:
            detail['paymentStatus'] = 'reminder'
        detail['receiptStatus'] = ('received' if detail['paymentDirection'] == 'receivable' else 'paid') if total == paid else 'partial' if paid else 'unpaid'
        detail['cashParts']=[{'scheduleKey':key[1],'outstanding':amount(max(0,p['capacity']-max(0,p['paid'])))} for key,p in allocated]
        detail['entries']=[e for _,p in allocated for e in p['entries']]
        detail['nonCashPaid'] = sum(e.get('appliedAmount', 0) for e in detail['entries'] if e.get('nonCash'))
        detail['cashPaid'] = detail['paid'] - detail['nonCashPaid']
        if detail.get('swissCase') and (detail['partyType'] == 'cedant' or detail.get('swissFacility')):
            deadline = detail['contractDueDate'] if detail['partyType'] == 'cedant' else detail['dueDate']
            detail['dueTime'] = ''
            detail['paymentStatus'] = ('settled' if total == paid else 'pending_review' if not deadline else
                'overdue' if today > deadline else 'due_today' if today == deadline else
                'reminder' if detail['partyType'] == 'cedant' and detail['dueDate'] and today >= detail['dueDate'] else 'upcoming')
        detail['canRecord']=detail['canRecord'] and total>paid
    for no, detail in details.items():
        if detail['cashTracking']!='derived':
            continue
        tx=detail['_tx']
        normalized=re.sub(r'-(?:TX|T)[123]([ab]?)(?=-|$)',r'-T*\1',no)
        paired=[]
        for candidate in details.values():
            other=candidate['_tx']
            if candidate['_source']!='premium' or candidate['_leg'] not in ('1','2'):
                continue
            if candidate['_historic']!=detail['_historic'] or candidate['_suffix']!=detail['_suffix']:
                continue
            other_no=str(other.get('txNo') or '')
            other_normalized=re.sub(r'-(?:TX|T)[123]([ab]?)(?=-|$)',r'-T*\1',other_no)
            exact=normalized!=no and other_normalized==normalized
            fallback=(normalized==no and other.get('reinsurerIdx')==tx.get('reinsurerIdx')
                      and other.get('installmentId')==tx.get('installmentId'))
            if exact or fallback:
                paired.append(candidate)
        # 2026-10-14：經紀費（T3）不再自動結清；只有 T1／T2 開始收付款時顯示 partial，結清一律由會計人工確認
        # （facility_accounting.apply_transactions 依 T1／T2 的人工確認狀態決定 T3 能否確認）
        partial=any(abs(p['paid'])>0 for p in paired)
        detail['settlement']='partial' if partial else 'open'
        detail['paymentStatus']=detail['settlement']
        detail['paid']=0
        detail['outstanding']=detail['amount']
        detail['cashParts']=[]
        detail['settlementDependencies']=[{'txNo':p['_tx']['txNo'],'settlement':p['settlement']} for p in paired]
    from .facility_accounting import apply_transactions
    apply_transactions(payload, details, schedule)
    return {no:{k:v for k,v in d.items() if not k.startswith('_')} for no,d in details.items()}


def payment_batches(cases):
    batches={}
    for case in cases:
        entries=objects(case['payload'].get('paymentEntries'))
        reversed_ids={e.get('reversalOf') for e in entries if e.get('entryType')=='reversal'}
        for entry in entries:
            bid=entry.get('batchId')
            if not bid or entry.get('entryType')!='payment':
                continue
            batch=batches.setdefault(bid,{'batchId':bid,'paymentDate':entry.get('paymentDate'),
                'amount':entry.get('batchAmount'),'currency':entry.get('currency'),
                'paymentDirection':entry.get('paymentDirection'),'partyName':entry.get('partyName'),
                'reference':entry.get('reference') or '', 'note':entry.get('note') or '',
                'createdAt':entry.get('createdAt'),'createdByName':entry.get('createdByName'), 'allocations':[]})
            batch['allocations'].append({'caseUid':case['caseUid'],'caseRowVersion':case['rowVersion'],
                'caseStatus':case['status'],'twRef':case['twRef'],'txNo':entry.get('transactionNo'),
                'source':next((t.get('source', 'premium') for t in objects(case['payload'].get('transactions')) if t.get('txNo') == entry.get('transactionNo')), 'premium'),
                'entryId':entry.get('id'),'amount':abs(number_or_zero(entry.get('amount'))),
                'amountEditLocked':entry_locked(case['payload'], entry),
                'reversed':entry.get('id') in reversed_ids})
    for batch in batches.values():
        allocations=batch['allocations']
        reversed_count=sum(a['reversed'] for a in allocations)
        batch['originalAmount'] = batch['amount']
        batch['amount'] = amount(sum(cents(a['amount']) for a in allocations))
        complete = True
        batch['status']='reversed' if reversed_count==len(allocations) else 'partial_reversal' if reversed_count else 'recorded'
        batch['canReverse']=not reversed_count and complete and all((a['caseStatus'] in ('posted','closed') or (a['caseStatus'] == 'reversed' and a['source'] == 'claim')) and not a['amountEditLocked'] for a in allocations)
    return sorted(batches.values(),key=lambda b:str(b.get('createdAt') or ''),reverse=True)
