"""Month-only ablation builder and fit-once pipeline; no real-data CLI.

The frozen four-feature module remains the shared authority for raw clocks,
complete role rosters, H60 eligibility and software versions. This module owns
the three-feature construction and estimator state; it never builds month X.
"""
from __future__ import annotations

import importlib.metadata
import platform
import warnings

import numpy as np
import pandas as pd
from sklearn.exceptions import ConvergenceWarning
from sklearn.linear_model import LogisticRegression
from sklearn.preprocessing import OneHotEncoder, StandardScaler

from scripts.review_baseline_pipeline import (
    ApprovalRosterContext, CANDIDATES, INNER_MONTHS, MEMBERSHIP_COLUMNS,
    PROBABILITY_SUM_ATOL, RAW_COLUMNS, SOFTWARE_VERSIONS,
    _requested, _role_block, _source, _training_eligibility,
    freeze_approval_roster,
)


PRIMARY = ('purchase_dayofweek', 'purchase_hour', 'approval_wait_hours')
OUTPUT_COLUMNS = tuple([f'purchase_dayofweek_{x}' for x in range(7)]
                       + [f'purchase_hour_{x}' for x in range(24)]
                       + ['scaled_approval_wait_hours'])


def validate_primary_features(features):
    if not isinstance(features, pd.DataFrame) or tuple(features.columns) != PRIMARY:
        raise ValueError('Primary feature schema and order must match the frozen three')
    if features.index.name != 'order_id' or features.index.has_duplicates or features.index.isna().any():
        raise ValueError('Feature order IDs must form a unique nonmissing index')
    if any(dtype != np.dtype('float64') for dtype in features.dtypes):
        raise ValueError('Every primary feature must have float64 dtype')
    values = features.to_numpy()
    if not np.isfinite(values).all():
        raise ValueError('Missing and nonfinite features stop the fold')
    for name, start, stop in [('purchase_dayofweek', 0, 6), ('purchase_hour', 0, 23)]:
        column = features[name].to_numpy()
        if ((column < start) | (column > stop) | (column != np.floor(column))).any():
            raise ValueError('Calendar category is outside the fixed vocabulary')
    if features.approval_wait_hours.lt(0).any():
        raise ValueError('Approval wait must be nonnegative raw hours')
    return features


def build_primary_features(raw_orders, requested_order_ids=None):
    """Build only requested rows; never construct month, join y or filter rows."""
    source = _source(raw_orders)
    frame = _requested(source, requested_order_ids)
    result = pd.DataFrame(index=frame.index)
    result['purchase_dayofweek'] = frame.purchase_time.dt.dayofweek.astype('float64')
    result['purchase_hour'] = frame.purchase_time.dt.hour.astype('float64')
    result['approval_wait_hours'] = (frame.prediction_time - frame.purchase_time).dt.total_seconds().div(3600).astype('float64')
    return validate_primary_features(result.loc[:, list(PRIMARY)])


