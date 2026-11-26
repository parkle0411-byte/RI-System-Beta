"""Total Gross Premium 逐月匯率（2026-11-26 業主決定）：台幣與美金都用每張保單「認列月」的匯率，不再全部用最新匯率。

  - 認列月＝Production 的 base_month 再套「起始月之前算在起始月」（原單與續保用保單生效月、批單用生效月與公告月較晚者、Oversea 用實際收付日）；
    舊資料保單用它的 Revenue Month（沒有月份時用本月）
  - 該月沒有匯率時用該月以前最新的一筆；那個月以前完全沒有時用任何月份中最新的一筆；沒有這個幣別的匯率時該筆為 0（與以前相同）
  - 美金＝每張保單用認列月匯率換成台幣後，再除以同一個月的 USD 匯率，最後加總（美金保單還原成原本的美金）
  - Mix by Class 與 Top Reinsurers 的金額與總額用同一套換算，加總永遠等於 Total Gross Premium
  - 不是 production_rules 的呼叫（差異測試）維持最新匯率的舊行為
純計算，不碰資料庫。"""
import os
from datetime import datetime
from zoneinfo import ZoneInfo
assert os.environ.get('RI_DISPOSABLE_QA') == 'true'
from dashboard.calc import build_dashboard, build_month_rate_lookup
from cases.calc.accounting import calc_legs_for_reinsurer
from production import calc as production
checks = []
def check(name, ok, detail=''):
    checks.append(name)
    assert ok, (name, detail)

check('premise: the Production start month is 2026-11 (earlier months are recognized in it)', production.start_month() == '2026-11', production.start_month())
now = datetime(2027, 3, 15, 10, tzinfo=ZoneInfo('Asia/Taipei'))
fx = [{'year_month': '2026-10', 'currency': 'USD', 'rate': 32.0}, {'year_month': '2026-11', 'currency': 'USD', 'rate': 30.0}, {'year_month': '2026-12', 'currency': 'USD', 'rate': 31.0},
      {'year_month': '2027-02', 'currency': 'USD', 'rate': 33.0}, {'year_month': '2027-04', 'currency': 'USD', 'rate': 28.0},   # 未來月份：本月以前的保單用不到它
      {'year_month': '2026-05', 'currency': 'USD', 'rate': 0},                                                                  # 零匯率忽略
      {'year_month': '2026-12', 'currency': 'EUR', 'rate': 36.0}, {'year_month': '2027-03', 'currency': 'EUR', 'rate': 38.0}]

# ---- 逐月匯率查表 ----
rate_at = build_month_rate_lookup(fx)
check('a month with a rate uses it (USD November 30, December 31)', rate_at('USD', '2026-11') == 30.0 and rate_at('USD', '2026-12') == 31.0)
check('a month without a rate uses the latest one before it (USD January 31, March 33, November 2026 EUR → none before → latest EUR 38)', (rate_at('USD', '2027-01'), rate_at('USD', '2027-03'), rate_at('EUR', '2026-11')) == (31.0, 33.0, 38.0))
check('before the first rate on file the latest rate overall is used (USD September 2026 → April 2027 at 28)', rate_at('USD', '2026-09') == 28.0 and rate_at('USD', '') == 28.0)
check('TWD is always 1 and a currency with no rate is 0', rate_at('TWD', '2026-05') == 1.0 and rate_at('JPY', '2026-05') == 0.0)
check('the first rate of a repeated month wins, like the existing lookup', build_month_rate_lookup([{'year_month': '2026-03', 'currency': 'USD', 'rate': 30}, {'year_month': '2026-03', 'currency': 'USD', 'rate': 99}])('USD', '2026-03') == 30)

