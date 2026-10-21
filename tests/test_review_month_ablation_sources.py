"""Synthetic source/roster handoff tests; no models, features or performance."""
from contextlib import contextmanager
from copy import deepcopy
from pathlib import Path
import shutil
import unittest
from unittest.mock import patch
from uuid import uuid4

import numpy as np
import pandas as pd

from scripts import review_month_ablation_sources as source
from tests.test_review_baseline_sources import bundle as synthetic_bundle


@contextmanager
def temporary_root():
    parent = (source.ROOT / '.runtime' / 'month_ablation_source_tests').resolve()
    if not parent.is_relative_to(source.ROOT.resolve()):
        raise RuntimeError('Temporary root must stay inside the workspace')
    parent.mkdir(parents=True, exist_ok=True)
    root = parent / uuid4().hex
    root.mkdir()
    try:
        yield root
    finally:
        if root.resolve().parent != parent:
            raise RuntimeError('Unexpected cleanup path')
        shutil.rmtree(root)


def write_json(root, path, value):
    target = root / path
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(source.files.json_bytes(value))
    return source.files.descriptor(target, root)


def load_fixture(root):
    base = synthetic_bundle(root)
    ledgers = {name: [] for name in source.CONTROL_SCORE_FILES}
    folds = []
    for fold in source.control_training.FOLDS:
        folds.append({'outer_fold': fold, 'selection': {'selected_C': .1},
                      'inner_candidates': [{'C': C} for C in (.1, 1., 10.)]})
        for role, train_role, filename in (
                ('inner_validation', 'inner_train_pool', 'inner_scores.csv'),
                ('outer_evaluation', 'outer_train_pool', 'outer_scores.csv')):
            truth = base.role_block(fold, role)
            train = base.role_block(fold, train_role)
            usable = train.role_label_usable
            prior = float(train.loc[usable, 'y'].eq(1).sum() / usable.sum())
            plans = [('constant_reference', None)] + (
                [('logistic_candidate', C) for C in (.1, 1., 10.)] if role == 'inner_validation'
                else [('logistic_selected', .1)])
            for model, C in plans:
                frame = truth.copy()
                frame['model'] = model
                frame['C'] = pd.Series([C] * len(frame), dtype='Float64')
                frame['probability_low_1_2'] = np.full(len(frame), prior if C is None else .4, dtype='float64')
                ledgers[filename].append(frame.loc[:, source.control_training.SCORE_COLUMNS])
    private = []
    for name in ledgers:
        ledgers[name] = pd.concat(ledgers[name], ignore_index=True)
        path = root / source.control_training.PRIVATE / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(source.control_training._csv_bytes(ledgers[name]))
        private.append(source.files.descriptor(path, root))
    report = {'status': 'completed_real_offline_minimal_baseline',
              'results': {'outer_folds': folds, 'execution': {
                  'score_rows_across_blocks': sum(len(frame) for frame in ledgers.values())}}}
    public = [write_json(root, source.control_training.REPORT, report)]
    method_spec = {'protocol': {'features': {'primary_order': list(source.treatment_pipeline.PRIMARY)}},
                   'synthetic': True}
    return base, method_spec, public, private, report, ledgers


@contextmanager
def mocked_inputs(root, fixture):
    base, method_spec, public, private, _, _ = fixture
    with (patch.object(source, '_frozen_provenance', return_value=(method_spec, public, private)),
          patch.object(source.baseline_sources, 'load_verified_sources', return_value=base)):
        yield


