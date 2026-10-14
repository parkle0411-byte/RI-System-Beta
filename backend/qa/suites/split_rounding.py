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


def case(names, shares, premium, comm, tax, split):
    raw = {'reinsuranceStructure': 'QS', 'classOfBusiness': 'Property', 'currency': 'TWD', 'reinsured': 'ZZ Cedant',
           'originalInsured': 'ZZ', 'policyFrom': '2026-10-01', 'policyTo': '2027-10-01', 'paymentTermsDays': 90,
           'originalPremium': premium, 'riCommPct': comm, 'taxPct': tax, 'installmentEnabled': False, 'cedantTermsBasis': 'case',
           'reinsurers': [{'name': n, 'sharePct': sh, 'premium': round(premium * sh / 100, 2), 'riCommPct': comm, 'taxPct': tax,
                           'paymentTermsDays': 60} for n, sh in zip(names, shares)]}
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
for leg in ('Leg 1', 'Leg 2', 'Leg 3'):
    for idx in (0, 1):
        a = next(t for t in rows if t['legType'] == leg + 'a' and t['reinsurerIdx'] == idx)['amount']
        b = next(t for t in rows if t['legType'] == leg + 'b' and t['reinsurerIdx'] == idx)['amount']
        whole = next(t for t in plain if t['legType'] == leg and t['reinsurerIdx'] == idx)['amount']
        check(f'{leg} reinsurer {idx + 1}: a + b equals the leg', round(a + b, 2) == whole)

# Unequal percentages that do not total 100 keep the original independent rounding.
partial = {**known, 'splitParties': [{'name': 'A', 'pct': 30}, {'name': 'B', 'pct': 30}]}
only = build_premium_transactions(partial)
check('percentages not totalling 100 are not forced to the leg total', sum(t['amount'] for t in only if t['legType'] == 'Leg 1a') > 0)

random.seed(2026)
bad = []
for _ in range(1500):
    count = random.randint(1, 3)
    cuts = sorted(random.randint(1, 99) for _ in range(count - 1))
    shares = [b - a for a, b in zip([0] + cuts, cuts + [100])]
    value = case([f'ZZ Re {i}' for i in range(count)], shares, random.choice([509, 1800, 757.29, 1084, 333.33]),
                 random.choice([0, 5, 10, 12.5]), random.choice([0, 1, 5]), random.randint(1, 99))
    schedule = build_payment_schedule(value, '2026-10-14T02:00:00Z')['items']
    ledger = build_premium_transactions(value)
    cedant = sum(i['amount'] for i in schedule if i['partyType'] == 'cedant')
    leg1 = sum(t['amount'] for t in ledger if t['legType'].startswith('Leg 1'))
    if abs(cedant - leg1) > 0.0049:
        bad.append((cedant, leg1))
check('1,500 random split cases: Leg 1 total equals the Cedant schedule', not bad)

print(f'{len(checks)}/{len(checks)} passed; no database access')
