"""Time-boundary, maturity and raw-cohort checks for development waiting folds."""
import unittest

import numpy as np
import pandas as pd

from scripts.delay_waiting_split import approval_cohort_audit, split_waiting_fold


def waiting_records():
    rows = []
    for day in pd.date_range('2018-01-01', '2018-04-14'):
        for hour, delayed in ((8, 0), (20, 1)):
            prediction = day + pd.Timedelta(hours=hour)
            rows.append({
                'order_id': f'{day:%Y%m%d}_{hour}',
                'order_purchase_timestamp': prediction - pd.Timedelta(hours=1),
                'prediction_time': prediction,
                'label_available_time': prediction + pd.Timedelta(hours=3),
                'delayed': delayed, 'new_route_feature': 'SP>RJ',
            })
    for order_id, prediction, available in (
        ('train_cutoff_equal', '2018-02-01 12:00', '2018-03-02 00:00'),
        ('train_cutoff_before', '2018-02-01 13:00', '2018-03-01 23:59:59.999999999'),
        ('validation_cutoff_equal', '2018-03-05 12:00', '2018-04-01 00:00'),
        ('validation_cutoff_before', '2018-03-05 13:00', '2018-03-31 23:59:59.999999999'),
        ('retrospective_evaluation', '2018-04-02 12:00', '2018-06-01 00:00'),
        ('evaluation_end', '2018-04-08 00:00', '2018-04-09 00:00'),
        ('fixed_test_start', '2018-05-26 00:00', '2018-05-27 00:00'),
    ):
        prediction = pd.Timestamp(prediction)
        rows.append({
            'order_id': order_id, 'order_purchase_timestamp': prediction - pd.Timedelta(hours=1),
            'prediction_time': prediction, 'label_available_time': pd.Timestamp(available),
            'delayed': 1, 'new_route_feature': 'SP>RJ',
        })
    return pd.DataFrame(rows)


