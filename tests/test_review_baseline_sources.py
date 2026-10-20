"""Synthetic metadata/source guards; no real-data features or model fits."""
from copy import deepcopy
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import pandas as pd

from scripts import review_baseline_sources as sources


def fixture():
    clocks = ['2017-01-02 12:00:00', '2017-02-02 12:00:00', '2017-02-15 12:00:00']
    for month in ['2017-09', '2017-11', '2017-12', '2018-02', '2018-04']:
        clocks.extend([month + '-02 12:00:00', month + '-03 12:00:00'])
    approval = pd.to_datetime(clocks)
    ids = ['synthetic-' + str(index) for index in range(len(clocks))]
    raw = pd.DataFrame({'order_id': ids,
                        'order_purchase_timestamp': (approval - pd.Timedelta(hours=1)).strftime('%Y-%m-%d %H:%M:%S'),
                        'order_approved_at': approval.strftime('%Y-%m-%d %H:%M:%S')}, dtype='string')
    orders = raw.assign(customer_id='synthetic-customer')
    cohort, _ = sources.dataset.approval_cohort(orders)
    reviews = pd.DataFrame({'review_id': ['review-' + str(i) for i in range(len(ids))],
                            'order_id': ids,
                            'review_score': ['1' if i % 2 else '5' for i in range(len(ids))],
                            'review_creation_date': approval.strftime('%Y-%m-%d %H:%M:%S'),
                            'review_answer_timestamp': (approval + pd.Timedelta(days=1)).strftime('%Y-%m-%d %H:%M:%S')}, dtype='string')
    reviews = reviews.loc[reviews.order_id != ids[2]]
    prepared, _ = sources.dataset.prepare_reviews(reviews)
    labels, summary = sources.dataset.label_asof(cohort, prepared, sources.dataset.OBSERVATION_CUTOFF)
    membership, folds = sources.dataset.build_membership(cohort, prepared)
    spec = {'expected_existing_cohort_orders': len(raw),
            'calendar_split_plan': sources.dataset.calendar_split_plan()}
    audit = {'order_quality': {'source_orders': len(raw)},
             'final_observation_labels': summary,
             'nested_calendar_development_support': folds}
    return raw, labels, membership, spec, audit


def bundle(root=None, public=(), private=()):
    raw, labels, membership, spec, audit = fixture()
    context, summary = sources._validate_loaded_frames(raw, labels, membership, spec, audit)
    result = sources.VerifiedReviewSources(
        sources.ROOT if root is None else Path(root), raw, membership, context,
        tuple(deepcopy(public)), tuple(deepcopy(private)), {'synthetic': True}, audit, summary)
    return result


