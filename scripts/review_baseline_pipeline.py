"""Primary-four builder and guarded fit-once baseline; no real-data CLI."""
from __future__ import annotations

import importlib.metadata
from dataclasses import dataclass
import platform
import warnings

import numpy as np
import pandas as pd
from sklearn.exceptions import ConvergenceWarning
from sklearn.linear_model import LogisticRegression
from sklearn.preprocessing import OneHotEncoder, StandardScaler

PRIMARY = ('purchase_month', 'purchase_dayofweek', 'purchase_hour', 'approval_wait_hours')
RAW_COLUMNS = ('order_id', 'order_purchase_timestamp', 'order_approved_at')
MEMBERSHIP_COLUMNS = ('outer_fold', 'role', 'fit_at', 'order_id', 'prediction_time',
                      'window_deadline', 'observation_cutoff', 'horizon_complete',
                      'label_state', 'role_label_usable', 'y', 'first_visible_answer_at')
STATES = {'known_low_1_2', 'known_other_3_5', 'immature_observation_window',
          'unpositionable_answer_source_quality', 'invalid_visible_review_quality',
          'ambiguous_first_answer_tie', 'first_answer_not_after_approval',
          'late_answer_unknown', 'no_visible_answer_at_cutoff'}
INNER_MONTHS = {'2017-12': '2017-09', '2018-02': '2017-11', '2018-04': '2017-12'}
CANDIDATES = (0.1, 1.0, 10.0)
SOFTWARE_VERSIONS = {'python': '3.12.10', 'numpy': '2.5.4', 'pandas': '3.0.6', 'scikit-learn': '1.9.1'}
PROBABILITY_SUM_ATOL = 1e-12
OUTPUT_COLUMNS = tuple([f'purchase_month_{x}' for x in range(1, 13)]
                       + [f'purchase_dayofweek_{x}' for x in range(7)]
                       + [f'purchase_hour_{x}' for x in range(24)]
                       + ['scaled_approval_wait_hours'])


@dataclass(frozen=True, slots=True, init=False)
class ApprovalRosterContext:
    """Independent immutable roster reference; upstream completeness is a caller duty."""

    rows: tuple
    context_version: str

    def __init__(self, expected_roster, *, context_version):
        if (not isinstance(expected_roster, pd.DataFrame)
                or tuple(expected_roster.columns) != ('order_id', 'prediction_time')
                or not isinstance(context_version, str) or not context_version):
            raise ValueError('A versioned ID/approval-time roster reference is required')
        ids = expected_roster.order_id
        times = _clock(expected_roster.prediction_time)
        if (ids.isna().any() or ids.duplicated().any()
                or not ids.map(lambda value: isinstance(value, str) and bool(value)).all()
                or times.isna().any() or not times.lt(pd.Timestamp('2018-05-01')).all()):
            raise ValueError('Roster reference must contain unique valid primary-cohort IDs/times')
        frame = pd.DataFrame({'order_id': ids.to_numpy(), 'prediction_time': times.to_numpy()})
        frame = frame.sort_values(['prediction_time', 'order_id'])
        object.__setattr__(self, 'rows', tuple(frame.itertuples(index=False, name=None)))
        object.__setattr__(self, 'context_version', context_version)

    def to_frame(self):
        return pd.DataFrame(self.rows, columns=['order_id', 'prediction_time'])


def _clock(values):
    result = pd.to_datetime(values, format='%Y-%m-%d %H:%M:%S', errors='coerce')
    if isinstance(result.dtype, pd.DatetimeTZDtype):
        raise ValueError('Only the original naive event clock is supported')
    return result


def _source(orders):
    if not isinstance(orders, pd.DataFrame) or not set(RAW_COLUMNS).issubset(orders.columns):
        raise ValueError('Raw order ID and both event clocks are required')
    if orders.columns.duplicated().any():
        raise ValueError('Duplicate raw source columns')
    frame = orders.loc[:, list(RAW_COLUMNS)].copy()
    ids = frame.order_id
    if ids.isna().any() or not ids.map(lambda value: isinstance(value, str) and bool(value)).all() or ids.duplicated().any():
        raise ValueError('Raw order IDs must be nonempty unique strings')
    frame['purchase_time'] = _clock(frame.order_purchase_timestamp)
    frame['prediction_time'] = _clock(frame.order_approved_at)
    return frame.set_index('order_id', drop=False)


def _requested(source, ids):
    ids = list(source.index) if ids is None else list(ids)
    if len(set(ids)) != len(ids) or any(not isinstance(value, str) or not value for value in ids):
        raise ValueError('Requested IDs must be nonempty unique strings')
    if not set(ids).issubset(source.index):
        raise ValueError('A requested order is missing from the source')
    frame = source.loc[ids]
    if (frame.purchase_time.isna().any() or frame.prediction_time.isna().any()
            or frame.prediction_time.lt(frame.purchase_time).any()):
        raise ValueError('Every requested order requires valid purchase<=approval clocks')
    return frame


