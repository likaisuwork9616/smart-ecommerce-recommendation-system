"""Keep complete-day capacity, old common-miss cohorts and ledger clocks fixed."""
from copy import deepcopy
import unittest

import numpy as np
import pandas as pd

from scripts.diagnose_unobserved_handover_age import (
    BASELINE, NEW, FEATURE, AGE_BINS, completed, age_bins, diagnose_phase,
    common_miss_recovery, verify_phase_ledger,
)
from tests.test_diagnose_handover_history import example, ledger_fixture, NEW as OLD_NEW
from tests.test_delay_route_exchanges import selected_scores


def fixture():
    frame, scores, known = example()
    frame[FEATURE] = np.resize([np.nan, 0, 24, 24.5, 72, 168, 168.1], len(frame))
    return frame, {BASELINE: scores[BASELINE], NEW: scores[OLD_NEW]}, known


def ledger_data(frame, scores, known, role='validation'):
    ledger, expected = ledger_fixture(frame, {BASELINE: scores[BASELINE], OLD_NEW: scores[NEW]}, known, role)
    ledger.candidate = ledger.candidate.replace({OLD_NEW: NEW})
    return ledger, {BASELINE: expected[BASELINE], NEW: expected[OLD_NEW]}


class UnobservedHandoverAgeDiagnosisTests(unittest.TestCase):
    def test_fixed_age_bin_edges_and_missing(self):
        frame, _, _ = fixture()
        self.assertEqual(list(age_bins(frame)[:7]),
                         ['missing_or_empty', 'up_to_24h', 'up_to_24h', 'over24_to72h',
                          'over24_to72h', 'over72_to168h', 'over168h'])

    def test_invalid_age_rejected(self):
        frame, _, _ = fixture()
        for value in (-1, np.inf):
            with self.subTest(value=value), self.assertRaises(ValueError):
                age_bins(frame.assign(**{FEATURE: value}))

    def test_single_age_metadata_and_exchange(self):
        frame, scores, known = fixture()
        result = diagnose_phase(frame, scores, known)
        exchange = result['pending_age_features']
        self.assertEqual(exchange['comparison']['added_features'], [FEATURE])
        self.assertEqual(exchange['comparison']['new_feature_count'], 102)
        self.assertEqual(exchange['summary']['recovered_delays'], 1)
        self.assertEqual(exchange['summary']['lost_delays'], 1)
        self.assertEqual([r['age_bin'] for r in exchange['pending_age_bins']], list(AGE_BINS))
        self.assertEqual(result['volume_context'][NEW]['alerts'], 4)

    def test_unknown_high_rank_order_still_uses_slot(self):
        frame, scores, known = fixture()
        result = diagnose_phase(frame, scores, known)
        self.assertEqual(result['volume_context'][NEW]['unknown_alerts'], 1)
        self.assertEqual(result['volume_context'][BASELINE]['alerts'], 4)

    def test_old_common_miss_defined_without_new_scores(self):
        frame, scores, known = fixture()
        frozen = {BASELINE: scores[BASELINE], completed.HANDOVER104: scores[NEW],
                  completed.NEW: scores[BASELINE]}
        one = common_miss_recovery(frame, frozen, scores, known)
        better = {**scores, NEW: selected_scores(len(frame), [0, 1, 4, 8])}
        two = common_miss_recovery(frame, frozen, better, known)
        self.assertEqual(one['cohort_rows'], 1)
        self.assertEqual(one['cohort_rows'], two['cohort_rows'])
        self.assertEqual(one['recovered'], 0)
        self.assertEqual(two['recovered'], 1)
        self.assertEqual(two['still_missed'], 0)
        self.assertEqual(sum(r['cohort_rows'] for r in two['routes']), 1)

    def test_common_miss_unknown_answers_excluded(self):
        frame, scores, known = fixture()
        frame.loc[0, 'delayed'] = 1
        frozen = {c: selected_scores(len(frame), [1, 2, 3, 4]) for c in completed.MATCHED}
        result = common_miss_recovery(frame, frozen, scores, known)
        self.assertEqual(result['cohort_rows'], 1)  # only order8, unknown order0 excluded

    def test_historical_ledger_checks(self):
        frame, scores, known = fixture()
        ledger, expected = ledger_data(frame, scores, known)
        actual, values, _ = verify_phase_ledger(frame, ledger, '2017-12-01', 'validation', expected, '2017-07')
        np.testing.assert_array_equal(actual, known)
        np.testing.assert_array_equal(values[NEW], scores[NEW])

    def test_changed_availability_and_outcome_rejected(self):
        frame, scores, known = fixture()
        ledger, expected = ledger_data(frame, scores, known)
        for column, value in (('known_at_selection', True), ('outcome_for_metrics', 0.)):
            changed = ledger.copy()
            changed.loc[0, column] = value
            with self.subTest(column=column), self.assertRaises(AssertionError):
                verify_phase_ledger(frame, changed, '2017-12-01', 'validation', expected, '2017-07')

    def test_duplicate_or_missing_candidate_rejected(self):
        frame, scores, known = fixture()
        ledger, expected = ledger_data(frame, scores, known)
        changed = ledger.copy()
        changed.loc[1, 'order_id'] = changed.loc[0, 'order_id']
        for bad in (changed, ledger.iloc[:-1]):
            with self.assertRaises(ValueError):
                verify_phase_ledger(frame, bad, '2017-12-01', 'validation', expected, '2017-07')

    def test_changed_budget_metrics_rejected(self):
        frame, scores, known = fixture()
        ledger, expected = ledger_data(frame, scores, known)
        changed = deepcopy(expected)
        changed[NEW]['validation_by_month']['2017-07']['full_batch']['capacity'] = 99
        with self.assertRaises(ValueError):
            verify_phase_ledger(frame, ledger, '2017-12-01', 'validation', changed, '2017-07')

    def test_evaluation_flags_not_historical(self):
        frame, scores, _ = fixture()
        known = np.ones(len(frame), bool)
        ledger, expected = ledger_data(frame, scores, known, role='evaluation')
        actual, _, _ = verify_phase_ledger(frame, ledger, '2017-12-01', 'evaluation', expected, '2017-07')
        self.assertTrue(actual.all())
        ledger.loc[0, 'known_at_selection'] = True
        with self.assertRaises(AssertionError):
            verify_phase_ledger(frame, ledger, '2017-12-01', 'evaluation', expected, '2017-07')


if __name__ == '__main__':
    unittest.main()
