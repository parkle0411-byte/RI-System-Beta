"""Mix by Class of Business 至少 10 列（2026-11-26 業主決定；`dashboard.calc.class_mix`）。

  - 依金額前 10 名，第 11 名之後併入 Other
  - 有金額的不足 10 個：依啟用中險種的 Master Data 順序補 0% 到 10 列；不重複（不分大小寫）
  - 完全沒有金額時不補
  - 沒傳險種清單時維持原本「前 5 名＋Other」
純計算，不碰資料庫。"""
import os
assert os.environ.get('RI_DISPOSABLE_QA') == 'true'
from dashboard.calc import build_dashboard, class_mix
checks = []
def check(name, ok, detail=''):
    checks.append(name)
    assert ok, (name, detail)
MASTER = [f'Class {i:02d}' for i in range(1, 16)]
seven = {f'Class {i:02d}': float(100 - i) for i in (3, 1, 9, 2, 12, 4, 14)}
r = class_mix(seven, MASTER)
check('seven classes with premium give exactly 10 rows', len(r) == 10, len(r))
check('the classes with premium come first, largest first', [x['name'] for x in r[:7]] == [f'Class {i:02d}' for i in (1, 2, 3, 4, 9, 12, 14)], [x['name'] for x in r])
check('the rest are filled in Master Data order with 0 amount and 0%, without repeating', [x['name'] for x in r[7:]] == ['Class 05', 'Class 06', 'Class 07'] and all(x['amount'] == 0 and x['pct'] == 0 for x in r[7:]), r[7:])
check('percentages still add up to 100', abs(sum(x['pct'] for x in r) - 100) < 1e-9)
check('there is no Other row when ten or fewer classes have premium', all(x['name'] != 'Other' for x in r))
twelve = {f'Class {i:02d}': float(100 - i) for i in range(1, 13)}
r = class_mix(twelve, MASTER)
check('more than ten: the top ten and one Other row holding the rest', len(r) == 11 and r[-1]['name'] == 'Other' and r[-1]['amount'] == (100 - 11) + (100 - 12) and abs(sum(x['pct'] for x in r) - 100) < 1e-9, r[-2:])
r = class_mix({'class 01': 5.0}, MASTER)
check('a class name that differs only in letter case is not listed twice', len(r) == 10 and sum(1 for x in r if x['name'].casefold() == 'class 01') == 1, [x['name'] for x in r])
r = class_mix({'Property': 5.0}, ['A', 'B'])
check('with fewer classes than ten all of them are listed', [x['name'] for x in r] == ['Property', 'A', 'B'], r)
check('with no premium at all nothing is filled in', class_mix({}, MASTER) == [])
r = class_mix(twelve, None)
check('without a class list the previous top five + Other is unchanged', len(r) == 6 and r[-1]['name'] == 'Other')
empty = build_dashboard([], [], [], production_rules=True, mix_classes=MASTER)
check('an empty dashboard stays empty', empty['classMix'] == [])
legacy = {'policies': [{'expiry': '2999-01-01', 'items': [{'currency': 'TWD', 'premium': 100, 'className': 'Class 02', 'party': 'QA Re', 'month': ''}]}], 'trend': [], 'bound': [], 'outstanding': []}
a = build_dashboard([], [], [], production_rules=True, legacy=legacy, mix_classes=MASTER)
b = build_dashboard([], [], [], production_rules=True, legacy=legacy)
check('through build_dashboard: 10 rows with the premium class first; other fields are the same as before', len(a['classMix']) == 10 and a['classMix'][0]['name'] == 'Class 02' and {k: v for k, v in a.items() if k != 'classMix'} == {k: v for k, v in b.items() if k != 'classMix'}, a['classMix'][:3])
print(f'{len(checks)}/{len(checks)} dashboard class mix checks passed')