class ExecutionGuardTests(unittest.TestCase):
    def test_feature_builders_are_blocked_before_values_exist(self):
        for module in (source.control_pipeline, source.treatment_pipeline):
            with self.assertRaises(RuntimeError):
                with source.forbid_model_execution() as counters:
                    module.build_primary_features(None)
            self.assertEqual(counters['forbidden_calls'], 1)

    def test_pipeline_construction_fit_transform_prediction_are_blocked(self):
        for cls in (source.control_pipeline.GuardedReviewBaseline,
                    source.treatment_pipeline.GuardedReviewMonthAblation):
            for name in ('__init__', 'fit_orders', 'transform_orders', 'predict_orders'):
                with self.subTest(cls=cls.__name__, name=name), self.assertRaises(RuntimeError):
                    with source.forbid_model_execution():
                        getattr(cls, name)(None)

    def test_sklearn_constructors_and_inherited_fit_transform_are_blocked(self):
        for cls in (source.control_pipeline.LogisticRegression, source.control_pipeline.StandardScaler,
                    source.control_pipeline.OneHotEncoder):
            for name in ('__init__', 'fit'):
                with self.subTest(cls=cls.__name__, name=name), self.assertRaises(RuntimeError):
                    with source.forbid_model_execution():
                        getattr(cls, name)(None)
        for cls in (source.control_pipeline.StandardScaler, source.control_pipeline.OneHotEncoder):
            with self.assertRaises(RuntimeError):
                with source.forbid_model_execution():
                    cls.fit_transform(None)

    def test_metrics_selection_and_control_training_entry_are_blocked(self):
        for module, name in [(source.evaluation, 'evaluate_role'), (source.evaluation, 'select_candidate'),
                             (source.evaluation, 'macro_average_precision'),
                             (source.control_training, 'execute_training'),
                             (source.control_training, '_execute_training')]:
            with self.assertRaises(RuntimeError):
                with source.forbid_model_execution():
                    getattr(module, name)(None)

    def test_swallowed_forbidden_call_still_fails_context_exit(self):
        with self.assertRaisesRegex(RuntimeError, 'attempted'):
            with source.forbid_model_execution() as counters:
                try:
                    source.evaluation.evaluate_role(None)
                except RuntimeError:
                    pass
        self.assertEqual(counters['forbidden_calls'], 1)

    def test_nested_guard_restores_original_functions_without_execution(self):
        original = source.treatment_pipeline.build_primary_features
        with source.forbid_model_execution() as outer:
            outer_function = source.treatment_pipeline.build_primary_features
            with source.forbid_model_execution() as inner:
                self.assertIsNot(source.treatment_pipeline.build_primary_features, outer_function)
            self.assertIs(source.treatment_pipeline.build_primary_features, outer_function)
        self.assertIs(source.treatment_pipeline.build_primary_features, original)
        self.assertEqual(outer['forbidden_calls'], 0)
        self.assertEqual(inner['forbidden_calls'], 0)


class PreparedSourceTests(unittest.TestCase):
    def test_complete_roles_and_all_frozen_control_blocks_load_without_execution(self):
        with temporary_root() as root:
            fixture = load_fixture(root)
            with mocked_inputs(root, fixture):
                prepared = source.load_prepared_sources(root)
            self.assertEqual(prepared.summary['source_bundle']['role_blocks'], 12)
            self.assertEqual(prepared.summary['frozen_control']['score_blocks'], 18)
            self.assertEqual(prepared.summary['forbidden_execution_attempts'], 0)
            for key in ('feature_builds', 'model_instantiations', 'model_fits', 'transforms',
                        'predictions', 'metrics_computed', 'candidate_selections'):
                self.assertEqual(prepared.summary[key], 0)
            self.assertFalse(prepared.summary['training_authorized_this_run'])
            self.assertTrue(prepared.verify_stable()['unchanged'])

    def test_frames_sources_reports_and_summaries_are_defensive_copies(self):
        with temporary_root() as root:
            fixture = load_fixture(root)
            with mocked_inputs(root, fixture):
                prepared = source.load_prepared_sources(root)
            expected = prepared.control_scores['inner_scores.csv'].copy()
            scores = prepared.control_scores
            raw, membership = prepared.raw_orders, prepared.membership
            scores['inner_scores.csv'].loc[0, 'probability_low_1_2'] = 99.
            raw.loc[0, 'order_id'] = 'changed'
            membership.loc[0, 'order_id'] = 'changed'
            prepared.public_sources[0]['sha256'] = 'changed'
            prepared.private_sources[0]['sha256'] = 'changed'
            prepared.method_spec['synthetic'] = False
            prepared.control_report['status'] = 'changed'
            prepared.summary['source_bundle']['role_blocks'] = 0
            pd.testing.assert_frame_equal(prepared.control_scores['inner_scores.csv'], expected)
            self.assertEqual(scores['inner_scores.csv'].loc[0, 'probability_low_1_2'], 99.)
            self.assertNotIn('changed', list(prepared.raw_orders.order_id))
            self.assertNotIn('changed', list(prepared.membership.order_id))
            self.assertTrue(prepared.method_spec['synthetic'])
            self.assertEqual(prepared.control_report['status'], 'completed_real_offline_minimal_baseline')
            self.assertEqual(prepared.summary['source_bundle']['role_blocks'], 12)
            prepared.verify_stable()

    def test_prediction_blocks_mask_all_future_fields_without_dropping_unknown(self):
        with temporary_root() as root:
            fixture = load_fixture(root)
            with mocked_inputs(root, fixture):
                prepared = source.load_prepared_sources(root)
            for fold in source.control_training.FOLDS:
                for role in ('inner_validation', 'outer_evaluation'):
                    truth = prepared.role_block(fold, role)
                    query = prepared.prediction_block(fold, role)
                    self.assertEqual(list(query.order_id), list(truth.order_id))
                    self.assertTrue(query.loc[:, list(source.baseline_sources.FUTURE_QUERY_COLUMNS)].isna().all().all())
                    for name in ('outer_fold', 'role', 'fit_at', 'order_id', 'prediction_time'):
                        pd.testing.assert_series_equal(query[name], truth[name])
            with self.assertRaises(ValueError):
                prepared.prediction_block('2017-12', 'inner_train_pool')

    def test_unbound_control_score_is_rejected_before_read(self):
        with temporary_root() as root:
            fixture = list(load_fixture(root))
            fixture[3] = fixture[3][1:]
            with mocked_inputs(root, fixture), patch.object(source.control_training, 'read_score_csv') as reader:
                with self.assertRaisesRegex(ValueError, 'lack private'):
                    source.load_prepared_sources(root)
            reader.assert_not_called()

    def test_changed_control_score_bytes_stop_before_parsing(self):
        with temporary_root() as root:
            fixture = load_fixture(root)
            (root / source.control_training.PRIVATE / 'inner_scores.csv').write_bytes(b'tampered')
            with mocked_inputs(root, fixture), patch.object(source.control_training, 'read_score_csv') as reader:
                with self.assertRaises(ValueError):
                    source.load_prepared_sources(root)
            reader.assert_not_called()

    def test_public_private_binding_overlap_rejected(self):
        with temporary_root() as root:
            fixture = list(load_fixture(root))
            fixture[3] = fixture[3] + fixture[2]
            with mocked_inputs(root, fixture), self.assertRaisesRegex(ValueError, 'overlap'):
                source.load_prepared_sources(root)

    def test_wrong_control_status_stops_before_score_read(self):
        with temporary_root() as root:
            fixture = list(load_fixture(root))
            fixture[4]['status'] = 'failed'
            fixture[2] = [write_json(root, source.control_training.REPORT, fixture[4])]
            with mocked_inputs(root, fixture), patch.object(source.control_training, 'read_score_csv') as reader:
                with self.assertRaisesRegex(ValueError, 'did not complete'):
                    source.load_prepared_sources(root)
            reader.assert_not_called()

    def test_unknown_score_or_metadata_corruption_cannot_return_prepared_bundle(self):
        for column, value in [('probability_low_1_2', np.nan), ('order_id', 'wrong-ID')]:
            with self.subTest(column=column), temporary_root() as root:
                fixture = list(load_fixture(root))
                frame = fixture[5]['inner_scores.csv'].copy()
                frame.loc[0, column] = value
                path = root / source.control_training.PRIVATE / 'inner_scores.csv'
                path.write_bytes(source.control_training._csv_bytes(frame))
                fixture[3][0] = source.files.descriptor(path, root)
                with mocked_inputs(root, fixture), self.assertRaises((ValueError, TypeError)):
                    source.load_prepared_sources(root)

    def test_stability_checks_continue_after_preparation(self):
        with temporary_root() as root:
            fixture = load_fixture(root)
            with mocked_inputs(root, fixture):
                prepared = source.load_prepared_sources(root)
            (root / source.control_training.PRIVATE / 'outer_scores.csv').write_bytes(b'late drift')
            with self.assertRaises(ValueError):
                prepared.verify_stable()

    def test_forbidden_call_inside_loader_cannot_be_hidden(self):
        with temporary_root() as root:
            fixture = load_fixture(root)
            with (patch.object(source, '_frozen_provenance', return_value=fixture[1:4]),
                  patch.object(source.baseline_sources, 'load_verified_sources',
                               side_effect=lambda root: source.treatment_pipeline.build_primary_features(None))):
                with self.assertRaises(RuntimeError):
                    source.load_prepared_sources(root)


