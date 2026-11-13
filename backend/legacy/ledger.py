"""Adapt standalone legacy transactions to existing Finance account operations.

The facade is an in-memory protocol, never a Case model or a dummy Case row.
Case-shaped DTO keys remain solely for backward-compatible Accounting clients.
"""
import copy
import os
import threading
from collections import OrderedDict
from datetime import date
from django.db import models
from django.db.models.expressions import RawSQL
from django.utils import timezone
from .models import LegacyTransaction
from .money import number
from .protocol import LegacyPayload

RULE_NAMES = {
    'auw': "Lloyd's Underwriter Syndicate No. 0609 AUW (Facility)",
    'allianz': 'Allianz Global Corporate & Specialty SE, Hong Kong Branch (Facility)',
    'great_american': 'Great American Insurance Company, Singapore Branch (Facility)',
    'qbe': 'QBE Hongkong & Shanghai Insurance Limited (Facility)',
    'swiss': 'Swiss Re Asia Pte. Ltd., Hong Kong Branch (Facility)',
    'ordinary': 'Ordinary legacy counterparty',
}


def detect_rule(name):
    from cases.manual_reference import is_auw_reinsurer
    from cases.allianz_accounting import target as allianz
    from cases.great_american_accounting import target as ga
    from cases.qbe_accounting import target as qbe
    from cases.calc.swiss_facility import is_swiss_facility
    if is_auw_reinsurer(name): return 'auw'
    for code, test in [('allianz',allianz),('great_american',ga),('qbe',qbe)]:
        if test({'classOfBusiness':'Property'},name): return code
    if is_swiss_facility(name): return 'swiss'
    from masterdata.models import MasterRecord
    if MasterRecord.objects.filter(entity_type__in=['reinsurer','foreign_broker'], name=name, is_active=True).exists():
        return 'ordinary'
    return ''


def settlement_name(t):
    """Accounting counterparty name (owner 2026-11-13): any name ending in "(Facility)" is shown
    without it, historical rows included, matching native Cases; the Legacy record keeps the full
    name and its Facility payment rule."""
    from cases.calc.accounting import strip_facility_tag
    raw=t.data.get('party','')
    return strip_facility_tag(raw) or raw


