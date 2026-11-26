"""Accounting · Receivable / Payable 的逾期部分（2026-11-26 業主決定；`insights.overdueOutstanding`）。

  - 逾期＝未結清（含部分收付）且「實際到期日」早於今天（台北日期）；實際到期日＝合約到期日，沒有就用到期日（與 Accounting 的逾期置頂同一規則）
  - 到期當天不算逾期；沒有到期日不算逾期
  - 與 Receivable / Payable 同一批帳款、同一個 5 年窗口、同一套匯率：逾期是兩個總額的一部分（子集）
  - 舊資料的未結清帳款用它的實際到期日（`due`）
  - 不傳 extras 時 build_dashboard 的回傳值完全不變
純計算，不碰資料庫。"""
import copy
import os
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo
assert os.environ.get('RI_DISPOSABLE_QA') == 'true'
from cases.cash_ledger import transaction_details
from cases.property_original import enabled, refresh_transactions
from dashboard.calc import build_dashboard
checks = []
def check(name, ok, detail=''):
    checks.append(name)
    assert ok, (name, detail)

TAIPEI = ZoneInfo('Asia/Taipei')
BASE = dict(reinsuranceStructure='QS', classOfBusiness='Property', classCode='PD', currency='TWD', originalPremium=100000,
            riCommPct=10, taxPct=1, paymentTermsDays=90, policyFrom='2026-01-15', policyTo='2027-01-15', reinsured='QA Cedant',
            reinsurers=[dict(name='QA Ordinary Re', sharePct=50, premium=100000, riCommPct=20, taxPct=1, paymentTermsDays=90)],
            transactions=[], paymentEntries=[], claims=[])
def case(i):
    p = copy.deepcopy(BASE)
    p['twRef'] = f'QAOVD{i:03d}'
    assert enabled(p)
    p['announcedAt'] = '2026-01-20T02:00:00+00:00'
    refresh_transactions(p, '2026-01-20T02:00:00+00:00')
    for t in p['transactions']:
        t['createdAt'] = '2026-01-20T02:00:00+00:00'
    return {'id': i, 'parent_case_id': None, 'status': 'closed', 'payload': p, 'announced_at': '2026-01-20T10:00:00+08:00', 'created_at': '2026-01-20T10:00:00+08:00'}
row = case(1)

def at(day):
    """台北 day 當天中午的時間點。"""
    return datetime.strptime(day, '%Y-%m-%d').replace(hour=12, tzinfo=TAIPEI)

def expected_for(now):
    """逐筆照規則算出的答案：未結清、不是衍生帳款、實際到期日早於今天。"""
    today = now.astimezone(TAIPEI).strftime('%Y-%m-%d')
    over = {'receivable': 0.0, 'payable': 0.0}; total = {'receivable': 0.0, 'payable': 0.0}
    for no, d in transaction_details(row['payload'], now).items():
        if d['cashTracking'] == 'derived' or abs(d['outstanding']) < .005:
            continue
        total[d['paymentDirection']] += abs(d['outstanding'])
        due = str(d.get('contractDueDate') or d.get('dueDate') or '')[:10]
        if due and due < today:
            over[d['paymentDirection']] += abs(d['outstanding'])
    return over, total

def run(now, legacy=None):
    ex = {}
    r = build_dashboard([row], [], [], now.astimezone(timezone.utc), tz=TAIPEI, production_rules=True, legacy=legacy, extras=ex)
    return r['metrics'], ex['overdueOutstanding']

details = {no: d for no, d in transaction_details(row['payload'], at('2026-01-21')).items() if d['cashTracking'] != 'derived' and abs(d['outstanding']) >= .005}
dues = sorted({str(d.get('contractDueDate') or d.get('dueDate') or '')[:10] for d in details.values()} - {''})
check('premise: the sample policy has open receivable and payable transactions with due dates', len(dues) >= 1 and {d['paymentDirection'] for d in details.values()} == {'receivable', 'payable'}, (dues, {d['paymentDirection'] for d in details.values()}))
first_due = dues[0]
before = at((datetime.strptime(first_due, '%Y-%m-%d') - timedelta(days=1)).strftime('%Y-%m-%d'))
on_day = at(first_due)
after = at((datetime.strptime(first_due, '%Y-%m-%d') + timedelta(days=1)).strftime('%Y-%m-%d'))
far = at('2030-01-01')

