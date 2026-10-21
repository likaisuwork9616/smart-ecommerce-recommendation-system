"""Synthetic publication, exact readback, privacy and fail-stop tests only."""
from copy import deepcopy
from pathlib import Path
import shutil
import unittest
from unittest.mock import patch
import uuid

import pandas as pd

from scripts import prepare_review_month_ablation as preparation
from scripts import review_baseline_evaluation as evaluation
from scripts import review_month_ablation_artifacts as writer
from scripts import review_month_ablation_training as training
from tests.test_review_month_ablation_pairing import synthetic_control_fixture


def synthetic_execution():
    """Twelve actual synthetic fits, with synthetic control scores and no control fit."""
    bundle, report, inner, outer = synthetic_control_fixture()
    for fold in report['results']['outer_folds']:
        name = fold['outer_fold']

        def evaluated(frame, role, model, C=None):
            truth = bundle.role_block(name, role)
            mask = writer.pairing._select(frame, name, role, model, C)
            probabilities = pd.Series(frame.loc[mask, 'probability_low_1_2'].to_numpy(), index=truth.order_id)
            return evaluation.evaluate_role(probabilities, truth)

        fold['inner_reference'] = evaluated(inner, 'inner_validation', 'constant_reference')
        fold['outer_reference'] = evaluated(outer, 'outer_evaluation', 'constant_reference')
        fold['outer_selected'] = evaluated(outer, 'outer_evaluation', 'logistic_selected', .1)
        for candidate in fold['inner_candidates']:
            candidate['evaluation'] = evaluated(inner, 'inner_validation', 'logistic_candidate', candidate['C'])
    report['results']['aggregate_selected'] = evaluation.macro_average_precision(
        [fold['outer_selected'] for fold in report['results']['outer_folds']])
    report['results']['aggregate_reference'] = evaluation.macro_average_precision(
        [fold['outer_reference'] for fold in report['results']['outer_folds']])
    bundle.control_report = report
    bundle.control_scores = {'inner_scores.csv': inner, 'outer_scores.csv': outer}
    return training.execute_training(bundle, {'execution_plan': preparation.execution_plan()})


class MonthAblationArtifactsTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.execution_fixture = synthetic_execution()

    def setUp(self):
        self.root = writer.ROOT / '.runtime' / ('ablation-writer-test-' + uuid.uuid4().hex)
        self.root.mkdir(parents=True)
        self.references = {}
        for key, name in writer.REFERENCE_PATHS.items():
            path = self.root / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(writer.files.json_bytes({'synthetic_reference': key}))
            self.references[key] = writer.files.descriptor(path, self.root)
        self.bound = list(self.references.values())
        self.execution = deepcopy(self.execution_fixture)
        self.calls = 0

    def tearDown(self):
        resolved = self.root.resolve()
        assert resolved.is_relative_to((writer.ROOT / '.runtime').resolve())
        assert resolved.name.startswith('ablation-writer-test-')
        shutil.rmtree(resolved)

    def verify(self):
        self.calls += 1
        writer.files.verify_sources(self.bound, self.root)

    def publish(self):
        return writer.publish(self.execution, self.references, verify_sources=self.verify,
                              bound_sources=self.bound, root=self.root)

    def assert_no_success(self):
        self.assertFalse((self.root / writer.REPORT).exists())
        directory = self.root / writer.PRIVATE
        if directory.exists():
            self.assertEqual(list(directory.iterdir()), [])

    def test_contract_exact_shapes_and_successful_private_roundtrip(self):
        contract = writer.artifact_schema_contract()
        self.assertEqual(contract['fit_audit_keys'], list(training.FIT_AUDIT_KEYS))
        self.assertEqual(contract['fit_record_keys'], list(training.FIT_RECORD_KEYS))
        result = self.publish()
        self.assertEqual(result['verification']['completed_estimator_fits'], 12)
        self.assertEqual(result['verification']['paired_blocks'], 18)
        self.assertEqual(self.calls, 4)
        directory = self.root / writer.PRIVATE
        self.assertEqual(set(x.name for x in directory.iterdir()), set(writer.PRIVATE_NAMES) - {'failure_receipt.json'})
        manifest = writer.files.read_json(directory / 'manifest.json')
        acceptance = writer.files.read_json(directory / 'paired_acceptance.json')
        self.assertEqual(set(manifest), set(contract['manifest_keys']))
        self.assertEqual(set(acceptance), set(contract['paired_acceptance_keys']))
        for reference in writer.REFERENCE_PATHS:
            self.assertEqual(manifest[reference], self.references[reference])
            self.assertEqual(acceptance[reference], self.references[reference])
        for descriptor in [*manifest['files'].values(), manifest['public_report']]:
            self.assertEqual(descriptor, writer.files.descriptor(self.root / descriptor['path'], self.root))
        for name, frame in zip(('inner_scores.csv', 'outer_scores.csv'), self.execution[1:3]):
            data = (directory / name).read_bytes()
            self.assertNotIn(b'\r\n', data)
            check = writer.codec.verify_score_bytes(frame, data)
            self.assertTrue(check['binary64_probabilities_exact'])
            restored = writer.codec.read_score_csv(data)
            self.assertTrue(restored.loc[~restored.role_label_usable, 'y'].isna().all())

    def test_public_result_omits_ids_coefficients_and_private_hashes(self):
        self.publish()
        public = (self.root / writer.REPORT).read_text(encoding='utf-8')
        for key in ('input_guard', 'control_manifest'):
            self.assertNotIn(self.references[key]['sha256'], public)
        for frame in self.execution[1:3]:
            for value in frame.order_id:
                self.assertNotIn('"' + value + '"', public)
        self.assertNotIn('coefficient_values', public)
        self.assertNotIn('scaler_mean', public)

    def test_same_byte_existing_success_is_replay_not_idempotent(self):
        self.publish()
        before = (self.root / writer.REPORT).read_bytes()
        with self.assertRaises(ValueError):
            self.publish()
        self.assertEqual((self.root / writer.REPORT).read_bytes(), before)

    def test_unexpected_namespace_file_or_directory_blocks_before_verify(self):
        directory = self.root / writer.PRIVATE
        directory.mkdir(parents=True)
        extra = directory / 'unexpected'
        extra.mkdir()
        with self.assertRaises(ValueError):
            self.publish()
        self.assertEqual(self.calls, 0)
        self.assertTrue(extra.is_dir())

    def test_public_output_collision_and_input_collision_refused(self):
        public = self.root / writer.REPORT
        public.parent.mkdir(parents=True, exist_ok=True)
        public.write_bytes(b'pre-existing report')
        with self.assertRaises(ValueError):
            self.publish()
        self.assertEqual(public.read_bytes(), b'pre-existing report')
        public.unlink()
        collision = dict(self.bound[0], path=writer.PRIVATE + '/outer_scores.csv')
        with self.assertRaisesRegex(ValueError, 'collides'):
            writer.preflight(self.root, self.bound + [collision])

    def test_changed_reference_and_noncanonical_reference_refused_before_write(self):
        (self.root / self.references['input_guard']['path']).write_bytes(b'changed')
        with self.assertRaises(ValueError):
            self.publish()
        self.assert_no_success()
        self.references['input_guard']['path'] = '.runtime/wrong_version/input_guard.json'
        with self.assertRaises(ValueError):
            self.publish()

    def test_missing_or_changed_output_audit_and_fit_order_refused(self):
        for mutation in ('count', 'shape', 'order', 'roster', 'sample', 'extra'):
            self.execution = deepcopy(self.execution_fixture)
            audit = self.execution[3]
            if mutation == 'count':
                audit['completed_estimator_fits'] = 11
            elif mutation == 'shape':
                audit['fit_records'][0]['coefficient_values'][0].pop()
            elif mutation == 'order':
                audit['fit_records'][0]['fit_sequence'] = 2
            elif mutation == 'roster':
                audit['fit_records'][0]['eligible_order_ids'].reverse()
            elif mutation == 'sample':
                audit['fit_records'][0]['scaler_samples'] += 1
            else:
                audit['fit_records'][0]['model_object'] = 'forbidden'
            with self.subTest(mutation=mutation), self.assertRaises(ValueError):
                self.publish()
            self.assert_no_success()

    def test_pairing_count_unknown_coverage_or_control_selection_mismatch_refused(self):
        for mutation in ('missing', 'unknown', 'independent', 'constant', 'inner_C'):
            self.execution = deepcopy(self.execution_fixture)
            pair = self.execution[4]
            if mutation == 'missing':
                pair['paired_blocks'].pop()
            elif mutation == 'unknown':
                pair['paired_blocks'][0]['unknown_or_ineligible_labels'] = 0
            elif mutation == 'independent':
                pair['independent_treatment_selection']['control_C_used'] = True
            elif mutation == 'constant':
                pair['constant_reference_equality'] = False
            else:
                pair['paired_blocks'][1]['control_C'] = 10.
            with self.subTest(mutation=mutation), self.assertRaises(ValueError):
                self.publish()
            self.assert_no_success()

    def test_nullable_or_full_score_corruption_refused_before_write(self):
        for mutation in ('fill_unknown', 'nonfinite_unknown', 'dropped', 'extra'):
            self.execution = deepcopy(self.execution_fixture)
            frame = self.execution[1]
            if mutation == 'fill_unknown':
                frame.loc[~frame.role_label_usable, 'y'] = 0
            elif mutation == 'nonfinite_unknown':
                frame.loc[~frame.role_label_usable, 'probability_low_1_2'] = float('nan')
            elif mutation == 'dropped':
                self.execution = (self.execution[0], frame.iloc[:-1], *self.execution[2:])
            else:
                frame['unexpected'] = 1
            with self.subTest(mutation=mutation), self.assertRaises(ValueError):
                self.publish()
            self.assert_no_success()

    def test_stale_pairing_proof_cannot_publish_changed_ids_order_truth_or_scores(self):
        for mutation in ('id', 'order', 'truth', 'probability', 'constant', 'coefficient', 'public_metric'):
            self.execution = deepcopy(self.execution_fixture)
            frame = self.execution[1]
            if mutation == 'id':
                frame.loc[0, 'order_id'] = 'synthetic-corrupted-id'
            elif mutation == 'order':
                frame.iloc[[0, 1]] = frame.iloc[[1, 0]].to_numpy()
            elif mutation == 'truth':
                frame.loc[0, 'first_visible_answer_at'] += pd.Timedelta(seconds=1)
            elif mutation == 'probability':
                index = frame.index[frame.model.eq('logistic_candidate')][0]
                frame.loc[index, 'probability_low_1_2'] = .123
            elif mutation == 'constant':
                frame.loc[frame.model.eq('constant_reference'), 'probability_low_1_2'] = .123
            elif mutation == 'coefficient':
                self.execution[3]['fit_records'][0]['coefficient_values'][0][0] += .123
            else:
                self.execution[0]['outer_folds'][0]['outer_selected']['metrics']['brier'] = .123
            with self.subTest(mutation=mutation), self.assertRaises(ValueError):
                self.publish()
            self.assert_no_success()

    def test_public_nested_extra_fields_and_private_values_refused(self):
        for mutation in ('top', 'metric_extra', 'selection_extra', 'fit_extra', 'private_hash', 'candidate_AP'):
            self.execution = deepcopy(self.execution_fixture)
            public = self.execution[0]
            if mutation == 'top':
                public['debug'] = 'bad'
            elif mutation == 'metric_extra':
                public['outer_folds'][0]['outer_selected']['metrics']['order_id'] = 'synthetic-private'
            elif mutation == 'selection_extra':
                public['outer_folds'][0]['selection']['debug'] = 'bad'
            elif mutation == 'fit_extra':
                public['fit_context_audits'][0]['scaler_mean'] = [2]
            elif mutation == 'private_hash':
                public['paired_comparison']['scope'] = self.references['input_guard']['sha256']
            else:
                public['outer_folds'][0]['selection']['candidate_average_precision'][0]['average_precision'] = .123
            with self.subTest(mutation=mutation), self.assertRaises(ValueError):
                self.publish()
            self.assert_no_success()

    def test_source_verifier_failure_before_write_has_no_artifacts(self):
        with self.assertRaises(RuntimeError):
            writer.publish(self.execution, self.references,
                           verify_sources=lambda: (_ for _ in ()).throw(RuntimeError('stop')),
                           bound_sources=self.bound, root=self.root)
        self.assert_no_success()

    def test_failure_after_private_write_rolls_back_only_owned_bytes(self):
        original = writer._write_exclusive
        count = 0

        def fail(path, data, created):
            nonlocal count
            count += 1
            if count == 3:
                raise OSError('synthetic writer failure')
            original(path, data, created)

        with patch.object(writer, '_write_exclusive', side_effect=fail), self.assertRaises(OSError):
            self.publish()
        self.assert_no_success()

    def test_partial_write_is_preserved_as_failure_evidence(self):
        def partial(path, data, created):
            path.parent.mkdir(parents=True, exist_ok=True)
            with path.open('xb') as stream:
                created.append((path, data))
                stream.write(data[:17])
            raise OSError('synthetic short write')

        with patch.object(writer, '_write_exclusive', side_effect=partial), self.assertRaises(OSError):
            self.publish()
        path = self.root / writer.PRIVATE / 'inner_scores.csv'
        self.assertEqual(len(path.read_bytes()), 17)
        self.assertFalse((self.root / writer.REPORT).exists())
        with self.assertRaises(ValueError):
            writer.preflight(self.root, self.bound)

    def test_failure_after_public_write_retracts_entire_owned_publication(self):
        def fail_late():
            self.verify()
            if self.calls == 4:
                raise RuntimeError('synthetic late verification failure')

        with self.assertRaises(RuntimeError):
            writer.publish(self.execution, self.references, verify_sources=fail_late,
                           bound_sources=self.bound, root=self.root)
        self.assert_no_success()

    def test_json_readback_failure_stops_and_retracts(self):
        original = writer.files.read_json

        def changed(path):
            return {'corrupt': True} if Path(path).name == 'fit_audit.json' else original(path)

        with patch.object(writer.files, 'read_json', side_effect=changed), self.assertRaises(ValueError):
            self.publish()
        self.assert_no_success()

    def test_unexpected_file_during_publication_preserved_success_retracted(self):
        original = writer._write_exclusive

        def injected(path, data, created):
            original(path, data, created)
            if path.name == 'inner_scores.csv':
                (path.parent / 'unexpected.bin').write_bytes(b'outside writer')

        with patch.object(writer, '_write_exclusive', side_effect=injected), self.assertRaises(ValueError):
            self.publish()
        self.assertFalse((self.root / writer.REPORT).exists())
        directory = self.root / writer.PRIVATE
        self.assertEqual([x.name for x in directory.iterdir()], ['unexpected.bin'])
        self.assertEqual((directory / 'unexpected.bin').read_bytes(), b'outside writer')

    def test_changed_owned_file_is_preserved_and_blocks_replay(self):
        original = writer._write_exclusive

        def replaced(path, data, created):
            original(path, data, created)
            if path.name == 'inner_scores.csv':
                path.write_bytes(b'external replacement')

        with patch.object(writer, '_write_exclusive', side_effect=replaced), self.assertRaises(ValueError):
            self.publish()
        self.assertEqual((self.root / writer.PRIVATE / 'inner_scores.csv').read_bytes(), b'external replacement')
        self.assertFalse((self.root / writer.REPORT).exists())

    def test_failure_receipt_exact_private_schema_blocks_retry(self):
        context = {'phase': 'prediction', 'outer_fold': '2017-12', 'role': 'inner_train_pool',
                   'C': .1, 'completed_estimator_fits': 1}
        result = writer.write_failure_receipt(context, 'ValueError', self.references, root=self.root)
        self.assertEqual(set(result), set(writer.artifact_schema_contract()['failure_receipt_keys']))
        self.assertEqual(result['execution_context'], context)
        path = self.root / writer.PRIVATE / 'failure_receipt.json'
        before = path.read_bytes()
        with self.assertRaises(FileExistsError):
            writer.write_failure_receipt(context, 'ValueError', self.references, root=self.root)
        self.assertEqual(path.read_bytes(), before)
        with self.assertRaises(ValueError):
            self.publish()

    def test_full_fit_pairing_failure_context_can_be_recorded(self):
        context = {'phase': 'complete_same_id_pairing', 'outer_fold': None, 'role': None,
                   'C': None, 'completed_estimator_fits': 12}
        receipt = writer.write_failure_receipt(context, 'ValueError', self.references, root=self.root)
        self.assertEqual(receipt['execution_context'], context)
        self.assertFalse((self.root / writer.REPORT).exists())

    def test_failure_receipt_does_not_record_exception_text_or_unbounded_context(self):
        context = {'phase': 'fit', 'outer_fold': None, 'role': None, 'C': None, 'completed_estimator_fits': 0}
        for invalid_context, exception in [(dict(context, completed_estimator_fits=13), 'ValueError'),
                                           (dict(context, order_id='secret'), 'ValueError'),
                                           (dict(context, phase='fit secret-id'), 'ValueError'),
                                           (context, 'ValueError: secret data')]:
            with self.assertRaises(ValueError):
                writer.write_failure_receipt(invalid_context, exception, self.references, root=self.root)
        self.assert_no_success()

    def test_alias_check_applies_to_every_output_including_failure_receipt(self):
        original = writer.preparation.control.reject_output_aliases

        def alias(path, root):
            if Path(path).name == 'failure_receipt.json':
                raise ValueError('synthetic alias')
            return original(path, root)

        with patch.object(writer.preparation.control, 'reject_output_aliases', side_effect=alias), self.assertRaises(ValueError):
            self.publish()
        self.assert_no_success()


if __name__ == '__main__':
    unittest.main()