def payload_for(t):
    d=t.data; a=d.get('amounts',{}); fin=copy.deepcopy(t.financial)
    stamp=d.get('confirmedAt') or (t.first_confirmed_at.isoformat() if t.first_confirmed_at else '')
    if t.batch_id and d.get('kind')=='claim' and d.get('claimIssueDate'):
        # 2026-11-11 owner: an imported claim is created on its Issue Date of Claim; the native claim
        # rule (creation date + 15 calendar days, reminder 7 days before) then applies unchanged.
        stamp=d['claimIssueDate']+'T00:00:00+08:00'
    no=t.number or str(t.uid)
    claim=d.get('kind')=='claim'
    source='claim' if claim else 'premium'
    settlement=settlement_name(t)
    # Claim T1 is RI receivable and T2 is Cedant payable in the native protocol.
    values=[-a.get('reinsurerNet',0),-a.get('cedantNet',0)] if claim else [a.get('cedantNet',0),a.get('reinsurerNet',0),a.get('brokerage',0)]
    txs=[]
    for i,value in enumerate(values,1):
        legno=f'{no}-'+(f'C1-T{i}' if claim else f'T{i}')
        txs.append(dict(txNo=legno,legType=f'Claim Leg {i}' if claim else f'Leg {i}',amount=value,source=source,
            label='Legacy claim' if claim else 'Legacy premium',reinsurer=d.get('party',''),reinsurerIdx=0,
            installmentId='single',createdAt=stamp,productionRecognized=False,postedMonth='',
            partyName=settlement if (claim and i==1 or not claim and i==2) else (d.get('cedant','') if i!=3 else 'Broker'),
            legacyOrigin=True,legacyHistorical=t.historical,legacyTransactionId=str(t.uid),settlement='open'))
    p=LegacyPayload(legacyTransactionUID=str(t.uid),legacyHistorical=t.historical,
        legacyAmounts=a,legacyData=copy.deepcopy(d),legacyStatus=t.status,
        financeWorkflowVersion='finance-review-v1',accountingRules='accounting-ag-20261022',
        currency=t.currency,twRef=t.reference,statementNo=d.get('statementNo',''),reinsured=d.get('cedant',''),originalInsured=d.get('insured',''),
        originalInsuredCn=d.get('insuredCn',''),ae=d.get('ae',''),classOfBusiness=d.get('classOfBusiness') or 'Property',classCode=d.get('classCode') or 'PD',
        reinsuranceStructure='QS',originalPremium=a.get('premium',0),riCommPct=d.get('commissionRate',0),taxPct=d.get('taxRate',0),
        paymentTermsDays=d.get('cedantDays',90),policyFrom=d.get('effectiveDate',''),policyTo=d.get('expiryDate',''),
        announcedAt=stamp,endorsementAnnouncedAt=stamp,endoEffectiveDate=d.get('effectiveDate',''),
        parentTwRef=t.reference if d.get('kind')=='endorsement' else '',
        reinsurers=[dict(name=RULE_NAMES.get(d.get('rule'),'Ordinary legacy counterparty'),
            foreignBroker=settlement,settlementRef=d.get('reinsurerRef',''),sharePct=100,premium=a.get('premium',0),riCommPct=0,taxPct=0,
            paymentTermsDays=d.get('reinsurerDays',90))],transactions=txs,
        paymentEntries=fin.get('paymentEntries',[]),financeClaimTracking=fin.get('financeClaimTracking',[]),
        swissAccounting=fin.get('swissAccounting',{}))
    saved={x.get('txNo'):x for x in fin.get('transactions',[])}
    for tx in txs:
        for key in ('settlement','settledAt','settledBy','settlementSource','settledDates','financeDates'):
            if key in saved.get(tx['txNo'],{}):tx[key]=copy.deepcopy(saved[tx['txNo']][key])
    if d.get('inheritedDates'):
        p['legacyInheritedDates']=d['inheritedDates']
    return p


def schedule(p, now=None):
    from cases.calc.payment_terms import build_payment_schedule, taipei_date, add_calendar_days
    from cases.calc.swiss_facility import quarter
    source=copy.deepcopy(p); source.pop('legacyTransactionUID',None)
    d=p['legacyData']; txs=p['transactions']
    # Native helpers determine deadlines. Exact legacy signed amounts are restored
    # afterwards; native underwriting premium/deduction formulas are NOT used.
    if p.get('legacyHistorical'):
        # Closed opening balances have source reminder dates, not new payment
        # obligations. Never infer a contractual/bank date from import time.
        from cases.cash_ledger import party,direction
        rows=[]
        for tx in txs[:2]:
            typ,name=party(p,tx);key='cedant' if typ=='cedant' else 'r1'
            reminder=d.get('receiveReminder','') if direction(tx)=='receivable' else d.get('payReminder','')
            rows.append(dict(partyType=typ,partyKey=key,partyName=name,scheduleKey='single:'+key,
                installmentId='single',baseDate='',dueDate=reminder,contractDueDate='',termsDays=None,
                amount=tx['amount'],paymentRule='legacy_imported'))
    elif d.get('kind')=='claim':
        base=taipei_date(p.get('announcedAt')) if p.get('announcedAt') else ''
        actual=quarter(base) if d.get('rule')=='swiss' else add_calendar_days(base,15)
        rows=[dict(partyType='reinsurer',partyKey='r1',partyName=p['reinsurers'][0]['foreignBroker']),
              dict(partyType='cedant',partyKey='cedant',partyName=d.get('cedant',''))]
        for i,r in enumerate(rows):
            r.update(scheduleKey='single:'+r['partyKey'],installmentId='single',baseDate=base,
                dueDate=add_calendar_days(actual,-7),contractDueDate=actual,termsDays=15,amount=txs[i]['amount'])
    else:
        native=build_payment_schedule(source,now)
        rows=native['items']
        for r in rows:
            idx=0 if r['partyType']=='cedant' else 1
            r.update(amount=txs[idx]['amount'],partyName=d.get('cedant','') if idx==0 else p['reinsurers'][0]['foreignBroker'])
    inherited=p.get('legacyInheritedDates',{})
    paid_by_key={}
    for e in p.get('paymentEntries',[]):
        paid_by_key[e.get('scheduleKey')]=paid_by_key.get(e.get('scheduleKey'),0)+float(e.get('amount',0))*(-1 if e.get('entryType')=='reversal' else 1)
    for r in rows:
        r['scheduleKey']='single:'+('cedant' if r['partyType']=='cedant' else 'r1')
        r['installmentId']='single'
        if inherited.get(r['partyType']):
            r.update(inherited[r['partyType']])
        paid=paid_by_key.get(r['scheduleKey'],0)
        r.update(paid=paid,outstanding=r['amount']-paid,source='claim' if d.get('kind')=='claim' else 'premium')
    if not p.get('legacyHistorical') and d.get('kind')!='claim':
        from cases.calc.swiss_facility import apply_schedule
        from cases.property_original import apply_schedules
        rows=apply_schedule(source,rows,now)
        rows=apply_schedules(source,rows)
    return dict(items=rows,issues=[],reviewRequired=False,totals={})


