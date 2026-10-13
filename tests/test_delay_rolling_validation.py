"""Monthly refit boundaries, mature historical validation and outcome isolation."""
import unittest

import pandas as pd

from scripts.delay_rolling_validation import (
    mature_validation_month, rolling_validation_schedule, split_rolling_month,
)


def rolling_records():
    rows = []
    for day in pd.date_range('2017-01-01', '2018-05-26'):
        for hour, delayed in ((8, 0), (20, 1)):
            approved = day + pd.Timedelta(hours=hour)
            rows.append({
                'order_id': f'{day:%Y%m%d}_{hour}',
                'order_purchase_timestamp': approved - pd.Timedelta(hours=1),
                'prediction_time': approved,
                'label_available_time': approved + pd.Timedelta(hours=2),
                'delayed': delayed, 'feature': 'SP->RJ',
            })
    for identity, approval, available, delayed in (
        ('train_label_equal', '2018-01-01 12:00', '2018-04-01', 1),
        ('train_label_before', '2018-01-01 13:00', '2018-03-31 23:59:59.999999999', 1),
        ('train_negative_label_equal', '2018-01-02 12:00', '2018-04-01', 0),
        ('train_approval_equal', '2018-01-31', '2018-02-01', 1),
        ('train_approval_before', '2018-01-30 23:59:59.999999999', '2018-02-01', 1),
        ('scoring_start_equal', '2018-04-01', '2018-04-02', 1),
        ('scoring_end_equal', '2018-05-01', '2018-05-02', 1),
        ('scoring_future_outcome', '2018-04-02 12:00', '2099-01-01', 1),
        ('validation_label_equal', '2017-12-15 12:00', '2018-04-01', 1),
        ('validation_label_before', '2017-12-15 13:00', '2018-03-31 23:59:59.999999999', 1),
        ('validation_negative_label_equal', '2017-12-16 12:00', '2018-04-01', 0),
        ('fixed_test_start_equal', '2018-05-26', '2018-05-27', 1),
    ):
        approved = pd.Timestamp(approval)
        rows.append({
            'order_id': identity,
            'order_purchase_timestamp': approved - pd.Timedelta(hours=1),
            'prediction_time': approved,
            'label_available_time': pd.Timestamp(available),
            'delayed': delayed, 'feature': 'SP->RJ',
        })
    return pd.DataFrame(rows)