class ReviewBaselineSourcesTest(unittest.TestCase):
    def test_merge_source_descriptors_deduplicates_exact_and_rejects_conflicts(self):
        first = {'path': 'one', 'bytes': 1, 'sha256': 'a'}
        second = {'path': 'two', 'bytes': 2, 'sha256': 'b'}
        self.assertEqual(sources.merge_sources([second, first], [first]), [first, second])
        with self.assertRaises(ValueError):
            sources.merge_sources([first], [dict(first, sha256='changed')])

    def test_complete_metadata_audit_builds_immutable_full_context_without_X_or_fit(self):
        raw, labels, membership, spec, audit = fixture()
        with (patch.object(sources.pipeline, 'build_primary_features', side_effect=AssertionError('no X')),
              patch.object(sources.pipeline.GuardedReviewBaseline, 'fit_orders', side_effect=AssertionError('no fit'))):
            context, summary = sources._validate_loaded_frames(raw, labels, membership, spec, audit)
        self.assertEqual(len(context.rows), len(raw))
        self.assertEqual(summary['role_blocks'], 12)
        self.assertEqual(summary['required_both_class_contexts'], 9)
        self.assertEqual(summary['global_known_labels'] + summary['global_unknown_labels'], len(raw))
        self.assertFalse(summary['historical_ingestion_verified'])

    def test_role_labels_are_unchanged_and_prediction_inputs_remove_all_future_fields(self):
        result = bundle()
        original = result.role_block('2017-12', 'inner_validation')
        query = result.prediction_block('2017-12', 'inner_validation')
        self.assertEqual(tuple(query.columns), sources.pipeline.MEMBERSHIP_COLUMNS)
        self.assertEqual(list(query.order_id), list(original.order_id))
        self.assertTrue(query.loc[:, list(sources.FUTURE_QUERY_COLUMNS)].isna().all().all())
        self.assertTrue(original.y.notna().all())
        for name in ['outer_fold', 'role', 'fit_at', 'order_id', 'prediction_time']:
            pd.testing.assert_series_equal(query[name], original[name])
        pd.testing.assert_frame_equal(original, result.role_block('2017-12', 'inner_validation'))

    def test_prediction_cannot_request_training_or_unknown_calendar(self):
        result = bundle()
        for fold, role in [('2017-12', 'inner_train_pool'), ('2019-01', 'outer_evaluation')]:
            with self.assertRaises(ValueError):
                result.prediction_block(fold, role)
        with self.assertRaises(ValueError):
            result.role_block('2017-12', 'unexpected')

    def test_frame_and_metadata_properties_are_defensive_copies(self):
        result = bundle()
        raw = result.raw_orders
        raw.loc[0, 'order_purchase_timestamp'] = 'tampered'
        membership = result.membership
        membership.loc[0, 'y'] = 1
        audit = result.dataset_audit
        audit['order_quality']['source_orders'] = 0
        spec = result.baseline_spec
        spec['synthetic'] = False
        summary = result.summary
        summary['role_blocks'] = 0
        self.assertNotEqual(result.raw_orders.loc[0, 'order_purchase_timestamp'], 'tampered')
        self.assertEqual(result.membership.loc[0, 'y'], 0)
        self.assertGreater(result.dataset_audit['order_quality']['source_orders'], 0)
        self.assertTrue(result.baseline_spec['synthetic'])
        self.assertEqual(result.summary['role_blocks'], 12)

    def test_dropped_raw_label_or_role_rows_cannot_shrink_denominators(self):
        raw, labels, membership, spec, audit = fixture()
        for changed in [(raw.iloc[:-1], labels, membership),
                        (raw, labels.iloc[:-1], membership),
                        (raw, labels, membership.iloc[:-1])]:
            with self.assertRaises(ValueError):
                sources._validate_loaded_frames(*changed, spec, audit)

    def test_training_unknown_cannot_be_filled_and_answer_at_fit_is_unavailable(self):
        raw, labels, membership, spec, audit = fixture()
        unknown = membership.loc[(membership.outer_fold == '2017-12')
                                 & (membership.role == 'inner_train_pool') & membership.y.isna()].index[0]
        changed = membership.copy()
        changed.loc[unknown, 'y'] = 0
        with self.assertRaises(ValueError):
            sources._validate_loaded_frames(raw, labels, changed, spec, audit)
        known = membership.loc[(membership.outer_fold == '2017-12')
                               & (membership.role == 'inner_train_pool') & membership.y.notna()].index[0]
        changed = membership.copy()
        changed.loc[known, 'first_visible_answer_at'] = changed.loc[known, 'fit_at']
        with self.assertRaises(ValueError):
            sources._validate_loaded_frames(raw, labels, changed, spec, audit)

    def test_raw_whitelist_and_changed_frozen_calendar_are_rejected(self):
        raw, labels, membership, spec, audit = fixture()
        with self.assertRaises(ValueError):
            sources._validate_loaded_frames(raw.assign(review_score=1), labels, membership, spec, audit)
        changed = deepcopy(spec)
        changed['calendar_split_plan'][0]['inner_fit_at'] = '2017-10-01 00:00:00'
        with self.assertRaises(ValueError):
            sources._validate_loaded_frames(raw, labels, membership, changed, audit)

    def test_snapshot_public_and_private_descriptors_are_copied_and_reverified(self):
        runtime = sources.ROOT / '.runtime'
        runtime.mkdir(exist_ok=True)
        with tempfile.TemporaryDirectory(dir=runtime) as directory:
            root = Path(directory)
            public, private = root / 'public', root / 'private'
            public.write_bytes(b'public-source')
            private.write_bytes(b'private-source')
            result = bundle(root, [sources.dataset.descriptor(public, root)],
                            [sources.dataset.descriptor(private, root)])
            self.assertEqual(result.verify_stable(), {'public_bound_files': 1,
                                                       'private_bound_files': 1, 'unchanged': True})
            copied = result.private_sources
            copied[0]['sha256'] = 'changed'
            result.verify_stable()
            private.write_bytes(b'tampered')
            with self.assertRaises(ValueError):
                result.verify_stable()

    def test_changed_parent_pin_fails_before_following_raw_or_private_guards(self):
        runtime = sources.ROOT / '.runtime'
        runtime.mkdir(exist_ok=True)
        with tempfile.TemporaryDirectory(dir=runtime) as directory:
            root = Path(directory)
            for name in sources.PARENT_SHAS:
                path = root / name
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(b'{}\n')
            with patch.object(sources.baseline, 'verify_contract', side_effect=AssertionError('not reached')):
                with self.assertRaises(ValueError):
                    sources._frozen_provenance(root)

    def test_provenance_failure_stops_before_parsing_any_raw_rows(self):
        with (patch.object(sources, '_frozen_provenance', side_effect=ValueError('changed guard')),
              patch.object(sources.pd, 'read_csv') as read):
            with self.assertRaises(ValueError):
                sources.load_verified_sources()
        read.assert_not_called()

    def test_loader_checks_sources_after_reading_and_never_writes_an_old_artifact(self):
        runtime = sources.ROOT / '.runtime'
        runtime.mkdir(exist_ok=True)
        with tempfile.TemporaryDirectory(dir=runtime) as directory:
            root = Path(directory)
            public = root / 'public-source'
            public.write_bytes(b'frozen')
            private_dir = root / sources.dataset.PRIVATE
            private_dir.mkdir(parents=True)
            for name in ['order_labels.csv', 'split_membership.csv']:
                (private_dir / name).write_bytes(b'synthetic-reader-fixture')
            raw, labels, membership, spec, audit = fixture()
            descriptor = sources.dataset.descriptor(public, root)
            values = iter([labels, membership])
            def read_and_change(*args):
                public.write_bytes(b'changed-after-preflight')
                return next(values)
            with patch.object(sources, '_frozen_provenance', return_value=(
                    {'synthetic': True}, spec, audit, [descriptor], [])), patch.object(
                    sources.pd, 'read_csv', return_value=raw), patch.object(
                    sources.dataset, 'read_private_csv', side_effect=read_and_change):
                with self.assertRaises(ValueError):
                    sources.load_verified_sources(root)
            self.assertEqual((private_dir / 'order_labels.csv').read_bytes(), b'synthetic-reader-fixture')
            self.assertEqual((private_dir / 'split_membership.csv').read_bytes(), b'synthetic-reader-fixture')


if __name__ == '__main__':
    unittest.main()
