"""Transaction numbering, batch 2 of the accounting unification (owner decisions 2026-11-13/14).

- Installment number before T: -R1-I2-T1 (Cedant aggregate -I2-T1; Oversea -R1-I2-T3).
- Rebuild after whole-Case Reverse ends in -V{cycle}; its reversal entries keep -RVS{cycle}.
- C only means Claim: -C{claim}-P{payment}-R{n}-T1/T2.
- Finance corrections of a closed month: reversal {base}-ADJ{n}-OLD, replacement {base}-ADJ{n}
  (checked in finance_corrections, which builds real closed corrections).
Pure calculation: nothing is written.
"""
import copy, re
from cases.calc.accounting import build_premium_transactions, build_claim_payment_transactions
from cases.calc.payment_terms import premium_installment_plan
from cases.property_original import transactions as property_transactions, enabled as property_enabled
from production.closing import confirm_case
from production.calc import production_keys_for_case

checks = []
def check(name, ok, detail=''):
    assert ok, (name, detail)
    checks.append(name)
    print('PASS ' + name)

NOW = '2026-09-01T00:00:00Z'
REF = 'TWPF2609001'
base = {'twRef': REF, 'currency': 'USD', 'policyFrom': '2026-09-01', 'policyTo': '2027-09-01', 'performanceMonth': '2026-09',
        'originalPremium': 1000, 'riCommPct': 10, 'paymentTermsDays': 30, 'taxPct': 0, 'announcedAt': NOW,
        'reinsurers': [{'name': 'QA Re One', 'sharePct': 60, 'premium': 480, 'riCommPct': 10, 'taxPct': 0},
                       {'name': 'QA Re Two', 'sharePct': 40, 'premium': 320, 'riCommPct': 10, 'taxPct': 0}]}
installments = {**base, 'installmentEnabled': True, 'performanceInstallments': [
    {'id': 'i1', 'performanceMonth': '2026-09', 'premium': 500, 'paymentBaseDate': '2026-09-01'},
    {'id': 'i2', 'performanceMonth': '2026-10', 'premium': 500, 'paymentBaseDate': '2026-10-01'}]}
numbers = lambda txs: [t['txNo'] for t in txs]
generated = []

# 1. Named reinsurers (every new Case): one T1/T2/T3 per reinsurer.
check('named reinsurers use the per-reinsurer ledger', property_enabled(base))
plain = property_transactions(base, NOW); generated += plain
check('no installments: -R{n}-T1/T2/T3', numbers(plain) == [f'{REF}-R{r}-T{leg}' for r in (1, 2) for leg in (1, 2, 3)], numbers(plain))
split = property_transactions(installments, NOW); generated += split
check('installments: the installment number comes before T (-R1-I2-T1)',
      numbers(split) == [f'{REF}-R{r}-I{i}-T{leg}' for i in (1, 2) for r in (1, 2) for leg in (1, 2, 3)], numbers(split))
plan = premium_installment_plan(installments)
per_period = [t for item in plan for t in build_premium_transactions(installments, item)]
check('per-installment build gives the same numbers', numbers(per_period) == numbers(split), numbers(per_period))
rebuilt = property_transactions({**installments, 'reversalCycle': 1}, NOW); generated += rebuilt
check('rebuild after whole-Case Reverse ends in -V{cycle}', numbers(rebuilt) == [n + '-V1' for n in numbers(split)], numbers(rebuilt))
check('second rebuild uses -V2', all(n.endswith('-V2') for n in numbers(property_transactions({**installments, 'reversalCycle': 2}, NOW))))

# 2. Preserved Cedant-aggregate layout (historical ledgers): T1/T3 without R.
aggregate = property_transactions({**installments, 'premiumLedgerLayout': 'preserved'}, NOW); generated += aggregate
check('aggregate layout: -I{n}-T1, -I{n}-T3 and per-reinsurer -R{n}-I{n}-T2',
      numbers(aggregate) == [x for i in (1, 2) for x in (f'{REF}-I{i}-T1', f'{REF}-I{i}-T3', f'{REF}-R1-I{i}-T2', f'{REF}-R2-I{i}-T2')], numbers(aggregate))
