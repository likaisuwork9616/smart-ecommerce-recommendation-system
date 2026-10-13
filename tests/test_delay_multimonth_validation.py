"""Shared monthly recall floors, calendar alignment and label maturity."""
import unittest

import numpy as np
import pandas as pd

from scripts.delay_alert_policy import choose_recall_threshold
from scripts.delay_multimonth_validation import (
    choose_multimonth_threshold, split_multimonth_fold,
)
from scripts.delay_waiting_split import approval_cohort_audit


def calendar_records():
    rows = []
    for day in pd.date_range('2016-01-01', '2018-05-26'):
        for hour, delayed in ((8, 0), (20, 1)):
            prediction = day + pd.Timedelta(hours=hour)
            rows.append({
                'order_id': f'{day:%Y%m%d}_{hour}',
                'order_purchase_timestamp': prediction - pd.Timedelta(hours=1),
                'prediction_time': prediction,
                'label_available_time': prediction + pd.Timedelta(hours=2),
                'delayed': delayed,
                'route_feature': 'SP->RJ',
            })
    for order_id, approval, available, delayed in (
        ('train_label_equal', '2017-08-01 12:00', '2017-10-01', 1),
        ('train_label_before', '2017-08-01 13:00', '2017-09-30 23:59:59.999999999', 1),
        ('validation_label_equal', '2017-12-15 12:00', '2018-04-01', 1),
        ('validation_label_before', '2017-12-15 13:00', '2018-03-31 23:59:59.999999999', 1),
        ('validation_negative_equal', '2017-10-15 13:00', '2018-04-01', 0),
        ('train_approval_equal', '2017-08-02', '2017-08-03', 1),
        ('validation_approval_equal', '2017-10-01', '2017-10-02', 1),
        ('validation_end_equal', '2018-01-01', '2018-01-02', 1),
        ('evaluation_approval_equal', '2018-04-01', '2018-04-02', 1),
        ('evaluation_end_equal', '2018-05-01', '2018-05-02', 1),
        ('evaluation_retrospective', '2018-04-02 12:00', '2018-06-01', 1),
    ):
        prediction = pd.Timestamp(approval)
        rows.append({
            'order_id': order_id,
            'order_purchase_timestamp': prediction - pd.Timedelta(hours=1),
            'prediction_time': prediction,
            'label_available_time': pd.Timestamp(available),
            'delayed': delayed,
            'route_feature': 'SP->RJ',
        })
    return pd.DataFrame(rows)


