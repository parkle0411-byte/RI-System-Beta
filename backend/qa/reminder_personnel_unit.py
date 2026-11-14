"""Reminder recipients follow linked Personnel and retain partial delivery."""
import unittest
from reminders.messages import contact_for, finance_emails, resolve_recipients


class ReminderPersonnel(unittest.TestCase):
    def setUp(self):
        self.ae = {'id':1, 'name':'Same Name', 'email':'ae@example.com', 'is_active':True,
                   'account_status':'active', 'supervisor_name':'Manager', 'supervisor_email':'manager@example.com'}
        self.namesake = {'id':2, 'name':'Same Name', 'email':'other@example.com', 'is_active':True, 'account_status':'active'}
        self.manager = {'id':3, 'name':'Manager', 'email':'manager@example.com', 'is_active':True, 'account_status':'active'}
        self.finance = {'id':4, 'name':'Finance', 'email':'finance@example.com', 'is_active':True, 'account_status':'active', 'role_code':'accounting'}
        self.people = [self.ae, self.namesake, self.manager, self.finance]

    def test_id_disambiguates_same_name_and_uses_manager(self):
        result = contact_for({'aePersonnelId':1, 'ae':'Historic Name'}, self.people)
        self.assertEqual((result['aeEmail'], result['supervisorEmail']), ('ae@example.com', 'manager@example.com'))

    def test_disabled_ae_still_notifies_active_manager(self):
        self.ae['account_status'] = 'disabled'
        result = contact_for({'aePersonnelId':1}, self.people)
        self.assertEqual((result['aeEmail'], result['supervisorEmail']), ('', 'manager@example.com'))
        self.assertTrue(result['missing'])
        self.assertNotIn('error', result)

    def test_disabled_manager_does_not_block_active_ae(self):
        self.manager['account_status'] = 'disabled'
        result = contact_for({'aePersonnelId':1}, self.people)
        self.assertEqual((result['aeEmail'], result['supervisorEmail']), ('ae@example.com', ''))
        self.assertTrue(result['missing'])

    def test_unlinked_name_is_not_guessed_but_finance_receives_payment_alert(self):
        result = resolve_recipients({'ae':'Same Name'}, self.people, finance_emails(self.people))
        self.assertEqual(result['recipients'], ['finance@example.com'])
        self.assertTrue(result['missing'])
        self.assertNotIn('error', result)

    def test_unlinked_property_ae_does_not_block_valid_owner(self):
        case = {'classOfBusiness':'Property', 'reinsuranceStructure':'QS', 'ownerPersonnelId':3,
                'propertyOriginalRules':'property-original-v1', 'reinsurers':[{'name':'Ordinary Re'}]}
        result = contact_for(case, self.people)
        self.assertEqual(result['supervisorEmail'], 'manager@example.com')
        self.assertEqual(result['aeEmail'], '')
        self.assertTrue(result['missing'])

    def test_inactive_or_disabled_finance_is_excluded(self):
        self.finance['account_status'] = 'disabled'
        self.assertEqual(finance_emails(self.people), [])


if __name__ == '__main__':
    unittest.main()
