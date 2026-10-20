"""Source, clock and immutable-output checks for offline day acceptance."""
from copy import deepcopy
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import numpy as np
import pandas as pd

from scripts import accept_frozen_daily_delivery as delivery
from tests.test_delay_daily_delivery_acceptance import fixture as score_fixture


DAY = '2018-02-01'


def raw_fixture():
    raw = pd.DataFrame({
        'order_id': ['edge-equal', 'canceled', 'missing', 'approval-early', 'delivery-early',
                     'promise-early', 'post-may', 'no-approval', 'next-day'],
        'order_status': ['delivered', 'canceled', 'delivered', 'delivered', 'delivered',
                         'delivered', 'unavailable', 'unavailable', 'delivered'],
        'order_purchase_timestamp': ['2018-02-01 12:00:00'] * 9,
        'order_approved_at': ['2018-02-01 12:00:00'] * 6 + ['2018-05-01', None, '2018-02-02 12:00:00'],
        'order_delivered_customer_date': ['2018-02-01 12:00:00'] * 8 + ['2018-02-02 12:00:00'],
        'order_estimated_delivery_date': ['2018-02-01'] * 8 + ['2018-02-02'],
    })
    raw.loc[1, 'order_purchase_timestamp'] = None
    raw.loc[2, 'order_purchase_timestamp'] = None
    raw.loc[3, 'order_purchase_timestamp'] = '2018-02-01 12:00:01'
    raw.loc[4, 'order_delivered_customer_date'] = '2018-02-01 11:59:59'
    raw.loc[5, 'order_estimated_delivery_date'] = '2018-01-31'
    for index in (6, 7):
        raw.loc[index, ['order_purchase_timestamp', 'order_delivered_customer_date',
                        'order_estimated_delivery_date']] = 'outside-scope-never-interpret'
    raw.loc[8, 'order_purchase_timestamp'] = '2018-02-02 12:00:00'
    return raw


def model_fixture():
    reports = []
    for setting in (.8, 1.):
        monthly = []
        for seed in delivery.core.SEEDS:
            models = {}
            for candidate, count in ((delivery.core.BASELINE, 101), (delivery.core.AGE, 102)):
                models[candidate] = {
                    'seed': seed, 'candidate': candidate, 'feature_count': count,
                    'classifier_parameters': {'random_state': seed, 'colsample_bytree': setting},
                    'training_design': 'deadline_wait0',
                    'score_semantics': 'sigmoid(raw margin), strictly monotone uncalibrated ranking score',
                    'version_artifact': {'path': f'models/fake_{setting}_{seed}_{count}.joblib',
                                         'sha256': f'{seed:064x}'},
                }
            monthly.append({'month': '2018-02', 'seed': seed, 'models': models, 'training_split': {
                'wait_days': 0, 'training_clock': 'deadline', 'model_fit_time': '2018-02-01T00:00:00',
                'scoring_start': '2018-02-01T00:00:00', 'scoring_end': '2018-03-01T00:00:00',
            }})
        reports.append({'monthly_training': monthly})
    seeds, colsample = reports
    colsample['frozen_reference'] = {'monthly_models': [
        {'month': '2018-02', 'seed': item['seed'], 'candidate': candidate, **model['version_artifact']}
        for item in seeds['monthly_training'] for candidate, model in item['models'].items()]}
    return colsample, seeds