def details(p, now=None, schedules=None):
    from cases.cash_ledger import cents, amount, family, direction, party, group, proportions
    from cases.calc.payment_terms import taipei_date, _status_for
    today=taipei_date(now); result={}; schedules=schedule(p,now)['items'] if schedules is None else schedules
    reversed_ids={e.get('reversalOf') for e in p.get('paymentEntries',[]) if e.get('entryType')=='reversal'}
    for tx in p['transactions']:
        no=tx['txNo']; src,leg,suffix=family(tx); typ,name=party(p,tx)
        value=cents(tx['amount']); sign=-1 if value<0 else 1
        derived=src=='premium' and leg=='3'
        item=next((x for x in schedules if x['partyType']==typ),{})
        entries=[{**e,'appliedAmount':e['amount']} for e in p.get('paymentEntries',[])
                 if e.get('transactionNo')==no and e.get('entryType')=='payment' and e.get('id') not in reversed_ids]
        paid=value if p.get('legacyHistorical') else sum(cents(e['amount']) for e in entries)
        if abs(paid)>abs(value) or paid and (paid<0)!=(value<0):
            raise ValueError('Legacy allocations exceed the account balance.')
        outstanding=value-paid; due=item.get('contractDueDate',''); reminder=item.get('dueDate','')
        result[no]=dict(amount=amount(value),paid=amount(paid),outstanding=amount(outstanding),entries=entries,
            partyType=typ,partyName=name,paymentDirection='retained' if derived else direction(tx),
            paymentGroup=group(p['currency'],direction(tx),typ,name),cashTracking='derived' if derived else 'cash',
            baseDate=item.get('baseDate',''),dueDate=reminder,contractDueDate=due,dueTime='',
            termsDays=item.get('termsDays'),paymentRule=p['legacyData'].get('rule',''),
            settlement='settled' if not outstanding else 'partial' if paid else 'open',
            paymentStatus=_status_for(due or reminder,abs(amount(outstanding)),abs(amount(paid)),today,now),
            fullPaymentRequired=src=='premium',canRecord=bool(outstanding and not derived and not p.get('legacyHistorical')),
            cashParts=[dict(scheduleKey=item.get('scheduleKey','transaction:'+no),outstanding=abs(amount(outstanding)))],
            nonCashPaid=sum(e['amount'] for e in entries if e.get('nonCash')),
            cashPaid=sum(e['amount'] for e in entries if not e.get('nonCash')),
            _sign=sign,_source=src,_leg=leg,_suffix=suffix,_tx=tx,_historic=False,
            postedMonth=p['legacyData'].get('revenueMonth',''),manualSettlementRequired=False,
            canConfirmSettlement=False,canCancelSettlement=False)
        for key in ('paymentAllowed','paymentBlockedReason','statementNeedsRevision','requiresCollectionConfirmation',
                    'collectionConfirmed','swissFacility','swissCgl','paymentRule','statementReference','statementDueDate',
                    'originalDueDate','projectedDueDate','confirmationCutoff'):
            if key in item:result[no][key]=item[key]
    cash=[r for r in result.values() if r['cashTracking']=='cash']
    for r in result.values():
        if r['cashTracking']=='derived':
            clear=all(x['settlement']=='settled' for x in cash)
            r.update(settlement='settled' if clear else 'open',paid=r['amount'] if clear else 0,
                outstanding=0 if clear else r['amount'],cashParts=[])
    if not p.get('legacyHistorical'):
        from cases.accounting_policy import apply_claim_details
        apply_claim_details(p,result,now)
        from cases.finance_workflow import apply_details
        apply_details(p,result,now)
    return result


