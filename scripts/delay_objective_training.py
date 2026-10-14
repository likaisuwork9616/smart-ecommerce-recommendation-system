"""Paired XGBoost classification and approval-day ranking objectives.

The two feature contracts and tree parameters are reused unchanged. Ranking
groups contain the supplied mature training rows for each approval day, not
the original complete day population. Sigmoid(margin) is solely a bounded
score interface; no probability calibration or future evaluation set is fit.
"""
from __future__ import annotations

import hashlib
import warnings

import numpy as np
import pandas as pd
from sklearn.base import BaseEstimator, ClassifierMixin
from sklearn.utils.validation import check_is_fitted
from threadpoolctl import threadpool_limits
from xgboost import XGBRanker

from scripts import delay_backlog_training as previous
from scripts.delay_budget_training import parameter_report
from scripts.train_delay_model import positive_probability


CLASSIFICATION_CANDIDATES = ('xgboost_engineering_geo', 'xgboost_backlog_7_14d')
NEW_CANDIDATES = ('xgboost_rank_geo', 'xgboost_rank_backlog_7_14d')
ALL_CANDIDATES = (*CLASSIFICATION_CANDIDATES, *NEW_CANDIDATES)
CANDIDATE_DESIGNS = {
    candidate: {
        'backbone_candidate': baseline,
        'feature_variant': variant,
        'family': 'xgboost',
        'training_objective': 'daily_ranking' if ranking else 'classification',
        'objective': 'rank:ndcg' if ranking else 'binary:logistic',
    }
    for variant, baseline, rank in zip(
        ('geo', 'backlog_7_14d'), CLASSIFICATION_CANDIDATES, NEW_CANDIDATES, strict=True)
    for candidate, ranking in ((baseline, False), (rank, True))
}


class DailyXGBRankClassifier(ClassifierMixin, BaseEstimator):
    """Expose XGBRanker margins as strictly monotone, uncalibrated scores."""

    def __init__(self, n_estimators=400, learning_rate=.05, max_depth=4,
                 min_child_weight=10., subsample=.8, colsample_bytree=.8,
                 reg_lambda=10., random_state=42, n_jobs=2, tree_method='hist',
                 objective='rank:ndcg', eval_metric='ndcg@20',
                 lambdarank_pair_method='topk', lambdarank_num_pair_per_sample=20,
                 ndcg_exp_gain=False):
        self.n_estimators = n_estimators
        self.learning_rate = learning_rate
        self.max_depth = max_depth
        self.min_child_weight = min_child_weight
        self.subsample = subsample
        self.colsample_bytree = colsample_bytree
        self.reg_lambda = reg_lambda
        self.random_state = random_state
        self.n_jobs = n_jobs
        self.tree_method = tree_method
        self.objective = objective
        self.eval_metric = eval_metric
        self.lambdarank_pair_method = lambdarank_pair_method
        self.lambdarank_num_pair_per_sample = lambdarank_num_pair_per_sample
        self.ndcg_exp_gain = ndcg_exp_gain

    def fit(self, X, y, group=None):
        labels, sizes = np.asarray(y), np.asarray(group)
        if (labels.ndim != 1 or not np.array_equal(np.unique(labels), [0, 1])
                or len(X.shape) != 2 or X.shape[0] != len(labels)
                or sizes.ndim != 1 or not np.issubdtype(sizes.dtype, np.integer)
                or (sizes <= 0).any() or sizes.sum() != len(labels)):
            raise ValueError('Daily XGBoost ranker requires binary mature labels and valid training day groups')
        if self.objective != 'rank:ndcg':
            raise ValueError('The paired ranking contrast requires rank:ndcg')
        if self.n_jobs < 1:
            raise ValueError('Require positive n_jobs')
        self.ranker_ = XGBRanker(**self.get_params(deep=False))
        # No eval_set, eval_group, early stopping, external weights or continuation.
        self.ranker_.fit(X, labels, group=sizes.tolist())
        self.classes_ = np.array([0, 1])
        self.n_features_in_ = X.shape[1]
        self.daily_training_groups_ = sizes.copy()
        return self

    def predict_margin(self, X):
        check_is_fitted(self, 'ranker_')
        # Pipeline.set_params after fitting changes the wrapper's prediction jobs.
        self.ranker_.set_params(n_jobs=self.n_jobs)
        margins = np.asarray(self.ranker_.predict(X, output_margin=True), dtype=float)
        if margins.ndim != 1 or len(margins) != X.shape[0] or not np.isfinite(margins).all():
            raise ValueError('XGBoost ranker margins must be finite and one-dimensional')
        return margins

    def predict_proba(self, X):
        margins = self.predict_margin(X)
        score = np.empty(len(margins), dtype=float)
        positive = margins >= 0
        score[positive] = 1 / (1 + np.exp(-margins[positive]))
        exp_negative = np.exp(margins[~positive])
        score[~positive] = exp_negative / (1 + exp_negative)
        order = np.argsort(margins, kind='stable')
        distinct = np.diff(margins[order]) > 0
        if ((score <= 0) | (score >= 1)).any() or (np.diff(score[order])[distinct] <= 0).any():
            raise ValueError('Rank score saturation would collapse margins or reach a bounded-score endpoint')
        return np.column_stack([1 - score, score])