class DailyDeliveryRunnerTests(unittest.TestCase):
    def temporary_root(self):
        directory = tempfile.TemporaryDirectory(dir=delivery.ROOT / '.runtime')
        self.addCleanup(directory.cleanup)
        return Path(directory.name)

    def test_raw_predicate_boundaries_and_mutually_exclusive_reasons(self):
        eligible, scoped = delivery.reconstruct_cohort(raw_fixture())
        self.assertEqual(eligible.order_id.tolist(), ['edge-equal', 'next-day'])
        self.assertEqual(len(scoped), 7)
        reasons = scoped.set_index('order_id').cohort_reason.to_dict()
        self.assertEqual(reasons['canceled'], 'not_final_delivered')
        self.assertEqual(reasons['missing'], 'missing_timeline')
        self.assertEqual(reasons['approval-early'], 'approval_before_purchase')
        self.assertEqual(reasons['delivery-early'], 'delivery_before_approval')
        self.assertEqual(reasons['promise-early'], 'promise_before_approval_day')
        self.assertNotIn('post-may', reasons)
        self.assertNotIn('no-approval', reasons)
        self.assertNotIn('delayed', eligible)

    def test_changed_final_status_changes_only_retrospective_cohort(self):
        raw = raw_fixture()
        expected, _ = delivery.reconstruct_cohort(raw)
        raw.loc[0, 'order_status'] = 'canceled'
        changed, _ = delivery.reconstruct_cohort(raw)
        self.assertEqual(len(expected) - len(changed), 1)
        self.assertNotIn('edge-equal', set(changed.order_id))

    def test_duplicate_raw_identity_and_aware_approval_clock_are_rejected(self):
        raw = raw_fixture()
        raw.loc[0, 'order_id'] = raw.order_id.iloc[1]
        with self.assertRaises(ValueError):
            delivery.reconstruct_cohort(raw)
        raw = raw_fixture()
        raw['order_approved_at'] = '2018-02-01T00:00:00Z'
        with self.assertRaises(ValueError):
            delivery.reconstruct_cohort(raw)

    def test_first_day_is_chosen_from_roster_without_any_score_argument(self):
        eligible, scoped = delivery.reconstruct_cohort(raw_fixture())
        roster, public = delivery.choose_day(eligible.iloc[::-1], eligible, scoped)
        self.assertEqual(public['day'], DAY)
        self.assertEqual(roster.order_id.tolist(), ['edge-equal'])
        self.assertEqual(public['raw_day_approval_rows'], 6)
        self.assertEqual(sum(public['mutually_exclusive_excluded_day_rows'].values()), 5)
        self.assertNotIn('fingerprint', json.dumps(public))

    def test_full_feature_roster_must_match_raw_ids_and_exact_timestamps(self):
        eligible, scoped = delivery.reconstruct_cohort(raw_fixture())
        for column, value in (('order_id', 'same-size-wrong-identity'),
                              ('prediction_time', pd.Timestamp('2018-02-01 12:00:01'))):
            changed = eligible.copy()
            changed.loc[0, column] = value
            with self.subTest(column=column), self.assertRaises(ValueError):
                delivery.choose_day(changed, eligible, scoped)
        with self.assertRaises(ValueError):
            delivery.choose_day(eligible.iloc[:1], eligible, scoped)

    def test_model_manifest_keeps_all_settings_and_seeds_without_private_fingerprints(self):
        colsample, seeds = model_fixture()
        result = delivery.model_manifest(colsample, seeds)
        self.assertEqual(len(result), 20)
        self.assertEqual({item['seed'] for item in result}, set(delivery.core.SEEDS))
        self.assertEqual({item['version'] for item in result}, set(delivery.core.VERSIONS))
        self.assertNotIn('training_order_sha256', json.dumps(result))
        self.assertTrue(all(item['reported_logical_model_fit_time'] == '2018-02-01T00:00:00' for item in result))

    def test_wrong_model_seed_feature_count_clock_or_source_reference_is_rejected(self):
        for kind in ('seed', 'feature', 'clock', 'frozen_sha', 'candidate', 'missing_seed'):
            colsample, seeds = model_fixture()
            info = seeds['monthly_training'][0]['models'][delivery.core.BASELINE]
            if kind == 'seed':
                info['classifier_parameters']['random_state'] = 42
            elif kind == 'feature':
                info['feature_count'] = 102
            elif kind == 'clock':
                seeds['monthly_training'][0]['training_split']['model_fit_time'] = '2018-02-02T00:00:00'
            elif kind == 'frozen_sha':
                colsample['frozen_reference']['monthly_models'][0]['sha256'] = 'bad-reference'
            elif kind == 'candidate':
                info['candidate'] = 'other-candidate'
            else:
                seeds['monthly_training'].pop()
            with self.subTest(kind=kind), self.assertRaises(ValueError):
                delivery.model_manifest(colsample, seeds)

    def test_source_hash_byte_count_duplicate_path_and_escape_fail_closed(self):
        root = self.temporary_root()
        path = root / 'source.bin'
        path.write_bytes(b'original')
        item = delivery.descriptor(path, root)
        self.assertEqual(delivery.verify_sources([item], root), 1)
        path.write_bytes(b'changed!')  # same byte count
        with self.assertRaises(ValueError):
            delivery.verify_sources([item], root)
        with self.assertRaises(ValueError):
            delivery.verify_sources([item, item], root)
        with self.assertRaises(ValueError):
            delivery.descriptor(delivery.ROOT / 'README.md', root)

    def test_score_reader_explicitly_excludes_outcome_values_and_checks_header(self):
        root = self.temporary_root()
        _, ledger = score_fixture(10)
        ledger['outcome_for_metrics'] = 'future-value-not-to-read'
        columns = ['order_id', 'prediction_time', 'fold', 'role', 'candidate', 'model_version',
                   'known_at_selection', 'outcome_for_metrics', 'delay_score', 'predicted_delayed', 'seed']
        ledger = ledger[columns + ['colsample_bytree']]
        path = root / 'scores.csv'
        ledger.to_csv(path, index=False)
        source = {'score_export': {'rows': len(ledger), 'source_columns': columns,
                                   'appended_discriminator': 'colsample_bytree'}}
        original = pd.read_csv
        with patch.object(delivery.pd, 'read_csv', wraps=original) as reader:
            selected, count = delivery.read_day_scores(path, DAY, source, chunksize=27)
        self.assertEqual((len(selected), count), (200, 200))
        self.assertNotIn('outcome_for_metrics', selected)
        value_reads = [call.kwargs for call in reader.call_args_list if 'usecols' in call.kwargs]
        self.assertEqual(len(value_reads), 1)
        self.assertNotIn('outcome_for_metrics', value_reads[0]['usecols'])
        source['score_export']['rows'] += 1
        with self.assertRaises(ValueError):
            delivery.read_day_scores(path, DAY, source)
        source['score_export']['source_columns'] = columns[:-1]
        with self.assertRaises(ValueError):
            delivery.read_day_scores(path, DAY, source)

    def test_private_path_requires_runtime_containment_ignore_and_source_separation(self):
        root = self.temporary_root()
        (root / '.runtime').mkdir()
        valid = root / '.runtime' / 'out.csv'
        with patch.object(delivery.subprocess, 'run') as run:
            run.return_value.returncode = 0
            self.assertEqual(delivery.private_path(valid, root=root), valid.resolve())
            with self.assertRaises(ValueError):
                delivery.private_path(root / 'tracked.csv', root=root)
            with self.assertRaises(ValueError):
                delivery.private_path(valid, root=root, sources=[{'path': '.runtime/out.csv'}])
            run.return_value.returncode = 1
            with self.assertRaises(ValueError):
                delivery.private_path(valid, root=root)

    def test_runtime_symlink_escape_is_rejected_before_git_check(self):
        root = self.temporary_root()
        outside = self.temporary_root()
        try:
            (root / '.runtime').symlink_to(outside, target_is_directory=True)
        except OSError:
            # Windows may not grant symlink privileges; mock only resolution,
            # exercising the same final absolute containment predicate.
            original = Path.resolve
            def resolve(path, *args, **kwargs):
                if path == root / '.runtime':
                    return outside
                if path == root / '.runtime/out.csv':
                    return outside / 'out.csv'
                return original(path, *args, **kwargs)
            with patch.object(Path, 'resolve', resolve), patch.object(delivery.subprocess, 'run') as run:
                with self.assertRaises(ValueError):
                    delivery.private_path(root / '.runtime/out.csv', root=root)
                run.assert_not_called()
        else:
            with patch.object(delivery.subprocess, 'run') as run:
                with self.assertRaises(ValueError):
                    delivery.private_path(root / '.runtime/out.csv', root=root)
                run.assert_not_called()

    def test_immutable_bundle_checks_every_existing_member_before_any_new_write(self):
        root = self.temporary_root()
        first, second = root / '.runtime/first.csv', root / '.runtime/second.csv'
        second.parent.mkdir()
        second.write_bytes(b'incompatible-existing-output')
        with patch.object(delivery.subprocess, 'run') as run:
            run.return_value.returncode = 0
            with self.assertRaises(ValueError):
                delivery.immutable_bundle({first: b'new', second: b'expected'}, root=root)
        self.assertFalse(first.exists())
        self.assertEqual(second.read_bytes(), b'incompatible-existing-output')

    def test_immutable_bundle_identical_rerun_preserves_bytes(self):
        root = self.temporary_root()
        path = root / '.runtime/one.csv'
        with patch.object(delivery.subprocess, 'run') as run:
            run.return_value.returncode = 0
            delivery.immutable_bundle({path: b'exact-bytes'}, root=root)
            delivery.immutable_bundle({path: b'exact-bytes'}, root=root)
        self.assertEqual(path.read_bytes(), b'exact-bytes')

    def test_public_json_rejects_nonfinite_duplicate_overwrite_source_and_wrong_location(self):
        root = self.temporary_root()
        path = root / 'report.json'
        delivery.immutable_json(path, {'status': 'ok'}, root=root)
        before = path.read_bytes()
        delivery.immutable_json(path, {'status': 'ok'}, root=root)
        self.assertEqual(path.read_bytes(), before)
        with self.assertRaises(ValueError):
            delivery.immutable_json(path, {'status': 'changed'}, root=root)
        with self.assertRaises(ValueError):
            delivery.immutable_json(root / 'nonfinite.json', {'bad': np.nan}, root=root)
        for content in ('{"duplicate":1,"duplicate":2}', '{"bad":NaN}', '{"bad":Infinity}'):
            path.write_text(content, encoding='utf-8')
            with self.subTest(content=content), self.assertRaises(ValueError):
                delivery.read_json(path)
        for target in (root / 'data/report.json', root / 'models/report.json', root / 'not-json.txt'):
            with self.subTest(target=target), self.assertRaises(ValueError):
                delivery.immutable_json(target, {}, root=root)
        with self.assertRaises(ValueError):
            delivery.immutable_json(path, {}, root=root, sources=[{'path': 'report.json'}])

    def test_csv_roundtrip_is_exact_and_mutated_score_or_selected_subset_is_rejected(self):
        roster, ledger = score_fixture(19)
        # Exactly representable near-boundary floating point values exercise
        # 17-digit writing and round-trip parsing without scoring any model.
        ledger['delay_score'] = np.nextafter(.5, 1.)
        _, private = delivery.core.accept_day(roster, ledger, day=DAY)
        rankings = delivery.csv_bytes(private)
        alerts = delivery.csv_bytes(private.loc[private.alert].reset_index(drop=True))
        checks = delivery.verify_csv_bundle(roster, rankings, alerts, private, day=DAY)
        self.assertEqual(checks['exact_frozen_score_rows_verified'], 380)
        self.assertEqual(checks['exact_selected_subset_rows_verified'], 20)
        changed = private.copy()
        changed.loc[0, 'score'] = .9  # Keeps rank 1 but violates its frozen score.
        with self.assertRaises(ValueError):
            delivery.verify_csv_bundle(roster, delivery.csv_bytes(changed), alerts, private, day=DAY)
        wrong_alerts = private.loc[private.alert].reset_index(drop=True).copy()
        wrong_alerts.loc[0, 'score'] = .9
        with self.assertRaises(ValueError):
            delivery.verify_csv_bundle(roster, rankings, delivery.csv_bytes(wrong_alerts), private, day=DAY)

    def test_boundaries_match_internally_but_no_individual_score_is_published(self):
        roster, ledger = score_fixture(10)
        public, private = delivery.core.accept_day(roster, ledger, day=DAY)
        frozen = {'seed_phases': {str(seed): {delivery.TARGET_PHASE: {'daily_boundaries': [{
            'day': DAY, 'full_rows': 10, 'capacity': 1, 'models': {version: {
                'known_alerts': 1, 'unknown_alerts': 0, 'cutoff_score': .5, 'next_score': .5,
                'score_margin': 0., 'cutoff_tie_rows': 10, 'cutoff_tie_alerted_rows': 1,
                'cutoff_tie_unalerted_rows': 9, 'cross_boundary_tie': True,
            } for version in delivery.core.VERSIONS}}]}} for seed in delivery.core.SEEDS}}
        checks = delivery.verify_boundaries(public, private, frozen)
        self.assertEqual(checks['runs_verified'], 20)
        self.assertFalse(checks['individual_boundary_scores_published'])
        self.assertNotIn('cutoff_score', json.dumps(checks))
        offset = deepcopy(frozen)
        row = offset['seed_phases']['11'][delivery.TARGET_PHASE]['daily_boundaries'][0]['models']['base08']
        row['known_alerts'], row['unknown_alerts'] = 0, 1
        with self.assertRaises(ValueError):
            delivery.verify_boundaries(public, private, offset)
        frozen['seed_phases']['11'][delivery.TARGET_PHASE]['daily_boundaries'][0]['models']['base08']['next_score'] = .4
        with self.assertRaises(ValueError):
            delivery.verify_boundaries(public, private, frozen)

    def test_contract_has_no_performance_metric_or_training_action(self):
        contract = delivery.contract()
        self.assertEqual(contract['event_signal_status'], 'pending_data_no_training')
        self.assertEqual(contract['seeds'], [11, 29, 42, 73, 101])
        self.assertEqual(contract['daily_fraction'], .1)
        self.assertNotIn('outcome_for_metrics', delivery.core.REQUIRED_LEDGER_COLUMNS)


if __name__ == '__main__':
    unittest.main()