class WaitingSplitTests(unittest.TestCase):
    def setUp(self):
        self.frame = waiting_records()

    def split(self, frame=None, **kwargs):
        return split_waiting_fold(self.frame if frame is None else frame,
                                  '2018-04-01', '2018-04-08',
                                  wait_days=kwargs.pop('wait_days', 10),
                                  validation_days=kwargs.pop('validation_days', 20), **kwargs)

    def test_wait_intervals_remove_new_approvals_from_both_gaps(self):
        splits, report = self.split()
        self.assertEqual(report['train_prediction_end'], '2018-02-20T00:00:00')
        self.assertEqual(report['model_fit_time'], '2018-03-02T00:00:00')
        self.assertEqual(report['validation_end'], '2018-03-22T00:00:00')
        all_ids = set().union(*(set(part.order_id) for part in splits.values()))
        for start, end, name in (('2018-02-20', '2018-03-02', 'train_wait'),
                                 ('2018-03-22', '2018-04-01', 'validation_wait')):
            gap = self.frame.loc[self.frame.prediction_time.between(
                pd.Timestamp(start), pd.Timestamp(end), inclusive='left')]
            self.assertFalse(set(gap.order_id) & all_ids)
            self.assertEqual(report[name]['prediction_rows_not_assigned'], len(gap))
            self.assertEqual(report[name]['days'], 10)
        self.assertIn('20180302_8', set(splits['validation'].order_id))
        self.assertIn('20180401_8', set(splits['evaluation'].order_id))
        self.assertNotIn('evaluation_end', all_ids)
        self.assertNotIn('fixed_test_start', all_ids)
        self.assertTrue(all('new_route_feature' in part for part in splits.values()))

    def test_labels_at_exact_cutoff_are_excluded_and_nanosecond_before_retained(self):
        splits, report = self.split()
        for partition in ('train', 'validation'):
            ids = set(splits[partition].order_id)
            self.assertNotIn(f'{partition}_cutoff_equal', ids)
            self.assertIn(f'{partition}_cutoff_before', ids)
            counts = report['partitions'][partition]
            self.assertEqual(counts['purged_rows'], 1)
            self.assertEqual(counts['purged_positive_rows'], 1)
            self.assertEqual(counts['rows_before_purge'], counts['rows'] + 1)
            self.assertEqual(counts['positive_rows_before_purge'], counts['positive_rows'] + 1)
            self.assertEqual(counts['negative_rows_before_purge'], counts['negative_rows'])
            self.assertEqual(counts['purged_negative_rows'], 0)
            self.assertEqual(counts['negative_retention_rate'], 1.0)
            self.assertEqual(counts['positive_retention_rate'],
                             counts['positive_rows'] / counts['positive_rows_before_purge'])

    def test_negative_maturity_exclusions_are_counted_separately(self):
        frame = self.frame.copy()
        frame.loc[frame.order_id.isin(['train_cutoff_equal', 'validation_cutoff_equal']), 'delayed'] = 0
        _, report = self.split(frame)
        for name in ('train', 'validation'):
            counts = report['partitions'][name]
            self.assertEqual(counts['purged_positive_rows'], 0)
            self.assertEqual(counts['positive_retention_rate'], 1.0)
            self.assertEqual(counts['purged_negative_rows'], 1)
            self.assertEqual(counts['negative_rows_before_purge'], counts['negative_rows'] + 1)
            self.assertEqual(counts['negative_retention_rate'],
                             counts['negative_rows'] / counts['negative_rows_before_purge'])

    def test_duplicate_external_indices_and_shuffle_do_not_change_splits(self):
        expected, report = self.split()
        shuffled = self.frame.sample(frac=1, random_state=19)
        shuffled.index = [0] * len(shuffled)
        actual, actual_report = self.split(shuffled)
        self.assertEqual(actual_report, report)
        for name in expected:
            pd.testing.assert_frame_equal(actual[name], expected[name])

    def test_evaluation_is_retrospective_and_changing_it_does_not_change_development(self):
        original, report = self.split()
        self.assertIn('retrospective_evaluation', set(original['evaluation'].order_id))
        self.assertEqual(report['partitions']['evaluation']['purged_rows'], 0)
        self.assertIsNone(report['partitions']['evaluation']['label_maturity_cutoff'])
        changed = self.frame.copy()
        evaluation = changed.prediction_time.between(pd.Timestamp('2018-04-01'),
                                                     pd.Timestamp('2018-04-08'), inclusive='left')
        changed.loc[evaluation, 'delayed'] = 1 - changed.loc[evaluation, 'delayed']
        changed.loc[evaluation, 'label_available_time'] = pd.Timestamp('2099-01-01')
        mutated, changed_report = self.split(changed)
        for name in ('train', 'validation'):
            pd.testing.assert_frame_equal(original[name], mutated[name])
            self.assertEqual(report['partitions'][name], changed_report['partitions'][name])
        self.assertEqual(report['partitions']['evaluation']['late_known_at_original_holdout_count'], 1)

    def test_wait_and_validation_days_require_integers(self):
        for invalid in (-1, 1.5, True, '30', None):
            with self.subTest(wait_days=invalid), self.assertRaises(ValueError):
                self.split(wait_days=invalid)
        for invalid in (0, -1, 1.5, False, '30', None):
            with self.subTest(validation_days=invalid), self.assertRaises(ValueError):
                self.split(validation_days=invalid)
        splits, report = self.split(wait_days=np.int64(0))
        self.assertEqual(report['train_wait']['days'], 0)
        self.assertEqual(report['validation_wait']['prediction_rows_not_assigned'], 0)
        self.assertTrue((splits['train'].prediction_time < pd.Timestamp(report['validation_start'])).all())

    def test_dates_must_be_whole_naive_days_and_cannot_cross_fixed_holdout(self):
        for start, end in (
            ('2018-04-01 12:00', '2018-04-08'),
            ('2018-04-01', '2018-04-08 00:00:01'),
            ('2018-04-01+00:00', '2018-04-08'),
            (pd.Timestamp('2018-04-01', tz='UTC'), '2018-04-08'),
            ('2018-04-08', '2018-04-01'), ('2018-04-01', '2018-04-01'),
            (pd.NaT, '2018-04-08'), ('2018-04-01', '2018-05-27'),
        ):
            with self.subTest(start=start, end=end), self.assertRaises(ValueError):
                split_waiting_fold(self.frame, start, end, wait_days=10, validation_days=20)
        _, report = split_waiting_fold(self.frame, '2018-04-01', '2018-05-26',
                                      wait_days=10, validation_days=20)
        self.assertEqual(report['evaluation_end'], report['fixed_test_start'])

    def test_invalid_metadata_fails_before_experiment(self):
        invalid_frames = [self.frame.drop(columns='delayed'),
                          pd.concat([self.frame, self.frame.iloc[:1]], ignore_index=True)]
        for column, value in (('order_id', None), ('prediction_time', pd.NaT),
                              ('delayed', 2), ('label_available_time', pd.Timestamp('2000-01-01'))):
            altered = self.frame.copy()
            altered.loc[0, column] = value
            invalid_frames.append(altered)
        aware = self.frame.copy()
        aware['prediction_time'] = aware['prediction_time'].dt.tz_localize('UTC')
        invalid_frames.append(aware)
        for index, frame in enumerate(invalid_frames):
            with self.subTest(index=index), self.assertRaises(ValueError):
                self.split(frame)

    def test_each_retained_partition_requires_both_classes(self):
        for start, end in ((None, '2018-02-20'), ('2018-03-02', '2018-03-22'),
                            ('2018-04-01', '2018-04-08')):
            frame = self.frame.copy()
            mask = frame.prediction_time < pd.Timestamp(end)
            if start is not None:
                mask &= frame.prediction_time >= pd.Timestamp(start)
            frame.loc[mask, 'delayed'] = 0
            with self.subTest(start=start), self.assertRaisesRegex(ValueError, 'both binary classes'):
                self.split(frame)


