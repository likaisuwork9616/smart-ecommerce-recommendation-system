"""Availability, volume conservation and frozen-source guards for handover feature diagnosis."""
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
from scripts.diagnose_handover_history import (
    ADDED_FEATURES, ANALYSIS, BASELINE, FOCUS_PHASES, MATCHED, MONTHS, NEW, diagnose_phase, history_support,
    compatibility_checks_from_phases,
    validate_output, validate_source_contract, verify_phase_ledger,
)
from tests.test_delay_route_exchanges import cohort, selected_scores
from tests.test_diagnose_rank_batch_size import batches


def example():
    frame = cohort(40)
    frame[ADDED_FEATURES[0]] = np.resize([0, 4, 5, 10], len(frame))
    frame[ADDED_FEATURES[1]] = np.where(frame[ADDED_FEATURES[0]].ge(5), 24., np.nan)
    frame[ADDED_FEATURES[2]] = np.where(frame[ADDED_FEATURES[0]].ge(5), 48., np.nan)
    frame['delayed'] = 0
    frame.loc[[2, 4, 8], 'delayed'] = 1
    frame['estimated_delivery_days'] = np.resize([10., 25.], len(frame))
    frame['label_available_time'] = pd.Timestamp('2017-08-01')
    frame.loc[0, 'label_available_time'] = pd.Timestamp('2017-12-01')
    scores = {BASELINE: selected_scores(40, [0, 1, 2, 3]),
              NEW: selected_scores(40, [0, 1, 4, 6])}
    return frame, scores, np.arange(40) != 0


def ledger_fixture(frame, scores, known, role='validation'):
    records, expected = [], {}
    for candidate in MATCHED:
        alert = apply_alert_policy(frame, scores[candidate], 0., .1)
        outcome = np.full(len(frame), np.nan)
        outcome[known] = frame.loc[known, 'delayed'].to_numpy()
        records.append(pd.DataFrame({
            'order_id': frame.order_id, 'prediction_time': frame.prediction_time,
            'candidate': candidate, 'model_version': '2017-07', 'role': role,
            'known_at_selection': known if role == 'validation' else np.zeros(len(frame), bool),
            'outcome_for_metrics': outcome, 'delay_score': scores[candidate],
            'predicted_delayed': alert.astype(int),
        }))
        metrics = alert_metrics(frame.loc[known, 'delayed'].to_numpy(), scores[candidate][known], alert[known])
        batch = batch_audit(frame, alert, .1, known)
        expected[candidate] = {'validation_by_month': {'2017-07': {
            'known_outcome_metrics': metrics, 'full_batch': batch}},
            'development_evaluation': metrics, 'evaluation_batch': batch}
    return pd.concat(records, ignore_index=True), expected


def source_fixture():
    order = [BASELINE, *(f'previous_{i}' for i in range(75))]
    previous = {'status': 'ok', 'experiment': 'rank_pair_method', 'candidate_order': order,
        'matched_candidate_order': [BASELINE],
        'source_candidate_versions': {'path': 'old.json', 'sha256': 'old'},
        'feature_dataset': {'path': 'features.csv', 'sha256': 'features'},
        'source_files': {'raw': 'frozen'}, 'folds': [], 'monthly_training': []}
    for name in ('2017-12', '2018-02', '2018-04'):
        previous['folds'].append({'name': name, 'schedule': {'cutoff': name},
            'validation_maturity': {'unchanged': True}, 'order_id_fingerprints': {'id': name},
            'experiment': {'models': {c: {'metric': c} for c in order}}})
    for month in MONTHS:
        previous['monthly_training'].append({'month': month, 'split': {'unchanged': month},
            'models': {BASELINE: {'version_artifact': {'path': month, 'sha256': 'frozen'},
                                  'training_split': {'train': month}}}})
    source = deepcopy(previous)
    source.update(experiment='handover_history_features', daily_cap=.1, reg_lambda=100.,
        pair_method='topk', added_features=list(ADDED_FEATURES), num_pair_per_sample=10,
        only_changed_component='three_seller_handover_features', candidate_order=[*order, NEW],
        matched_candidate_order=list(MATCHED), new_candidate_order=[NEW])
    source['source_features'] = deepcopy(source['feature_dataset'])
    source['feature_dataset'] = {'path': 'newfeatures.csv', 'sha256': 'newfeatures'}
    source['candidate_specifications'] = {
        BASELINE: {'numeric_features': [f'feature_{i}' for i in range(93)],
                   'categorical_features': [f'category_{i}' for i in range(8)],
                   'classifier_parameters': {'reg_lambda': 100., 'lambdarank_pair_method': 'topk'}},
        NEW: {'numeric_features': [*(f'feature_{i}' for i in range(93)), *ADDED_FEATURES],
              'categorical_features': [f'category_{i}' for i in range(8)],
              'classifier_parameters': {'reg_lambda': 100., 'lambdarank_pair_method': 'topk'}}}
    for fold in source['folds']:
        fold['experiment']['models'][NEW] = {'metric': 'mean'}
    for row in source['monthly_training']:
        row['models'][NEW] = {'version_artifact': {'path': row['month'] + '/mean', 'sha256': 'new'},
                              'training_split': {'train': row['month']}}
    specification = {k: deepcopy(source[k]) for k in ('experiment', 'daily_cap', 'reg_lambda',
        'pair_method', 'added_features', 'num_pair_per_sample', 'only_changed_component', 'candidate_order',
        'matched_candidate_order', 'new_candidate_order')}
    return source, previous, specification