def claim_error(p):
    if p['legacyData'].get('kind')!='claim': return ''
    ds=[d for d in details(p).values() if d['cashTracking']=='cash']
    received=sum(abs(x['paid']) for x in ds if x['paymentDirection']=='receivable')
    paid=sum(abs(x['paid']) for x in ds if x['paymentDirection']=='payable')
    return 'Claim payments must not exceed recovered funds including valid offsets.' if paid>received+.004 else ''


def _accounting_full(t):
    """One confirmed transaction's Accounting view, rows and (non-historical premium) payment-schedule rows.

    2026-11-13：未結清的交易原本在 accounting_data 與 accounting_schedules 各算一次付款排程；改為同一次計算共用
    （排程在任何明細計算之前由同一份 payload 取得，與原本兩處的結果相同）。"""
    from cases.transaction_ledger import transaction_rows
    class Snapshot:
        def __init__(self,payload):self.payload=payload
        def details(self,mode):return details(self.payload,schedules=shared)
    p=payload_for(t)
    shared=None if t.historical else schedule(p)['items']
    view=dict(caseUid=str(t.uid),rootCaseUid=str(t.uid),rowVersion=t.version,twRef=t.reference,
        status='closed' if t.historical else 'posted',announcedAt=t.first_confirmed_at,reinsured=t.data.get('cedant',''),currency=t.currency,payload=p)
    rows=[]
    imported={e.get('transactionNo') for e in p.get('paymentEntries',[]) if e.get('entryKind')=='legacy-import'}
    for row in transaction_rows([view],{view['caseUid']:Snapshot(p)}):
        # 2026-11-11 owner: same position/logic as native rows (premium Effective Date, claim DOL).
        row.update(origin='legacy',legacyTransactionId=str(t.uid),legacyHistorical=t.historical,
            legacyImported=bool(t.batch_id),legacyInstallmentNo=t.data.get('installmentNo',''),legacyLossNo=t.data.get('lossNo','') if t.data.get('kind')=='claim' else '',
            accountDisplayDate=(t.data.get('lossDate') if t.data.get('kind')=='claim' else t.data.get('effectiveDate')) or '')
        if not t.historical and row.get('txNo') in imported:
            # Settled in the Register before import: reconciled before import, never re-reviewed.
            row.update(legacyImportSettled=True,financeReviewed=True,reviewBatchId='',reviewDate='',reviewedByName='',reviewReference='',
                reviewNote='Settled before import.',historicalTermsMissing=False,canRecord=False,
                canConfirmSettlement=False,canCancelSettlement=False,manualSettlementRequired=False)
        if t.historical:
            row.update(financeReviewed=True,reviewBatchId='',reviewDate='',reviewedByName='',reviewReference='',
                reviewNote='Historical reconciliation completed before import.',historicalTermsMissing=False,
                canRecord=False,canConfirmSettlement=False,canCancelSettlement=False,manualSettlementRequired=False)
        rows.append(row)
    schedule_rows=[]
    if shared is not None and p['legacyData'].get('kind')!='claim':
        schedule_rows=[{**row,'key':str(t.uid)+':'+row['scheduleKey'],
            'caseUid':str(t.uid),'rootCaseUid':str(t.uid),'caseRowVersion':t.version,
            'rowVersion':t.version,'caseStatus':'posted','twRef':t.reference,'source':'premium',
            'origin':'legacy','legacyTransactionId':str(t.uid),'legacyHistorical':False,
            'entries':[e for e in p['paymentEntries'] if e.get('scheduleKey')==row['scheduleKey']]} for row in shared]
    return view,rows,schedule_rows


