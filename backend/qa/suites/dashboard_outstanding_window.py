"""2026-10-29 業主：Dashboard 的未結清應收／應付只算 5 年內「建立」的帳款（往回 5 年、每天滾動；正常 2 年內結清）。
每筆帳款看自己的建立時間（createdAt 的台北日期）：保費帳款是 Announce 時、理賠帳款是記錄理賠付款時。
建立時間缺漏或無法解讀的照算。純計算，不寫資料庫。"""
import copy
import os
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

from cases.property_original import enabled, refresh_transactions
from dashboard.calc import build_dashboard, _years_before, _taipei_day

assert os.environ.get('RI_DISPOSABLE_QA') == 'true'
checks = []
def check(name, ok, detail=''):
    assert ok, f'{name} {detail}'
    checks.append(name); print('PASS ' + name, flush=True)

TAIPEI = ZoneInfo('Asia/Taipei')
NOW = datetime(2026, 10, 29, 3, 0, tzinfo=timezone.utc)          # 台北 2026-10-29 11:00
CUTOFF = '2021-10-29'
BASE = dict(reinsuranceStructure='QS', classOfBusiness='Property', classCode='PD', currency='TWD', originalPremium=100000,
            riCommPct=10, taxPct=1, paymentTermsDays=90, policyFrom='2026-01-15', policyTo='2027-01-15', reinsured='QA Cedant',
            reinsurers=[dict(name='QA Ordinary Re', sharePct=50, premium=100000, riCommPct=20, taxPct=1, paymentTermsDays=90)],
            transactions=[], paymentEntries=[], claims=[])
_ids = iter(range(1, 1000))

def case(created='2026-01-20T02:00:00+00:00', *, claims=(), policy_from='2026-01-15'):
    """created：保費帳款的建立時間（Announce 時）；claims：[(理賠帳款建立時間, 金額)]。"""
    p = copy.deepcopy(BASE)
    p['policyFrom'] = policy_from
    p['twRef'] = f'QAWIN{next(_ids):03d}'
    assert enabled(p)
    p['announcedAt'] = '2026-01-20T02:00:00+00:00'
    refresh_transactions(p, '2026-01-20T02:00:00+00:00')
    for t in p['transactions']:
        if created is None:
            t.pop('createdAt', None)
        else:
            t['createdAt'] = created
    for n, (stamp, amount) in enumerate(claims, 1):
        p['claims'].append({'id': n, 'dateOfLoss': '2026-03-01', 'lossNo': f'L{n}'})
        p['transactions'].append({'txNo': f"{p['twRef']}-C{n}-R1", 'source': 'claim', 'claimId': n, 'paymentId': 1, 'legType': 'Claim Leg 1',
                                  'reinsurer': 'QA Ordinary Re', 'reinsurerIdx': 0, 'amount': amount, 'settlement': 'open', 'createdAt': stamp})
    return {'id': next(_ids), 'parent_case_id': None, 'status': 'closed', 'payload': p,
            'announced_at': '2026-01-20T10:00:00+08:00', 'created_at': '2026-01-20T10:00:00+08:00'}

def out(*rows):
    m = build_dashboard(list(rows), [], [], NOW, tz=TAIPEI, production_rules=True)['metrics']
    return round(m['outstandingLeg1Ntd'] + m['outstandingLeg2Ntd'], 2), m

total, metrics = out(case())
check('the window start is shown: today minus 5 years (Taipei)', metrics.get('outstandingSince') == CUTOFF, metrics.get('outstandingSince'))
check('entries created recently are counted', total > 0, total)
recent_premium = total

check('entries created 6 years ago: not counted', out(case('2020-06-01T02:00:00+00:00'))[0] == 0)
check('entries created on the boundary day (Taipei date) are counted', out(case('2021-10-29T00:30:00+08:00'))[0] == recent_premium)
check('the Taipei date decides: 2021-10-28 16:30 UTC is 2021-10-29 in Taipei, counted', out(case('2021-10-28T16:30:00+00:00'))[0] == recent_premium)
check('entries created the day before the boundary (Taipei): not counted', out(case('2021-10-28T23:59:00+08:00'))[0] == 0)
check('entries created 4 years ago: counted', out(case('2022-11-01T02:00:00+00:00'))[0] == recent_premium)
check('missing creation time: still counted (debts are never hidden)', out(case(None))[0] == recent_premium)
check('unreadable creation time: still counted', out(case('not a date'))[0] == recent_premium)
check('the policy effective date does not matter, only when the entry was created',
      out(case(policy_from='2018-01-01'))[0] == recent_premium and out(case('2019-01-01T00:00:00+00:00', policy_from='2026-01-15'))[0] == 0)

with_claim = out(case(claims=[('2026-05-01T02:00:00+00:00', 3000)]))[0]
claim_only = round(with_claim - recent_premium, 2)
check('a recent claim entry adds its own outstanding amount', claim_only > 0, (with_claim, recent_premium))
check('old premium entries with a recent claim entry: only the claim is counted',
      out(case('2019-01-01T00:00:00+00:00', claims=[('2026-05-01T02:00:00+00:00', 3000)]))[0] == claim_only)
check('recent premium with a claim entry created 7 years ago: only the premium is counted',
      out(case(claims=[('2019-05-01T02:00:00+00:00', 3000)]))[0] == recent_premium)
check('everything older than 5 years: nothing counted',
      out(case('2019-01-01T00:00:00+00:00', claims=[('2019-05-01T02:00:00+00:00', 3000)]))[0] == 0)
check('several cases add up the same as each one alone',
      out(case(), case('2020-06-01T02:00:00+00:00'), case('2019-01-01T00:00:00+00:00', claims=[('2026-05-01T02:00:00+00:00', 3000)]))[0]
      == round(recent_premium + claim_only, 2))
check('Feb 29 rolls back to Feb 28 in a non-leap year', _years_before('2028-02-29', 5) == '2023-02-28' and _years_before('2024-02-29', 4) == '2020-02-29')
check('creation time helper: Taipei date, None for missing or unreadable',
      _taipei_day('2021-10-28T16:30:00Z') == '2021-10-29' and _taipei_day('') is None and _taipei_day(None) is None and _taipei_day('x') is None)
print(f'{len(checks)}/{len(checks)} passed (pure calculation)', flush=True)
