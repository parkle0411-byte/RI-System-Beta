"""2026-11-02 效能優化：結果必須與原寫法完全相同。
- json_roundtrip（最後的深層複製）快速版與原寫法逐項相同（型別、鍵順序、-0、NaN／Infinity、undefined、子類別）。
- 同一件案件的付款排程與交易明細共用一次指紋；關閉快取時不算指紋，結果相同。
純計算，不寫資料庫。"""
import math
import os
import random
from datetime import datetime, timezone

from cases import case_result_cache as crc
from cases.calc import jsnum
from cases.calc.jsnum import UNDEFINED, json_roundtrip, _json_roundtrip_reference
from cases.property_original import enabled, refresh_transactions
from cases.shared_compute import CaseCompute

assert os.environ.get('RI_DISPOSABLE_QA') == 'true'
checks = []
def check(name, ok, detail=''):
    assert ok, f'{name} {detail}'
    checks.append(name); print('PASS ' + name, flush=True)


class F(float): pass
class D(dict): pass
class L(list): pass
KEYS = ['a', 'b', '0', '1', '10', '01', '-1', '4294967294', '4294967295', '１', '', 'z']
rnd = random.Random(1102)
def leaf():
    return rnd.choice([None, True, False, 0, -0.0, 0.0, 1, -5, 2 ** 60, 1.5, math.nan, math.inf, -math.inf, '', 'é漢', UNDEFINED, F(-0.0), F(math.nan), F(2.5)])
def gen(depth=0):
    r = rnd.random()
    if depth > 4 or r < .35: return leaf()
    if r < .7:
        box = D() if rnd.random() < .1 else {}
        for k in rnd.sample(KEYS, rnd.randint(0, 7)): box[k] = gen(depth + 1)
        return box
    items = [gen(depth + 1) for _ in range(rnd.randint(0, 5))]
    return L(items) if rnd.random() < .1 else items
def canon(v):
    if isinstance(v, dict): return ('D', type(v).__name__, [(k, canon(x)) for k, x in v.items()])
    if isinstance(v, list): return ('L', type(v).__name__, [canon(x) for x in v])
    if isinstance(v, float): return ('F', type(v).__name__, 'nan' if v != v else repr(v), math.copysign(1, v))
    return (type(v).__name__, repr(v))

diffs = sum(canon(json_roundtrip(v)) != canon(_json_roundtrip_reference(v)) for v in (gen() for _ in range(30000)))
check('deep copy: 30,000 random values identical to the original method', diffs == 0, diffs)
check('deep copy: integer-like keys first, then insertion order',
      list(json_roundtrip({'b': 1, '2': 2, 'a': 3, '1': 4})) == ['1', '2', 'b', 'a'])
check('deep copy: -0 -> 0, NaN/Infinity -> null, undefined key dropped, undefined in list -> null',
      json_roundtrip({'x': -0.0, 'n': math.nan, 'i': math.inf, 'u': UNDEFINED, 'l': [UNDEFINED, 1]}) == {'x': 0.0, 'n': None, 'i': None, 'l': [None, 1]}
      and math.copysign(1, json_roundtrip(-0.0)) == 1)
src = {'a': [{'b': 1}]}; out = json_roundtrip(src); out['a'][0]['b'] = 9
check('deep copy: result does not share nested objects with the source', src == {'a': [{'b': 1}]})
big = {str(i): i for i in range(500)}
json_roundtrip(big)
check('deep copy: key-order memo skips very large objects', tuple(big) not in jsnum._KEY_ORDER_MEMO)

p = dict(reinsuranceStructure='QS', classOfBusiness='Property', classCode='PD', currency='TWD', originalPremium=100000, riCommPct=10, taxPct=1,
         paymentTermsDays=90, policyFrom='2026-01-15', policyTo='2027-01-15', reinsured='QA Cedant', twRef='QAPERF001',
         reinsurers=[dict(name='QA Ordinary Re', sharePct=50, premium=100000, riCommPct=20, taxPct=1, paymentTermsDays=90)],
         transactions=[], paymentEntries=[], claims=[])
assert enabled(p)
p['announcedAt'] = '2026-01-20T02:00:00+00:00'
refresh_transactions(p, '2026-01-20T02:00:00+00:00')
case = {'caseUid': 'u1', 'payload': p, 'currency': 'TWD', 'reinsured': 'QA Cedant'}
now = datetime(2026, 11, 2, 3, 0, tzinfo=timezone.utc)
calls = []
real = crc.fingerprint
crc_fp = lambda payload: calls.append(1) or real(payload)
import cases.shared_compute as sc
sc.fingerprint = crc_fp
try:
    crc.clear(); cc = CaseCompute(case, now); a = (cc.schedule('raw'), cc.details('override'))
    check('one fingerprint per case for schedule + details', len(calls) == 1, len(calls))
    crc.clear(); fresh = (CaseCompute(case, now).schedule('raw'), CaseCompute(case, now).details('override'))
    check('results equal a fresh computation', canon(json_roundtrip(a)) == canon(json_roundtrip(fresh)))
    calls.clear(); os.environ['RI_CASE_RESULT_CACHE'] = 'false'
    off = CaseCompute(case, now); b = (off.schedule('raw'), off.details('override'))
    check('cache off: no fingerprint, same results', not calls and canon(json_roundtrip(a)) == canon(json_roundtrip(b)), len(calls))
finally:
    os.environ.pop('RI_CASE_RESULT_CACHE', None); sc.fingerprint = real; crc.clear()
print(f'{len(checks)}/{len(checks)} passed (pure calculation)', flush=True)
