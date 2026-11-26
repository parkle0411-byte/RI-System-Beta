"""Dashboard 補充資料（2026-11-25，業主決定）：前前年對照、險種逐月佣金、近 12 個月件數、再保人件數。

全部是新增欄位（`insights`），既有欄位與數字逐位元組不變：
  - 不傳 extras 時，build_dashboard 的回傳值與傳入 extras 時完全相同（差異測試與其他呼叫不受影響）
  - brokerage.prior2＝前前年每月佣金（已結算月份用 Production 關帳數字，與 prior／current 同一套規則）
  - byClass：前 5 大險種各一列，其餘併入 Other，各險種加總永遠等於當月總額（含舊資料與 Facility）
  - trends：近 12 個月新承保件數（含舊資料）；今年各月加總＝Total Bound YTD
  - reinsurersByCases：在保保單件數（新系統＋舊資料在保保單），其餘再保人的件數是聯集
純計算，不碰資料庫。"""
import os
from datetime import datetime
from zoneinfo import ZoneInfo
assert os.environ.get('RI_DISPOSABLE_QA') == 'true'
from dashboard.calc import build_dashboard
checks = []
def check(name, ok, detail=''):
    checks.append(name)
    assert ok, (name, detail)

now = datetime(2026, 11, 19, 10, tzinfo=ZoneInfo('Asia/Taipei'))
def case(i, kind, posted, klass='Property', reinsurers=(), parent=None, status='posted'):
    payload = {'newOrRenew': kind, 'postedAt': posted, 'policyTo': '2027-11-01', 'classOfBusiness': klass, 'currency': 'TWD',
               'originalPremium': 1000, 'reinsurers': [{'name': n, 'sharePct': 50, 'premium': 1000} for n in reinsurers]}
    return {'id': i, 'parent_case_id': parent, 'status': status, 'announced_at': posted, 'payload': payload}
rows = [case(1, 'Renew', '2026-11-03T02:00:00Z', 'Property', ['Swiss Re', 'Allianz']),
        case(2, 'New', '2026-11-04T02:00:00Z', 'Commercial General Liability', ['Swiss Re']),
        case(3, 'Renew', '2026-03-04T02:00:00Z', 'Product Recall', ['QBE']),
        case(4, 'New', '2025-06-04T02:00:00Z', 'Property', ['Allianz', 'Swiss Re']),
        case(5, 'New', '2026-11-10T02:00:00Z', 'Property', ['Swiss Re'], parent=1)]   # 批單：算在保單 1 上，不另外算一件
closed = [
    {'year_month': '2026-03', 'rows': [{'caseId': 3, 'income': 300}, {'caseId': 1, 'income': 100}, {'caseId': 'legacy:9', 'classCode': 'GL', 'income': 40}, {'caseId': 'legacy:8', 'classCode': 'ZZ', 'income': 7}]},
    {'year_month': '2025-03', 'rows': [{'caseId': 4, 'income': 500}]},
    {'year_month': '2024-03', 'rows': [{'caseId': 4, 'income': 250}, {'caseId': 1, 'income': 50}]},
    {'year_month': '2024-04', 'rows': [{'caseId': 999, 'income': 9999}]},   # 看不到的案件不算（與既有規則相同）
]
legacy = {'policies': [{'expiry': '2027-05-01', 'items': [{'currency': 'TWD', 'premium': 1000, 'className': 'Property', 'party': 'Swiss Re (Facility)'}]},
                       {'expiry': '2027-06-01', 'items': [{'currency': 'TWD', 'premium': 500, 'className': 'Property', 'party': 'Legacy Re'}]},
                       {'expiry': '2026-01-01', 'items': [{'currency': 'TWD', 'premium': 800, 'className': 'Property', 'party': 'Expired Re'}]}],
          'trend': [{'month': '2026-05', 'incomeTwd': 1000, 'className': 'Property'}, {'month': '2026-05', 'incomeTwd': 200, 'className': 'Commercial General Liability'},
                    {'month': '2025-05', 'incomeTwd': 700}],   # 沒有險種的舊資料收入 → Other
          'outstanding': [], 'bound': [{'month': '2026-11', 'newOrRenew': 'Renew'}, {'month': '2026-02', 'newOrRenew': 'New'}, {'month': '2025-12', 'newOrRenew': ''}]}