def _primary_roster(source):
    valid = (source.purchase_time.notna() & source.prediction_time.notna()
             & source.prediction_time.ge(source.purchase_time)
             & source.prediction_time.lt(pd.Timestamp('2018-05-01')))
    return source.loc[valid, ['order_id', 'prediction_time']].reset_index(drop=True).sort_values(
        ['prediction_time', 'order_id']).reset_index(drop=True)


def freeze_approval_roster(raw_orders, *, context_version):
    """Call once with a separately trusted complete source, before query slicing."""
    return ApprovalRosterContext(_primary_roster(_source(raw_orders)), context_version=context_version)


def validate_primary_features(features):
    if not isinstance(features, pd.DataFrame) or tuple(features.columns) != PRIMARY:
        raise ValueError('Primary feature schema and order must match the frozen four')
    if features.index.name != 'order_id' or features.index.has_duplicates or features.index.isna().any():
        raise ValueError('Feature order IDs must form a unique nonmissing index')
    if any(dtype != np.dtype('float64') for dtype in features.dtypes):
        raise ValueError('Every primary feature must have float64 dtype')
    values = features.to_numpy()
    if not np.isfinite(values).all():
        raise ValueError('Missing and nonfinite features stop the fold')
    for name, start, stop in [('purchase_month', 1, 12), ('purchase_dayofweek', 0, 6), ('purchase_hour', 0, 23)]:
        column = features[name].to_numpy()
        if ((column < start) | (column > stop) | (column != np.floor(column))).any():
            raise ValueError('Calendar category is outside the fixed vocabulary')
    if features.approval_wait_hours.lt(0).any():
        raise ValueError('Approval wait must be nonnegative raw hours')
    return features


def build_primary_features(raw_orders, requested_order_ids=None):
    """Build only requested rows; never join labels or silently filter a row."""
    source = _source(raw_orders)
    frame = _requested(source, requested_order_ids)
    result = pd.DataFrame(index=frame.index)
    result['purchase_month'] = frame.purchase_time.dt.month.astype('float64')
    result['purchase_dayofweek'] = frame.purchase_time.dt.dayofweek.astype('float64')
    result['purchase_hour'] = frame.purchase_time.dt.hour.astype('float64')
    result['approval_wait_hours'] = (frame.prediction_time - frame.purchase_time).dt.total_seconds().div(3600).astype('float64')
    return validate_primary_features(result.loc[:, list(PRIMARY)])


def _plan(outer_fold, role):
    if outer_fold not in INNER_MONTHS:
        raise ValueError('Outer fold is outside the frozen development calendar')
    outer = pd.Timestamp(outer_fold + '-01')
    inner = pd.Timestamp(INNER_MONTHS[outer_fold] + '-01')
    if role == 'inner_train_pool':
        return None, inner, inner
    if role == 'outer_train_pool':
        return None, outer, outer
    if role == 'inner_validation':
        return inner, inner + pd.offsets.MonthBegin(1), inner
    if role == 'outer_evaluation':
        return outer, outer + pd.offsets.MonthBegin(1), outer
    raise ValueError('Unknown role')


def _role_block(raw_orders, membership, outer_fold, role, context):
    if not isinstance(membership, pd.DataFrame) or tuple(membership.columns) != MEMBERSHIP_COLUMNS:
        raise ValueError('Frozen membership schema must match exactly')
    start, end, fit_at = _plan(outer_fold, role)
    source = _source(raw_orders)
    actual_roster = _primary_roster(source)
    reference = context.to_frame()
    if (list(actual_roster.order_id) != list(reference.order_id)
            or not actual_roster.prediction_time.equals(reference.prediction_time)):
        raise ValueError('Raw full primary roster differs from the independent frozen context')
    in_role = reference.prediction_time.lt(end)
    if start is not None:
        in_role &= reference.prediction_time.ge(start)
    expected = reference.loc[in_role]
    block = membership.loc[(membership.outer_fold == outer_fold) & (membership.role == role)].copy()
    if block.empty or block.order_id.isna().any() or block.order_id.duplicated().any():
        raise ValueError('Role must contain a nonempty unique order roster')
    if list(block.order_id) != list(expected.order_id):
        raise ValueError('Role roster must retain the full canonical calendar denominator')
    predictions = _clock(block.prediction_time)
    if not predictions.reset_index(drop=True).equals(expected.prediction_time.reset_index(drop=True)):
        raise ValueError('Membership own approval clock differs from raw source')
    if not _clock(block.fit_at).eq(fit_at).all():
        raise ValueError('Membership fit clock differs from the frozen context')
    _requested(source, block.order_id)
    return source, block.reset_index(drop=True), fit_at


