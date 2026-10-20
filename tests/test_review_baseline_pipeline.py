"""Synthetic-only leakage and fail-closed pipeline tests; no real files or metrics."""
from copy import deepcopy
import unittest
from unittest.mock import patch

import numpy as np
import pandas as pd
from sklearn.exceptions import ConvergenceWarning

from scripts import review_baseline_pipeline as pipeline


def fixture():
    ids = ['a', 'b', 'c', 'd', 'u', 'q1', 'q2', 'q3']
    approval = pd.to_datetime(['2017-06-10 12:00:00'] * 5 +
                              ['2017-09-02 00:00:00', '2017-09-18 23:00:00', '2017-09-30 12:00:00'])
    waits = pd.to_timedelta([0, 2, 4, 6, 1000, 1, 1, 1], unit='h')
    raw = pd.DataFrame({'order_id': ids, 'order_purchase_timestamp': approval - waits,
                        'order_approved_at': approval})
    membership = pd.DataFrame({'outer_fold': '2017-12',
                               'role': ['inner_train_pool'] * 5 + ['inner_validation'] * 3,
                               'fit_at': pd.Timestamp('2017-09-01'), 'order_id': ids,
                               'prediction_time': approval,
                               'window_deadline': approval + pd.Timedelta(days=60),
                               'observation_cutoff': pd.Timestamp('2017-09-01'),
                               'horizon_complete': [True] * 5 + [False] * 3,
                               'label_state': ['known_other_3_5', 'known_low_1_2'] * 2 +
                                              ['no_visible_answer_at_cutoff'] * 4,
                               'role_label_usable': [True] * 4 + [False] * 4,
                               'y': pd.Series([0, 1, 0, 1, pd.NA, pd.NA, pd.NA, pd.NA], dtype='Int64'),
                               'first_visible_answer_at': pd.to_datetime(['2017-06-11'] * 4 + [None] * 4)})
    return raw, membership.loc[:, list(pipeline.MEMBERSHIP_COLUMNS)]


def model(raw=None, membership=None, C=1.0, context=None):
    default_raw, default_membership = fixture()
    raw = default_raw if raw is None else raw
    membership = default_membership if membership is None else membership
    context = context or pipeline.freeze_approval_roster(raw, context_version='synthetic-v1')
    result = pipeline.GuardedReviewBaseline(C, context=context)
    result.fit_orders(raw, membership, outer_fold='2017-12', role='inner_train_pool')
    return result


def transformed(result, raw, membership):
    return result.transform_orders(raw, membership, outer_fold='2017-12', role='inner_validation')


def predicted(result, raw, membership):
    return result.predict_orders(raw, membership, outer_fold='2017-12', role='inner_validation')