m, o = run(before)
check('nothing is overdue the day before the earliest due date', o['receivable'] == 0 and o['payable'] == 0, o)
m, o = run(on_day)
exp, tot = expected_for(on_day)
check('a transaction due today is not overdue (the due day itself does not count)', abs(o['receivable'] - exp['receivable']) < 1e-6 and abs(o['payable'] - exp['payable']) < 1e-6 and o['receivable'] + o['payable'] < tot['receivable'] + tot['payable'], (o, exp))
m, o = run(after)
exp, tot = expected_for(after)
check('the day after the earliest due date that transaction is overdue (matches the transaction-by-transaction answer)', abs(o['receivable'] - exp['receivable']) < 1e-6 and abs(o['payable'] - exp['payable']) < 1e-6 and o['receivable'] + o['payable'] > 0, (o, exp))
m, o = run(far)
exp, tot = expected_for(far)
check('long after every due date everything outstanding is overdue and equals the Receivable / Payable totals', abs(o['receivable'] - m['outstandingLeg1Ntd']) < 1e-6 and abs(o['payable'] - m['outstandingLeg2Ntd']) < 1e-6 and o['receivable'] + o['payable'] > 0, (o, m['outstandingLeg1Ntd'], m['outstandingLeg2Ntd']))
check('overdue is always a part of the totals (never more) on every day tested', all(run(n)[1]['receivable'] <= run(n)[0]['outstandingLeg1Ntd'] + 1e-6 and run(n)[1]['payable'] <= run(n)[0]['outstandingLeg2Ntd'] + 1e-6 for n in (before, on_day, after, far)))

# ---- 既有輸出完全不變 ----
a = build_dashboard([row], [], [], after.astimezone(timezone.utc), tz=TAIPEI, production_rules=True)
b = build_dashboard([row], [], [], after.astimezone(timezone.utc), tz=TAIPEI, production_rules=True, extras={})
check('the returned dashboard is identical with or without extras', a == b)

# ---- 舊資料 ----
legacy = {'policies': [], 'trend': [], 'bound': [], 'outstanding': [
    {'txNo': 'L1', 'currency': 'TWD', 'outstanding': 100.0, 'paymentDirection': 'receivable', 'ageDate': '', 'postedRate': None, 'postedMonth': '2026-05', 'due': '2026-10-28'},   # 昨天到期：逾期
    {'txNo': 'L2', 'currency': 'TWD', 'outstanding': 200.0, 'paymentDirection': 'receivable', 'ageDate': '', 'postedRate': None, 'postedMonth': '2026-05', 'due': '2026-10-29'},   # 今天到期：不算
    {'txNo': 'L3', 'currency': 'TWD', 'outstanding': 400.0, 'paymentDirection': 'receivable', 'ageDate': '', 'postedRate': None, 'postedMonth': '2026-05', 'due': ''},             # 沒有到期日：不算
    {'txNo': 'L4', 'currency': 'TWD', 'outstanding': 800.0, 'paymentDirection': 'payable', 'ageDate': '', 'postedRate': None, 'postedMonth': '2026-05', 'due': '2026-01-01'},      # 逾期的應付
    {'txNo': 'L5', 'currency': 'USD', 'outstanding': 10.0, 'paymentDirection': 'payable', 'ageDate': '', 'postedRate': 30.0, 'postedMonth': '2026-05', 'due': '2026-10-01'}]}      # 美金：用上帳匯率換成台幣
now_l = at('2026-10-29')
ex_l = {}
rl = build_dashboard([], [], [], now_l.astimezone(timezone.utc), tz=TAIPEI, production_rules=True, legacy=legacy, extras=ex_l)
ol = ex_l['overdueOutstanding']
check('legacy outstanding: yesterday overdue, today and no-date not overdue', ol['receivable'] == 100.0, ol)
check('legacy overdue payable includes the foreign-currency item at its posted rate (800 + 10 USD × 30)', ol['payable'] == 800.0 + 300.0, ol)
check('the legacy totals are unchanged and the overdue part stays inside them', rl['metrics']['outstandingLeg1Ntd'] == 700.0 and rl['metrics']['outstandingLeg2Ntd'] == 1100.0, (rl['metrics']['outstandingLeg1Ntd'], rl['metrics']['outstandingLeg2Ntd']))

# ---- 沒有任何未結清帳款 ----
ex_e = {}
build_dashboard([], [], [], now_l.astimezone(timezone.utc), tz=TAIPEI, production_rules=True, extras=ex_e)
check('with nothing outstanding the overdue amounts are zero', ex_e['overdueOutstanding'] == {'receivable': 0.0, 'payable': 0.0}, ex_e['overdueOutstanding'])
print(f'{len(checks)}/{len(checks)} dashboard overdue checks passed')
