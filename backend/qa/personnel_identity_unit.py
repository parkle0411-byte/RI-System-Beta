import unittest
from types import SimpleNamespace
from cases.personnel_identity import eligible, historical_match, assign_creator, valid_email


class PersonnelIdentity(unittest.TestCase):
    def person(self, name='Name', role='sales', active=True, status='active'):
        return SimpleNamespace(pk=17, name=name, email='person@example.com', role_code=role, is_active=active, account_status=status)

    def test_eligibility_uses_role_and_active_not_account_status(self):
        for role in ('sales', 'general_manager', 'admin'):
            self.assertTrue(eligible(self.person(role=role, status='disabled')))
            self.assertFalse(eligible(self.person(role=role, active=False)))
        self.assertFalse(eligible(self.person(role='accounting')))

    def test_historical_match_never_guesses(self):
        inactive = self.person(name='Jane', role='accounting', active=False)
        self.assertIs(historical_match(' JANE ', [inactive]), inactive)
        self.assertIsNone(historical_match('Jane', [inactive, self.person(name='jane')]))
        self.assertIsNone(historical_match('', [inactive]))

    def test_new_draft_defaults_both_fields_and_raw_inputs(self):
        payload = {'ownerPersonnelId': 3, 'ae': 'Old', 'draftInput': {'ae': 'Old'}}
        assign_creator(payload, self.person(status='disabled'))
        for data in (payload, payload['draftInput']):
            self.assertEqual((data['ownerPersonnelId'], data['aePersonnelId'], data['ae']), (17, 17, 'Name'))
        with self.assertRaises(ValueError): assign_creator({}, self.person(role='accounting'))

    def test_linked_email_is_authoritative(self):
        person = self.person()
        self.assertEqual(valid_email(person, 'old@example.com', linked=True), 'person@example.com')
        person.email = 'bad address'
        self.assertEqual(valid_email(person, 'old@example.com', linked=True), '')
        self.assertEqual(valid_email(None, 'old@example.com'), 'old@example.com')
        self.assertEqual(valid_email(None, 'invalid'), '')


if __name__ == '__main__':
    unittest.main()
