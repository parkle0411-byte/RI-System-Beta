import unittest
from cases.facility_declaration_ledger import settlement_plan, transactions, corrected_transactions
from cases.calc.accounting import reconciliation_ref_for
from cases.cash_ledger import transaction_details


class DeclarationLedger(unittest.TestCase):
    def setUp(self):
        self.facility = {'reinsured': 'Cedant', 'currency': 'USD', 'riCommPct': 20, 'taxPct': 0,
                         'reinsurers': [{'name': 'A', 'facilityReference': 'RA', 'sharePct': 50, 'deductionPct': 30, 'taxPct': 0},
                                        {'name': 'B', 'facilityReference': 'RB', 'sharePct': 30, 'deductionPct': 25, 'taxPct': 0}]}
        self.declaration = {'premium': 100, 'claim': 30, 'statementNo': 'S1', 'periodFrom': '2026-07-01',
                            'periodTo': '2026-09-30', 'dueDate': '2026-12-14'}

    def test_partial_placement_and_references(self):
        lines = settlement_plan(self.facility, self.declaration)
        self.assertEqual(sum(x['net'] for x in lines if x['partyType'] == 'cedant'), 40)
        self.assertEqual(sum(x['net'] for x in lines if x['partyType'] == 'reinsurer'), 33.5)
        self.assertEqual([(x['reinsurerReference'], x['statementNo']) for x in lines[::2]], [('RA', 'S1'), ('RB', 'S1')])
        self.assertEqual([x['direction'] for x in lines], ['receivable', 'payable', 'receivable', 'payable'])

    def test_claim_only_reverses_directions_and_has_no_brokerage(self):
        lines = settlement_plan(self.facility, {**self.declaration, 'premium': 0, 'claim': 100})
        self.assertEqual([x['direction'] for x in lines], ['payable', 'receivable', 'payable', 'receivable'])
        self.assertTrue(all(x['brokerage'] == 0 for x in lines))

    def test_signed_adjustment_reverses_directions(self):
        positive = settlement_plan(self.facility, self.declaration)
        negative = settlement_plan(self.facility, {**self.declaration, 'premium': -100, 'claim': -30})
        for a, b in zip(positive, negative):
            self.assertEqual(a['net'], -b['net'])
            self.assertNotEqual(a['direction'], b['direction'])

    def test_netted_transactions_are_cash_trackable_and_references_follow_source(self):
        facility = {**self.facility, 'twRef': 'TWPA2607001', 'reinsuranceStructure': 'FACILITY'}
        txs = transactions(facility, self.declaration, 'test-id', '2026-10-01T00:00:00Z', '2026-09')
        details = transaction_details({**facility, 'transactions': txs, 'paymentEntries': []})
        self.assertEqual(details[txs[0]['txNo']]['paymentDirection'], 'receivable')
        self.assertEqual(details[txs[1]['txNo']]['paymentDirection'], 'payable')
        self.assertTrue(details[txs[0]['txNo']]['canRecord'])
        self.assertEqual(details[txs[0]['txNo']]['dueDate'], '2026-12-14')
        self.assertEqual(reconciliation_ref_for(facility, txs[0]), 'S1')
        self.assertEqual(reconciliation_ref_for(facility, txs[1]), 'RA')
        facility['reinsurers'][0]['facilityReference'] = 'RA-NEW'
        self.assertEqual(reconciliation_ref_for(facility, txs[1]), 'RA-NEW')

    def test_closed_correction_retains_original_reversal_and_full_replacement(self):
        facility = {**self.facility, 'twRef': 'TWPA2607001', 'reinsuranceStructure': 'FACILITY'}
        original = transactions(facility, self.declaration, 'test-id', '2026-10-01T00:00:00Z', '2026-09')
        replacement = transactions(facility, {**self.declaration, 'premium': 120}, 'test-id', '2026-11-01T00:00:00Z', '2026-11')
        corrected = corrected_transactions(original, replacement, 1, True)
        self.assertEqual(len(corrected), 18)
        for before in original:
            reversal = next(row for row in corrected if row.get('reversalOf') == before['txNo'])
            self.assertEqual(reversal['amount'], -before['amount'])
            self.assertTrue(reversal['isReversalEntry'])
        self.assertEqual(len([row for row in corrected if row.get('correctionRevision') == 1]), 6)

    def test_review_prerequisite_does_not_cross_declarations(self):
        from cases.finance_workflow import review_prerequisite
        facility = {**self.facility, 'twRef': 'TWPA2607001', 'reinsuranceStructure': 'FACILITY'}
        first = transactions(facility, self.declaration, 'first', '2026-10-01T00:00:00Z', '2026-09')
        second = transactions(facility, self.declaration, 'second', '2026-11-01T00:00:00Z', '2026-10')
        detail = {'paymentDirection': 'payable', 'partyType': 'reinsurer'}
        kind, references = review_prerequisite({**facility, 'transactions': first + second}, second[1]['txNo'], detail)
        self.assertEqual(kind, 'premium')
        self.assertEqual(references, [second[0]['txNo']])

    def test_existing_named_facility_rules_do_not_override_ppw(self):
        from cases.calc.swiss_facility import applies
        swiss = 'Swiss Re Asia Pte. Ltd., Hong Kong Branch (Facility)'
        facility = {**self.facility, 'twRef': 'TWPA2607001', 'classOfBusiness': 'Property',
                    'reinsuranceStructure': 'FACILITY', 'reinsurers': [{**self.facility['reinsurers'][0], 'name': swiss}]}
        txs = transactions(facility, self.declaration, 'test-id', '2026-10-01T00:00:00Z', '2026-09')
        detail = transaction_details({**facility, 'transactions': txs, 'paymentEntries': []})[txs[1]['txNo']]
        self.assertFalse(applies(facility))
        self.assertEqual(detail['dueDate'], '2026-12-14')


if __name__ == '__main__': unittest.main()
