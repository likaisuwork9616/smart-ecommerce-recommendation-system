"""Synthetic score/metadata and publication checks; never train or predict."""
from copy import deepcopy
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import numpy as np
import pandas as pd

from scripts import diagnose_review_scores as runner
from scripts import run_review_baseline as training
from tests.test_review_baseline_training import SyntheticBundle


def frozen_fixture():
    bundle, ledgers, folds = SyntheticBundle(), {'inner_scores.csv': [], 'outer_scores.csv': []}, []
    for fold in training.FOLDS:
        old = {'outer_fold': fold, 'selection': {'selected_C': .1}, 'inner_candidates': []}
        for role, train_role, filename in (
                ('inner_validation', 'inner_train_pool', 'inner_scores.csv'),
                ('outer_evaluation', 'outer_train_pool', 'outer_scores.csv')):
            truth = bundle.role_block(fold, role)
            prior = runner.evaluation.constant_reference_probability(bundle.role_block(fold, train_role))
            inner = role == 'inner_validation'
            models = [('constant_reference', None)] + ([('logistic_candidate', C) for C in (.1, 1., 10.)]
                                                       if inner else [('logistic_selected', .1)])
            for model, C in models:
                p = pd.Series(prior if C is None else np.linspace(.1, .8, len(truth)), index=truth.order_id)
                evaluation = runner.evaluation.evaluate_role(p, truth)
                frame = truth.copy()
                frame['model'], frame['C'] = model, C
                frame['C'] = frame.C.astype('Float64')
                frame['probability_low_1_2'] = p.to_numpy()
                ledgers[filename].append(frame.loc[:, training.SCORE_COLUMNS])
                if inner and C is not None:
                    old['inner_candidates'].append({'C': C, 'evaluation': evaluation})
                else:
                    key = 'inner_reference' if inner else 'outer_reference' if C is None else 'outer_selected'
                    old[key] = evaluation
        folds.append(old)
    ledgers = {name: pd.concat(frames, ignore_index=True) for name, frames in ledgers.items()}
    report = {'results': {'outer_folds': folds, 'execution': {
        'score_rows_across_blocks': sum(len(frame) for frame in ledgers.values())}}}
    return bundle, report, ledgers


def write_fixture(root, ledgers):
    directory = root / training.PRIVATE
    directory.mkdir(parents=True)
    for name, frame in ledgers.items():
        (directory / name).write_bytes(training._csv_bytes(frame))
    for name in runner.CODE:
        path = root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text('synthetic bound code\n', encoding='utf-8')