def _accounting_one(t):
    """One confirmed transaction's Accounting view and rows (reads only this row)."""
    return _accounting_full(t)[:2]


def accounting_queryset():
    """Accounting 讀的舊案範圍（已確認的歷史＋新增交易）。"""
    return LegacyTransaction.objects.filter(status='confirmed')


def historical_queryset():
    """快取範圍：只有匯入的歷史交易（唯讀、全部已結清）。新增批單／理賠每次重算。"""
    return accounting_queryset().filter(historical=True)


def _compute_accounting_data():
    """原本的完整計算（快取關閉時使用，也是快取結果的比對基準）。"""
    views=[];rows=[]
    for t in accounting_queryset().order_by('reference','uid'):
        view,items=_accounting_one(t)
        views.append(view);rows.extend(items)
    return views,rows


# ---- 2026-11-10 效能：Accounting 舊案歷史結果快取（業主同意；小改，回應逐位元組相同） ----
# 歷史交易（3,693 筆 → 11,079 列）每次 Accounting 都重算，約 3 秒。歷史交易的結果只取決於
# 該列內容與台北日期（全部已結清，狀態不受時刻影響），所以用「歷史資料指紋＋台北日期」當鑰匙：
# - 指紋由 MySQL 對每列「除 original（原始 Excel，計算不用）以外的全部欄位」取 MD5 再合併，
#   直接改資料庫（不加版本、不改 updated_at）、增減列、改狀態都會被發現。
# - 新增的批單／理賠（historical=False）會受對帳批次與當下時間影響，每次照常重算，不快取。
# - 每個 gunicorn worker 只記一份；計算前後指紋或日期不同就不記。
# - 排序與原本相同（reference、uid）；歷史／新增的集合和排序清單對不上時，改用完整計算。
# - 回傳每列與每件的淺層複本；RI_LEGACY_RESULT_CACHE=false 可整個關掉（與原本完全相同）。
_CACHE_LOCK=threading.Lock()
_CACHE={}


class _BitXor(models.Aggregate):
    function='BIT_XOR'
    output_field=models.PositiveBigIntegerField()


def _cache_enabled():
    return os.environ.get('RI_LEGACY_RESULT_CACHE','true').strip().lower()!='false'


def _today():
    from cases.calc.payment_terms import taipei_date
    return taipei_date(None)


def _fingerprint(qs):
    table=LegacyTransaction._meta.db_table
    columns=[f.column for f in LegacyTransaction._meta.concrete_fields if f.name!='original']
    digest=RawSQL('CAST(CONV(LEFT(MD5(JSON_ARRAY('+','.join(f'`{table}`.`{c}`' for c in columns)+')),16),16,10) AS UNSIGNED)',[])
    found=qs.order_by().aggregate(rows=models.Count('pk'),digest=_BitXor(digest))
    return (found['rows'],found['digest'])


