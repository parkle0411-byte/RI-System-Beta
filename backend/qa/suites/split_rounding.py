"""Performance Split cents: a + b equals the leg exactly and the Leg 1 total equals the payment schedule.

Pure calculations (no database writes), so it can also run outside the disposable stack.
"""
import random

from cases.draft import normalize_draft
from cases.calc.accounting import build_premium_transactions
from cases.calc.payment_terms import build_payment_schedule

checks = []


def check(name, condition):
    assert condition, name
    checks.append(name)
    print('PASS ' + name)


def case(names, shares, premium, comm, tax, split, currency='TWD'):
    # Property QS Original uses fixed 40/60 or 70/30; arbitrary legacy splits are verified outside that scope.
    # 2026-10-20：TWD 保費只准整數（每步取位到元）；USD 保留兩位小數
    whole = currency == 'TWD'
    raw = {'reinsuranceStructure': 'QS', 'classOfBusiness': 'Legacy Split Class', 'currency': currency, 'reinsured': 'ZZ Cedant',
           'originalInsured': 'ZZ', 'policyFrom': '2026-10-01', 'policyTo': '2027-10-01', 'paymentTermsDays': 90,
           'originalPremium': premium, 'riCommPct': comm, 'taxPct': tax, 'installmentEnabled': False, 'cedantTermsBasis': 'case',
           'reinsurers': [{'name': n, 'sharePct': sh, 'premium': round(premium * sh / 100) if whole else round(premium * sh / 100, 2), 'riCommPct': comm, 'taxPct': tax,
                           'paymentTermsDays': 60} for n, sh in zip(names, shares)], 'originalInsuredCn':'合成測試被保險人'}
    if split:
        raw.update(splitEnabled=True, splitParties=[{'name': 'A', 'pct': split}, {'name': 'B', 'pct': round(100 - split, 6)}])
    result = normalize_draft(raw)
    assert not result['errors'], result['errors']
    value = result['value']
    value['twRef'] = 'ZZ-SPLIT'
    return value


# Known case from the 2026-10-14 debug: 1800 premium, 5% commission+tax, uneven split.
known = case(['ZZ Re A', 'ZZ Re B'], [60, 40], 1800, 5, 0, 33)
rows = build_premium_transactions(known)
plain = build_premium_transactions({**known, 'splitEnabled': False})
check('Performance Split does not split the independent T1/T2/T3 cash ledgers',[(t['txNo'],t['amount']) for t in rows]==[(t['txNo'],t['amount']) for t in plain] and len(rows)==6)
from production.calc import build_production_preview
report=build_production_preview([{'id':1,'case_uid':'QA-SPLIT','status':'posted','payload':known,'announced_at':'2026-10-01T00:00:00Z'}],'2026-10',{},[])['rows']
check('Performance Split belongs to Production, with two people per reinsurer',len(report)==4)
check('Production premium is conserved across the two people',sum(r['premium'] for r in report)==1800)
check('Other Staff gets rounded Case total 820 x 67%=549; first RI absorbs the one-dollar tail',sum(r['income'] for r in report if r['ae']=='B')==549 and sum(r['income'] for r in report if r['ae']=='A')==271)

random.seed(2026)
bad = []
for n in range(1500):
    count = random.randint(1, 3)
    cuts = sorted(random.sample(range(1, 100), count - 1))
    shares = [b - a for a, b in zip([0] + cuts, cuts + [100])]
    currency = 'USD' if n % 2 else 'TWD'   # TWD 只用整數保費；USD 保留小數保費
    premiums = [509, 1800, 757.29, 1084, 333.33] if currency == 'USD' else [509, 1800, 757, 1084, 333]
    value = case([f'ZZ Re {i}' for i in range(count)], shares, random.choice(premiums),
                 random.choice([0, 5, 10, 12.5]), random.choice([0, 1, 5]), random.randint(1, 99), currency)
    schedule = build_payment_schedule(value, '2026-10-14T02:00:00Z')['items']
    ledger = build_premium_transactions(value)
    cedant = sum(i['amount'] for i in schedule if i['partyType'] == 'cedant')
    leg1 = sum(t['amount'] for t in ledger if t['legType'].startswith('Leg 1'))
    if abs(cedant - leg1) > 0.0049:
        bad.append((cedant, leg1))
check('1,500 random split cases (TWD whole dollars and USD cents): Leg 1 total equals the Cedant schedule', not bad)

print(f'{len(checks)}/{len(checks)} passed; no database access')