class HandoverHistoryDiagnosisTests(unittest.TestCase):
    def test_support_threshold_and_nonnegative_ordered_duration_contract(self):
        frame, _, _ = example()
        counts, enough = history_support(frame)
        np.testing.assert_array_equal(enough[:4], [False, False, True, True])
        np.testing.assert_array_equal(counts[:4], [0, 4, 5, 10])
        for column in ADDED_FEATURES:
            with self.subTest(missing=column), self.assertRaises(ValueError):
                history_support(frame.drop(columns=column))

    def test_malformed_support_or_fabricated_quantiles_fail(self):
        frame, _, _ = example()
        cases = [(ADDED_FEATURES[0], 0, -1), (ADDED_FEATURES[0], 0, .5),
                 (ADDED_FEATURES[0], 0, np.inf), (ADDED_FEATURES[0], 0, np.nan),
                 (ADDED_FEATURES[1], 1, 24.), (ADDED_FEATURES[2], 1, 48.),
                 (ADDED_FEATURES[1], 2, np.nan), (ADDED_FEATURES[2], 2, np.inf),
                 (ADDED_FEATURES[1], 2, -1.), (ADDED_FEATURES[2], 2, 10.)]
        for column, row, value in cases:
            changed = frame.copy()
            changed[column] = changed[column].astype(float)
            changed.loc[row, column] = value
            with self.subTest(column=column, row=row, value=value), self.assertRaises(ValueError):
                history_support(changed)

    def test_support_partition_preserves_cross_group_slots_without_rebudgeting(self):
        frame, scores, known = example()
        report = diagnose_phase(frame, scores, known)['handover_features']
        rows = report['feature_support_bins']
        self.assertEqual([r['support_bin'] for r in rows], ['history_lt5', 'history_ge5'])
        self.assertEqual([r['full_batch_rows'] for r in rows], [20, 20])
        self.assertEqual([r['old_alerts'] for r in rows], [2, 2])
        # The first subgroup gets three new alerts, above its fictitious 20*10% cap.
        self.assertEqual([r['new_alerts'] for r in rows], [3, 1])
        self.assertEqual([r['net_TP'] for r in rows], [1, -1])
        self.assertEqual([r['net_alerts'] for r in rows], [1, -1])
        for key in COUNT_FIELDS:
            self.assertEqual(sum(r[key] for r in rows), report['summary'][key])
        self.assertTrue(all('capacity' not in r for r in rows))

    def test_empty_support_group_has_no_invented_statistics_or_recall(self):
        frame, scores, known = example()
        frame[ADDED_FEATURES[0]] = 0
        frame[ADDED_FEATURES[1]] = np.nan
        frame[ADDED_FEATURES[2]] = np.nan
        row = diagnose_phase(frame, scores, known)['handover_features']['feature_support_bins'][1]
        self.assertEqual(row['full_batch_rows'], 0)
        self.assertIsNone(row['event_count_minimum'])
        self.assertIsNone(row['event_count_median'])
        self.assertIsNone(row['event_count_maximum'])
        self.assertIsNone(row['old_recall'])
        self.assertIsNone(row['new_recall'])

    def test_descriptive_compatibility_never_compensates_across_months(self):
        def context(tp):
            return {'known_outcome_metrics': {'confusion_matrix': [[1, 1], [100 - tp, tp]]}}
        phases = {phase: {'context': {BASELINE: context(old), NEW: context(new)}}
                  for phase, old, new in zip(FOCUS_PHASES, (21, 52, 65), (25, 51, 70), strict=True)}
        targets = {'reference_candidate': BASELINE, 'used_for_selection': False,
            'historical_outcome_cutoff': '2017-12-01T00:00:00', 'july_historical_TP': 21,
            'september_historical_TP': 52, 'december_development_TP': 65}
        checks = compatibility_checks_from_phases(phases, targets)
        self.assertTrue(checks[0]['all_three_descriptive_periods_not_worse'])
        self.assertFalse(checks[1]['both_historical_months_not_worse'])
        self.assertFalse(checks[1]['all_three_descriptive_periods_not_worse'])
        self.assertEqual(checks[1]['july_difference'], 4)
        self.assertEqual(checks[1]['september_difference'], -1)
        self.assertTrue(all(row['used_for_selection'] is False for row in checks))

    def test_compatibility_rejects_changed_reference_or_unavailable_phase(self):
        phases = {phase: {'context': {candidate: {'known_outcome_metrics': {'confusion_matrix': [[1, 1], [1, 1]]}}
                                      for candidate in MATCHED}} for phase in FOCUS_PHASES}
        targets = {'reference_candidate': BASELINE, 'used_for_selection': False,
            'historical_outcome_cutoff': '2017-12-01T00:00:00', 'july_historical_TP': 1,
            'september_historical_TP': 1, 'december_development_TP': 1}
        for altered in ({**targets, 'used_for_selection': True}, {**targets, 'reference_candidate': NEW},
                        {**targets, 'july_historical_TP': 2},
                        {**targets, 'historical_outcome_cutoff': '2018-01-01T00:00:00'}):
            with self.assertRaises(ValueError):
                compatibility_checks_from_phases(phases, altered)
        incomplete = dict(phases)
        incomplete.pop(FOCUS_PHASES[-1])
        with self.assertRaises(ValueError):
            compatibility_checks_from_phases(incomplete, targets)

    def test_matched_feature_semantics_and_changed_delay_ranks(self):
        frame, scores, known = example()
        result = diagnose_phase(frame, scores, known, keep_cross=True)
        contrast = result['handover_features']
        self.assertEqual(contrast['comparison']['old_feature_count'], 101)
        self.assertEqual(contrast['comparison']['new_feature_count'], 104)
        self.assertEqual(contrast['comparison']['added_features'], list(ADDED_FEATURES))
        self.assertEqual(contrast['comparison']['pair_method'], 'topk')
        self.assertEqual(contrast['comparison']['fixed_num_pair_per_sample'], 10)
        self.assertEqual(contrast['comparison']['fixed_l2'], 100.)
        self.assertEqual([contrast['summary'][k] for k in
                         ('old_alerts', 'new_alerts', 'recovered_delays', 'lost_delays', 'net_TP')], [4, 4, 1, 1, 0])
        self.assertIn('route_day_allocations', contrast)
        self.assertIn('route_by_promise', contrast)
        volume = contrast['volume_bins'][0]
        self.assertEqual(volume['changed_delay_ranks']['recovered_delays']['rows'], 1)
        self.assertEqual(volume['changed_delay_ranks']['lost_delays']['rows'], 1)
        self.assertEqual(volume['changed_delay_ranks']['recovered_delays']['new_relative_bins']['<=10%'], 1)
        self.assertNotIn('private-order-', json.dumps(result))

    def test_unknown_competes_before_mask_and_corruption_cannot_change_report(self):
        frame, scores, known = example()
        actual = diagnose_phase(frame, scores, known, keep_cross=True)
        self.assertEqual(actual['volume_context'][BASELINE]['unknown_alerts'], 1)
        self.assertEqual(actual['volume_context'][BASELINE]['known_alerts'], 3)
        changed = frame.copy()
        changed['delayed'] = changed.delayed.astype(object)
        changed.loc[~known, 'delayed'] = 'future outcome forbidden'
        self.assertEqual(diagnose_phase(changed, scores, known, keep_cross=True), actual)

    def test_volume_partitions_use_full_days_and_preserve_unknown_counts(self):
        frame = batches([9, 99, 100, 199, 200, 399, 400])
        n = len(frame)
        frame[ADDED_FEATURES[0]] = 5
        frame[ADDED_FEATURES[1]] = 24.
        frame[ADDED_FEATURES[2]] = 48.
        scores = {BASELINE: np.resize(np.linspace(0, 1, 400), n),
                  NEW: np.resize(np.linspace(1, 0, 400), n)}
        known = np.arange(n) % 4 != 0
        frame.loc[known & (np.arange(n) % 7 == 0), 'delayed'] = 1
        report = diagnose_phase(frame, scores, known)['handover_features']
        self.assertEqual([row['days'] for row in report['volume_bins']], [2, 2, 2, 1])
        self.assertEqual([row['capacity'] for row in report['volume_bins']], [9, 29, 59, 40])
        for key in COUNT_FIELDS:
            self.assertEqual(sum(row[key] for row in report['volume_bins']), report['summary'][key])
        for row in report['volume_bins']:
            for dimension in ('routes', 'promise_days'):
                for key in COUNT_FIELDS:
                    self.assertEqual(sum(v[key] for v in row[dimension]), row[key])
            self.assertEqual(row['old_alerts'], row['capacity'])
            self.assertEqual(row['new_alerts'], row['capacity'])

    def test_ties_use_ids_and_small_days_receive_no_extra_alerts(self):
        frame = batches([9, 10])
        frame[ADDED_FEATURES[0]] = 0
        frame[ADDED_FEATURES[1]] = np.nan
        frame[ADDED_FEATURES[2]] = np.nan
        scores = {candidate: np.full(len(frame), .5) for candidate in MATCHED}
        result = diagnose_phase(frame, scores, np.ones(len(frame), bool))['handover_features']
        self.assertEqual([row['old_alerts'] for row in result['days']], [0, 1])
        self.assertEqual(result['summary']['dropped_alerts'], 0)
        self.assertEqual(result['summary']['added_alerts'], 0)
        shuffled = frame.sample(frac=1, random_state=7).reset_index(drop=True)
        other = diagnose_phase(shuffled, scores, np.ones(len(frame), bool))['handover_features']
        self.assertEqual(other, result)

    def test_empty_volume_bins_have_zero_counts_and_no_recall_claim(self):
        frame, scores, known = example()
        result = diagnose_phase(frame, scores, known)['handover_features']
        self.assertNotIn('route_day_allocations', result)
        self.assertNotIn('route_by_promise', result)
        for row in result['volume_bins'][1:]:
            self.assertEqual(row['full_batch_rows'], 0)
            self.assertEqual(row['capacity'], 0)
            self.assertIsNone(row['old_recall'])
            self.assertIsNone(row['new_recall'])
            self.assertEqual(row['changed_delay_ranks']['lost_delays']['rows'], 0)

    def test_missing_scores_bad_masks_or_observed_labels_fail(self):
        frame, scores, known = example()
        for candidate in MATCHED:
            missing = dict(scores)
            missing.pop(candidate)
            with self.assertRaises(ValueError):
                diagnose_phase(frame, missing, known)
        for bad in (known.astype(int), known[:-1], known[:, None]):
            with self.assertRaises(ValueError):
                diagnose_phase(frame, scores, bad)
        frame.loc[1, 'delayed'] = 2
        with self.assertRaises(ValueError):
            diagnose_phase(frame, scores, known)

    def test_contract_keeps_all_76_previous_metrics_and_feature_settings(self):
        source, previous, spec = source_fixture()
        validate_source_contract(source, previous, spec)
        changes = [lambda x: x.update(reg_lambda=10.), lambda x: x.update(num_pair_per_sample=20),
            lambda x: x.update(pair_method='mean'),
            lambda x: x.update(added_features=list(reversed(ADDED_FEATURES))),
            lambda x: x.update(only_changed_component='reg_lambda'),
            lambda x: x['folds'][0]['experiment']['models'][BASELINE].update(metric='changed'),
            lambda x: x['folds'][0]['schedule'].update(cutoff='changed'),
            lambda x: x['monthly_training'][0]['models'][BASELINE]['version_artifact'].update(sha256='changed'),
            lambda x: x['monthly_training'][0]['models'][BASELINE]['training_split'].update(train='changed'),
            lambda x: x['monthly_training'].pop(),
            lambda x: x['source_candidate_versions'].update(sha256='changed'),
            lambda x: x['source_features'].update(sha256='changed'),
            lambda x: x['candidate_specifications'][NEW]['numeric_features'].pop(),
            lambda x: x['candidate_specifications'][NEW]['categorical_features'].reverse(),
            lambda x: x['candidate_specifications'][NEW]['classifier_parameters'].update(reg_lambda=10.)]
        for change in changes:
            mutated = deepcopy(source)
            change(mutated)
            with self.subTest(change=change), self.assertRaises(ValueError):
                validate_source_contract(mutated, previous, spec)
        modified_spec = deepcopy(spec)
        modified_spec['daily_cap'] = .2
        with self.assertRaises(ValueError):
            validate_source_contract(source, previous, modified_spec)

    def test_ledger_known_cutoff_is_strict_and_unknown_scores_still_compete(self):
        frame, scores, known = example()
        ledger, expected = ledger_fixture(frame, scores, known)
        found, actual_scores, context = verify_phase_ledger(frame, ledger, '2017-12-01', 'validation', expected, '2017-07')
        np.testing.assert_array_equal(found, known)
        for candidate in MATCHED:
            np.testing.assert_array_equal(actual_scores[candidate], scores[candidate])
            self.assertEqual(context[candidate]['full_batch']['alerts'], 4)
            self.assertEqual(context[candidate]['full_batch']['unknown_outcome_alerts'], 1)
        changed = frame.copy()
        changed['delayed'] = changed.delayed.astype(object)
        changed.loc[~known, 'delayed'] = 'forbidden'
        self.assertEqual(verify_phase_ledger(changed, ledger, '2017-12-01', 'validation', expected, '2017-07')[2], context)

    def test_ledger_rejects_future_labels_incomplete_batch_and_wrong_phase(self):
        frame, scores, known = example()
        ledger, expected = ledger_fixture(frame, scores, known)
        cases = [ledger.iloc[1:], ledger.assign(known_at_selection=True),
            ledger.assign(outcome_for_metrics=ledger.outcome_for_metrics.fillna(1)),
            ledger.assign(role='evaluation'), ledger.assign(model_version='2017-09'),
            ledger.assign(delay_score=np.nan), ledger.assign(predicted_delayed=2)]
        for bad in cases:
            with self.subTest(rows=len(bad)), self.assertRaises((ValueError, AssertionError)):
                verify_phase_ledger(frame, bad, '2017-12-01', 'validation', expected, '2017-07')
        modified = deepcopy(expected)
        modified[BASELINE]['validation_by_month']['2017-07']['known_outcome_metrics']['precision'] = .999
        with self.assertRaises(ValueError):
            verify_phase_ledger(frame, ledger, '2017-12-01', 'validation', modified, '2017-07')

    def test_development_cannot_claim_labels_available_for_selection(self):
        frame, scores, _ = example()
        known = np.ones(len(frame), bool)
        ledger, expected = ledger_fixture(frame, scores, known, role='evaluation')
        actual_known, _, _ = verify_phase_ledger(frame, ledger, '2017-07-01', 'evaluation', expected, '2017-07')
        self.assertTrue(actual_known.all())
        with self.assertRaises(AssertionError):
            verify_phase_ledger(frame, ledger.assign(known_at_selection=True), '2017-07-01', 'evaluation', expected, '2017-07')

    def test_output_guard_preserves_sources_unrelated_and_malformed_reports(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source, other, malformed, own = [root / name for name in ('source.json', 'other.json', 'bad.json', 'own.json')]
            source.write_text('{"status":"ok"}', encoding='utf-8')
            other.write_text('{"analysis":"another"}', encoding='utf-8')
            malformed.write_text('invalid JSON', encoding='utf-8')
            own.write_text(json.dumps({'analysis': ANALYSIS, 'format_version': 1}), encoding='utf-8')
            for output in (source, other, malformed, root / 'new.csv'):
                with self.subTest(output=output), self.assertRaises(ValueError):
                    validate_output(output, source)
            self.assertEqual(validate_output(own, source), own.resolve())
            self.assertEqual(validate_output(root / 'new.json', source), (root / 'new.json').resolve())
            self.assertEqual(source.read_text(encoding='utf-8'), '{"status":"ok"}')


if __name__ == '__main__':
    unittest.main()