def _historical_results():
    qs=historical_queryset()
    key=(_today(),_fingerprint(qs))
    with _CACHE_LOCK:
        hit=_CACHE.get('value') if _CACHE.get('key')==key else None
    if hit is None:
        hit={str(t.uid):_accounting_one(t) for t in qs.order_by('reference','uid')}
        if (_today(),_fingerprint(qs))==key:
            with _CACHE_LOCK:
                _CACHE.clear();_CACHE.update(key=key,value=hit)
    return hit


# ---- 2026-11-13 效能：未結清舊資料（historical=False）的每筆結果快取（業主同意；回應內容不變） ----
# 做法比照新系統案件的 cases/case_result_cache.py：計算結果只取決於「這一列的內容」與「台北日期」，
# 所以用「該列內容指紋（除 original 外全部欄位的 MD5，由 MySQL 計算）＋台北日期」當鑰匙：
# 對帳、收付、修改或直接改資料庫都會改變指紋；過了台北午夜鑰匙也不同，會重新計算。
# - 對帳狀態（review_fields）由 Accounting 在取得結果後即時套用，不在快取內。
# - 每個 gunicorn worker 各自一份，最多 RI_LEGACY_OPEN_CACHE_SIZE 筆（預設 20,000），超過丟掉最久沒用的。
# - RI_LEGACY_OPEN_CACHE=false 可整個關掉（每次直接計算）。回傳每列的淺層複本，呼叫端改不到記住的內容。
_OPEN_LOCK=threading.Lock()
_OPEN=OrderedDict()


def _open_cache_enabled():
    return os.environ.get('RI_LEGACY_OPEN_CACHE','true').strip().lower()!='false'


def _open_cache_limit():
    try:return max(0,int(os.environ.get('RI_LEGACY_OPEN_CACHE_SIZE','20000')))
    except ValueError:return 20000


def _row_digest():
    table=LegacyTransaction._meta.db_table
    columns=[f.column for f in LegacyTransaction._meta.concrete_fields if f.name!='original']
    return RawSQL('MD5(JSON_ARRAY('+','.join(f'`{table}`.`{c}`' for c in columns)+'))',[])


def _open_results():
    """未結清舊資料每筆的 (uid, view, rows, schedule_rows)，依 reference、uid 排序。"""
    qs=accounting_queryset().filter(historical=False)
    if not _open_cache_enabled():
        return [(t.uid,*_accounting_full(t)) for t in qs.order_by('reference','uid')]
    today=_today()
    order=list(qs.order_by('reference','uid').annotate(row_digest=_row_digest()).values_list('uid','row_digest'))
    found={}
    with _OPEN_LOCK:
        for uid,digest in order:
            hit=_OPEN.get((uid,digest,today))
            if hit is not None:
                _OPEN.move_to_end((uid,digest,today));found[uid]=hit
    missing=[uid for uid,_ in order if uid not in found]
    fresh={}
    for start in range(0,len(missing),500):
        # 指紋與資料在同一個查詢取得：存進快取的結果一定對應它自己的內容指紋。
        for t in qs.filter(pk__in=missing[start:start+500]).annotate(row_digest=_row_digest()):
            fresh[t.uid]=(t.row_digest,_accounting_full(t))
    limit=_open_cache_limit()
    if fresh and limit:
        with _OPEN_LOCK:
            for uid,(digest,value) in fresh.items():
                _OPEN[(uid,digest,today)]=value;_OPEN.move_to_end((uid,digest,today))
            while len(_OPEN)>limit:_OPEN.popitem(last=False)
    result=[]
    for uid,_ in order:
        value=found.get(uid) or (fresh[uid][1] if uid in fresh else None)
        if value is None:continue   # 查詢之間被撤回或刪除的列：下一次請求就不會再列出
        view,rows,schedule_rows=value
        result.append((uid,dict(view),[dict(r) for r in rows],[dict(r) for r in schedule_rows]))
    return result