# ---- 保單 ----
def case(i, currency, premium, policy_from, klass='Property', reinsurers=('Swiss Re',), parent=None, status='posted', posted=None):
    payload = {'newOrRenew': 'New', 'postedAt': (posted or policy_from) + 'T02:00:00Z', 'policyFrom': policy_from, 'policyTo': '2027-12-01', 'classOfBusiness': klass, 'currency': currency,
               'originalPremium': premium, 'reinsurers': [{'name': n, 'sharePct': 50, 'premium': premium} for n in reinsurers]}
    return {'id': i, 'parent_case_id': parent, 'status': status, 'announced_at': (posted or policy_from) + 'T02:00:00Z', 'payload': payload}
def cp(row):
    payload = row['payload']
    return sum(calc_legs_for_reinsurer(payload, r)['cp'] for r in payload['reinsurers'])
usd_nov = case(1, 'USD', 1000, '2026-11-05', 'Property', ['Swiss Re'])                    # 認列 2026-11：USD 30
eur_dec = case(2, 'EUR', 2000, '2026-12-05', 'Commercial General Liability', ['Allianz'])   # 認列 2026-12：EUR 36，USD 31
twd_jan = case(3, 'TWD', 640000, '2027-01-20', 'Property', ['Swiss Re'])                    # 認列 2027-01：TWD 1，USD 31（沒有一月匯率 → 十二月）
usd_old = case(4, 'USD', 500, '2026-03-10', 'Product Recall', ['QBE'])                      # 起始月之前 → 認列在 2026-11：USD 30（不是三月）
eur_mar = case(5, 'EUR', 1000, '2027-03-02', 'Property', ['Allianz'])                       # 認列 2027-03：EUR 38，USD 33
rows = [usd_nov, eur_dec, twd_jan, usd_old, eur_mar]
ex = {}
r = build_dashboard(rows, [], fx, now, production_rules=True, extras=ex)
g = r['metrics']['grossPremiumNtd']
expected = cp(usd_nov) * 30 + cp(eur_dec) * 36 + cp(twd_jan) + cp(usd_old) * 30 + cp(eur_mar) * 38
check('Total Gross Premium converts each policy at its recognition month (Nov USD 30, Dec EUR 36, Jan TWD 1, a March policy recognized in the start month → USD 30, Mar EUR 38)', abs(g - expected) < 1e-6, (g, expected))
latest = (cp(usd_nov) + cp(usd_old)) * 33 + (cp(eur_dec) + cp(eur_mar)) * 38 + cp(twd_jan)
check('it is no longer the old all-latest-rate total', abs(g - latest) > 1 and abs(r['metrics']['grossPremiumNtd'] - latest) > 1)
usd_expected = cp(usd_nov) + cp(usd_old) + cp(eur_dec) * 36 / 31 + cp(twd_jan) / 31 + cp(eur_mar) * 38 / 33
check('the USD total converts each policy at the same month: USD policies come back as their own USD amount', abs(ex['grossPremiumUsd']['amount'] - usd_expected) < 1e-6, (ex['grossPremiumUsd'], usd_expected))
check('the USD amount is not simply the TWD total over one rate', abs(ex['grossPremiumUsd']['amount'] - g / 33.0) > 1 and ex['grossPremiumUsd']['basis'] == 'recognition-month')
check('the class mix and the reinsurer ranking add up to the Total Gross Premium', abs(sum(x['amount'] for x in r['classMix']) - g) < 1e-6 and abs(sum(x['amount'] for x in r['reinsurers']) - g) < 1e-6, (sum(x['amount'] for x in r['classMix']), sum(x['amount'] for x in r['reinsurers']), g))
swiss = next(x['amount'] for x in r['reinsurers'] if x['name'] == 'Swiss Re')
check('a reinsurer takes its own policies at their own month rates (Swiss Re = November USD at 30 plus January TWD)', abs(swiss - (cp(usd_nov) * 30 + cp(twd_jan))) < 1e-6, (swiss, cp(usd_nov) * 30 + cp(twd_jan)))

