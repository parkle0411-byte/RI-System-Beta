"""Production attribution distinguishes Personnel even when names match."""
import unittest
from production.calc import performance_people, production_source_signature


class ProductionPersonnel(unittest.TestCase):
    def test_case_ae_identity_and_historical_name(self):
        people = performance_people({'ae':'Historical Name', 'aePersonnelId':12})
        self.assertEqual(people, [{'name':'Historical Name', 'pct':100.0, 'personnelId':12}])

    def test_split_uses_each_party_identity(self):
        people = performance_people({'ae':'AE', 'aePersonnelId':12, 'splitEnabled':True,
                                     'splitParties':[{'name':'Same Name','personnelId':12,'pct':70}, {'name':'Same Name','personnelId':13,'pct':30}]})
        self.assertEqual([p['personnelId'] for p in people], [12, 13])

    def test_same_name_different_identity_invalidates_signature(self):
        row = {'id':'1','ae':'Same Name','aePersonnelId':12,'comm':0}
        self.assertNotEqual(production_source_signature([row]), production_source_signature([{**row, 'aePersonnelId':13}]))


if __name__ == '__main__':
    unittest.main()
