"""Incomplete drafts may be saved, but entered loss history must be valid."""
import unittest
from cases.draft_input import normalize
from cases.draft import loss_record_save_errors


class LossDraftValidation(unittest.TestCase):
    def case(self, family):
        return {'classOfBusiness': family, 'reinsuranceStructure': 'QS', 'currency': 'USD',
                'lossRecordYears': None, 'lossAdvisedDate': '', 'lossRecord': []}

    def test_incomplete_and_inconsistent_history_can_be_saved(self):
        for family in ('Product Recall', 'Commercial General Liability'):
            with self.subTest(family=family):
                case = self.case(family)
                case.update(newOrRenew='Renew', lossRecordYears=0, lossRecord=[{'date': '', 'cause': '', 'lossPaid': None}])
                self.assertEqual(normalize(case)['errors'], [])

    def test_invalid_entered_values_are_rejected(self):
        for family in ('Product Recall', 'Commercial General Liability'):
            for change in ({'lossRecordYears': -1}, {'lossRecordYears': 1.5},
                           {'lossAdvisedDate': '2026-02-30'},
                           {'lossRecord': [{'date': '2026-99-01'}]},
                           {'lossRecord': [{'lossPaid': 0}]},
                           {'lossRecord': [{'lossPaid': -10}]}):
                with self.subTest(family=family, change=change):
                    self.assertTrue(normalize({**self.case(family), **change})['errors'])

    def test_standard_save_rejects_entered_zero_but_allows_missing(self):
        for family in ('Product Recall', 'Commercial General Liability'):
            with self.subTest(family=family):
                case = self.case(family)
                case['lossRecord'] = [{'lossPaid': None}]
                self.assertEqual(loss_record_save_errors(case), [])
                case['lossRecord'] = [{'lossPaid': 0}]
                self.assertTrue(loss_record_save_errors(case))


if __name__ == '__main__':
    unittest.main()