class RollingMonthlySplitTests(unittest.TestCase):
    def setUp(self):
        self.frame = rolling_records()

    def split(self, frame=None):
        return split_rolling_month(self.frame if frame is None else frame, '2018-04-01')

    def test_monthly_refit_uses_recent_mature_training_and_disjoint_scoring(self):
        splits, report = self.split()
        self.assertEqual(report['model_fit_time'], '2018-04-01T00:00:00')
        self.assertEqual(report['train_prediction_end'], '2018-01-31T00:00:00')
        self.assertEqual(report['training_label_cutoff'], '2018-04-01T00:00:00')
        self.assertEqual(report['scoring_end'], '2018-05-01T00:00:00')
        self.assertEqual(report['train_wait']['days'], 60)
        train, scoring = splits['train'], splits['scoring']
        self.assertTrue((train.prediction_time < pd.Timestamp('2018-01-31')).all())
        self.assertTrue((train.label_available_time < pd.Timestamp('2018-04-01')).all())
        self.assertTrue(scoring.prediction_time.between(pd.Timestamp('2018-04-01'),
                                                      pd.Timestamp('2018-05-01'), inclusive='left').all())
        self.assertFalse(set(train.order_id) & set(scoring.order_id))
        self.assertIn('feature', train)
        self.assertIn('feature', scoring)

    def test_strict_training_approval_and_label_boundaries(self):
        splits, report = self.split()
        train_ids = set(splits['train'].order_id)
        for identity in ('train_approval_equal', 'train_label_equal', 'train_negative_label_equal'):
            self.assertNotIn(identity, train_ids)
        self.assertIn('train_approval_before', train_ids)
        self.assertIn('train_label_before', train_ids)
        self.assertIn('scoring_start_equal', set(splits['scoring'].order_id))
        self.assertNotIn('scoring_end_equal', set(splits['scoring'].order_id))
        gap = self.frame.loc[self.frame.prediction_time.between(pd.Timestamp('2018-01-31'),
                                                               pd.Timestamp('2018-04-01'), inclusive='left')]
        self.assertEqual(report['train_wait']['prediction_rows_not_assigned'], len(gap))
        self.assertFalse(set(gap.order_id) & train_ids)

    def test_training_maturity_reports_positive_and_negative_exclusions(self):
        _, report = self.split()
        maturity = report['partitions']['train']
        # The two December validation fixtures are also historical training
        # approvals by April, so each class has two outcomes exactly at cutoff.
        self.assertEqual(maturity['purged_rows'], 4)
        self.assertEqual(maturity['purged_positive_rows'], 2)
        self.assertEqual(maturity['purged_negative_rows'], 2)
        self.assertEqual(maturity['positive_retention_rate'],
                         maturity['positive_rows'] / maturity['positive_rows_before_purge'])
        self.assertEqual(maturity['negative_retention_rate'],
                         maturity['negative_rows'] / maturity['negative_rows_before_purge'])
        self.assertEqual(maturity['label_maturity_cutoff'], report['model_fit_time'])

    def test_scoring_keeps_future_labels_and_has_no_outcome_maturity_summary(self):
        splits, report = self.split()
        self.assertIn('scoring_future_outcome', set(splits['scoring'].order_id))
        expected = self.frame.prediction_time.between(pd.Timestamp('2018-04-01'),
                                                     pd.Timestamp('2018-05-01'), inclusive='left')
        self.assertEqual(len(splits['scoring']), int(expected.sum()))
        scoring_report = report['partitions']['scoring']
        self.assertFalse(scoring_report['label_maturity_filter_applied'])
        self.assertFalse(scoring_report['outcomes_used_for_selection'])
        self.assertIsNone(scoring_report['label_maturity_cutoff'])
        self.assertNotIn('positive_rows', scoring_report)
        self.assertNotIn('label_available_time_max', scoring_report)

    def test_future_evaluation_outcomes_cannot_change_training_or_scoring_membership(self):
        expected, report = self.split()
        changed = self.frame.copy()
        future = changed.prediction_time >= pd.Timestamp('2018-04-01')
        changed.loc[future, 'delayed'] = 1 - changed.loc[future, 'delayed']
        changed.loc[future, 'label_available_time'] = pd.Timestamp('2099-01-01')
        actual, changed_report = self.split(changed)
        pd.testing.assert_frame_equal(actual['train'], expected['train'])
        pd.testing.assert_series_equal(actual['scoring'].order_id, expected['scoring'].order_id)
        self.assertEqual(report, changed_report)

    def test_shuffle_and_duplicate_external_indices_do_not_change_identity(self):
        expected, report = self.split()
        shuffled = self.frame.sample(frac=1, random_state=61)
        shuffled.index = [0] * len(shuffled)
        actual, actual_report = self.split(shuffled)
        self.assertEqual(actual_report, report)
        for name in expected:
            pd.testing.assert_frame_equal(actual[name], expected[name])

    def test_training_requires_two_classes_but_scoring_can_have_only_one(self):
        changed = self.frame.copy()
        mask = changed.prediction_time.between(pd.Timestamp('2018-04-01'),
                                               pd.Timestamp('2018-05-01'), inclusive='left')
        changed.loc[mask, 'delayed'] = 0
        splits, _ = self.split(changed)
        self.assertEqual(splits['scoring'].delayed.nunique(), 1)
        changed.loc[changed.prediction_time < pd.Timestamp('2018-01-31'), 'delayed'] = 0
        with self.assertRaisesRegex(ValueError, 'train.*both binary classes'):
            self.split(changed)
        with self.assertRaisesRegex(ValueError, 'scoring must contain'):
            self.split(self.frame.loc[~mask])

    def test_later_month_refit_adds_previously_unavailable_labels(self):
        april, _ = self.split()
        may, report = split_rolling_month(self.frame, '2018-05-01', '2018-05-26')
        self.assertNotIn('train_label_equal', set(april['train'].order_id))
        self.assertIn('train_label_equal', set(may['train'].order_id))
        self.assertTrue(set(april['train'].order_id) < set(may['train'].order_id))
        self.assertEqual(report['train_prediction_end'], '2018-03-02T00:00:00')
        self.assertNotIn('fixed_test_start_equal', set(may['scoring'].order_id))

    def test_invalid_month_end_metadata_and_holdout_boundaries_fail(self):
        for start, end in (
            ('2018-04-02', None), ('2018-04-01 12:00', None),
            (pd.Timestamp('2018-04-01', tz='UTC'), None), (pd.NaT, None),
            ('2018-04-01', '2018-04-01'), ('2018-04-01', '2018-03-31'),
            ('2018-04-01', '2018-05-02'), ('2018-04-01', '2018-04-02 00:00:01'),
            ('2018-05-01', None), ('2018-05-01', '2018-05-27'),
        ):
            with self.subTest(start=start, end=end), self.assertRaises(ValueError):
                split_rolling_month(self.frame, start, end)
        partial, _ = split_rolling_month(self.frame, '2018-04-01', '2018-04-08')
        self.assertTrue((partial['scoring'].prediction_time < pd.Timestamp('2018-04-08')).all())
        for invalid in (self.frame.drop(columns='delayed'),
                        pd.concat([self.frame, self.frame.iloc[:1]], ignore_index=True)):
            with self.assertRaises(ValueError):
                self.split(invalid)


