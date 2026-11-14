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
        self.case['productRecall']['events'].append({'name': ' DEFECT ', 'selected': True})
        self.assertIn('productRecall.events.4.name', self.fields(ready=False))
        self.case['productRecall']['events'][-1]['name'] = ' '
        self.assertNotIn('productRecall.events.4.name', self.fields(ready=False))
        self.assertIn('productRecall.events.4.name', self.fields())

    def test_unselected_loss_amount_is_preserved_but_not_checked(self):
        row = self.case['productRecall']['losses'][0]
        row.update(selected=False, amount=5000)
        self.assertNotIn('productRecall.losses.0.amount', self.fields())
        row['selected'] = True
        self.assertIn('productRecall.losses.0.amount', self.fields())

    def test_other_sublimit_must_not_duplicate_unselected_loss(self):
        self.case['productRecall']['losses'][0]['selected'] = False
        self.case['productRecall']['additionalSublimits'].append({'name': 'first party recall costs', 'amount': 100})
        self.assertIn('productRecall.additionalSublimits.0.name', self.fields(False))

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
