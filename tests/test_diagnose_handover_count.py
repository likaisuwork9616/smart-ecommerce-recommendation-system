"""Three-model score-ledger diagnosis preserves cohorts and daily budgets."""
from copy import deepcopy
import json
from pathlib import Path
import tempfile
import unittest

import numpy as np
import pandas as pd

from scripts.compare_calibration_budget import alert_metrics, batch_audit
from scripts.delay_calibration_policy import apply_alert_policy
from scripts.delay_route_exchanges import COUNT_FIELDS
from scripts.diagnose_budget_misses import PROMISE_BINS
from scripts import diagnose_handover_history as history
from scripts.diagnose_handover_count import (
    ADDED_FEATURES, ANALYSIS, BASELINE, COMPARISONS, HANDOVER104, MATCHED, NEW,
    diagnose_phase, pair_diagnostics, regression_cohorts, validate_output,
    validate_source_contract, verify_phase_ledger,
)
from tests.test_delay_route_exchanges import cohort, selected_scores
from tests.test_diagnose_handover_history import source_fixture as previous_source_fixture


def example(rows=40):
    frame = cohort(rows)
    frame['estimated_delivery_days'] = np.resize([7., 30., 30.25, 32.], rows)
    counts = np.resize([0, 1, 4, 5, 20], rows)
    frame[ADDED_FEATURES[0]] = counts
    frame[ADDED_FEATURES[1]] = np.where(counts >= 5, 24., np.nan)
    frame[ADDED_FEATURES[2]] = np.where(counts >= 5, 48., np.nan)
    frame['label_available_time'] = pd.Timestamp('2017-08-01')
    frame['delayed'] = 0
    frame.loc[[2, 4, 8], 'delayed'] = 1
    scores = {BASELINE: selected_scores(rows, [0, 1, 2, 3]),
              HANDOVER104: selected_scores(rows, [0, 1, 4, 6]),
              NEW: selected_scores(rows, [0, 2, 4, 8])}
    return frame, scores, np.ones(rows, bool)


def ledger_fixture(frame, scores, known, role='validation'):
    rows, expected = [], {}
    for candidate in MATCHED:
        alert = apply_alert_policy(frame, scores[candidate], 0., .1)
        outcome = np.full(len(frame), np.nan)
        outcome[known] = frame.loc[known, 'delayed'].to_numpy()
        rows.append(pd.DataFrame({'order_id': frame.order_id, 'prediction_time': frame.prediction_time,
            'candidate': candidate, 'model_version': '2017-07', 'role': role,
            'known_at_selection': known if role == 'validation' else np.zeros(len(frame), bool),
            'outcome_for_metrics': outcome, 'delay_score': scores[candidate],
            'predicted_delayed': alert.astype(int)}))
        metrics = alert_metrics(frame.loc[known, 'delayed'].to_numpy(), scores[candidate][known], alert[known])
        batch = batch_audit(frame, alert, .1, known)
        expected[candidate] = {'validation_by_month': {'2017-07': {'known_outcome_metrics': metrics, 'full_batch': batch}},
            'development_evaluation': metrics, 'evaluation_batch': batch}
    return pd.concat(rows, ignore_index=True), expected


def source_fixture():
    previous, _, _ = previous_source_fixture()
    source = deepcopy(previous)
    source.update(experiment='handover_count_ablation', only_changed_component='single_seller_handover_count_feature',
        matched_candidate_order=list(MATCHED), new_candidate_order=[NEW],
        candidate_order=[*previous['candidate_order'], NEW], added_features=ADDED_FEATURES[:1])
    source['source_features'] = {key: previous['feature_dataset'][key] for key in ('path', 'sha256')}
    previous['score_export'] = {'path': 'old_scores.csv', 'sha256': 'old_scores'}
    source['source_scores'] = deepcopy(previous['score_export'])
    source['candidate_specifications'][NEW] = deepcopy(source['candidate_specifications'][BASELINE])
    source['candidate_specifications'][NEW]['numeric_features'].extend(ADDED_FEATURES[:1])
    for fold in source['folds']:
        fold['experiment']['models'][NEW] = {'metric': 'count-only'}
    for row in source['monthly_training']:
        row['models'][NEW] = {'version_artifact': {'path': row['month'] + '/count', 'sha256': 'new'},
                              'training_split': {'train': row['month']}}
    specification = {key: deepcopy(source[key]) for key in ('experiment', 'daily_cap', 'reg_lambda',
        'pair_method', 'added_features', 'num_pair_per_sample', 'only_changed_component',
        'candidate_order', 'matched_candidate_order', 'new_candidate_order')}
    return source, previous, specification