class MultimonthSplitTests(unittest.TestCase):
    def setUp(self):
        self.frame = calendar_records()

    def split(self, frame=None):
        return split_multimonth_fold(self.frame if frame is None else frame,
                                     '2018-04-01', '2018-05-01')

    def test_three_complete_months_align_down_after_sixty_day_wait(self):
        splits, report = self.split()
        self.assertEqual(report['train_prediction_end'], '2017-08-02T00:00:00')
        self.assertEqual(report['model_fit_time'], '2017-10-01T00:00:00')
        self.assertEqual(report['validation_start'], '2017-10-01T00:00:00')
        self.assertEqual(report['validation_end'], '2018-01-01T00:00:00')
        self.assertEqual(report['threshold_selection_time'], '2018-04-01T00:00:00')
        self.assertEqual(report['validation_days'], 92)
        self.assertEqual(report['train_wait']['days'], 60)
        self.assertEqual(report['validation_wait']['days'], 90)
        self.assertEqual([m['month'] for m in report['validation_months']],
                         ['2017-10', '2017-11', '2017-12'])
        for part in splits.values():
            self.assertIn('route_feature', part.columns)
        _, february = split_multimonth_fold(self.frame, '2018-02-01', '2018-03-01')
        self.assertEqual(february['validation_end'], '2017-12-01T00:00:00')
        self.assertEqual(february['validation_start'], '2017-09-01T00:00:00')
        self.assertEqual(february['validation_wait']['days'], 62)

    def test_strict_approval_boundaries_leave_both_wait_gaps_unassigned(self):
        splits, report = self.split()
        all_ids = set().union(*(set(frame.order_id) for frame in splits.values()))
        self.assertNotIn('train_approval_equal', all_ids)
        self.assertIn('validation_approval_equal', set(splits['validation'].order_id))
        self.assertNotIn('validation_end_equal', all_ids)
        self.assertIn('evaluation_approval_equal', set(splits['evaluation'].order_id))
        self.assertNotIn('evaluation_end_equal', all_ids)
        for key in ('train_wait', 'validation_wait'):
            gap = report[key]
            mask = self.frame.prediction_time.between(pd.Timestamp(gap['start']),
                                                      pd.Timestamp(gap['end']), inclusive='left')
            self.assertEqual(gap['prediction_rows_not_assigned'], int(mask.sum()))
            self.assertFalse(set(self.frame.loc[mask].order_id) & all_ids)

    def test_labels_equal_to_cutoff_purged_and_nanosecond_before_retained(self):
        splits, report = self.split()
        for name in ('train', 'validation'):
            ids = set(splits[name].order_id)
            self.assertNotIn(f'{name}_label_equal', ids)
            self.assertIn(f'{name}_label_before', ids)
        self.assertNotIn('validation_negative_equal', set(splits['validation'].order_id))
        self.assertEqual(report['partitions']['train']['purged_positive_rows'], 1)
        val = report['partitions']['validation']
        self.assertEqual(val['purged_positive_rows'], 1)
        self.assertEqual(val['purged_negative_rows'], 1)
        self.assertEqual(val['rows_before_purge'], val['rows'] + 2)
        october, november, december = report['validation_months']
        self.assertEqual(october['purged_negative_rows'], 1)
        self.assertEqual(december['purged_positive_rows'], 1)
        self.assertEqual(november['purged_rows'], 0)
        for month in report['validation_months']:
            self.assertEqual(month['positive_retention_rate'],
                             month['positive_rows'] / month['positive_rows_before_purge'])
            self.assertEqual(month['negative_retention_rate'],
                             month['negative_rows'] / month['negative_rows_before_purge'])

    def test_every_validation_month_requires_both_mature_classes(self):
        for month, positive in (('2017-10', 0), ('2017-11', 1), ('2017-12', 0)):
            frame = self.frame.copy()
            mask = frame.prediction_time.dt.strftime('%Y-%m').eq(month)
            frame.loc[mask, 'delayed'] = positive
            with self.subTest(month=month), self.assertRaisesRegex(ValueError, f'validation month {month}'):
                self.split(frame)
        frame = self.frame.copy()
        mask = frame.prediction_time.dt.strftime('%Y-%m').eq('2017-11') & frame.delayed.eq(1)
        frame.loc[mask, 'label_available_time'] = pd.Timestamp('2018-04-01')
        with self.assertRaisesRegex(ValueError, 'validation month 2017-11'):
            self.split(frame)

    def test_evaluation_is_retrospective_and_cannot_change_validation(self):
        original, report = self.split()
        changed = self.frame.copy()
        mask = changed.prediction_time.between(pd.Timestamp('2018-04-01'),
                                               pd.Timestamp('2018-05-01'), inclusive='left')
        changed.loc[mask, 'delayed'] = 1 - changed.loc[mask, 'delayed']
        changed.loc[mask, 'label_available_time'] = pd.Timestamp('2099-01-01')
        mutated, changed_report = self.split(changed)
        for name in ('train', 'validation'):
            pd.testing.assert_frame_equal(original[name], mutated[name])
            self.assertEqual(report['partitions'][name], changed_report['partitions'][name])
        self.assertEqual(report['validation_months'], changed_report['validation_months'])
        self.assertIn('evaluation_retrospective', set(original['evaluation'].order_id))
        self.assertEqual(report['partitions']['evaluation']['late_known_at_original_holdout_count'], 1)
        self.assertIsNone(report['partitions']['evaluation']['label_maturity_cutoff'])

    def test_invalid_and_holdout_boundaries_rejected(self):
        for start, end in (('2018-04-01 12:00', '2018-05-01'),
                           (pd.Timestamp('2018-04-01', tz='UTC'), '2018-05-01'),
                           ('2018-04-01', '2018-05-27'),
                           ('2018-05-26', '2018-05-27'),
                           ('2018-05-01', '2018-04-01'),
                           ('2018-04-01', '2018-04-01'),
                           (pd.NaT, '2018-05-01')):
            with self.subTest(start=start, end=end), self.assertRaises(ValueError):
                split_multimonth_fold(self.frame, start, end)
        _, report = split_multimonth_fold(self.frame, '2018-04-01', '2018-05-26')
        self.assertEqual(report['evaluation_end'], report['fixed_test_start'])

    def test_shuffle_duplicate_external_index_and_metadata_guards(self):
        expected, report = self.split()
        shuffled = self.frame.sample(frac=1, random_state=6)
        shuffled.index = [0] * len(shuffled)
        actual, shuffled_report = self.split(shuffled)
        self.assertEqual(report, shuffled_report)
        for name in expected:
            pd.testing.assert_frame_equal(expected[name], actual[name])
        invalid = (self.frame.drop(columns='delayed'),
                   pd.concat([self.frame, self.frame.iloc[:1]], ignore_index=True))
        for frame in invalid:
            with self.assertRaises(ValueError):
                self.split(frame)

    def test_common_report_schema_supports_existing_raw_approval_audit(self):
        _, report = self.split()
        raw = self.frame[['order_id', 'prediction_time']].rename(
            columns={'prediction_time': 'order_approved_at'})
        raw['order_status'] = 'delivered'
        raw = pd.concat([raw, pd.DataFrame([{
            'order_id': 'cancelled_no_inferred_label', 'order_approved_at': pd.Timestamp('2017-11-15'),
            'order_status': 'canceled',
        }])], ignore_index=True)
        audit = approval_cohort_audit(raw, self.frame, report)
        validation = audit['partitions']['validation']
        self.assertEqual(validation['not_in_eligible_cohort_rows'], 1)
        self.assertEqual(validation['known_eligible_labels_at_cutoff'], report['partitions']['validation']['rows'])
        self.assertEqual(validation['status_counts']['canceled'], 1)
        self.assertIsNone(audit['partitions']['evaluation']['known_eligible_labels_at_cutoff'])


