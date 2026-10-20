"""Boundary, as-of, maturity, nested-calendar and immutable output contracts."""
from pathlib import Path
import tempfile
import unittest

import pandas as pd

from scripts import freeze_review_dataset as audit


def orders(times=('2018-01-02 00:00:00',), ids=None):
    ids = ids or ['one'] * len(times)
    return pd.DataFrame({'order_id': ids, 'customer_id': ['customer'] * len(times),
                         'order_purchase_timestamp': ['2016-01-01 00:00:00'] * len(times),
                         'order_approved_at': list(times)}, dtype='string')


def cohort(times=('2018-01-02 00:00:00',), ids=None):
    return audit.approval_cohort(orders(times, ids))[0]


def reviews(answers=('2018-01-03 00:00:00',), scores=('1',), ids=None):
    return pd.DataFrame({'review_id': ids or [f'r{i}' for i in range(len(answers))],
                         'order_id': ['one'] * len(answers), 'review_score': scores,
                         'review_creation_date': ['2018-01-01 00:00:00'] * len(answers),
                         'review_answer_timestamp': answers}, dtype='string')


def labels(data=None, cutoff='2018-07-01', roster=None):
    data = reviews() if data is None else data
    return audit.label_asof(cohort() if roster is None else roster,
                            audit.prepare_reviews(data)[0], cutoff)