class HandoverCountDiagnosisTests(unittest.TestCase):
    def test_both_pairwise_summaries_use_actual_candidates_and_feature_changes(self):
        frame, scores, known = example()
        result = diagnose_phase(frame, scores, known)
        self.assertEqual(set(result['comparisons']), set(COMPARISONS))
        baseline = result['comparisons']['baseline101_to_count102']
        extended = result['comparisons']['handover104_to_count102']
        self.assertEqual(baseline['comparison']['added_features'], ADDED_FEATURES[:1])
        self.assertEqual(extended['comparison']['added_features'], [])
        self.assertEqual(extended['comparison']['removed_features'], ADDED_FEATURES[1:])
        self.assertEqual([baseline['comparison'][key] for key in ('old_feature_count', 'new_feature_count')], [101, 102])
        self.assertEqual(set(extended['volume_context']), {HANDOVER104, NEW})
        self.assertEqual(set(extended['days'][0]['models']), {HANDOVER104, NEW})
        self.assertEqual([baseline['summary'][key] for key in ('recovered_delays', 'lost_delays', 'net_TP')], [2, 0, 2])
        self.assertEqual([extended['summary'][key] for key in ('recovered_delays', 'lost_delays', 'net_TP')], [2, 0, 2])

    def test_local_aliases_never_mutate_imported_candidate_constants(self):
        frame, scores, known = example()
        before = (history.BASELINE, history.NEW, history.MATCHED)
        pair_diagnostics(frame, scores, known, HANDOVER104, NEW, keep_cross=True)
        self.assertEqual((history.BASELINE, history.NEW, history.MATCHED), before)

    def test_declared_support_promise_cells_and_volumes_partition_with_empty_groups(self):
        frame, scores, known = example()
        frame[ADDED_FEATURES[0]] = 0
        frame[ADDED_FEATURES[1]] = np.nan
        frame[ADDED_FEATURES[2]] = np.nan
        result = pair_diagnostics(frame, scores, known, BASELINE, NEW)
        for dimension in ('history_support_bins', 'intersection_cells', 'volume_bins', 'promise_days', 'routes', 'days'):
            for field in COUNT_FIELDS:
                self.assertEqual(sum(row[field] for row in result[dimension]), result['summary'][field], (dimension, field))
        self.assertEqual(len(result['history_support_bins']), 3)
        self.assertEqual(len(result['intersection_cells']), 12)
        self.assertEqual(len(result['promise_days']), len(PROMISE_BINS))
        self.assertEqual(len(result['volume_bins']), 4)
        for row in result['history_support_bins'][1:]:
            self.assertEqual(row['full_batch_rows'], 0)
            self.assertIsNone(row['new_recall'])
            self.assertNotIn('capacity', row)

    def test_support_keeps_original_daily_allocation_without_subgroup_cap(self):
        frame, scores, known = example()
        frame[ADDED_FEATURES[0]] = 5
        frame[ADDED_FEATURES[1]] = 24.
        frame[ADDED_FEATURES[2]] = 48.
        frame.loc[[0, 2, 4, 8], ADDED_FEATURES] = [1, np.nan, np.nan]
        result = pair_diagnostics(frame, scores, known, BASELINE, NEW)
        sparse = result['history_support_bins'][1]
        self.assertEqual(sparse['full_batch_rows'], 4)
        self.assertEqual(sparse['new_alerts'], 4)
        self.assertNotIn('capacity', sparse)

    def test_unknown_outcomes_compete_before_mask_without_being_read(self):
        frame, scores, known = example()
        known[[0, 2, 6]] = False
        result = diagnose_phase(frame, scores, known, keep_cross=True)
        frame['delayed'] = frame.delayed.astype(object)
        frame.loc[~known, 'delayed'] = 'future forbidden'
        self.assertEqual(diagnose_phase(frame, scores, known, keep_cross=True), result)
        self.assertEqual(result['comparisons']['baseline101_to_count102']['summary']['old_unknown_alerts'], 2)

    def test_fixed_regression_cohorts_do_not_change_when_102_scores_change(self):
        frame, scores, known = example()
        first = regression_cohorts(frame, scores, known)['cohorts']
        changed = {**scores, NEW: selected_scores(len(frame), [10, 11, 12, 13])}
        second = regression_cohorts(frame, changed, known)['cohorts']
        for name in first:
            self.assertEqual(first[name]['cohort_rows'], second[name]['cohort_rows'])
            for candidate in (BASELINE, HANDOVER104):
                self.assertEqual(first[name]['models'][candidate], second[name]['models'][candidate])
        self.assertEqual(first['all_original_lost_delays']['count102_recovered'], 1)
        self.assertEqual(second['all_original_lost_delays']['count102_still_missed'], 1)

    def test_regression_group_boundaries_and_all_route_rows_are_retained(self):
        frame, scores, known = example()
        frame.loc[2, 'estimated_delivery_days'] = 30.
        frame.loc[2, 'state_route'] = 'SP->MG'
        row = regression_cohorts(frame, scores, known)['cohorts']['sparse_short_non_SP_RJ']
        self.assertEqual(row['cohort_rows'], 1)
        self.assertEqual(row['count102_recovered'], 1)
        self.assertEqual({r['state_route'] for r in row['routes']}, set(frame.state_route))
        frame.loc[2, 'estimated_delivery_days'] = 30.25
        frame.loc[2, 'state_route'] = 'SP->RJ'
        frame.loc[2, ADDED_FEATURES] = [5, 24., 48.]
        row = regression_cohorts(frame, scores, known)['cohorts']['supported_long_SP_RJ']
        self.assertEqual(row['cohort_rows'], 1)
        self.assertEqual(row['models'][NEW]['rank_bins']['<=10%'], 1)
        self.assertLessEqual(row['models'][NEW]['off_top10_gap_slots']['maximum'], 0)

    def test_focus_detail_uses_same_summary_and_actual_ids(self):
        frame, scores, known = example()
        result = pair_diagnostics(frame, scores, known, HANDOVER104, NEW, keep_cross=True)
        for field in COUNT_FIELDS:
            self.assertEqual(result['summary'][field], result['sparse_intersection_detail']['summary'][field])
        self.assertIn('route_day_allocations', result)
        self.assertIn('route_by_promise', result)
        self.assertEqual(len(result['sparse_intersection_detail']['intersection_cells']), 12)

    def test_complete_tied_tiny_day_and_shuffling_keep_exact_floor_budget(self):
        frame, _, known = example(9)
        scores = {candidate: np.full(9, .5) for candidate in MATCHED}
        report = diagnose_phase(frame, scores, known)
        for contrast in report['comparisons'].values():
            self.assertEqual(contrast['summary']['new_alerts'], 0)
            self.assertEqual(contrast['summary']['old_alerts'], 0)
        shuffled = frame.sample(frac=1, random_state=2).reset_index(drop=True)
        self.assertEqual(diagnose_phase(shuffled, scores, known), report)

    def test_three_complete_ledger_cohorts_exactly_reconcile_metrics_and_unknowns(self):
        frame, scores, known = example()
        frame.loc[0, 'label_available_time'] = pd.Timestamp('2017-12-01')
        known[0] = False
        ledger, expected = ledger_fixture(frame, scores, known)
        actual_known, actual_scores, context = verify_phase_ledger(frame, ledger, '2017-12-01', 'validation', expected, '2017-07')
        np.testing.assert_array_equal(actual_known, known)
        self.assertEqual(set(context), set(MATCHED))
        for candidate in MATCHED:
            np.testing.assert_array_equal(actual_scores[candidate], scores[candidate])

    def test_evaluation_masks_not_presented_as_available_at_selection(self):
        frame, scores, known = example()
        ledger, expected = ledger_fixture(frame, scores, known, role='evaluation')
        _, _, context = verify_phase_ledger(frame, ledger, '2017-12-01', 'evaluation', expected, '2017-07')
        self.assertEqual(set(context), set(MATCHED))
        ledger.loc[0, 'known_at_selection'] = True
        with self.assertRaises(AssertionError):
            verify_phase_ledger(frame, ledger, '2017-12-01', 'evaluation', expected, '2017-07')

    def test_missing_duplicated_wrong_decision_and_invalid_score_ledger_fail(self):
        frame, scores, known = example()
        ledger, expected = ledger_fixture(frame, scores, known)
        cases = [ledger.iloc[:-1], pd.concat([ledger.iloc[:-1], ledger.iloc[:1]]),
                 ledger.assign(delay_score=np.inf), ledger.assign(predicted_delayed=0)]
        for changed in cases:
            with self.subTest(shape=changed.shape), self.assertRaises((ValueError, AssertionError)):
                verify_phase_ledger(frame, changed, '2017-12-01', 'validation', expected, '2017-07')

    def test_source_contract_accepts_only_count_extension_and_frozen_77_metrics(self):
        source, previous, spec = source_fixture()
        validate_source_contract(source, previous, spec)
        cases = []
        changed = deepcopy(source); changed['folds'][0]['experiment']['models'][BASELINE]['metric'] = 'changed'; cases.append(changed)
        changed = deepcopy(source); changed['candidate_specifications'][NEW]['numeric_features'].append(ADDED_FEATURES[1]); cases.append(changed)
        changed = deepcopy(source); changed['candidate_specifications'][NEW]['classifier_parameters']['reg_lambda'] = 10; cases.append(changed)
        changed = deepcopy(source); changed['monthly_training'][0]['models'][HANDOVER104]['version_artifact']['sha256'] = 'changed'; cases.append(changed)
        changed = deepcopy(source); changed['feature_dataset']['sha256'] = 'changed'; cases.append(changed)
        changed = deepcopy(source); changed['folds'][0]['schedule'] = {}; cases.append(changed)
        changed = deepcopy(source); changed['source_features'] = previous['source_features']; cases.append(changed)
        for altered in cases:
            with self.subTest(keys=altered.keys()), self.assertRaises(ValueError):
                validate_source_contract(altered, previous, spec)

    def test_source_rejects_another_experiment_or_posthoc_specification(self):
        source, previous, spec = source_fixture()
        for altered in ({**source, 'experiment': 'another'}, {**source, 'only_changed_component': 'quantiles'},
                        {**source, 'added_features': ADDED_FEATURES}, {**source, 'num_pair_per_sample': 20}):
            with self.assertRaises(ValueError):
                validate_source_contract(altered, previous, spec)
        with self.assertRaises(ValueError):
            validate_source_contract(source, previous, {**spec, 'reg_lambda': 10})

    def test_malformed_groups_scores_and_known_masks_are_rejected(self):
        frame, scores, known = example()
        for column, value in ((ADDED_FEATURES[0], .5), ('estimated_delivery_days', np.nan), ('delayed', 'bad')):
            changed = frame.copy(); changed[column] = changed[column].astype(object); changed.loc[0, column] = value
            with self.subTest(column=column), self.assertRaises(ValueError):
                diagnose_phase(changed, scores, known)
        with self.assertRaises(ValueError):
            diagnose_phase(frame, {BASELINE: scores[BASELINE]}, known)
        with self.assertRaises(ValueError):
            diagnose_phase(frame, scores, known.astype(int))

    def test_only_aggregate_finite_json_and_safe_report_destination(self):
        frame, scores, known = example()
        encoded = json.dumps(diagnose_phase(frame, scores, known, keep_cross=True), allow_nan=False)
        for private in ('private-order-', 'delay_score', 'donor_order'):
            self.assertNotIn(private, encoded)
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / 'source.json'
            source.write_text('{}', encoding='utf-8')
            output = Path(directory) / 'own.json'
            with self.assertRaises(ValueError):
                validate_output(source, source)
            output.write_text('{}', encoding='utf-8')
            with self.assertRaises(ValueError):
                validate_output(output, source)
            output.write_text(json.dumps({'analysis': ANALYSIS, 'format_version': 1}), encoding='utf-8')
            self.assertEqual(validate_output(output, source), output.resolve())


if __name__ == '__main__':
    unittest.main()