class GuardedReviewMonthAblation:
    """Fit once on one guarded context; query target metadata is never inspected."""

    __slots__ = ('__C', '__state', '__encoder', '__scaler', '__estimator', '__context', '__fit_ids', '__pool_ids', '__roster')

    def __init__(self, C=1.0, *, context):
        if isinstance(C, (bool, np.bool_)) or C not in CANDIDATES:
            raise ValueError('C must be one frozen candidate')
        versions = {'python': platform.python_version()}
        versions.update({name: importlib.metadata.version(name) for name in SOFTWARE_VERSIONS if name != 'python'})
        if versions != SOFTWARE_VERSIONS:
            raise ValueError('The frozen ablation requires the complete pinned software versions')
        if not isinstance(context, ApprovalRosterContext):
            raise ValueError('An independent immutable approval roster context is required')
        self.__roster = context
        self.__C = float(C)
        self.__state = 'NEW'
        self.__encoder = self.__scaler = self.__estimator = None
        self.__context = None
        self.__fit_ids = self.__pool_ids = ()

    @property
    def C(self):
        return self.__C

    @property
    def state(self):
        return self.__state

    def __fail(self):
        self.__state = 'FAILED'
        self.__encoder = self.__scaler = self.__estimator = None
        self.__context = None
        self.__fit_ids = self.__pool_ids = ()

    def __transform(self, features):
        validate_primary_features(features)
        categorical = self.__encoder.transform(features.loc[:, list(PRIMARY[:2])])
        numeric = self.__scaler.transform(features.loc[:, [PRIMARY[2]]])
        result = np.concatenate([categorical, numeric], axis=1)
        if result.shape != (len(features), 32) or not np.isfinite(result).all():
            raise ValueError('Transformed features must be finite fixed-width32')
        return pd.DataFrame(result, index=features.index.copy(), columns=OUTPUT_COLUMNS)

    def fit_orders(self, raw_orders, frozen_membership, *, outer_fold, role):
        try:
            if self.__state != 'NEW':
                raise ValueError('Each candidate/context requires a new fit-once instance')
            self.__state = 'FITTING'
            if role not in ('inner_train_pool', 'outer_train_pool') or self.__C not in CANDIDATES:
                raise ValueError('Only frozen training roles and C candidates may fit')
            _, block, fit_at = _role_block(raw_orders, frozen_membership, outer_fold, role, self.__roster)
            usable, y = _training_eligibility(block, fit_at)
            # Validate every role source clock, then construct/fit only eligible X.
            features = build_primary_features(raw_orders, block.loc[usable, 'order_id'])
            encoder = OneHotEncoder(categories=[np.arange(7), np.arange(24)],
                                    drop=None, handle_unknown='error', sparse_output=False, dtype=np.float64)
            scaler = StandardScaler(with_mean=True, with_std=True)
            estimator = LogisticRegression(C=self.__C, l1_ratio=0.0, solver='lbfgs', dual=False,
                                           tol=1e-8, max_iter=1000, fit_intercept=True, class_weight=None,
                                           random_state=42, warm_start=False, verbose=0)
            with warnings.catch_warnings():
                warnings.simplefilter('error', ConvergenceWarning)
                categorical = encoder.fit_transform(features.loc[:, list(PRIMARY[:2])])
                numeric = scaler.fit_transform(features.loc[:, [PRIMARY[2]]])
                transformed = np.concatenate([categorical, numeric], axis=1)
                if transformed.shape[1] != 32 or not np.isfinite(transformed).all():
                    raise ValueError('Training transform is not finite width32')
                estimator.fit(transformed, y)
            if (not np.isfinite(estimator.coef_).all() or not np.isfinite(estimator.intercept_).all()
                    or set(estimator.classes_) != {0, 1}):
                raise ValueError('Fitted coefficients/classes violate the frozen contract')
            self.__encoder, self.__scaler, self.__estimator = encoder, scaler, estimator
            self.__context = (outer_fold, role, fit_at)
            self.__fit_ids = tuple(features.index)
            self.__pool_ids = tuple(block.order_id)
            self.__state = 'FITTED'
            return self
        except Exception:
            self.__fail()
            raise

    def __query_features(self, raw_orders, membership, outer_fold, role):
        if self.__state != 'FITTED':
            raise ValueError('No successful fitted context is available')
        expected_role = 'inner_validation' if self.__context[1] == 'inner_train_pool' else 'outer_evaluation'
        if outer_fold != self.__context[0] or role != expected_role:
            raise ValueError('Query must use the fitted context paired query role')
        _, block, fit_at = _role_block(raw_orders, membership, outer_fold, role, self.__roster)
        if fit_at != self.__context[2] or set(block.order_id) & set(self.__pool_ids):
            raise ValueError('Query context changed or train/query order overlap')
        # No query y/state/usability/first-answer/maturity/observation cutoff read here.
        return build_primary_features(raw_orders, block.order_id)

    def transform_orders(self, raw_orders, frozen_membership, *, outer_fold, role):
        try:
            features = self.__query_features(raw_orders, frozen_membership, outer_fold, role)
            with warnings.catch_warnings():
                warnings.simplefilter('error', ConvergenceWarning)
                return self.__transform(features)
        except Exception:
            self.__fail()
            raise

    def predict_orders(self, raw_orders, frozen_membership, *, outer_fold, role):
        try:
            transformed = self.transform_orders(raw_orders, frozen_membership, outer_fold=outer_fold, role=role)
            with warnings.catch_warnings():
                warnings.simplefilter('error', ConvergenceWarning)
                probabilities = self.__estimator.predict_proba(transformed.to_numpy())
            classes = self.__estimator.classes_
            positive = np.flatnonzero(classes == 1)
            if (probabilities.shape != (len(transformed), len(classes)) or len(positive) != 1
                    or not np.isfinite(probabilities).all() or (probabilities < 0).any()
                    or (probabilities > 1).any()
                    or not np.allclose(probabilities.sum(axis=1), 1.0, rtol=0, atol=PROBABILITY_SUM_ATOL)):
                raise ValueError('Predicted probabilities violate P(y=1) contract')
            return pd.Series(probabilities[:, positive[0]], index=transformed.index, name='probability_low_1_2')
        except Exception:
            self.__fail()
            raise

    def audit_state(self):
        result = {'state': self.__state, 'C': self.__C, 'fit_context': self.__context,
                  'context_version': self.__roster.context_version,
                  'eligible_order_ids': tuple(self.__fit_ids), 'train_pool_order_ids': tuple(self.__pool_ids),
                  'output_columns': OUTPUT_COLUMNS}
        if self.__state == 'FITTED':
            result.update({'scaler_mean': self.__scaler.mean_.copy(), 'scaler_variance': self.__scaler.var_.copy(),
                           'scaler_scale': self.__scaler.scale_.copy(),
                           'scaler_samples': int(self.__scaler.n_samples_seen_),
                           'coefficient_values': self.__estimator.coef_.copy(),
                           'intercept_values': self.__estimator.intercept_.copy(),
                           'classes': self.__estimator.classes_.copy()})
        return result