# ---- 既有輸出完全不變 ----
plain = build_dashboard(rows, [], [], now, production_rules=True, closed_reports=closed, legacy=legacy)
ex = {}
with_extras = build_dashboard(rows, [], [], now, production_rules=True, closed_reports=closed, legacy=legacy, extras=ex)
check('the returned dashboard is identical with or without extras', plain == with_extras)
check('extras are not written into the returned dashboard (they only fill the dict that was passed in)', 'insights' not in with_extras and set(ex) == {'brokerage', 'trends', 'reinsurersByCases', 'grossPremiumUsd', 'overdueOutstanding', 'outstandingByCurrency'}, set(ex))
for year in (2025, 2024):
    a = build_dashboard(rows, [], [], now, production_rules=True, closed_reports=closed, legacy=legacy, brokerage_year=year)
    b = build_dashboard(rows, [], [], now, production_rules=True, closed_reports=closed, legacy=legacy, brokerage_year=year, extras={})
    check(f'identical for brokerage year {year} too', a == b)

# ---- 前前年 ----
b = with_extras['brokerage']
check('prior2 has one value per month like prior and current', len(ex['brokerage']['prior2']) == len(b['current']) == 11 and len(ex['brokerage']['prior2Status']) == 11)
check('prior2 is the year before last (2024) and uses closed-report numbers', ex['brokerage']['prior2'][2] == 300 and ex['brokerage']['prior2Status'][2] == 'closed', ex['brokerage']['prior2'])
check('prior2 skips cases the viewer cannot see', ex['brokerage']['prior2'][3] == 0, ex['brokerage']['prior2'][3])
h = {}
build_dashboard(rows, [], [], now, production_rules=True, closed_reports=closed, legacy=legacy, brokerage_year=2025, extras=h)
check('for a historical year prior2 is two years earlier (12 months)', len(h['brokerage']['prior2']) == 12)

# ---- 險種逐月 ----
bc = ex['brokerage']['byClass']
names = bc['names']
check('classes are the top five plus Other', names[-1] == 'Other' and len(names) <= 6 and names[0] in ('Property', 'Commercial General Liability', 'Product Recall'), names)
def total(year_key, i):
    return sum(bc[year_key][n][i] for n in names)
ok = all(abs(total('current', i) - b['current'][i]) < 1e-6 and abs(total('prior', i) - b['prior'][i]) < 1e-6 and abs(total('prior2', i) - ex['brokerage']['prior2'][i]) < 1e-6 for i in range(11))
check('the classes always add up to the month total (current, prior and prior2)', ok)
check('a closed month is split by the case class (March 2026: Product Recall 300, Property 100)', bc['current']['Product Recall'][2] == 300 and bc['current']['Property'][2] == 100, {n: bc['current'][n][2] for n in names})
check('legacy rows in a closed report use their class code (GL → Commercial General Liability); unknown codes go to Other', bc['current']['Commercial General Liability'][2] == 40 and bc['current']['Other'][2] == 7, {n: bc['current'][n][2] for n in names})
check('an open month uses the legacy class name (May 2026)', bc['current']['Property'][4] == 1000 and bc['current']['Commercial General Liability'][4] == 200, {n: bc['current'][n][4] for n in names})
check('legacy income without a class lands in Other (May 2025)', bc['prior']['Other'][4] == 700, {n: bc['prior'][n][4] for n in names})

