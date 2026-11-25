import unittest
from datetime import date, datetime, timezone
from decimal import Decimal

from cases.facility_placement import calculate, correction_delta, normalize_facility_draft, revenue_month, validate_declaration, validate_facility


class FacilityPlacementRules(unittest.TestCase):
    def setUp(self):
        self.facility = dict(policyFrom='2026-07-01', currency='USD', riCommPct=20, taxPct=0, ppwDays=75,
            reinsurers=[dict(name='A', facilityReference='REF-A', sharePct=50, deductionPct=30, taxPct=0),
                        dict(name='B', facilityReference='REF-B', sharePct=30, deductionPct=25, taxPct=0)])
        self.declaration = dict(periodFrom='2026-07-01', periodTo='2026-09-30', statementNo='S1', premium=100, claim=30)

    def test_due_date_and_partial_placement_accounting(self):
        self.assertEqual(validate_declaration(self.facility, self.declaration)['dueDate'], '2026-12-14')
        rows = calculate(self.facility, 100, 30)
        self.assertEqual(sum(r['premium'] for r in rows), 80)
        self.assertEqual(sum(r['cedantCommission'] for r in rows), 16)
        self.assertEqual(sum(r['claim'] for r in rows), 24)
        self.assertEqual(sum(r['cedantNet'] for r in rows), 40)
        self.assertAlmostEqual(sum(r['reinsurerNet'] for r in rows), 33.5)
        self.assertAlmostEqual(sum(r['brokerage'] for r in rows), 6.5)

    def test_claim_only_and_signs(self):
        for premium, claim in [(0, 40), (-100, 0), (0, -40)]:
            data = {**self.declaration, 'premium': premium, 'claim': claim}
            validate_declaration(self.facility, data)
        self.assertEqual(sum(r['brokerage'] for r in calculate(self.facility, 0, 40)), 0)

    def test_twd_rounding_preserves_placed_totals(self):
        facility = {**self.facility, 'currency': 'TWD', 'riCommPct': 10,
            'reinsurers': [{**self.facility['reinsurers'][0], 'sharePct': 50, 'deductionPct': 20},
                           {**self.facility['reinsurers'][1], 'sharePct': 30, 'deductionPct': 20}]}
        positive = calculate(facility, 1005, 1005)
        negative = calculate(facility, -1005, -1005)
        self.assertEqual(sum(r['premium'] for r in positive), 804)
        self.assertEqual(sum(r['claim'] for r in positive), 804)
        self.assertEqual(sum(r['cedantCommission'] for r in positive), 80)
        for a, b in zip(positive, negative):
            for field in ('premium', 'claim', 'cedantCommission', 'cedantTax', 'deduction', 'brokerage', 'cedantNet', 'reinsurerNet'):
                self.assertEqual(a[field], -b[field], field)

    def test_nonzero_first_period_and_statement(self):
        for changes in ({'premium': 0, 'claim': 0}, {'periodFrom': '2026-07-02'}, {'statementNo': ' '}):
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                validate_declaration(self.facility, {**self.declaration, **changes})

    def test_draft_overlap_duplicate_reference_and_future_gap(self):
        prior = [{**self.declaration, 'id': 1}]
        for changes in ({'periodFrom': '2026-09-30', 'periodTo': '2026-10-31', 'statementNo': 'S2'},
                        {'periodFrom': '2026-10-01', 'periodTo': '2026-10-31', 'statementNo': 's1'}):
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                validate_declaration(self.facility, {**self.declaration, **changes}, prior)
        later = {**self.declaration, 'periodFrom': '2026-11-01', 'periodTo': '2026-11-30', 'statementNo': 'S2'}
        validate_declaration(self.facility, later, prior)

    def test_edit_excludes_self_but_not_other_periods(self):
        current = {**self.declaration, 'id': 1}
        validate_declaration(self.facility, current, [current], exclude_id=1)
        other = {**current, 'id': 2, 'statementNo': 'S2', 'periodFrom': '2026-10-01', 'periodTo': '2026-12-31'}
        with self.assertRaises(ValueError):
            validate_declaration(self.facility, {**current, 'periodTo': '2026-10-01'}, [current, other], exclude_id=1)

    def test_reference_share_and_dates_are_validated(self):
        for changed in ([{**self.facility['reinsurers'][0], 'facilityReference': ''}],
                        [{**self.facility['reinsurers'][0], 'sharePct': 101}]):
            with self.subTest(changed=changed), self.assertRaises(ValueError):
                validate_declaration({**self.facility, 'reinsurers': changed}, self.declaration)
        with self.assertRaises(ValueError):
            validate_declaration(self.facility, {**self.declaration, 'periodTo': '2026-02-30'})

    def test_facility_readiness_has_fixed_type_and_no_premium_requirement(self):
        facility = {**self.facility, 'facilityName': 'Travel', 'reinsured': 'Cedant',
                    'originalAssuredDescription': 'Various groups as declared by the Reinsured',
                    'classOfBusiness': 'Personal Accident', 'policyTo': '2027-07-01', 'facilityTypePrefix': 'Travel'}
        self.assertEqual(validate_facility(facility)['type'], 'Travel Personal Accident Facultative Facility Reinsurance')
        for key in ('facilityName', 'reinsured', 'originalAssuredDescription', 'classOfBusiness', 'currency'):
            with self.subTest(field=key), self.assertRaises(ValueError):
                validate_facility({**facility, key: ''})
        for field in ('name', 'sharePct', 'deductionPct', 'taxPct', 'facilityReference'):
            reinsurers = [{**row} for row in facility['reinsurers']]
            reinsurers[1][field] = ''
            with self.subTest(reinsurer_field=field), self.assertRaises(ValueError):
                validate_facility({**facility, 'reinsurers': reinsurers})
        reinsurers = [{**row, 'deductionPct': 0, 'taxPct': 0} for row in facility['reinsurers']]
        validate_facility({**facility, 'reinsurers': reinsurers})

    def test_currency_precision_and_limits(self):
        for changes in ({'premium': '100.001'}, {'premium': '1000000000000'}, {'claim': 'NaN'}):
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                validate_declaration(self.facility, {**self.declaration, **changes})
        with self.assertRaises(ValueError):
            validate_declaration({**self.facility, 'currency': 'TWD'}, {**self.declaration, 'claim': '0.01'})

    def test_revenue_month_uses_prior_open_month(self):
        self.assertEqual(revenue_month(date(2027, 1, 7), set()), '2026-12')
        self.assertEqual(revenue_month(date(2027, 1, 7), {'2026-12'}), '2027-01')
        with self.assertRaises(ValueError):
            revenue_month(date(2027, 1, 7), {'2026-12', '2027-01'})

    def test_full_amount_correction_delta(self):
        self.assertEqual(correction_delta({'premium': '100.15', 'claim': 30}, {'premium': '120.20', 'claim': 25}),
                         {'premium': Decimal('20.05'), 'claim': Decimal('-5')})

    def test_facility_revenue_appears_on_dashboard_in_revenue_month(self):
        from dashboard.calc import build_dashboard
        result = build_dashboard([], [], [], datetime(2026, 11, 20, tzinfo=timezone.utc),
                                 facility_trend=[{'month': '2026-10', 'incomeTwd': 1250}])
        self.assertEqual(result['brokerage']['current'][9], 1250)
        self.assertEqual(result['brokerage']['current'][10], 0)

    def test_draft_normalization_preserves_input_and_refuses_posting_state(self):
        draft = normalize_facility_draft({**self.facility, 'facilityName': 'Travel', 'facilityTypePrefix': 'Travel',
             'reinsured': 'Cedant', 'classOfBusiness': 'Personal Accident', 'policyTo': '2027-07-01',
             'transactions': [{'amount': 100000}], 'originalInsured': 'Should not be used'})
        self.assertEqual(draft['reinsuranceStructure'], 'FACILITY')
        self.assertEqual(draft['reinsurers'][0]['facilityReference'], 'REF-A')
        self.assertEqual(draft['transactions'], [])
        self.assertEqual(draft['originalInsured'], '')
        self.assertEqual(draft['type'], 'Travel Personal Accident Facultative Facility Reinsurance')
        with self.assertRaises(ValueError):
            normalize_facility_draft({**self.facility, 'reinsurers': [dict(name='A', sharePct=70), dict(name='B', sharePct=40)]})


if __name__ == '__main__':
    unittest.main()