def candidate_design(candidate):
    if candidate not in CANDIDATE_DESIGNS:
        raise ValueError(f'Unknown objective contrast candidate: {candidate}')
    return CANDIDATE_DESIGNS[candidate].copy()


def feature_names(candidate):
    return previous.feature_names(candidate_design(candidate)['backbone_candidate'])


def prepare_input(frame, candidate):
    return previous.prepare_input(frame, candidate_design(candidate)['backbone_candidate'])


def feature_set(candidate):
    return previous.feature_set(candidate_design(candidate)['backbone_candidate'])


def make_candidate(candidate, seed=42, n_jobs=2):
    """Keep the existing whitelist/preprocessing and every shared tree setting."""
    if n_jobs < 1:
        raise ValueError('Require positive n_jobs')
    design = candidate_design(candidate)
    pipeline = previous.make_candidate(design['backbone_candidate'], seed=seed, n_jobs=n_jobs)
    if candidate in NEW_CANDIDATES:
        baseline = pipeline.named_steps['classifier'].get_params(deep=False)
        shared = ('n_estimators', 'learning_rate', 'max_depth', 'min_child_weight',
                  'subsample', 'colsample_bytree', 'reg_lambda', 'random_state',
                  'n_jobs', 'tree_method')
        pipeline.set_params(classifier=DailyXGBRankClassifier(**{name: baseline[name] for name in shared}))
    return pipeline


def fit_version(train, scoring, candidate, seed=42, n_jobs=2):
    """Fit sorted mature rows once, then score without reading future outcomes."""
    design = candidate_design(candidate)
    if train.empty or train.order_id.isna().any() or train.order_id.duplicated().any():
        raise ValueError('Require nonempty unique training order identities')
    training = train.copy()
    training['prediction_time'] = pd.to_datetime(training.prediction_time, errors='raise')
    if training.prediction_time.isna().any():
        raise ValueError('Training approval times must be present')
    training = training.sort_values(['prediction_time', 'order_id'], kind='stable').reset_index(drop=True)
    day_sizes = training.groupby(training.prediction_time.dt.normalize(), sort=True).size().to_numpy(dtype=int)
    ranking = candidate in NEW_CANDIDATES
    params = {'classifier__group': day_sizes} if ranking else {}
    pipeline = make_candidate(candidate, seed, n_jobs)
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter('always')
        with threadpool_limits(limits=n_jobs):
            pipeline.fit(prepare_input(training, candidate), training.delayed, **params)
    pipeline.set_params(classifier__n_jobs=1)
    with threadpool_limits(limits=1):
        values = positive_probability(pipeline, prepare_input(scoring, candidate))
    if not np.isfinite(values).all() or ((values < 0) | (values > 1)).any():
        raise ValueError('Invalid objective contrast score')
    classifier = pipeline.named_steps['classifier']
    daily_labels = training.groupby(training.prediction_time.dt.normalize(), sort=True).delayed.agg(['size', 'sum'])
    query_counts = {
        'queries': len(daily_labels),
        'mixed_label_queries': int(((daily_labels['sum'] > 0) & (daily_labels['sum'] < daily_labels['size'])).sum()),
        'all_on_time_queries': int(daily_labels['sum'].eq(0).sum()),
        'all_delayed_queries': int(daily_labels['sum'].eq(daily_labels['size']).sum()),
    }
    report = {
        'classifier_parameters': parameter_report(classifier.get_params(deep=False)),
        'training_jobs': n_jobs,
        'prediction_jobs': 1,
        'training_design': 'deadline_wait0',
        'paired_model_family': design['family'],
        'paired_backbone_candidate': design['backbone_candidate'],
        'paired_feature_variant': design['feature_variant'],
        'training_objective': design['training_objective'],
        'training_order': 'prediction_time ascending, then order_id ascending; stable sort',
        'training_order_sha256': hashlib.sha256('\n'.join(training.order_id.astype(str)).encode('utf-8')).hexdigest(),
        'daily_training_groups': day_sizes.tolist() if ranking else None,
        'daily_training_query_counts': query_counts if ranking else None,
        'daily_training_group_semantics': 'mature supplied training rows grouped by approval calendar day' if ranking else None,
        'ranker_objective': 'rank:ndcg / binary gain [0,1] / topk 20 pair generation; separate daily floor(10% * N) alert policy' if ranking else None,
        'score_semantics': 'sigmoid(raw margin), strictly monotone uncalibrated ranking score' if ranking else 'binary:logistic classifier score',
        'fit_warnings': sorted({f'{warning.category.__name__}: {warning.message}' for warning in caught}),
    }
    if ranking:
        report['ranker_parameters'] = parameter_report(classifier.ranker_.get_params(deep=False))
    return pipeline, values, report
