"""Accounting · Receivable / Payable 依幣別分開（2026-11-26 業主決定；`insights.outstandingByCurrency`）。

  - 每個幣別一列，金額是原幣別（不換匯）；台幣在前，其他幣別依代碼排序
  - 同一批帳款、同一個 5 年窗口；逾期是該幣別金額的子集（實際到期日早於今天）
  - 台幣列加總＝Receivable / Payable 台幣總額；舊資料的外幣未結清帳款算在它自己的幣別
  - 不傳 extras 時 build_dashboard 的回傳值完全不變
純計算，不碰資料庫。"""
import os
from datetime import datetime, timezone
from zoneinfo import ZoneInfo
assert os.environ.get('RI_DISPOSABLE_QA') == 'true'
from dashboard.calc import build_dashboard
checks = []
def check(name, ok, detail=''):
    checks.append(name)
    assert ok, (name, detail)

TAIPEI = ZoneInfo('Asia/Taipei')
now = datetime.strptime('2026-10-29', '%Y-%m-%d').replace(hour=12, tzinfo=TAIPEI).astimezone(timezone.utc)
def item(no, cur, amount, direction, due, rate=None):
    return {'txNo': no, 'currency': cur, 'outstanding': amount, 'paymentDirection': direction, 'ageDate': '', 'postedRate': rate, 'postedMonth': '2026-05', 'due': due}
legacy = {'policies': [], 'trend': [], 'bound': [], 'outstanding': [
    item('L1', 'TWD', 100.4, 'receivable', '2026-10-28'),           # 台幣逾期應收
    item('L2', 'TWD', 200.4, 'receivable', '2026-10-29'),           # 今天到期：不算逾期
    item('L3', 'TWD', 800.0, 'payable', '2026-01-01'),              # 台幣逾期應付
    item('L4', 'USD', 10.25, 'payable', '2026-10-01', 30.0),        # 美金逾期應付
    item('L5', 'USD', 5.5, 'receivable', ''),                       # 美金應收、沒有到期日：不算逾期
    item('L6', 'JPY', 3000.0, 'receivable', '2026-09-01', 0.2),     # 日圓逾期應收
    item('L7', 'EUR', 7.0, 'payable', '2026-12-01', 35.0)]}         # 歐元未到期
ex = {}
r = build_dashboard([], [], [], now, tz=TAIPEI, production_rules=True, legacy=legacy, extras=ex)
rows = ex['outstandingByCurrency']
by = {x['currency']: x for x in rows}
check('TWD comes first and the other currencies follow in code order', [x['currency'] for x in rows] == ['TWD', 'EUR', 'JPY', 'USD'], [x['currency'] for x in rows])
check('TWD row is the TWD totals; due today is not overdue', by['TWD'] == {'currency': 'TWD', 'receivable': 300.8, 'payable': 800.0, 'overdueReceivable': 100.4, 'overduePayable': 800.0} or (abs(by['TWD']['receivable'] - 300.8) < 1e-9 and by['TWD']['payable'] == 800.0 and by['TWD']['overdueReceivable'] == 100.4 and by['TWD']['overduePayable'] == 800.0), by['TWD'])
check('USD row keeps original USD amounts (no conversion); no due date is not overdue', by['USD']['receivable'] == 5.5 and by['USD']['payable'] == 10.25 and by['USD']['overdueReceivable'] == 0 and by['USD']['overduePayable'] == 10.25, by['USD'])
check('JPY and EUR rows are separate', by['JPY']['receivable'] == 3000.0 and by['JPY']['overdueReceivable'] == 3000.0 and by['EUR']['payable'] == 7.0 and by['EUR']['overduePayable'] == 0, (by['JPY'], by['EUR']))
check('overdue never exceeds the row total', all(x['overdueReceivable'] <= x['receivable'] + 1e-9 and x['overduePayable'] <= x['payable'] + 1e-9 for x in rows))
a = build_dashboard([], [], [], now, tz=TAIPEI, production_rules=True, legacy=legacy)
b = build_dashboard([], [], [], now, tz=TAIPEI, production_rules=True, legacy=legacy, extras={})
check('the returned dashboard is identical with or without extras', a == b)
ex_e = {}
build_dashboard([], [], [], now, tz=TAIPEI, production_rules=True, extras=ex_e)
check('with nothing outstanding there are no rows', ex_e['outstandingByCurrency'] == [], ex_e['outstandingByCurrency'])
print(f'{len(checks)}/{len(checks)} dashboard outstanding currency checks passed')
