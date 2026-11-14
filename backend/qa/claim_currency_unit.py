import unittest
from cases.claim_currency import claim_currency, multi_currency_scope, valid_amount, allocate_claim_shares
from cases.calc.accounting import build_claim_payment_transactions


class ClaimCurrency(unittest.TestCase):
    def test_scope(self):
        for kind in ('Product Recall', 'Commercial General Liability', 'Stock Throughput'):
            self.assertTrue(multi_currency_scope({'classOfBusiness': kind, 'reinsuranceStructure': 'QS'}))
        self.assertFalse(multi_currency_scope({'classOfBusiness': 'Property', 'reinsuranceStructure': 'QS'}))
        self.assertFalse(multi_currency_scope({'classOfBusiness': 'Commercial General Liability', 'reinsuranceStructure': 'XOL'}))

    def test_legacy_fallback(self):
        case = {'currency': 'TWD'}
        self.assertEqual(claim_currency(case, {}), 'TWD')
        self.assertEqual(claim_currency(case, {'currency': 'usd'}), 'USD')

    def test_precision_rejects_instead_of_rounding(self):
        self.assertTrue(valid_amount('100.00', 'TWD'))
        self.assertFalse(valid_amount('100.50', 'TWD'))
        self.assertTrue(valid_amount('-0.25', 'USD'))
        self.assertFalse(valid_amount('1.001', 'USD'))
        self.assertFalse(valid_amount('NaN', 'USD'))

    def test_claim_transactions_keep_claim_currency(self):
        root = {'twRef': 'TWPR2601001', 'currency': 'USD', 'reinsurers': [{'name': 'A'}]}
        split = {'reinsurers': [{'name': 'A', 'sharePct': 50}]}
        claim = {'id': 1, 'currency': 'TWD'}
        rows = build_claim_payment_transactions(root, split, claim, {'id': 1, 'amount': 101})
        self.assertEqual([row['currency'] for row in rows], ['TWD', 'TWD'])
        self.assertEqual([row['amount'] for row in rows], [51, 51])

    def test_legacy_transactions_do_not_add_currency(self):
        root = {'twRef': 'X', 'currency': 'USD', 'reinsurers': [{'name': 'A'}]}
        split = {'reinsurers': [{'name': 'A', 'sharePct': 50}]}
        rows = build_claim_payment_transactions(root, split, {'id': 1}, {'id': 1, 'amount': 1.01})
        self.assertNotIn('currency', rows[0])

    def test_rounding_preserves_total_for_positive_and_negative_claims(self):
        self.assertEqual(sum(allocate_claim_shares(1, [33, 33, 34], 'TWD')), 1)
        self.assertEqual(sum(allocate_claim_shares(-1, [33, 33, 34], 'TWD')), -1)
        self.assertEqual(round(sum(allocate_claim_shares(1, [33, 33, 34], 'USD')), 2), 1)


if __name__ == '__main__':
    unittest.main()