def _training_eligibility(block, fit_at):
    prediction = _clock(block.prediction_time)
    deadline = _clock(block.window_deadline)
    cutoff = _clock(block.observation_cutoff)
    first = _clock(block.first_visible_answer_at)
    if not prediction.lt(fit_at).all() or not cutoff.eq(fit_at).all():
        raise ValueError('Training clocks must precede the role fit cutoff')
    if not deadline.eq(prediction + pd.Timedelta(days=60)).all():
        raise ValueError('Training H60 deadlines changed')
    for name in ('horizon_complete', 'role_label_usable'):
        if not block[name].map(lambda value: isinstance(value, (bool, np.bool_))).all():
            raise ValueError('Training masks must contain actual booleans')
    mature = deadline.lt(fit_at)
    if not block.horizon_complete.eq(mature).all():
        raise ValueError('Training maturity must use deadline strictly before fit')
    usable = block.role_label_usable.astype(bool)
    if not block.label_state.isin(STATES).all():
        raise ValueError('Unknown training label state')
    known = block.label_state.isin(['known_low_1_2', 'known_other_3_5'])
    if not usable.eq(known).all():
        raise ValueError('Training state and usability disagree')
    if block.loc[~usable, 'y'].notna().any() or block.loc[usable, 'y'].isna().any():
        raise ValueError('Unknown targets must remain nullable and cannot fit')
    y = pd.to_numeric(block.y, errors='coerce')
    if not y.loc[usable].isin([0, 1]).all() or block.loc[usable, 'y'].map(lambda value: isinstance(value, (bool, np.bool_))).any():
        raise ValueError('Eligible targets must be numeric binary labels')
    if (not block.loc[y.eq(1).fillna(False), 'label_state'].eq('known_low_1_2').all()
            or not block.loc[y.eq(0).fillna(False), 'label_state'].eq('known_other_3_5').all()):
        raise ValueError('Training class and label state disagree')
    visible = block.first_visible_answer_at.notna()
    if (visible & (first.isna() | first.ge(fit_at))).any():
        raise ValueError('Training answer metadata is invalid or not visible before fit')
    if (block.label_state.eq('no_visible_answer_at_cutoff') & first.notna()).any():
        raise ValueError('No-visible-answer training state contradicts its visible answer')
    if (block.label_state.eq('immature_observation_window') & mature).any():
        raise ValueError('Immature training state contradicts the H60 maturity flag')
    if (block.label_state.eq('late_answer_unknown') & ~(first.notna() & first.gt(deadline))).any():
        raise ValueError('Late-answer training state requires a visible answer after H60')
    if (block.label_state.eq('first_answer_not_after_approval') & ~(first.notna() & first.le(prediction))).any():
        raise ValueError('Early-answer training state contradicts its first answer')
    eligible_clock = mature & first.gt(prediction) & first.le(deadline) & first.lt(fit_at)
    if (usable & ~eligible_clock).any():
        raise ValueError('Eligible training label violates maturity or first-answer bounds')
    if not set(y.loc[usable].astype(int)) == {0, 1}:
        raise ValueError('Both classes are required in eligible training rows')
    return usable, y.loc[usable].astype('int64').to_numpy()


class GuardedReviewBaseline:
    """Fit once on one guarded context; query target metadata is never inspected."""

    __slots__ = ('__C', '__state', '__encoder', '__scaler', '__estimator', '__context', '__fit_ids', '__pool_ids', '__roster')

    def __init__(self, C=1.0, *, context):
        if isinstance(C, (bool, np.bool_)) or C not in CANDIDATES:
            raise ValueError('C must be one frozen candidate')
        versions = {'python': platform.python_version()}
        versions.update({name: importlib.metadata.version(name) for name in SOFTWARE_VERSIONS if name != 'python'})
        if versions != SOFTWARE_VERSIONS:
            raise ValueError('The frozen baseline requires the complete pinned software versions')
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
        categorical = self.__encoder.transform(features.loc[:, list(PRIMARY[:3])])
        numeric = self.__scaler.transform(features.loc[:, [PRIMARY[3]]])
        result = np.concatenate([categorical, numeric], axis=1)
        if result.shape != (len(features), 44) or not np.isfinite(result).all():
            raise ValueError('Transformed features must be finite fixed-width44')
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
            encoder = OneHotEncoder(categories=[np.arange(1, 13), np.arange(7), np.arange(24)],
                                    drop=None, handle_unknown='error', sparse_output=False, dtype=np.float64)
            scaler = StandardScaler(with_mean=True, with_std=True)
            estimator = LogisticRegression(C=self.__C, l1_ratio=0.0, solver='lbfgs', dual=False,
                                           tol=1e-8, max_iter=1000, fit_intercept=True, class_weight=None,
                                           random_state=42, warm_start=False, verbose=0)
            with warnings.catch_warnings():
                warnings.simplefilter('error', ConvergenceWarning)
                categorical = encoder.fit_transform(features.loc[:, list(PRIMARY[:3])])
                numeric = scaler.fit_transform(features.loc[:, [PRIMARY[3]]])
                transformed = np.concatenate([categorical, numeric], axis=1)
                if transformed.shape[1] != 44 or not np.isfinite(transformed).all():
                    raise ValueError('Training transform is not finite width44')
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