class ReviewDatasetContractTest(unittest.TestCase):
    def test_no_review_unknown_never_negative(self):
        frame, summary = labels(reviews().iloc[:0])
        self.assertTrue(pd.isna(frame.y.iloc[0]))
        self.assertEqual(frame.label_state.iloc[0], 'no_visible_answer_at_cutoff')
        self.assertEqual(summary['unknown_or_ineligible_labels'], 1)

    def test_known_scores_binary_without_changing_input(self):
        for score, target in [('1', 1), ('2', 1), ('3', 0), ('5', 0)]:
            source = reviews(scores=(score,))
            original = source.copy(deep=True)
            frame, _ = labels(source)
            self.assertEqual(int(frame.y.iloc[0]), target)
            pd.testing.assert_frame_equal(source, original)

    def test_early_first_answer_cannot_repick_later(self):
        for early in ['2018-01-01 20:00:00', '2018-01-02 00:00:00']:
            frame, _ = labels(reviews((early, '2018-01-04 00:00:00'), ('5', '1')))
            self.assertTrue(pd.isna(frame.y.iloc[0]))
            self.assertEqual(frame.label_state.iloc[0], 'first_answer_not_after_approval')

    def test_earliest_tie_even_same_score_quarantines(self):
        frame, _ = labels(reviews(('2018-01-03 00:00:00',) * 2, ('1', '1')))
        self.assertEqual(frame.label_state.iloc[0], 'ambiguous_first_answer_tie')
        self.assertTrue(pd.isna(frame.y.iloc[0]))

    def test_duplicate_pair_quarantines_but_cross_order_reuse_allowed(self):
        data = reviews()
        frame, _ = labels(pd.concat([data, data], ignore_index=True))
        self.assertEqual(frame.label_state.iloc[0], 'invalid_visible_review_quality')
        frame, _ = labels(pd.concat([data, data.assign(order_id='other')], ignore_index=True))
        self.assertEqual(int(frame.y.iloc[0]), 1)

    def test_visible_invalid_in_window_quarantines_without_repick(self):
        for column, value in [('review_id', None), ('review_score', '1.5'),
                              ('review_score', 'invalid'), ('review_creation_date', None),
                              ('review_creation_date', '2018-01-05 00:00:00')]:
            source = reviews(('2018-01-03 00:00:00', '2018-01-04 00:00:00'), ('1', '5'))
            source.loc[1, column] = value
            with self.subTest(column=column, value=value):
                frame, _ = labels(source)
                self.assertEqual(frame.label_state.iloc[0], 'invalid_visible_review_quality')
                self.assertTrue(pd.isna(frame.y.iloc[0]))

    def test_parseable_future_bad_rows_never_quarantine_past_fit(self):
        source = reviews(('2018-01-03 00:00:00', '2018-03-05 00:00:00'), ('1', 'bad'))
        # Same key and missing creation are future-only at the fit cutoff.
        source.loc[1, 'review_id'] = source.loc[0, 'review_id']
        source.loc[1, 'review_creation_date'] = None
        frame, _ = labels(source, cutoff='2018-03-04')
        self.assertEqual(int(frame.y.iloc[0]), 1)

    def test_bad_rows_outside_horizon_never_taint_target(self):
        source = reviews(('2018-01-03 00:00:00', '2018-06-01 00:00:00'), ('1', 'bad'))
        source.loc[1, 'review_id'] = source.loc[0, 'review_id']
        frame, _ = labels(source)
        self.assertEqual(int(frame.y.iloc[0]), 1)

    def test_missing_answer_static_source_quality_quarantine(self):
        for answer in [None, 'bad-clock']:
            source = reviews(('2018-01-03 00:00:00', answer), ('1', '5'))
            frame, summary = labels(source)
            self.assertEqual(frame.label_state.iloc[0], 'unpositionable_answer_source_quality')
            self.assertFalse(summary['source_quality_quarantine_is_historical_availability_proof'])

    def test_deadline_equal_cutoff_immature_even_already_answered(self):
        deadline = cohort().window_deadline.iloc[0]
        frame, summary = labels(cutoff=deadline)
        self.assertFalse(frame.horizon_complete.iloc[0])
        self.assertTrue(pd.isna(frame.y.iloc[0]))
        self.assertEqual(summary['early_answered_but_immature_excluded'], 1)

    def test_horizon_endpoint_allowed_after_strict_maturity(self):
        deadline = cohort().window_deadline.iloc[0]
        source = reviews((str(deadline),))
        frame, _ = labels(source, cutoff=deadline + pd.Timedelta(seconds=1))
        self.assertEqual(int(frame.y.iloc[0]), 1)

    def test_answer_equal_cutoff_not_visible_and_no_future_reason_leak(self):
        source = reviews(('2018-03-04 00:00:00',))
        frame, _ = labels(source, cutoff='2018-03-04')
        self.assertEqual(frame.label_state.iloc[0], 'no_visible_answer_at_cutoff')
        self.assertTrue(pd.isna(frame.first_visible_answer_at.iloc[0]))
        self.assertTrue(pd.isna(frame.y.iloc[0]))

    def test_visible_answer_after_horizon_is_unknown_never_negative(self):
        frame, _ = labels(reviews(('2018-04-01 00:00:00',), ('5',)))
        self.assertEqual(frame.label_state.iloc[0], 'late_answer_unknown')
        self.assertTrue(pd.isna(frame.y.iloc[0]))

    def test_calendar_inner_latest_mature_full_month(self):
        plan = audit.calendar_split_plan()
        self.assertEqual([x['inner_query_start'][:7] for x in plan], ['2017-09', '2017-11', '2017-12'])
        for row in plan:
            outer = pd.Timestamp(row['outer_fit_at'])
            end = pd.Timestamp(row['inner_query_end_exclusive'])
            self.assertLessEqual(end + pd.Timedelta(days=60), outer)
            self.assertGreater(end + pd.offsets.MonthBegin(1) + pd.Timedelta(days=60), outer)

    def test_each_inner_fit_recomputes_availability_not_outer_labels(self):
        roster = cohort(('2017-07-15 00:00:00',), ['one'])
        source = reviews(('2017-09-10 00:00:00',))
        source.loc[:, 'review_creation_date'] = '2017-07-01 00:00:00'
        # This answer is within H60, but appears only after the inner fit.
        membership, folds = audit.build_membership(roster, audit.prepare_reviews(source)[0])
        first_inner = membership.loc[(membership.outer_fold == '2017-12') & (membership.role == 'inner_train_pool')]
        self.assertTrue(first_inner.first_visible_answer_at.isna().all())
        self.assertTrue(first_inner.y.isna().all())
        first_outer = membership.loc[(membership.outer_fold == '2017-12') & (membership.role == 'outer_train_pool')]
        self.assertEqual(list(first_outer.y), [1])
        self.assertTrue(all(not any(x['train_query_order_overlap'].values()) for x in folds))

    def test_all_query_ids_retained_unknowns_and_nested_role_coverage(self):
        roster = cohort(('2017-08-01 00:00:00', '2017-09-15 00:00:00',
                         '2017-12-02 00:00:00', '2018-02-02 00:00:00',
                         '2018-04-02 00:00:00'), ['old', 'inner', 'dec', 'feb', 'apr'])
        membership, folds = audit.build_membership(roster, audit.prepare_reviews(reviews().iloc[:0])[0])
        self.assertTrue(membership.y.isna().all())
        for month, order_id in [('2017-12', 'dec'), ('2018-02', 'feb'), ('2018-04', 'apr')]:
            block = membership.loc[(membership.outer_fold == month) & (membership.role == 'outer_evaluation')]
            self.assertEqual(list(block.order_id), [order_id])
        self.assertEqual(len(folds), 3)
        self.assertEqual(sum(len(row['roles']) for row in folds), 12)

    def test_cohort_preserves_status_and_missing_features_exclusive_cutoff(self):
        source = orders(('2018-04-30 23:59:59', '2018-05-01 00:00:00'), ['one', 'two'])
        source['order_status'] = 'canceled'
        source['some_feature'] = pd.NA
        result, quality = audit.approval_cohort(source)
        self.assertEqual(list(result.order_id), ['one'])
        self.assertFalse(quality['final_status_filter_applied'])
        source.loc[1, 'order_id'] = 'one'
        with self.assertRaises(ValueError):
            audit.approval_cohort(source)

    def test_exact_nullable_csv_readback_and_no_future_label_column(self):
        frame, _ = labels(reviews().iloc[:0])
        checked = audit.assert_exact_private(frame, audit.csv_bytes(frame))
        self.assertEqual(checked['exact_cells_compared'], len(audit.LABEL_COLUMNS))
        self.assertTrue(checked['nullable_y_mask_verified'])
        self.assertNotIn('first_score', frame.columns)
        corrupted = audit.csv_bytes(frame).replace(b',False,,', b',False,0,')
        with self.assertRaises(AssertionError):
            audit.assert_exact_private(frame, corrupted)

    def test_strict_json_source_guard_and_immutable_bundle_preflight(self):
        runtime = audit.ROOT / '.runtime'
        runtime.mkdir(exist_ok=True)
        with tempfile.TemporaryDirectory(dir=runtime) as directory:
            root = Path(directory)
            source = root / 'source'
            source.write_bytes(b'first')
            bound = audit.descriptor(source, root)
            self.assertEqual(audit.verify_sources([bound], root), 1)
            source.write_bytes(b'changed')
            with self.assertRaises(ValueError):
                audit.verify_sources([bound], root)
            output = root / 'test.json'
            audit.immutable_write(output, audit.json_bytes({'count': 1}))
            before = output.read_bytes()
            audit.immutable_write(output, audit.json_bytes({'count': 1}))
            self.assertEqual(before, output.read_bytes())
            with self.assertRaises(ValueError):
                audit.immutable_write(output, audit.json_bytes({'count': 2}))
            for data in [b'{"x": 1,"x": 2}', b'{"x": NaN}']:
                output.write_bytes(data)
                with self.assertRaises(ValueError):
                    audit.read_json(output)

    def test_private_path_must_be_ignored_runtime_and_bundle_fail_before_any_write(self):
        with self.assertRaises(ValueError):
            audit.safe_output(audit.ROOT / 'reports/private.csv', '', private=True)
        runtime = audit.ROOT / '.runtime'
        runtime.mkdir(exist_ok=True)
        with tempfile.TemporaryDirectory(dir=runtime) as directory:
            folder = Path(directory)
            labels_frame, _ = labels()
            membership, _ = audit.build_membership(cohort(), audit.prepare_reviews(reviews())[0])
            spec = {'protocol': audit.protocol(), 'sources': []}
            (folder / 'manifest.json').write_bytes(b'conflict')
            with self.assertRaises(ValueError):
                audit.write_private_bundle(labels_frame, membership, spec, directory=folder)
            self.assertFalse((folder / 'order_labels.csv').exists())
            self.assertFalse((folder / 'split_membership.csv').exists())

    def test_conflicting_public_report_blocks_all_private_writes(self):
        runtime = audit.ROOT / '.runtime'
        runtime.mkdir(exist_ok=True)
        with tempfile.TemporaryDirectory(dir=runtime) as directory:
            folder = Path(directory)
            output = folder / 'report.json'
            output.write_bytes(b'conflicting-public-report')
            labels_frame, _ = labels()
            membership, _ = audit.build_membership(cohort(), audit.prepare_reviews(reviews())[0])
            def preflight(outputs, checks):
                audit.immutable_preflight(output, audit.json_bytes({'new': 'report'}))
            with self.assertRaises(ValueError):
                audit.write_private_bundle(labels_frame, membership,
                                           {'protocol': audit.protocol(), 'sources': []},
                                           directory=folder / 'private', public_preflight=preflight)
            self.assertEqual(output.read_bytes(), b'conflicting-public-report')
            self.assertFalse((folder / 'private').exists())

    def test_private_manifest_binds_actual_spec_bytes_not_canonical_reencoding(self):
        runtime = audit.ROOT / '.runtime'
        runtime.mkdir(exist_ok=True)
        with tempfile.TemporaryDirectory(dir=runtime) as directory:
            folder = Path(directory)
            specification = folder / 'specification.json'
            specification.write_bytes(b'{ "x" : 1 }\n')
            actual_sha = audit.descriptor(specification)['sha256']
            labels_frame, _ = labels()
            membership, _ = audit.build_membership(cohort(), audit.prepare_reviews(reviews())[0])
            audit.write_private_bundle(labels_frame, membership,
                                       {'protocol': audit.protocol(), 'sources': []},
                                       directory=folder / 'private', specification_sha256=actual_sha)
            manifest = audit.read_json(folder / 'private/manifest.json')
            self.assertEqual(manifest['specification_sha256'], actual_sha)
            self.assertNotEqual(actual_sha, __import__('hashlib').sha256(audit.json_bytes({'x': 1})).hexdigest())

    def test_public_output_cannot_resolve_outside_project_root(self):
        with self.assertRaises(ValueError):
            audit.safe_output(audit.ROOT.parent / 'outside.json', '../outside.json')


if __name__ == '__main__':
    unittest.main()