class ReviewBaselinePipelineTest(unittest.TestCase):
    def test_builder_exact_four_order_raw_hours_and_source_id_order(self):
        raw, _ = fixture()
        features = pipeline.build_primary_features(raw, ['d', 'a'])
        self.assertEqual(tuple(features.columns), pipeline.PRIMARY)
        self.assertEqual(list(features.index), ['d', 'a'])
        self.assertEqual(list(features.approval_wait_hours), [6.0, 0.0])
        self.assertEqual(features.loc['a', 'purchase_month'], 6.0)
        self.assertEqual(features.loc['a', 'purchase_dayofweek'], 5.0)
        self.assertEqual(features.loc['a', 'purchase_hour'], 12.0)
        self.assertTrue(all(dtype == np.dtype('float64') for dtype in features.dtypes))

    def test_requested_missing_duplicate_invalid_clock_never_silently_dropped(self):
        raw, _ = fixture()
        for ids in [['absent'], ['a', 'a']]:
            with self.assertRaises(ValueError):
                pipeline.build_primary_features(raw, ids)
        for column in ['order_purchase_timestamp', 'order_approved_at']:
            broken = raw.copy()
            broken.loc[0, column] = pd.NaT
            with self.assertRaises(ValueError):
                pipeline.build_primary_features(broken, ['a'])
        broken = raw.copy()
        broken.loc[0, 'order_purchase_timestamp'] += pd.Timedelta(hours=1)
        with self.assertRaises(ValueError):
            pipeline.build_primary_features(broken, ['a'])

    def test_extra_future_source_fields_cannot_enter_X(self):
        raw, _ = fixture()
        original = pipeline.build_primary_features(raw)
        raw['review_score'] = 1
        raw['order_status'] = 'delivered'
        raw['actual_delivery'] = '2099-01-01'
        raw['target_metadata'] = 'forbidden'
        pd.testing.assert_frame_equal(original, pipeline.build_primary_features(raw))

    def test_future_raw_target_and_status_mutation_cannot_change_fitted_model(self):
        raw, membership = fixture()
        first = model()
        raw['review_score'] = [1, 5, 2, 4, 1, 5, 2, 1]
        raw['order_status'] = 'canceled'
        raw['actual_delivery'] = '2099-01-01'
        second = model(raw, membership)
        for name in ['coefficient_values', 'intercept_values', 'scaler_mean', 'scaler_variance']:
            np.testing.assert_array_equal(first.audit_state()[name], second.audit_state()[name])
        pd.testing.assert_series_equal(predicted(first, raw, membership), predicted(second, raw, membership))

    def test_direct_X_extra_and_permuted_schema_rejected(self):
        raw, _ = fixture()
        features = pipeline.build_primary_features(raw)
        for changed in [features.iloc[:, ::-1], features.assign(y=1), features.drop(columns=['purchase_hour'])]:
            with self.assertRaises(ValueError):
                pipeline.validate_primary_features(changed)

    def test_direct_X_nonfinite_category_wait_dtype_rejected(self):
        raw, _ = fixture()
        features = pipeline.build_primary_features(raw)
        for name, value in [('purchase_month', 13), ('purchase_dayofweek', 0.5), ('purchase_hour', 24),
                             ('approval_wait_hours', -1), ('approval_wait_hours', np.inf), ('purchase_month', np.nan)]:
            changed = features.copy()
            changed.loc['a', name] = value
            with self.assertRaises(ValueError):
                pipeline.validate_primary_features(changed)
        changed = features.astype('int64')
        with self.assertRaises(ValueError):
            pipeline.validate_primary_features(changed)

    def test_scaler_only_eligible_rows_ddof0_and_fixed44(self):
        raw, membership = fixture()
        result = model()
        state = result.audit_state()
        self.assertEqual(state['eligible_order_ids'], ('a', 'b', 'c', 'd'))
        self.assertEqual(state['scaler_samples'], 4)
        np.testing.assert_allclose(state['scaler_mean'], [3.0])
        np.testing.assert_allclose(state['scaler_variance'], [5.0])
        np.testing.assert_allclose(state['scaler_scale'], [np.sqrt(5)])
        values = transformed(result, raw, membership)
        self.assertEqual(values.shape, (3, 44))
        self.assertEqual(tuple(values.columns), pipeline.OUTPUT_COLUMNS)
        self.assertEqual(list(values.index), ['q1', 'q2', 'q3'])
        np.testing.assert_allclose(values.iloc[:, :43].sum(axis=1), [3, 3, 3])

    def test_unknown_outlier_never_changes_scaler_or_estimator(self):
        raw, membership = fixture()
        first = model()
        altered = raw.copy()
        altered.loc[altered.order_id == 'u', 'order_purchase_timestamp'] -= pd.Timedelta(hours=8000)
        second = model(altered, membership)
        for name in ['scaler_mean', 'scaler_variance', 'scaler_scale', 'coefficient_values', 'intercept_values']:
            np.testing.assert_array_equal(first.audit_state()[name], second.audit_state()[name])
        pd.testing.assert_series_equal(predicted(first, raw, membership), predicted(second, altered, membership))

    def test_zero_variance_scale_one(self):
        raw, membership = fixture()
        raw.loc[raw.order_id.isin(['a', 'b', 'c', 'd']), 'order_purchase_timestamp'] = pd.Timestamp('2017-06-10 10:00:00')
        state = model(raw, membership).audit_state()
        np.testing.assert_array_equal(state['scaler_variance'], [0.0])
        np.testing.assert_array_equal(state['scaler_scale'], [1.0])

    def test_query_future_target_metadata_never_read_even_inconsistent(self):
        raw, membership = fixture()
        result = model()
        original_values = transformed(result, raw, membership)
        original_probabilities = predicted(result, raw, membership)
        altered = membership.copy()
        query = altered.role.eq('inner_validation')
        for name in ['y', 'label_state', 'role_label_usable', 'horizon_complete', 'first_visible_answer_at',
                     'window_deadline', 'observation_cutoff']:
            altered[name] = altered[name].astype(object)
            altered.loc[query, name] = 'unavailable-inconsistent-future-target'
        pd.testing.assert_frame_equal(original_values, transformed(result, raw, altered))
        pd.testing.assert_series_equal(original_probabilities, predicted(result, raw, altered))

    def test_query_own_time_after_fit_and_unseen_legal_categories_retained(self):
        raw, membership = fixture()
        result = model()
        query = membership.loc[membership.role == 'inner_validation']
        self.assertTrue(query.prediction_time.ge(pd.Timestamp('2017-09-01')).all())
        probabilities = predicted(result, raw, query)
        self.assertEqual(list(probabilities.index), ['q1', 'q2', 'q3'])
        self.assertTrue(np.isfinite(probabilities).all())
        self.assertTrue(probabilities.between(0, 1).all())

    def test_subset_query_drop_from_both_inputs_rejected_by_independent_context(self):
        raw, membership = fixture()
        result = model()
        truncated_raw = raw.loc[raw.order_id != 'q3']
        truncated_membership = membership.loc[membership.order_id != 'q3']
        with self.assertRaises(ValueError):
            predicted(result, truncated_raw, truncated_membership)
        self.assertEqual(result.state, 'FAILED')

    def test_unknown_invalid_raw_clock_stops_before_fitting_or_dropping(self):
        raw, membership = fixture()
        context = pipeline.freeze_approval_roster(raw, context_version='v1')
        raw.loc[raw.order_id == 'u', 'order_purchase_timestamp'] = pd.NaT
        result = pipeline.GuardedReviewBaseline(context=context)
        with self.assertRaises(ValueError):
            result.fit_orders(raw, membership, outer_fold='2017-12', role='inner_train_pool')
        self.assertEqual(result.state, 'FAILED')
        self.assertNotIn('coefficient_values', result.audit_state())

    def test_train_ID_in_query_roster_is_rejected(self):
        raw, membership = fixture()
        extra = membership.iloc[[0]].copy()
        extra['role'] = 'inner_validation'
        changed = pd.concat([membership, extra])
        result = model()
        with self.assertRaises(ValueError):
            predicted(result, raw, changed)
        self.assertEqual(result.state, 'FAILED')

    def test_independent_context_copies_input_and_returned_frame(self):
        raw, membership = fixture()
        expected = raw[['order_id', 'order_approved_at']].rename(columns={'order_approved_at': 'prediction_time'})
        context = pipeline.ApprovalRosterContext(expected, context_version='synthetic-v1')
        expected.loc[0, 'order_id'] = 'tampered'
        returned = context.to_frame()
        returned.loc[0, 'order_id'] = 'also-tampered'
        result = model(raw, membership, context=context)
        self.assertEqual(result.state, 'FITTED')
        self.assertNotIn('tampered', [row[0] for row in context.rows])

    def test_membership_missing_extra_duplicate_or_clock_drift_rejected(self):
        raw, membership = fixture()
        changes = [membership.loc[membership.order_id != 'a'], pd.concat([membership, membership.iloc[:1]])]
        changed = membership.copy()
        changed.loc[0, 'prediction_time'] += pd.Timedelta(seconds=1)
        changes.append(changed)
        for changed in changes:
            instance = pipeline.GuardedReviewBaseline(context=pipeline.freeze_approval_roster(raw, context_version='v1'))
            with self.assertRaises(ValueError):
                instance.fit_orders(raw, changed, outer_fold='2017-12', role='inner_train_pool')
            self.assertEqual(instance.state, 'FAILED')

    def test_unknown_y_imputation_and_inconsistent_masks_rejected(self):
        raw, membership = fixture()
        changes = []
        for name, value in [('y', 0), ('role_label_usable', True), ('label_state', 'known_other_3_5')]:
            changed = membership.copy()
            changed.loc[4, name] = value
            changes.append(changed)
        for changed in changes:
            with self.assertRaises(ValueError):
                model(raw, changed)

    def test_unknown_reason_metadata_must_match_observable_training_clocks(self):
        raw, membership = fixture()
        for state in ['immature_observation_window', 'late_answer_unknown', 'first_answer_not_after_approval']:
            changed = membership.copy()
            changed.loc[4, 'label_state'] = state
            with self.assertRaises(ValueError):
                model(raw, changed)
        changed = membership.copy()
        changed.loc[4, 'first_visible_answer_at'] = pd.Timestamp('2017-06-12')
        with self.assertRaises(ValueError):
            model(raw, changed)

    def test_answer_equal_fit_or_before_approval_or_after_H_stops_fit(self):
        raw, membership = fixture()
        for answer in [pd.Timestamp('2017-09-01'), pd.Timestamp('2017-06-10 12:00:00'), pd.Timestamp('2017-08-10')]:
            changed = membership.copy()
            changed.loc[0, 'first_visible_answer_at'] = answer
            with self.assertRaises(ValueError):
                model(raw, changed)

    def test_answer_equal_H_endpoint_is_allowed_when_window_mature(self):
        raw, membership = fixture()
        membership.loc[0, 'first_visible_answer_at'] = membership.loc[0, 'window_deadline']
        self.assertEqual(model(raw, membership).state, 'FITTED')

    def test_H_deadline_equal_fit_not_mature(self):
        raw, membership = fixture()
        new_t = pd.Timestamp('2017-09-01') - pd.Timedelta(days=60)
        raw.loc[raw.order_id == 'a', ['order_purchase_timestamp', 'order_approved_at']] = new_t
        membership.loc[0, 'prediction_time'] = new_t
        membership.loc[0, 'window_deadline'] = pd.Timestamp('2017-09-01')
        membership.loc[0, 'first_visible_answer_at'] = new_t + pd.Timedelta(days=1)
        # Canonical order changes after moving a into July.
        train = membership.loc[membership.role == 'inner_train_pool'].sort_values(['prediction_time', 'order_id'])
        membership = pd.concat([train, membership.loc[membership.role == 'inner_validation']])
        with self.assertRaises(ValueError):
            model(raw, membership)

    def test_both_classes_required_without_fallback(self):
        raw, membership = fixture()
        membership.loc[:3, 'y'] = 0
        membership.loc[:3, 'label_state'] = 'known_other_3_5'
        with self.assertRaises(ValueError):
            model(raw, membership)

    def test_query_role_cannot_fit_wrong_context_cannot_score(self):
        raw, membership = fixture()
        instance = pipeline.GuardedReviewBaseline(context=pipeline.freeze_approval_roster(raw, context_version='v1'))
        with self.assertRaises(ValueError):
            instance.fit_orders(raw, membership, outer_fold='2017-12', role='inner_validation')
        self.assertEqual(instance.state, 'FAILED')
        fitted = model()
        with self.assertRaises(ValueError):
            fitted.predict_orders(raw, membership, outer_fold='2017-12', role='outer_evaluation')
        self.assertEqual(fitted.state, 'FAILED')

    def test_refit_failure_discards_model_and_fresh_instance_isolated(self):
        raw, membership = fixture()
        first, second = model(), model(C=0.1)
        second_before = second.audit_state()['coefficient_values'].copy()
        with self.assertRaises(ValueError):
            first.fit_orders(raw, membership, outer_fold='2017-12', role='inner_train_pool')
        self.assertEqual(first.state, 'FAILED')
        self.assertNotIn('coefficient_values', first.audit_state())
        np.testing.assert_array_equal(second_before, second.audit_state()['coefficient_values'])
        with self.assertRaises(ValueError):
            predicted(first, raw, membership)

    def test_fresh_outer_refit_uses_later_eligible_history_and_own_scaler(self):
        raw, membership = fixture()
        context = pipeline.freeze_approval_roster(raw, context_version='v1')
        inner = model(raw, membership, context=context)
        before = inner.audit_state()
        outer_membership = membership.copy()
        outer_membership['role'] = 'outer_train_pool'
        outer_membership['fit_at'] = pd.Timestamp('2017-12-01')
        outer_membership['observation_cutoff'] = pd.Timestamp('2017-12-01')
        outer_membership['horizon_complete'] = True
        outer_membership.loc[5:, 'role_label_usable'] = True
        outer_membership.loc[5:, 'y'] = pd.Series([0, 1, 0], index=[5, 6, 7], dtype='Int64')
        outer_membership.loc[5:, 'label_state'] = ['known_other_3_5', 'known_low_1_2', 'known_other_3_5']
        outer_membership.loc[5:, 'first_visible_answer_at'] = outer_membership.loc[5:, 'prediction_time'] + pd.Timedelta(days=1)
        outer = pipeline.GuardedReviewBaseline(context=context)
        outer.fit_orders(raw, outer_membership, outer_fold='2017-12', role='outer_train_pool')
        after = outer.audit_state()
        self.assertEqual(after['scaler_samples'], 7)
        np.testing.assert_allclose(after['scaler_mean'], [15 / 7])
        np.testing.assert_allclose(after['scaler_variance'], [188 / 49])
        self.assertEqual(after['fit_context'], ('2017-12', 'outer_train_pool', pd.Timestamp('2017-12-01')))
        self.assertEqual(before['fit_context'][1], 'inner_train_pool')
        np.testing.assert_array_equal(before['scaler_mean'], inner.audit_state()['scaler_mean'])
        np.testing.assert_array_equal(before['coefficient_values'], inner.audit_state()['coefficient_values'])

    def test_readonly_C_and_diagnostic_copies_no_estimator_handle(self):
        result = model()
        with self.assertRaises(AttributeError):
            result.C = 10.0
        state = result.audit_state()
        state['scaler_mean'][0] = 999
        state['coefficient_values'][:] = 999
        self.assertEqual(result.audit_state()['scaler_mean'][0], 3.0)
        self.assertFalse(np.all(result.audit_state()['coefficient_values'] == 999))
        self.assertNotIn('estimator', state)
        for value in [0, 0.5, 100, True, np.nan]:
            with self.assertRaises(ValueError):
                pipeline.GuardedReviewBaseline(value, context=pipeline.freeze_approval_roster(fixture()[0], context_version='v1'))

    def test_frozen_constructor_parameters_and_no_deprecated_arguments(self):
        original = pipeline.LogisticRegression
        with patch.object(pipeline, 'LogisticRegression', wraps=original) as constructor:
            model(C=10.0)
        self.assertEqual(constructor.call_args.kwargs, {
            'C': 10.0, 'l1_ratio': 0.0, 'solver': 'lbfgs', 'dual': False,
            'tol': 1e-8, 'max_iter': 1000, 'fit_intercept': True, 'class_weight': None,
            'random_state': 42, 'warm_start': False, 'verbose': 0})

    def test_convergence_warning_discards_local_fit(self):
        raw, membership = fixture()
        instance = pipeline.GuardedReviewBaseline(context=pipeline.freeze_approval_roster(raw, context_version='v1'))
        with patch.object(pipeline.LogisticRegression, 'fit', side_effect=ConvergenceWarning('synthetic')):
            with self.assertRaises(ConvergenceWarning):
                instance.fit_orders(raw, membership, outer_fold='2017-12', role='inner_train_pool')
        self.assertEqual(instance.state, 'FAILED')
        self.assertNotIn('coefficient_values', instance.audit_state())

    def test_nonfinite_coefficients_stop_without_retries(self):
        raw, membership = fixture()
        original = pipeline.LogisticRegression.fit
        def broken(estimator, X, y):
            original(estimator, X, y)
            estimator.coef_[0, 0] = np.nan
            return estimator
        instance = pipeline.GuardedReviewBaseline(context=pipeline.freeze_approval_roster(raw, context_version='v1'))
        with patch.object(pipeline.LogisticRegression, 'fit', broken):
            with self.assertRaises(ValueError):
                instance.fit_orders(raw, membership, outer_fold='2017-12', role='inner_train_pool')
        self.assertEqual(instance.state, 'FAILED')

    def test_nonfinite_or_out_of_range_probability_stops_context(self):
        raw, membership = fixture()
        for value in [np.nan, -0.1, 1.1]:
            result = model()
            with patch.object(pipeline.LogisticRegression, 'predict_proba', return_value=np.full((3, 2), value)):
                with self.assertRaises(ValueError):
                    predicted(result, raw, membership)
            self.assertEqual(result.state, 'FAILED')

    def test_probability_rows_must_sum_one_with_fixed_tolerance(self):
        raw, membership = fixture()
        result = model()
        with patch.object(pipeline.LogisticRegression, 'predict_proba', return_value=np.full((3, 2), 0.8)):
            with self.assertRaises(ValueError):
                predicted(result, raw, membership)
        self.assertEqual(result.state, 'FAILED')
        self.assertEqual(pipeline.PROBABILITY_SUM_ATOL, 1e-12)

    def test_complete_pinned_software_versions_enforced_before_fit(self):
        raw, _ = fixture()
        context = pipeline.freeze_approval_roster(raw, context_version='v1')
        original = pipeline.importlib.metadata.version
        def changed(name):
            return 'unsupported' if name == 'numpy' else original(name)
        with patch.object(pipeline.importlib.metadata, 'version', side_effect=changed):
            with self.assertRaises(ValueError):
                pipeline.GuardedReviewBaseline(context=context)


if __name__ == '__main__':
    unittest.main()