def accounting_bundle(scope='all'):
    """Accounting 一次取得舊資料的 views、transaction rows 與 payment-schedule rows（未結清的每筆只算一次）。

    scope：'all'／'open'／'history'，意義同 accounting_data。schedule rows 只來自未結清的保費交易，
    依 uid 排序（與原本的 accounting_schedules() 相同）。"""
    if scope=='history':
        views,rows=accounting_data('history')
        return views,rows,[]
    opened=_open_results()
    schedule_rows=[r for _,_,_,srows in sorted(opened,key=lambda item:item[0].hex) for r in srows]
    if scope=='open':
        return [v for _,v,_,_ in opened],[r for _,_,rows,_ in opened for r in rows],schedule_rows
    views,rows=accounting_data('all',_opened=opened)
    return views,rows,schedule_rows


def accounting_data(scope='all',_opened=None):
    """Read imported balances through the existing row renderer, never Case rows.

    scope（2026-11-13，Accounting 分段載入）：'all' 與原本完全相同；'open' 只含非歷史交易（新增的批單／理賠與
    匯入時尚未收付完的資料）；'history' 只含匯入時已全部結清的歷史交易。'open' 與 'history' 合起來等於 'all'。"""
    if scope == 'open':
        opened=_open_results() if _opened is None else _opened
        return [v for _,v,_,_ in opened],[r for _,_,rows,_ in opened for r in rows]
    if scope == 'history':
        if _cache_enabled():
            history=_historical_results()
            order=[str(uid) for uid in historical_queryset().order_by('reference','uid').values_list('uid',flat=True)]
            if set(order)==set(history):
                views=[];rows=[]
                for uid in order:
                    view,items=history[uid]
                    views.append(dict(view));rows.extend(dict(row) for row in items)
                return views,rows
        views=[];rows=[]
        for t in historical_queryset().order_by('reference','uid'):
            view,items=_accounting_one(t)
            views.append(view);rows.extend(items)
        return views,rows
    if not _cache_enabled():
        return _compute_accounting_data()
    history=_historical_results()
    opened=_open_results() if _opened is None else _opened
    fresh={str(uid):(view,rows) for uid,view,rows,_ in opened}
    order=[(str(uid),historical) for uid,historical in accounting_queryset().order_by('reference','uid').values_list('uid','historical')]
    if ({uid for uid,h in order if h}!=set(history) or {uid for uid,h in order if not h}!=set(fresh)):
        return _compute_accounting_data()
    views=[];rows=[]
    for uid,historical in order:
        view,items=(history if historical else fresh)[uid]
        views.append(dict(view));rows.extend(dict(row) for row in items)
    return views,rows


class FinanceFacade:
    def __init__(self, record):
        self.record=record; self.pk=record.pk; self.case_uid=record.uid
        self.row_version=record.version; self.payload=payload_for(record)
        self.status='posted'; self.is_archived=False; self.recycled_at=None
        self.tw_ref=record.reference; self.legacy=True
        self.case_kind='legacy'; self.announced_at=record.first_confirmed_at; self.parent_case_id=None

    def save(self):
        self.record.financial={k:copy.deepcopy(self.payload.get(k,{} if k=='swissAccounting' else []))
                               for k in ('paymentEntries','financeClaimTracking','swissAccounting','transactions')}
        self.record.version=self.row_version
        self.record.save(update_fields=['financial','version','updated_at'])


def locked_facades(ids):
    return {str(t.uid):FinanceFacade(t) for t in LegacyTransaction.objects.select_for_update().filter(
        pk__in=ids,status='confirmed',historical=False).order_by('uid')}


def all_payment_payloads():
    for t in LegacyTransaction.objects.filter(status='confirmed',historical=False).only('financial'):
        yield {'paymentEntries':t.financial.get('paymentEntries',[])}


def accounting_schedules():
    """Payment-schedule rows of unsettled legacy premium transactions (same rows and order as before 2026-11-13)."""
    return accounting_bundle('open')[2]