class ProvenanceTests(unittest.TestCase):
    def test_parent_hash_change_stops_before_following_any_old_guard(self):
        with temporary_root() as root:
            for path in source.PINNED:
                write_json(root, path, {'changed': True})
            with patch.object(source.method, 'load_provenance') as loader:
                with self.assertRaisesRegex(ValueError, 'changed'):
                    source._frozen_provenance(root)
            loader.assert_not_called()

    def test_proof_requires_complete_successful_tests_and_exact_feature_structure(self):
        proof = source.files.read_json(source.ROOT / source.PIPELINE_PROOF)
        method_spec = source.files.read_json(source.ROOT / source.method.SPEC)
        source._verify_pipeline_proof(proof, method_spec)
        variants = []
        for key, value in [('tests_run', 74), ('skips', 1), ('errors', 1)]:
            bad = deepcopy(proof)
            bad['tests'][key] = value
            variants.append(bad)
        bad = deepcopy(proof)
        bad['tests']['test_ids'][-1] = bad['tests']['test_ids'][0]
        variants.append(bad)
        for key, value in [('output_columns', 44), ('control_output_columns', 32),
                           ('primary_order', ['purchase_month']), ('frozen_control_code_unchanged', False)]:
            bad = deepcopy(proof)
            bad['implementation'][key] = value
            variants.append(bad)
        bad = deepcopy(proof)
        bad['software_versions']['python'] = 'changed'
        variants.append(bad)
        for bad in variants:
            with self.assertRaises(ValueError):
                source._verify_pipeline_proof(bad, method_spec)


if __name__ == '__main__':
    unittest.main()