aggregate_v = property_transactions({**installments, 'premiumLedgerLayout': 'preserved', 'reversalCycle': 1}, NOW)
check('aggregate rebuild ends in -V1', numbers(aggregate_v) == [n + '-V1' for n in numbers(aggregate)], numbers(aggregate_v))

# 3. Calculation without named reinsurers (ordinary builder): same order, split parties a/b after T.
unnamed = {**installments, 'reinsurers': [{**r, 'name': ''} for r in installments['reinsurers']]}
check('unnamed reinsurers use the ordinary builder', not property_enabled(unnamed))
ordinary = [t for item in premium_installment_plan(unnamed) for t in build_premium_transactions(unnamed, item)]; generated += ordinary
check('ordinary builder: -R{n}-I{n}-T{leg}', numbers(ordinary) == [f'{REF}-R{r}-I{i}-T{leg}' for i in (1, 2) for r in (1, 2) for leg in (1, 2, 3)], numbers(ordinary))
parties = {**unnamed, 'splitEnabled': True, 'splitParties': [{'name': 'QA A', 'pct': 60}, {'name': 'QA B', 'pct': 40}]}
party_txs = [t for item in premium_installment_plan(parties) for t in build_premium_transactions(parties, item)]; generated += party_txs
check('split parties keep a/b right after T (-R1-I2-T1a)', numbers(party_txs)[:6] == [f'{REF}-R1-I1-T{leg}{s}' for s in 'ab' for leg in (1, 2, 3)], numbers(party_txs)[:6])

# 4. Production close after whole-Case Reverse (ordinary builder): -RVS{cycle} reversal, -V{cycle} rebuild.
old = {'txNo': f'{REF}-R1-T1', 'amount': 900, 'legType': 'Leg 1', 'reversed': True}
unnamed_full = {**base, 'reinsurers': [{**r, 'name': ''} for r in base['reinsurers']]}
case = {'tw_ref': REF, 'status': 'posted', 'payload': {**unnamed_full, 'reversalCycle': 1, 'pendingReversalOffset': True, 'transactions': [old]}}
closed = confirm_case(copy.deepcopy(case), [{'reinsurerKey': key} for key in production_keys_for_case(case)])['payload']['transactions']
check('stored numbers are kept', closed[0]['txNo'] == old['txNo'])
check('whole-Case reversal entry keeps -RVS{cycle}', any(t.get('isReversalEntry') and t['txNo'] == f'{REF}-R1-T1-RVS1' and t['amount'] == -900 for t in closed), numbers(closed))
fresh = [t for t in closed if not t.get('isReversalEntry') and not t.get('reversed')]; generated += fresh
check('rebuilt accounts end in -V{cycle}', numbers(fresh) == [f'{REF}-R{r}-T{leg}-V1' for r in (1, 2) for leg in (1, 2, 3)], numbers(fresh))

# 5. Claims keep C.
claims = build_claim_payment_transactions(base, base, {'id': 3, 'lossNo': 'LOSS-QA'}, {'id': 2, 'amount': 50})
check('claims: -C{claim}-P{payment}-R{n}-T1/T2', numbers(claims) == [f'{REF}-C3-P2-R{r}-T{leg}' for r in (1, 2) for leg in (1, 2)], numbers(claims))

# 6. C only means Claim; numbers are unique.
check('no premium number uses C', generated and not [n for n in numbers(generated) if re.search(r'-C[0-9]', n)], numbers(generated))
for label, txs in [('plain', plain), ('installments', split), ('rebuild', rebuilt), ('aggregate', aggregate), ('ordinary', ordinary), ('parties', party_txs), ('closing', closed)]:
    check('unique numbers: ' + label, len(set(numbers(txs))) == len(txs), numbers(txs))
print(f'{len(checks)}/{len(checks)} transaction-numbering checks passed')