class ApprovalAuditTests(unittest.TestCase):
    def setUp(self):
        self.frame = waiting_records()
        _, self.report = split_waiting_fold(self.frame, '2018-04-01', '2018-04-08',
                                            wait_days=10, validation_days=20)
        self.orders = self.frame[['order_id', 'prediction_time']].rename(
            columns={'prediction_time': 'order_approved_at'})
        self.orders['order_status'] = 'delivered'
        extra = pd.DataFrame([
            {'order_id': 'cancelled_val', 'order_approved_at': pd.Timestamp('2018-03-10'), 'order_status': 'canceled'},
            {'order_id': 'shipping_val', 'order_approved_at': pd.Timestamp('2018-03-11'), 'order_status': 'shipped'},
            {'order_id': 'unknown_eval', 'order_approved_at': pd.Timestamp('2018-04-03'), 'order_status': None},
            {'order_id': 'no_approval', 'order_approved_at': pd.NaT, 'order_status': 'canceled'},
            {'order_id': 'train_gap', 'order_approved_at': pd.Timestamp('2018-02-22'), 'order_status': 'shipped'},
            {'order_id': 'val_gap', 'order_approved_at': pd.Timestamp('2018-03-25'), 'order_status': 'shipped'},
        ])
        self.orders = pd.concat([self.orders, extra], ignore_index=True)

    def test_raw_approval_counts_keep_excluded_statuses_separate_from_labels(self):
        audit = approval_cohort_audit(self.orders, self.frame, self.report)
        self.assertEqual(audit['raw_rows_without_approval'], 1)
        for name in ('train', 'validation', 'evaluation'):
            part = audit['partitions'][name]
            original = self.report['partitions'][name]
            self.assertEqual(part['eligible_completed_rows'], original['rows_before_purge'])
            self.assertEqual(sum(part['status_counts'].values()), part['raw_approved_rows'])
            self.assertEqual(part['raw_approved_rows'],
                             part['eligible_completed_rows'] + part['not_in_eligible_cohort_rows'])
            if name != 'evaluation':
                self.assertEqual(part['known_eligible_labels_at_cutoff'], original['rows'])
        val = audit['partitions']['validation']
        self.assertEqual(val['not_in_eligible_cohort_rows'], 2)
        self.assertEqual(val['status_counts']['canceled'], 1)
        self.assertEqual(val['status_counts']['shipped'], 1)
        evaluation = audit['partitions']['evaluation']
        self.assertEqual(evaluation['not_in_eligible_cohort_rows'], 1)
        self.assertEqual(evaluation['status_counts']['<missing>'], 1)
        self.assertIsNone(evaluation['known_eligible_labels_at_cutoff'])
        self.assertIsNone(evaluation['label_maturity_cutoff'])

    def test_audit_is_unchanged_by_external_indices_and_never_invents_snapshot(self):
        expected = approval_cohort_audit(self.orders, self.frame, self.report)
        orders = self.orders.sample(frac=1, random_state=2)
        orders.index = [0] * len(orders)
        frame = self.frame.sample(frac=1, random_state=3)
        frame.index = [0] * len(frame)
        actual = approval_cohort_audit(orders, frame, self.report)
        self.assertEqual(actual, expected)
        self.assertIn('No dataset snapshot date is assumed', actual['scope'])

    def test_audit_rejects_mismatched_raw_approval_or_missing_eligible_order(self):
        mismatched = self.orders.copy()
        mismatched.loc[0, 'order_approved_at'] += pd.Timedelta(hours=1)
        absent = self.orders.iloc[1:].copy()
        for orders in (mismatched, absent):
            with self.assertRaisesRegex(ValueError, 'match raw non-null approval'):
                approval_cohort_audit(orders, self.frame, self.report)

    def test_invalid_raw_schema_duplicates_and_aware_timestamps_fail(self):
        aware = self.orders.copy()
        aware['order_approved_at'] = aware['order_approved_at'].dt.tz_localize('UTC')
        invalid_orders = (self.orders.drop(columns='order_status'),
                          pd.concat([self.orders, self.orders.iloc[:1]]), aware)
        for orders in invalid_orders:
            with self.assertRaises(ValueError):
                approval_cohort_audit(orders, self.frame, self.report)


if __name__ == '__main__':
    unittest.main()
