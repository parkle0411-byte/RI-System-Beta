"""Check generated numbers and preservation of legacy reversal history."""
from cases.calc.accounting import build_premium_transactions, build_claim_payment_transactions
from cases.calc.payment_terms import premium_installment_plan
from production.closing import confirm_case
from production.calc import production_keys_for_case

checks = []
def check(name, ok):
    assert ok, name
    checks.append(name)
    print('PASS ' + name)

payload = {'twRef': 'TWPAR2609001', 'currency': 'USD', 'policyFrom': '2026-09-01',
           'performanceMonth': '2026-09', 'originalPremium': 1000, 'riCommPct': 10,
           'paymentTermsDays': 30, 'taxPct': 0,
           'reinsurers': [{'name': 'QA Re', 'sharePct': 100, 'premium': 800, 'riCommPct': 10, 'taxPct': 0}]}
txs = build_premium_transactions(payload)
check('premium transactions use T1, T2 and T3', [tx['txNo'] for tx in txs] == ['TWPAR2609001-R1-T1', 'TWPAR2609001-R1-T2', 'TWPAR2609001-R1-T3'])
check('the numbering change preserves amounts and Leg types', [tx['amount'] for tx in txs] == [900, 720, 180] and [tx['legType'] for tx in txs] == ['Leg 1', 'Leg 2', 'Leg 3'])
split = {**payload, 'splitEnabled': True, 'splitParties': [{'name': 'QA A', 'pct': 60}, {'name': 'QA B', 'pct': 40}]}
check('split-party suffixes remain a and b', [tx['txNo'] for tx in build_premium_transactions(split)] == ['TWPAR2609001-R1-T1a','TWPAR2609001-R1-T2a','TWPAR2609001-R1-T3a','TWPAR2609001-R1-T1b','TWPAR2609001-R1-T2b','TWPAR2609001-R1-T3b'])
installments = {**payload, 'installmentEnabled': True, 'performanceInstallments': [
    {'id': 'i1', 'performanceMonth': '2026-09', 'premium': 500, 'paymentBaseDate': '2026-09-01'},
    {'id': 'i2', 'performanceMonth': '2026-10', 'premium': 500, 'paymentBaseDate': '2026-10-01'}]}
plan = premium_installment_plan(installments)
check('installment sequence follows Tn as -I1 and -I2', [tx['txNo'] for item in plan for tx in build_premium_transactions(installments, item)] == [f'TWPAR2609001-R1-T{leg}-I{period}' for period in (1,2) for leg in (1,2,3)])
claims = build_claim_payment_transactions(payload, payload, {'id': 1, 'lossNo': 'LOSS-2026'}, {'id': 2, 'amount': 50})
check('claim prefix uses C1 and preserves payment/reinsurer/Leg segments', [tx['txNo'] for tx in claims] == ['TWPAR2609001-C1-P2-R1-T1', 'TWPAR2609001-C1-P2-R1-T2'])
check('claims continue to use actual claim IDs after C', [tx['txNo'] for tx in build_claim_payment_transactions(payload,payload,{'id':12},{'id':3,'amount':-50})] == ['TWPAR2609001-C12-P3-R1-T1','TWPAR2609001-C12-P3-R1-T2'])
old = {'txNo':'TWPAR2609001-R1-TX1','amount':900,'legType':'Leg 1','reversed':True}
case = {'tw_ref': payload['twRef'], 'status':'posted', 'payload':{**payload, 'reversalCycle':1,'pendingReversalOffset':True,'transactions':[old]}}
closed = confirm_case(case, [{'reinsurerKey': key} for key in production_keys_for_case(case)])['payload']['transactions']
check('historical stored transaction numbers are preserved', closed[0]['txNo'] == old['txNo'])
check('legacy reversal keeps its original reference and RVS suffix', any(tx.get('isReversalEntry') and tx['txNo'] == 'TWPAR2609001-R1-TX1-RVS1' and tx['amount'] == -900 for tx in closed))
check('corrected transactions use the new format with the existing cycle suffix', [tx['txNo'] for tx in closed if not tx.get('isReversalEntry') and not tx.get('reversed')] == ['TWPAR2609001-R1-T1-C1','TWPAR2609001-R1-T2-C1','TWPAR2609001-R1-T3-C1'])
print(f'{len(checks)}/{len(checks)} transaction-code checks passed')