# ---- 近 12 個月件數 ----
t = ex['trends']
check('trends cover the last 12 months ending this month', len(t['months']) == 12 and t['months'][0] == '2025-12' and t['months'][-1] == '2026-11', t['months'])
this_year = [i for i, m in enumerate(t['months']) if m.startswith('2026')]
check('this year\'s monthly counts add up to Total Bound YTD', sum(t['bound'][i] for i in this_year) == with_extras['metrics']['ytdCurrent'], (sum(t['bound'][i] for i in this_year), with_extras['metrics']['ytdCurrent']))
check('this month\'s counts equal Renewals and New Business Bound MTD', t['renew'][-1] == with_extras['metrics']['renewalsMtd'] and t['new'][-1] == with_extras['metrics']['newBusinessMtd'], (t['renew'][-1], t['new'][-1]))
check('the renewal series is new system only (legacy bound a Renew this month and it is not counted)', t['renew'][-1] == 1 and t['renew'][t['months'].index('2026-11')] == with_extras['metrics']['renewalsMtd'], t['renew'])
check('legacy bound policies are counted (Feb 2026 new, Dec 2025 blank kind only in the total)', t['new'][t['months'].index('2026-02')] == 1 and t['bound'][t['months'].index('2025-12')] == 1 and t['renew'][t['months'].index('2025-12')] == 0)
check('counts have the same length as the month list', all(len(t[k]) == 12 for k in ('bound', 'renew', 'new')))

# ---- 再保人件數 ----
r = ex['reinsurersByCases']
by = {row['name']: row['cases'] for row in r['rows']}
check('Swiss Re counts policies, not shares: policies 1, 2, 4 plus the legacy policy (the endorsement of policy 1 is not another case)', by.get('Swiss Re') == 4, by)
check('Allianz counts policies 1 and 4; QBE policy 3; the legacy party counts once', by.get('Allianz') == 2 and by.get('QBE') == 1 and by.get('Legacy Re') == 1, by)
check('an expired legacy policy is not counted', 'Expired Re' not in by)
check('ranking is by cases, most first', [row['cases'] for row in r['rows']] == sorted((row['cases'] for row in r['rows']), reverse=True))
check('policies counts every in-force policy once', r['policies'] == 6, r['policies'])
many = [case(100 + i, 'New', '2026-11-05T02:00:00Z', 'Property', [f'Re {i}']) for i in range(8)] + [case(120, 'New', '2026-11-05T02:00:00Z', 'Property', ['Re 6', 'Re 7'])]
mex = {}
build_dashboard(many, [], [], now, production_rules=True, extras=mex)
rr = mex['reinsurersByCases']['rows']
check('more than six reinsurers: top six then Other counted as a union of policies (no double counting)', len(rr) == 7 and rr[-1]['name'] == 'Other' and rr[-1]['cases'] == 2 and mex['reinsurersByCases']['policies'] == 9, rr)

# ---- 個人 Dashboard（沒有舊資料） ----
pe = {}
personal = build_dashboard(rows, [], [], now, production_rules=True, closed_reports=closed, extras=pe)
check('without legacy input everything still works and the metrics match the plain call', personal['metrics'] == build_dashboard(rows, [], [], now, production_rules=True, closed_reports=closed)['metrics'] and len(pe['trends']['bound']) == 12)
# ---- Total Gross Premium 的 USD 對照（逐月匯率的細節在 dashboard_gross_monthly_fx）----
fx = [{'year_month': '2026-09', 'currency': 'USD', 'rate': 31.0}, {'year_month': '2026-10', 'currency': 'USD', 'rate': 32.0}]
gx = {}
gm = build_dashboard(rows, [], fx, now, production_rules=True, closed_reports=closed, legacy=legacy, extras=gx)
gu = gx['grossPremiumUsd']
check('with a USD rate on file the insights carry a USD amount that says it is converted at each policy\'s recognition month', gu is not None and gu['basis'] == 'recognition-month' and gu['amount'] > 0, gu)
none_fx = {}
build_dashboard(rows, [], [{'year_month': '2026-10', 'currency': 'EUR', 'rate': 35.0}], now, production_rules=True, extras=none_fx)
check('no USD rate at all: no USD amount', none_fx['grossPremiumUsd'] is None and ex['grossPremiumUsd'] is None)
check('empty dashboard still produces well-formed insights', len(build_dashboard([], [], [], now, production_rules=True, extras=(z := {})) and z['trends']['months']) == 12 and z['reinsurersByCases'] == {'rows': [], 'policies': 0} and z['grossPremiumUsd'] is None)
print(f'{len(checks)}/{len(checks)} dashboard insights checks passed')