class RollingValidationScheduleTests(unittest.TestCase):
    def test_three_complete_months_are_fixed_before_evaluation(self):
        schedules = (
            ('2017-12-01', '2018-01-01', ['2017-07', '2017-08', '2017-09'], 61),
            ('2018-02-01', '2018-03-01', ['2017-09', '2017-10', '2017-11'], 62),
            ('2018-04-01', '2018-05-01', ['2017-10', '2017-11', '2017-12'], 90),
        )
        for start, end, expected, wait in schedules:
            report = rolling_validation_schedule(start, end)
            self.assertEqual([month['month'] for month in report['validation_months']], expected)
            self.assertEqual(report['validation_wait']['days'], wait)
            self.assertEqual(report['validation_month_count'], 3)
            self.assertEqual(report['validation_label_cutoff'], pd.Timestamp(start).isoformat())
            for month in report['validation_months']:
                first, last = map(pd.Timestamp, (month['start'], month['end']))
                self.assertEqual(first.day, 1)
                self.assertEqual(last, first + pd.DateOffset(months=1))
                self.assertEqual(month['model_fit_time'], month['start'])
                self.assertEqual(month['label_maturity_cutoff'], report['evaluation_start'])
                self.assertGreaterEqual((pd.Timestamp(start) - last).days, 60)

    def test_schedule_has_same_month_and_holdout_guards_as_refit(self):
        for start, end in (('2018-04-02', '2018-05-01'),
                           ('2018-04-01', '2018-05-02'),
                           ('2018-04-01', '2018-04-01'),
                           ('2018-05-01', '2018-05-27')):
            with self.subTest(start=start, end=end), self.assertRaises(ValueError):
                rolling_validation_schedule(start, end)
        report = rolling_validation_schedule('2018-05-01', '2018-05-26')
        self.assertEqual(report['evaluation_end'], report['fixed_test_start'])


class RollingMatureValidationTests(unittest.TestCase):
    def setUp(self):
        splits, _ = split_rolling_month(rolling_records(), '2017-12-01')
        self.scoring = splits['scoring']

    def test_only_labels_strictly_before_cutoff_are_used_without_negative_relabeling(self):
        before = self.scoring.copy(deep=True)
        mature, report = mature_validation_month(self.scoring, '2018-04-01')
        identities = set(mature.order_id)
        self.assertNotIn('validation_label_equal', identities)
        self.assertNotIn('validation_negative_label_equal', identities)
        self.assertIn('validation_label_before', identities)
        self.assertEqual(report['purged_rows'], 2)
        self.assertEqual(report['purged_positive_rows'], 1)
        self.assertEqual(report['purged_negative_rows'], 1)
        self.assertEqual(report['rows_before_purge'], report['rows'] + 2)
        self.assertEqual(report['positive_retention_rate'],
                         report['positive_rows'] / report['positive_rows_before_purge'])
        self.assertEqual(report['negative_retention_rate'],
                         report['negative_rows'] / report['negative_rows_before_purge'])
        pd.testing.assert_frame_equal(before, self.scoring)

    def test_mature_validation_is_order_independent_and_requires_two_mature_classes(self):
        expected, report = mature_validation_month(self.scoring, '2018-04-01')
        shuffled = self.scoring.sample(frac=1, random_state=63)
        shuffled.index = [0] * len(shuffled)
        actual, actual_report = mature_validation_month(shuffled, '2018-04-01')
        self.assertEqual(report, actual_report)
        pd.testing.assert_frame_equal(actual, expected)
        changed = self.scoring.copy()
        changed.loc[changed.delayed.eq(1), 'label_available_time'] = pd.Timestamp('2018-04-01')
        with self.assertRaisesRegex(ValueError, 'validation month 2017-12.*both binary classes'):
            mature_validation_month(changed, '2018-04-01')

    def test_invalid_maturity_cutoffs_empty_or_multiple_months_fail(self):
        extra_month = rolling_records().loc[lambda frame: frame.prediction_time.dt.month.eq(11)].iloc[:2]
        for frame, cutoff in (
            (self.scoring, '2017-12-31'), (self.scoring, '2018-05-27'),
            (self.scoring, '2018-04-01 12:00'),
            (self.scoring, pd.Timestamp('2018-04-01', tz='UTC')),
            (self.scoring.iloc[:0], '2018-04-01'),
            (pd.concat([self.scoring, extra_month], ignore_index=True), '2018-04-01'),
        ):
            with self.subTest(cutoff=cutoff, rows=len(frame)), self.assertRaises(ValueError):
                mature_validation_month(frame, cutoff)
        _, report = mature_validation_month(self.scoring, '2018-05-26')
        self.assertEqual(report['label_maturity_cutoff'], '2018-05-26T00:00:00')


if __name__ == '__main__':
    unittest.main()