# ---- 批單、單一匯率、舊口徑 ----
endo = case(6, 'USD', 200, '2027-02-10', 'Property', ['Swiss Re'], parent=1, posted='2027-02-12')
endo['payload'].update({'parentTwRef': 'TW-X', 'endoEffectiveDate': '2027-02-10', 'createdAt': '2027-02-12T02:00:00Z'})
r2 = build_dashboard(rows + [endo], [], fx, now, production_rules=True)
check('an endorsement of an in-force policy uses its own recognition month (February USD at 33)', abs(r2['metrics']['grossPremiumNtd'] - (g + cp(endo) * 33)) < 1e-6, (r2['metrics']['grossPremiumNtd'] - g, cp(endo) * 33))
one_rate = [{'year_month': '2027-03', 'currency': 'USD', 'rate': 33.0}, {'year_month': '2027-03', 'currency': 'EUR', 'rate': 38.0}]
r3 = build_dashboard(rows, [], one_rate, now, production_rules=True)
check('with a single rate per currency on file every month resolves to it: identical to the old all-latest total', abs(r3['metrics']['grossPremiumNtd'] - latest) < 1e-6, (r3['metrics']['grossPremiumNtd'], latest))
r4 = build_dashboard(rows, [], fx, now)
check('without production rules (the Alpha comparison mode) the old latest-rate behaviour is unchanged', abs(r4['metrics']['grossPremiumNtd'] - latest) < 1e-6, (r4['metrics']['grossPremiumNtd'], latest))
check('no other dashboard number changes', {k: v for k, v in r['metrics'].items() if k != 'grossPremiumNtd'} == {k: v for k, v in r4['metrics'].items() if k != 'grossPremiumNtd'})

# ---- 舊資料：用 Revenue Month ----
legacy = {'policies': [{'expiry': '2027-12-01', 'items': [{'currency': 'USD', 'premium': 1000, 'className': 'Property', 'party': 'Legacy Re', 'month': '2026-11'},
                                                          {'currency': 'USD', 'premium': 1000, 'className': 'Property', 'party': 'Legacy Re', 'month': '2026-12'},
                                                          {'currency': 'USD', 'premium': 1000, 'className': 'Property', 'party': 'Legacy Re'}]}],   # 沒有月份：用本月（2027-03 → 33）
          'trend': [], 'outstanding': [], 'bound': []}
ex5 = {}
r5 = build_dashboard([], [], fx, now, production_rules=True, legacy=legacy, extras=ex5)
check('legacy items convert at their Revenue Month (30, 31) and use this month when no month is known (33)', abs(r5['metrics']['grossPremiumNtd'] - (1000 * 30 + 1000 * 31 + 1000 * 33)) < 1e-6, r5['metrics']['grossPremiumNtd'])
check('legacy USD items come back as their own USD amounts', abs(ex5['grossPremiumUsd']['amount'] - 3000) < 1e-6, ex5['grossPremiumUsd'])
check('the class mix and reinsurer ranking still add up with legacy items', abs(sum(x['amount'] for x in r5['classMix']) - r5['metrics']['grossPremiumNtd']) < 1e-6 and abs(sum(x['amount'] for x in r5['reinsurers']) - r5['metrics']['grossPremiumNtd']) < 1e-6)

# ---- 沒有 USD 匯率 ----
ex6 = {}
r6 = build_dashboard(rows, [], [{'year_month': '2026-12', 'currency': 'EUR', 'rate': 36.0}], now, production_rules=True, extras=ex6)
check('no USD rate at all: no USD amount (the TWD total is still computed with the rates that exist)', ex6['grossPremiumUsd'] is None and r6['metrics']['grossPremiumNtd'] > 0)
ex7 = {}
build_dashboard([], [], [], now, production_rules=True, extras=ex7)
check('an empty dashboard has no USD amount', ex7['grossPremiumUsd'] is None)
print(f'{len(checks)}/{len(checks)} gross premium monthly-rate checks passed')