class MultimonthThresholdTests(unittest.TestCase):
    def test_pooled_target_can_hide_zero_recall_month_and_month_floor_fixes_it(self):
        y = [1, 1, 1, 0, 1, 1, 1, 0]
        scores = [.9, .8, .7, .6, .3, .2, .1, .4]
        months = ['2018-01'] * 4 + ['2018-02'] * 4
        pooled_threshold, pooled = choose_recall_threshold(y, scores, .30)
        threshold, policy = choose_multimonth_threshold(y, scores, months, .30)
        self.assertEqual(pooled_threshold, .8)
        self.assertGreaterEqual(pooled['achieved_recall'], .30)
        self.assertEqual(int(np.sum(np.asarray(scores)[4:7] >= pooled_threshold)), 0)
        self.assertEqual(threshold, .3)
        self.assertEqual([month['recall'] for month in policy['months']], [1.0, 1 / 3])
        self.assertTrue(policy['all_months_meet_recall_floor'])
        self.assertEqual(policy['minimum_month_recall'], 1 / 3)
        self.assertEqual(policy['pooled']['confusion_matrix'], [[0, 2], [2, 4]])
        self.assertFalse(policy['evaluation_recall_guarantee'])

    def test_shared_threshold_preserves_all_ties_and_can_exceed_floor(self):
        y = [1, 1, 1, 1, 0, 0] * 2
        scores = [.8, .5, .5, .1, .5, .2, .9, .4, .4, .1, .4, .3]
        months = ['2018-01'] * 6 + ['2018-02'] * 6
        threshold, policy = choose_multimonth_threshold(y, scores, months, .5)
        self.assertEqual(threshold, .4)
        self.assertEqual([row['highest_feasible_threshold'] for row in policy['months']], [.5, .4])
        self.assertEqual([row['recall'] for row in policy['months']], [.75, .75])
        self.assertEqual(policy['pooled']['confusion_matrix'], [[2, 2], [2, 6]])
        self.assertTrue(np.all(np.asarray(scores)[np.asarray(scores) == .4] >= threshold))

    def test_highest_shared_threshold_matches_independent_exhaustive_search(self):
        rng = np.random.default_rng(28)
        y = np.tile(np.r_[np.zeros(10), np.ones(10)], 3)
        months = np.repeat(['2017-09', '2017-10', '2017-11'], 20)
        # Rounded values intentionally create score ties and boundary groups.
        scores = np.round(rng.random(len(y)), 1)
        for target in (.1, .3, .5, 1.0):
            feasible = []
            for candidate in np.unique(scores):
                recalls = [np.mean(scores[(months == month) & (y == 1)] >= candidate)
                           for month in set(months)]
                if min(recalls) >= target:
                    feasible.append(float(candidate))
            threshold, policy = choose_multimonth_threshold(y, scores, months, target)
            self.assertEqual(threshold, max(feasible))
            self.assertGreaterEqual(policy['minimum_month_recall'], target)
            self.assertEqual(policy['predicted_positive_rows'], int((scores >= threshold).sum()))

    def test_month_dates_periods_and_shuffling_are_equivalent(self):
        y = np.array([0, 1, 0, 1, 0, 1])
        scores = np.array([.1, .8, .2, .7, .3, .6])
        months = ['2017-09'] * 2 + ['2017-10'] * 2 + ['2017-11'] * 2
        expected = choose_multimonth_threshold(y, scores, months)
        order = np.array([5, 1, 0, 3, 4, 2])
        dates = [pd.Timestamp(month) + pd.Timedelta(days=10) for month in months]
        periods = [pd.Period(month, freq='M') for month in months]
        for values in (dates, periods, np.asarray(dates, dtype='datetime64[ns]')):
            self.assertEqual(choose_multimonth_threshold(y, scores, values), expected)
            shuffled = np.asarray(values)[order]
            self.assertEqual(choose_multimonth_threshold(y[order], scores[order], shuffled), expected)

    def test_months_without_either_class_are_rejected(self):
        for y in ([0, 1, 0, 0], [0, 1, 1, 1]):
            with self.subTest(y=y), self.assertRaisesRegex(ValueError, 'validation month 2018-02'):
                choose_multimonth_threshold(y, [.8, .9, .1, .2], ['2018-01'] * 2 + ['2018-02'] * 2)

    def test_invalid_labels_scores_months_and_target_fail(self):
        valid = ([0, 1, 0, 1], [.1, .9, .2, .8], ['2018-01'] * 2 + ['2018-02'] * 2)
        invalid = [
            ([], [], []),
            ([0, 1], valid[1], valid[2]),
            (valid[0], valid[1], ['2018-01']),
            ([0, 2, 0, 1], valid[1], valid[2]),
            ([0, 0, 0, 0], valid[1], valid[2]),
            (valid[0], [.1, np.nan, .2, .8], valid[2]),
            (valid[0], [.1, np.inf, .2, .8], valid[2]),
            (valid[0], [.1, 1.1, .2, .8], valid[2]),
            (valid[0], [[.1, .9], [.2, .8]], valid[2]),
            (valid[0], valid[1], ['2018-01', None, '2018-02', '2018-02']),
            (valid[0], valid[1], ['2018-01', 'invalid', '2018-02', '2018-02']),
            (valid[0], valid[1], [201801, 201801, 201802, 201802]),
            (valid[0], valid[1], [pd.Timestamp('2018-01-01', tz='UTC')] * 4),
            (valid[0], valid[1], [pd.Period('2018', freq='Y')] * 4),
        ]
        for index, args in enumerate(invalid):
            with self.subTest(index=index), self.assertRaises(ValueError):
                choose_multimonth_threshold(*args)
        for target in (0, -.1, 1.1, None, np.nan, np.inf, True, [.3], .3 + 1j):
            with self.subTest(target=target), self.assertRaises(ValueError):
                choose_multimonth_threshold(*valid, min_recall=target)


if __name__ == '__main__':
    unittest.main()
