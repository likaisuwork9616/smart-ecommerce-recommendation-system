"""Synthetic, outcome-free evidence for one-day frozen-score delivery."""
from copy import deepcopy
import io
import json
import unittest

import numpy as np
import pandas as pd

from scripts import delay_daily_delivery_acceptance as acceptance


DAY = '2018-02-01'


def fixture(rows=20):
    roster = pd.DataFrame({
        'order_id': [f'private-acceptance-{index:03d}' for index in range(rows)],
        'prediction_time': pd.Timestamp(DAY) + pd.to_timedelta(np.arange(rows), unit='m'),
    })
    parts = []
    for version in acceptance.VERSIONS:
        colsample, candidate = acceptance.VERSION_SOURCE[version]
        for seed in acceptance.SEEDS:
            part = roster.copy()
            part['fold'], part['role'], part['model_version'] = '2018-02', 'evaluation', '2018-02'
            part['candidate'], part['colsample_bytree'], part['seed'] = candidate, colsample, seed
            part['known_at_selection'] = False
            part['delay_score'] = .5
            part['predicted_delayed'] = (np.arange(rows) < rows // 10).astype(int)
            parts.append(part)
    return roster, pd.concat(parts, ignore_index=True)


class DailyDeliveryAcceptanceTests(unittest.TestCase):
    def test_all_twenty_runs_have_canonical_private_schema_and_reconcile(self):
        roster, ledger = fixture(19)
        roster = roster.iloc[::-1]
        roster.index = np.arange(19) * 7
        ledger = ledger.sample(frac=1, random_state=73)
        public, private = acceptance.accept_day(roster, ledger, day=DAY)
        self.assertEqual((public['full_day_rows'], public['daily_capacity']), (19, 1))
        self.assertEqual((public['run_count'], public['score_rows'], public['alerts_across_runs']), (20, 380, 20))
        self.assertEqual(tuple(private.columns), acceptance.PRIVATE_COLUMNS)
        self.assertEqual(private.version.drop_duplicates().tolist(), list(acceptance.VERSIONS))
        for version in acceptance.VERSIONS:
            self.assertEqual(private.loc[private.version.eq(version), 'seed'].drop_duplicates().tolist(),
                             list(acceptance.SEEDS))
        self.assertTrue(public['labels_not_read'])
        self.assertEqual(public['outcome_columns_read'], 0)
        self.assertFalse(public['source_has_saved_daily_rank'])
        self.assertEqual(public['saved_daily_ranks_verified'], 0)

    def test_ties_use_identity_ascending_and_unknown_outcomes_keep_slots(self):
        roster, ledger = fixture()
        ledger['outcome_for_metrics'] = 'future-outcome-must-never-be-read'
        ledger['state_route'] = 'arbitrary-unseen-group'
        public, private = acceptance.accept_day(roster.iloc[::-1], ledger.iloc[::-1], day=DAY)
        for (_, _), part in private.groupby(['version', 'seed'], sort=False):
            self.assertEqual(part.order_id.tolist(), sorted(roster.order_id))
            self.assertEqual(part.loc[part.alert, 'order_id'].tolist(), roster.order_id.iloc[:2].tolist())
        tie = public['runs'][0]['ties']
        self.assertEqual(tie['tied_score_groups'], 1)
        self.assertEqual(tie['rows_in_tied_score_groups'], 20)
        self.assertEqual((tie['cutoff_tie_rows'], tie['cutoff_tie_alerted_rows'], tie['cutoff_tie_unalerted_rows']),
                         (20, 2, 18))
        self.assertTrue(tie['cross_boundary_tie'])

    def test_changing_labels_and_groups_does_not_change_any_output(self):
        roster, ledger = fixture()
        expected_public, expected_private = acceptance.accept_day(roster, ledger, day=DAY)
        changed = ledger.assign(outcome_for_metrics=np.nan, delayed='unavailable-future-label',
                                state_route='SP->RJ', arbitrary_group='forbidden-slice')
        public, private = acceptance.accept_day(roster.assign(delayed=object()), changed, day=DAY)
        self.assertEqual(public, expected_public)
        pd.testing.assert_frame_equal(private, expected_private, check_exact=True)

    def test_score_descending_precedes_identity_and_flags_must_match(self):
        roster, ledger = fixture(10)
        last = roster.order_id.iloc[-1]
        ledger['delay_score'] = .1
        ledger.loc[ledger.order_id.eq(last), 'delay_score'] = .9
        ledger['predicted_delayed'] = ledger.order_id.eq(last).astype(int)
        public, private = acceptance.accept_day(roster, ledger, day=DAY)
        self.assertTrue(private.loc[private['rank'].eq(1), 'order_id'].eq(last).all())
        self.assertEqual(private.loc[private.alert, 'order_id'].nunique(), 1)
        self.assertFalse(public['runs'][0]['ties']['cross_boundary_tie'])

    def test_floor_capacity_for_nine_ten_and_nineteen(self):
        for size, capacity in ((9, 0), (10, 1), (19, 1)):
            with self.subTest(size=size):
                roster, ledger = fixture(size)
                public, private = acceptance.accept_day(roster, ledger, day=DAY)
                self.assertEqual(public['daily_capacity'], capacity)
                self.assertEqual(int(private.alert.sum()), 20 * capacity)
                if not capacity:
                    tie = public['runs'][0]['ties']
                    self.assertFalse(tie['cross_boundary_tie'])
                    self.assertFalse(tie['boundary_has_selected_row'])
                    self.assertTrue(tie['boundary_has_unselected_row'])
                    self.assertEqual(tie['cutoff_tie_rows'], 0)

    def test_public_json_contains_no_identity_or_score_value(self):
        roster, ledger = fixture()
        public, _ = acceptance.accept_day(roster, ledger, day=DAY)
        text = json.dumps(public, allow_nan=False)
        self.assertNotIn('private-acceptance-', text)
        self.assertNotIn('cutoff_score', text)
        self.assertNotIn('next_score', text)
        self.assertNotIn('score_margin', text)
        self.assertNotIn('"score":', text)
        self.assertNotIn('"rank":', text)
        self.assertEqual(json.loads(json.dumps(acceptance.schema(), allow_nan=False)), acceptance.schema())

    def test_input_frames_are_not_mutated(self):
        roster, ledger = fixture()
        expected_roster, expected_ledger = deepcopy(roster), deepcopy(ledger)
        acceptance.accept_day(roster, ledger, day=DAY)
        pd.testing.assert_frame_equal(roster, expected_roster, check_exact=True)
        pd.testing.assert_frame_equal(ledger, expected_ledger, check_exact=True)

    def test_empty_or_missing_input_schema_is_rejected(self):
        roster, ledger = fixture()
        for bad_roster, bad_ledger in ((roster.iloc[:0], ledger), (roster.drop(columns='order_id'), ledger),
                                      (roster, ledger.iloc[:0]), (roster, ledger.drop(columns='delay_score'))):
            with self.subTest(roster_columns=list(bad_roster), ledger_columns=list(bad_ledger)):
                with self.assertRaises(ValueError):
                    acceptance.accept_day(bad_roster, bad_ledger, day=DAY)

    def test_missing_or_extra_row_is_rejected(self):
        roster, ledger = fixture()
        for changed in (ledger.iloc[1:], pd.concat([ledger, ledger.iloc[:1]], ignore_index=True)):
            with self.assertRaises(ValueError):
                acceptance.accept_day(roster, changed, day=DAY)

    def test_duplicate_identity_or_same_size_wrong_identity_is_rejected(self):
        roster, ledger = fixture()
        for value in (roster.order_id.iloc[1], 'unexpected-identity'):
            changed = ledger.copy()
            changed.loc[0, 'order_id'] = value
            with self.subTest(value=value), self.assertRaises(ValueError):
                acceptance.accept_day(roster, changed, day=DAY)
        changed_roster = roster.copy()
        changed_roster.loc[0, 'order_id'] = changed_roster.order_id.iloc[1]
        with self.assertRaises(ValueError):
            acceptance.accept_day(changed_roster, ledger, day=DAY)

    def test_invalid_or_empty_identity_is_rejected(self):
        roster, ledger = fixture()
        for value in (None, '', ' outer-space', 'outer-space ', 12):
            for target in ('roster', 'ledger'):
                bad_roster, bad_ledger = roster.copy(), ledger.copy()
                changed = bad_roster if target == 'roster' else bad_ledger
                changed['order_id'] = changed.order_id.astype(object)
                changed.loc[0, 'order_id'] = value
                with self.subTest(value=value, target=target), self.assertRaises(ValueError):
                    acceptance.accept_day(bad_roster, bad_ledger, day=DAY)

    def test_different_day_or_timestamp_mismatch_is_rejected(self):
        roster, ledger = fixture()
        for value in (pd.Timestamp('2018-02-02'), pd.Timestamp('2018-02-01 01:00:00')):
            changed = ledger.copy()
            changed.loc[0, 'prediction_time'] = value
            with self.subTest(value=value), self.assertRaises(ValueError):
                acceptance.accept_day(roster, changed, day=DAY)
        changed = roster.copy()
        changed.loc[0, 'prediction_time'] = pd.Timestamp('2018-01-31')
        with self.assertRaises(ValueError):
            acceptance.accept_day(changed, ledger, day=DAY)

    def test_missing_numeric_invalid_or_timezone_clock_is_rejected(self):
        roster, ledger = fixture()
        for value in (pd.NaT, 0, 'invalid-clock', '2018-02-01T00:00:00Z',
                      pd.Timestamp('2018-02-01', tz='America/Sao_Paulo')):
            changed = ledger.copy()
            changed['prediction_time'] = changed.prediction_time.astype(object)
            changed.loc[0, 'prediction_time'] = value
            with self.subTest(value=value), self.assertRaises(ValueError):
                acceptance.accept_day(roster, changed, day=DAY)

    def test_day_must_be_midnight_naive_and_in_model_month(self):
        roster, ledger = fixture()
        for day in ('2018-02-01 01:00:00', '2018-02-01T00:00:00Z', '2018-03-01', None, 0):
            with self.subTest(day=day), self.assertRaises(ValueError):
                acceptance.accept_day(roster, ledger, day=day)

    def test_bad_fold_role_or_model_version_is_rejected(self):
        roster, ledger = fixture()
        for column, value in (('fold', '2018-04'), ('role', 'validation'), ('model_version', '2018-04')):
            changed = ledger.copy()
            changed.loc[0, column] = value
            with self.subTest(column=column), self.assertRaises(ValueError):
                acceptance.accept_day(roster, changed, day=DAY)
        with self.assertRaises(ValueError):
            acceptance.accept_day(roster, ledger, day=DAY, role='validation')

    def test_missing_seed_extra_seed_and_noninteger_seed_are_rejected(self):
        roster, ledger = fixture()
        for value in (999, 11.0, True, '11'):
            changed = ledger.copy()
            changed['seed'] = changed.seed.astype(object)
            changed.loc[0, 'seed'] = value
            with self.subTest(value=value), self.assertRaises(ValueError):
                acceptance.accept_day(roster, changed, day=DAY)
        changed = ledger.copy()
        changed.loc[changed.seed.eq(11), 'seed'] = 29
        with self.assertRaises(ValueError):
            acceptance.accept_day(roster, changed, day=DAY)

    def test_changed_candidate_or_colsample_is_rejected(self):
        roster, ledger = fixture()
        for column, value in (('candidate', 'unknown-candidate'), ('colsample_bytree', .9),
                              ('colsample_bytree', True), ('colsample_bytree', '.8')):
            changed = ledger.copy()
            changed[column] = changed[column].astype(object)
            changed.loc[0, column] = value
            with self.subTest(column=column, value=value), self.assertRaises(ValueError):
                acceptance.accept_day(roster, changed, day=DAY)

    def test_same_total_size_cannot_hide_a_missing_version_seed_cohort(self):
        roster, ledger = fixture()
        changed = ledger.copy()
        changed.loc[(changed.candidate.eq(acceptance.BASELINE)) & changed.colsample_bytree.eq(.8)
                    & changed.seed.eq(11), 'candidate'] = acceptance.AGE
        with self.assertRaises(ValueError):
            acceptance.accept_day(roster, changed, day=DAY)

    def test_nan_infinite_out_of_bounds_complex_string_and_boolean_score_are_rejected(self):
        roster, ledger = fixture()
        for value in (np.nan, np.inf, -np.inf, -.01, 1.01, 0.5 + 0j, '.5', True):
            changed = ledger.copy()
            changed['delay_score'] = changed.delay_score.astype(object)
            changed.loc[0, 'delay_score'] = value
            with self.subTest(value=value), self.assertRaises(ValueError):
                acceptance.accept_day(roster, changed, day=DAY)

    def test_saved_alert_flag_must_be_binary_and_reconcile_with_ranking(self):
        roster, ledger = fixture()
        for value in (2, np.nan, '1', 1.0, 0):
            changed = ledger.copy()
            changed['predicted_delayed'] = changed.predicted_delayed.astype(object)
            changed.loc[0, 'predicted_delayed'] = value
            with self.subTest(value=value), self.assertRaises(ValueError):
                acceptance.accept_day(roster, changed, day=DAY)

    def test_selection_availability_flag_is_boolean_false_not_metric_knownness(self):
        roster, ledger = fixture()
        for value in (True, 0, 'False', np.nan):
            changed = ledger.copy()
            changed['known_at_selection'] = changed.known_at_selection.astype(object)
            changed.loc[0, 'known_at_selection'] = value
            with self.subTest(value=value), self.assertRaises(ValueError):
                acceptance.accept_day(roster, changed, day=DAY)

    def test_explicit_saved_rank_is_verified_if_present(self):
        roster, ledger = fixture()
        ledger['source_rank'] = np.tile(np.arange(1, 21), 20)
        public, _ = acceptance.accept_day(roster, ledger, day=DAY, saved_rank_column='source_rank')
        self.assertEqual(public['saved_daily_ranks_verified'], 400)
        self.assertTrue(public['source_has_saved_daily_rank'])
        for value in (2, 1.0, True):
            changed = ledger.copy()
            changed['source_rank'] = changed.source_rank.astype(object)
            changed.loc[0, 'source_rank'] = value
            with self.subTest(value=value), self.assertRaises(ValueError):
                acceptance.accept_day(roster, changed, day=DAY, saved_rank_column='source_rank')
        with self.assertRaises(ValueError):
            acceptance.accept_day(roster, ledger, day=DAY, saved_rank_column='missing-column')

    def test_private_output_csv_readback_rechecks_all_rows_and_canonical_order(self):
        roster, ledger = fixture()
        _, private = acceptance.accept_day(roster, ledger, day=DAY)
        readback = pd.read_csv(io.StringIO(private.to_csv(index=False)), float_precision='round_trip',
                               parse_dates=['prediction_time'])
        result = acceptance.verify_private_output(roster, readback, day=DAY)
        self.assertEqual((result['rows_verified'], result['runs_verified'], result['rank_rows_verified']),
                         (400, 20, 400))
        self.assertTrue(result['canonical_row_order_verified'])
        self.assertFalse(result['source_score_provenance_verified_by_this_function'])
        with self.assertRaises(ValueError):
            acceptance.verify_private_output(roster, readback.iloc[::-1], day=DAY)

    def test_private_output_schema_denominator_capacity_rank_and_alert_fail_closed(self):
        roster, ledger = fixture()
        _, private = acceptance.accept_day(roster, ledger, day=DAY)
        for column, value in (('full_day_rows', 19), ('daily_capacity', 3), ('rank', 2),
                              ('alert', False), ('version', 'unfrozen-version')):
            changed = private.copy()
            changed.loc[0, column] = value
            with self.subTest(column=column), self.assertRaises(ValueError):
                acceptance.verify_private_output(roster, changed, day=DAY)
        with self.assertRaises(ValueError):
            acceptance.verify_private_output(roster, private.assign(outcome_for_metrics=1), day=DAY)

    def test_output_internal_consistency_does_not_prove_frozen_score_provenance(self):
        roster, ledger = fixture()
        _, private = acceptance.accept_day(roster, ledger, day=DAY)
        changed = private.copy()
        changed['score'] = .4  # Preserves ties and ranks, but changes every frozen score.
        result = acceptance.verify_private_output(roster, changed, day=DAY)
        self.assertFalse(result['source_score_provenance_verified_by_this_function'])
        with self.assertRaises(AssertionError):
            pd.testing.assert_frame_equal(changed, private, check_exact=True)


if __name__ == '__main__':
    unittest.main()