class FrozenScoreGuardTest(unittest.TestCase):
    def setUp(self):
        self.bundle, self.report, self.ledgers = frozen_fixture()
        self.truth = self.bundle.role_block('2017-12', 'inner_validation')
        self.frame = self.ledgers['inner_scores.csv'].iloc[:len(self.truth)].copy()
        self.expected = self.report['results']['outer_folds'][0]['inner_reference']
        self.prior = runner.evaluation.constant_reference_probability(
            self.bundle.role_block('2017-12', 'inner_train_pool'))

    def check_block(self, frame):
        return runner.verify_score_block(frame, self.truth, 'constant_reference', None,
                                         self.expected, self.prior)

    def test_complete_metadata_unknown_scores_and_prior(self):
        p = self.check_block(self.frame)
        self.assertEqual(list(p.index), list(self.truth.order_id))
        self.assertTrue(p.notna().all())
        self.assertTrue(self.truth.y.isna().any())

    def test_every_metadata_column_mismatch_rejected(self):
        for column in runner.files.MEMBERSHIP_COLUMNS:
            with self.subTest(column=column):
                bad = self.frame.copy()
                bad[column] = bad[column].astype(object)
                bad.loc[bad.index[0], column] = 'tampered'
                with self.assertRaises(ValueError):
                    self.check_block(bad)

    def test_order_drop_duplicate_extra_model_and_C_rejected(self):
        for bad in (self.frame.iloc[::-1], self.frame.iloc[:-1],
                    pd.concat([self.frame, self.frame.iloc[:1]]),
                    self.frame.assign(model='other'), self.frame.assign(C=.1)):
            with self.assertRaises(ValueError):
                self.check_block(bad)

    def test_unknown_probability_still_validated(self):
        for value in (np.nan, np.inf, -0.1, 1.1):
            bad = self.frame.copy()
            bad.loc[~bad.role_label_usable, 'probability_low_1_2'] = value
            with self.assertRaises(ValueError):
                self.check_block(bad)

    def test_wrong_reference_prior_rejected_even_with_matching_metrics(self):
        bad = self.frame.assign(probability_low_1_2=.2)
        p = pd.Series(.2, index=self.truth.order_id)
        expected = runner.evaluation.evaluate_role(p, self.truth)
        with self.assertRaises(ValueError):
            runner.verify_score_block(bad, self.truth, 'constant_reference', None, expected, self.prior)

    def test_known_score_change_fails_frozen_metric_check(self):
        with self.assertRaises(ValueError):
            runner.assert_same({'brier': .2}, {'brier': .3})
        with self.assertRaises(ValueError):
            runner.assert_same({'brier': float('nan')}, {'brier': .3})

    def test_complete_18_blocks_and_unexpected_or_missing_rows(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            write_fixture(root, self.ledgers)
            blocks, rows = runner.load_verified_score_blocks(self.bundle, self.report, root)
            self.assertEqual(len(blocks), 18)
            self.assertEqual(rows, sum(map(len, self.ledgers.values())))
            frame = self.ledgers['outer_scores.csv']
            path = root / training.PRIVATE / 'outer_scores.csv'
            for bad in (frame.iloc[:-1], pd.concat([frame, frame.iloc[:1]]),
                        frame.assign(C=2.), frame.assign(role='new_role')):
                path.write_bytes(training._csv_bytes(bad))
                with self.assertRaises(ValueError):
                    runner.load_verified_score_blocks(self.bundle, self.report, root)


class ReadOnlyExecutionTest(unittest.TestCase):
    def test_model_operations_fail_before_execution(self):
        from sklearn.linear_model import LogisticRegression
        from sklearn.preprocessing import OneHotEncoder, StandardScaler
        with runner.forbid_model_execution() as calls:
            for operation in (lambda: training.GuardedReviewBaseline(),
                              lambda: LogisticRegression().fit(None, None),
                              lambda: LogisticRegression().predict_proba(None),
                              lambda: StandardScaler().fit(None),
                              lambda: StandardScaler().transform(None),
                              lambda: OneHotEncoder().fit(None),
                              lambda: OneHotEncoder().transform(None)):
                with self.assertRaises(RuntimeError):
                    operation()
            self.assertEqual(calls['forbidden_calls'], 7)

    def test_full_synthetic_publication_readonly_replay_and_changed_code_rejection(self):
        bundle, report, ledgers = frozen_fixture()
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            write_fixture(root, ledgers)
            private = [runner.files.descriptor(root / training.PRIVATE / name, root) for name in ledgers]
            with patch.object(runner.sources, 'load_verified_sources', return_value=bundle), \
                    patch.object(runner, 'verify_training_snapshot', return_value=(report, [], private)), \
                    patch.object(runner.files, 'safe_output', side_effect=lambda path, *a, **k: Path(path).resolve()):
                runner.run(root, specification_only=True)
                result = runner.run(root)
                payload = (root / runner.REPORT).read_bytes()
                self.assertEqual(result['verification']['model_fit_calls'], 0)
                self.assertEqual(result['verification']['score_blocks_verified'], 18)
                self.assertEqual(len(result['folds']), 3)
                runner.run(root)
                self.assertEqual((root / runner.REPORT).read_bytes(), payload)
                (root / runner.CODE[0]).write_text('changed', encoding='utf-8')
                with self.assertRaises(ValueError):
                    runner.run(root)
                self.assertEqual((root / runner.REPORT).read_bytes(), payload)

    def test_private_change_rejected_by_guard_and_no_report_written(self):
        bundle, report, ledgers = frozen_fixture()
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            write_fixture(root, ledgers)
            private = [runner.files.descriptor(root / training.PRIVATE / name, root) for name in ledgers]
            with patch.object(runner.files, 'safe_output', side_effect=lambda path, *a, **k: Path(path).resolve()):
                runner.freeze_specification([], private, root)
                path = root / training.PRIVATE / 'inner_scores.csv'
                path.write_bytes(path.read_bytes() + b'\n')
                updated = [runner.files.descriptor(root / training.PRIVATE / name, root) for name in ledgers]
                with self.assertRaises(ValueError):
                    runner.verify_diagnostic_specification([], updated, root)
                self.assertFalse((root / runner.REPORT).exists())

    def test_training_snapshot_missing_changed_parent_or_failure_receipt(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            with self.assertRaises((ValueError, FileNotFoundError)):
                runner.verify_training_snapshot(None, root)
            for path in runner.PARENTS:
                file = root / path
                file.parent.mkdir(parents=True, exist_ok=True)
                file.write_text('{}', encoding='utf-8')
            with self.assertRaisesRegex(ValueError, 'changed'):
                runner.verify_training_snapshot(None, root)


if __name__ == '__main__':
    unittest.main()
