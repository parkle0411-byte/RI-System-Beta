import unittest
from cases.claim_loss_record import claim_loss_rows, renewal_claim_snapshots, plan_snapshot_sync, retry_snapshot_sync


class ClaimLossRecord(unittest.TestCase):
    def test_reserve_and_signed_obligations(self):
        case = {'currency': 'USD', 'claims': [{'id': 2, 'dateOfLoss': '2026-01-01', 'outstandingReserve': 10,
                 'currency': 'JPY', 'payments': [{'amount': 100}, {'amount': -15}]}]}
        row = claim_loss_rows(case, 'TWPR2601001', 'case-id')[0]
        self.assertEqual((row['currency'], row['lossPaid'], row['claimId']), ('JPY', 95, 2))
        self.assertEqual(row['sourceTwRef'], 'TWPR2601001')

    def test_floor_and_historical_currency(self):
        case = {'currency': 'TWD', 'claims': [{'id': 1, 'outstandingReserve': 0, 'payments': [{'amount': -1}]}]}
        self.assertEqual((claim_loss_rows(case)[0]['lossPaid'], claim_loss_rows(case)[0]['currency']), (0, 'TWD'))

    def test_renewal_snapshot_is_independent_of_subsequent_claim_changes(self):
        source = {'currency': 'USD', 'claims': [{'id': 1, 'outstandingReserve': 10, 'payments': []}]}
        snapshot = renewal_claim_snapshots(source, 'TWPR2601001', 'root-uid')
        source['claims'][0]['outstandingReserve'] = 25
        self.assertEqual(snapshot[0]['lossPaid'], 10)
        self.assertEqual((snapshot[0]['source'], snapshot[0]['sourceCaseUid']), ('claimSnapshot', 'root-uid'))

    def test_sync_conflicts_are_checked_per_field_and_local_money_never_backflows(self):
        snapshot = {'date': '2026-01-01', 'cause': 'Old', 'lossPaid': 10, 'currency': 'USD',
                    'sourceBaseline': {'date': '2026-01-01', 'cause': 'Old'}}
        source = {'dateOfLoss': '2026-01-01', 'causeOfLoss': 'Someone else changed it'}
        updated, patch = plan_snapshot_sync(snapshot, {'date': '2026-01-02', 'cause': 'New', 'lossPaid': 20}, source, reason='Correct date')
        self.assertEqual(patch, {'dateOfLoss': '2026-01-02'})
        self.assertEqual(updated['sync']['cause']['state'], 'conflict')
        self.assertEqual(updated['lossPaid'], 20)
        self.assertEqual(snapshot['lossPaid'], 10)

    def test_missing_source_is_pending_and_date_needs_a_reason(self):
        snapshot = {'date': '2026-01-01', 'cause': 'Old'}
        with self.assertRaises(ValueError):
            plan_snapshot_sync(snapshot, {'date': '2026-01-02'}, None)
        updated, patch = plan_snapshot_sync(snapshot, {'date': '2026-01-02'}, None, reason='Correct date')
        self.assertFalse(patch)
        self.assertEqual(updated['sync']['date']['state'], 'pending')

    def test_retry_requires_conflict_choice_to_match_current_value(self):
        snapshot = {'cause': 'New', 'sync': {'cause': {'state': 'conflict', 'base': 'Old', 'desired': 'New', 'observed': 'Changed'}}}
        updated, patch = retry_snapshot_sync(snapshot, {'causeOfLoss': 'Changed again'}, decisions={'cause': {'choice': 'use_renewal', 'observed': 'Changed'}})
        self.assertFalse(patch)
        self.assertEqual(updated['sync']['cause']['observed'], 'Changed again')
        updated, patch = retry_snapshot_sync(updated, {'causeOfLoss': 'Changed again'}, decisions={'cause': {'choice': 'use_renewal', 'observed': 'Changed again'}})
        self.assertEqual(patch, {'causeOfLoss': 'New'})
        self.assertEqual(updated['sync']['cause']['state'], 'synced')

    def test_cancel_keeps_renewal_value(self):
        snapshot = {'cause': 'New', 'sync': {'cause': {'state': 'conflict', 'base': 'Old', 'desired': 'New'}}}
        updated, patch = retry_snapshot_sync(snapshot, {'causeOfLoss': 'Other'}, decisions={'cause': {'choice': 'keep_source'}})
        self.assertEqual(updated['cause'], 'New')
        self.assertEqual(updated['sync']['cause']['state'], 'cancelled')
        self.assertFalse(patch)


if __name__ == '__main__':
    unittest.main()
