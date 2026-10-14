"""Regression cohorts must respect unknown labels and complete-day ranking."""
import json
from pathlib import Path
import tempfile
import unittest

import numpy as np

from scripts.compare_backlog_objectives import CLASSIFIERS, MATCHED, RANKERS
from scripts.diagnose_objective_misses import ANALYSIS, original_regression_cohort, validate_output
from tests.test_delay_route_exchanges import cohort, selected_scores


class ObjectiveMissDiagnosisTests(unittest.TestCase):
    def test_unknown_labels_are_never_read_and_original_lost_delays_keep_full_day_ranks(self):
        frame = cohort(40)
        frame['delayed'] = 0
        frame.loc[[1, 4, 8], 'delayed'] = 1
        frame['estimated_delivery_days'] = np.resize([10., 25.], len(frame))
        known = np.arange(len(frame)) != 0
        scores = {
            CLASSIFIERS[0]: selected_scores(40, [0, 1, 2, 3]),
            CLASSIFIERS[1]: selected_scores(40, [0, 2, 3, 4]),
            RANKERS[0]: selected_scores(40, [0, 1, 4, 5]),
            RANKERS[1]: selected_scores(40, [0, 2, 6, 7]),
        }
        actual = original_regression_cohort(frame, scores, known)
        self.assertEqual(actual['cohort_rows'], 1)
        self.assertEqual(actual['known_rows'], 39)
        self.assertEqual(actual['known_delayed_rows'], 3)
        self.assertEqual([actual['models'][c]['in_top10'] for c in MATCHED], [1, 0, 1, 0])
        self.assertEqual(actual['models'][RANKERS[1]]['rank_bins']['10-20%'], 1)
        self.assertEqual(actual['models'][RANKERS[1]]['in_top20'], 1)
        for dimension in ('routes', 'promise_days', 'route_by_promise'):
            self.assertEqual(sum(row['cohort_rows'] for row in actual[dimension]), 1)
            self.assertEqual(sum(row['known_rows'] for row in actual[dimension]), 39)
            self.assertTrue(any(row['cohort_rows'] == 0 for row in actual[dimension]))
        corrupted = frame.copy()
        corrupted['delayed'] = corrupted.delayed.astype(object)
        corrupted.loc[~known, 'delayed'] = 'future outcome must never be read'
        self.assertEqual(original_regression_cohort(corrupted, scores, known), actual)
        self.assertNotIn('private-order-', json.dumps(actual))

    def test_empty_original_regression_cohort_has_zero_counts_and_no_fraction_claim(self):
        frame = cohort(20)
        frame['estimated_delivery_days'] = 10.
        scores = {candidate: selected_scores(20, [0, 1]) for candidate in MATCHED}
        actual = original_regression_cohort(frame, scores, np.ones(20, bool))
        self.assertEqual(actual['cohort_rows'], 0)
        self.assertTrue(all(model['in_top10'] == 0 and model['fraction_in_top10'] is None
                            for model in actual['models'].values()))

    def test_output_cannot_overwrite_source_or_unrelated_reports(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source, unrelated, own = (root / name for name in ('source.json', 'unrelated.json', 'own.json'))
            source.write_text('{"status":"ok"}', encoding='utf-8')
            unrelated.write_text('{"analysis":"another_analysis"}', encoding='utf-8')
            own.write_text(json.dumps({'analysis': ANALYSIS, 'format_version': 1}), encoding='utf-8')
            for bad in (source, unrelated, root / 'new.csv'):
                with self.subTest(path=bad), self.assertRaises(ValueError):
                    validate_output(bad, source)
            self.assertEqual(source.read_text(encoding='utf-8'), '{"status":"ok"}')
            self.assertEqual(validate_output(own, source), own.resolve())


if __name__ == '__main__':
    unittest.main()
