"""Synthetic boundary checks for temporal availability, not RFM performance."""
from datetime import datetime
import unittest
from scripts import audit_rfm_temporal_data as audit


def row(purchase='2018-09-02 00:00:00', delivery='2018-09-04 00:00:00',
        approval='2018-09-03 00:00:00', status='delivered'):
    return dict(zip((*audit.CLOCKS, 'order_status'), (purchase, approval, delivery, status)))


class TemporalInventoryTests(unittest.TestCase):
    def setUp(self):
        self.start = datetime(2018, 9, 1)
        self.end = datetime(2018, 10, 1)

    def test_cutoff_excludes_equal_purchase(self):
        self.assertEqual(audit.event_reason(row(purchase='2018-10-01 00:00:00'), self.end), 'purchase_at_or_after_T')

    def test_cutoff_excludes_equal_delivery(self):
        self.assertEqual(audit.event_reason(row(delivery='2018-10-01 00:00:00'), self.end), 'delivery_at_or_after_T')

    def test_late_old_delivery_is_not_new_purchase(self):
        result = audit.coverage([row(purchase='2018-08-31 00:00:00')], self.start, self.end)
        self.assertEqual(result['purchase_rows'], 0)
        self.assertEqual(result['earlier_purchase_delivery_events_in_interval'], 1)

    def test_left_boundary_included_right_boundary_excluded(self):
        rows = [row(purchase='2018-09-01 00:00:00'), row(purchase='2018-10-01 00:00:00')]
        self.assertEqual(audit.coverage(rows, self.start, self.end)['purchase_rows'], 1)

    def test_future_delivery_is_not_observed_by_probe(self):
        result = audit.coverage([row(delivery='2018-10-15 00:00:00')], self.start, self.end)
        self.assertEqual(result['eligible_new_purchase_event_proxy'], 0)

    def test_final_delivered_without_clock_not_accepted(self):
        self.assertEqual(audit.event_reason(row(delivery=''), self.end), 'missing_or_invalid_delivery')

    def test_approval_conflict_rejected(self):
        self.assertEqual(audit.event_reason(row(approval='2018-09-05 00:00:00'), self.end), 'approval_clock_conflict')

    def test_missing_approval_keeps_original_proxy_semantics(self):
        self.assertEqual(audit.event_reason(row(approval=''), self.end), 'eligible_event_proxy')

    def test_negative_delivery_rejected(self):
        self.assertEqual(audit.event_reason(row(delivery='2018-09-01 00:00:00'), self.end), 'delivery_before_purchase')

    def test_canceled_not_eligible_even_with_delivery(self):
        self.assertEqual(audit.event_reason(row(status='canceled'), self.end), 'status_not_delivered')

    def test_invalid_purchase_prevents_complete_inventory(self):
        with self.assertRaises(ValueError):
            audit.event_reason(row(purchase='2018-02-30 00:00:00'), self.end)

    def test_empty_observation_does_not_mean_complete(self):
        result = audit.coverage([], self.start, self.end)
        self.assertIsNone(result['upstream_complete'])
        self.assertFalse(result['accepted_for_temporal_validation'])

    def test_duplicate_packaging_is_one_version(self):
        copies = [{'table': 'orders', 'sha256': 'same', 'container': p} for p in ('raw', 'backup1', 'backup2')]
        self.assertEqual(audit.distinct_versions(copies), {'orders': 1})

    def test_different_bytes_detected(self):
        self.assertEqual(audit.distinct_versions([{'table': 'orders', 'sha256': v} for v in ('a', 'b')]), {'orders': 2})

    def test_inventory_does_not_mutate_input(self):
        original = row(); before = original.copy()
        audit.coverage([original], self.start, self.end)
        self.assertEqual(original, before)


if __name__ == '__main__':
    unittest.main()
