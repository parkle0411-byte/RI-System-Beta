"""Fast checks for Product Recall risk rules; no database is used."""
import copy
import unittest
from cases.product_recall import initial, issues


class ProductRecallRisk(unittest.TestCase):
    def setUp(self):
        self.case = {'classOfBusiness': 'Product Recall', 'reinsuranceStructure': 'QS', 'currency': 'USD',
                     'limitOfLiability': 1000, 'deductibles': 100, 'productRecall': initial()}
        self.case.update(originalExclusions='None', originalConditions='As agreed', reinsuredRetention='Waived',
                         expressWarranties='None', conditionsPrecedent='None', subjectivities='None')
        self.case['productRecall']['choiceOfLaw'] = 'Taiwan'
        for row in self.case['productRecall']['losses']:
            row['amount'] = 100

    def fields(self, ready=True):
        return {row['field'] for row in issues(self.case, ready=ready)}

    def test_complete_case(self):
        self.assertFalse(self.fields())

    def test_missing_and_duplicate_names(self):
        self.case['productRecall']['eventsOtherSelected'] = True
        self.case['productRecall']['events'].append({'id': 'extra', 'name': ' DEFECT ', 'selected': True})
        self.assertIn('productRecall.events.4.name', self.fields(ready=False))
        self.case['productRecall']['events'][-1]['name'] = ' '
        self.assertNotIn('productRecall.events.4.name', self.fields(ready=False))
        self.assertIn('productRecall.events.4.name', self.fields())

    def test_unselected_loss_is_not_checked_and_limit_does_not_cap_sublimit(self):
        row = self.case['productRecall']['losses'][0]
        row.update(selected=False, amount=0, currency='USD')
        self.assertNotIn('productRecall.losses.0.amount', self.fields())
        row.update(selected=True, amount=5000)
        self.assertNotIn('productRecall.losses.0.amount', self.fields())
        row.update(currency='TWD', amount='100.5')
        self.assertIn('productRecall.losses.0.amount', self.fields(False))
        row.update(currency='EUR')
        self.assertNotIn('productRecall.losses.0.amount', self.fields(False))
        row.update(amount='1e500')
        self.assertIn('productRecall.losses.0.amount', self.fields(False))

    def test_other_group_toggle_and_incomplete_rows(self):
        risk = self.case['productRecall']
        risk['losses'].append({'id': 'custom', 'name': '', 'fixed': False, 'selected': False, 'currency': 'EUR', 'amount': None})
        risk['lossesOtherSelected'] = False
        self.assertNotIn('productRecall.losses.4.name', self.fields())
        risk['lossesOtherSelected'] = True
        self.assertNotIn('productRecall.losses.4.name', self.fields(False))
        self.assertIn('productRecall.losses.4.name', self.fields())
        self.assertIn('productRecall.losses.4.amount', self.fields())

    def test_duplicate_matching_only_folds_english_letters(self):
        self.case['productRecall']['eventsOtherSelected'] = True
        self.case['productRecall']['events'].extend([
            {'id': 'x1', 'name': 'Straße', 'fixed': False, 'selected': True},
            {'id': 'x2', 'name': 'STRASSE', 'fixed': False, 'selected': True},
        ])
        self.assertNotIn('productRecall.events.5.name', self.fields(False))
        self.case['productRecall']['events'][-1]['name'] = 'straße'
        self.assertIn('productRecall.events.5.name', self.fields(False))

    def test_selection_flags_must_be_boolean(self):
        self.case['productRecall']['eventsOtherSelected'] = 'false'
        self.assertIn('productRecall.eventsOtherSelected', self.fields(False))
        self.case['productRecall']['events'][0]['selected'] = 'false'
        self.assertIn('productRecall.events.0.selected', self.fields(False))

    def test_deductible_or_retention_and_precision(self):
        self.case.update(currency='TWD', deductibles='1.5', selfInsuredRetention='')
        self.assertIn('deductibles', self.fields())
        self.case.update(deductibles='', selfInsuredRetention='As agreed')
        self.assertNotIn('deductibles', self.fields())
        self.case['selfInsuredRetention'] = ''
        self.assertIn('deductibles', self.fields())

    def test_renewal_copy_keeps_selection(self):
        renewal = copy.deepcopy(self.case)
        renewal['productRecall']['events'][0]['selected'] = False
        self.assertTrue(self.case['productRecall']['events'][0]['selected'])


if __name__ == '__main__':
    unittest.main()
