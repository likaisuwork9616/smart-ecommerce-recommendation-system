"""Second prespecified round: unresolved-order context and daily ranking loss."""
from __future__ import annotations

import warnings

from lightgbm import LGBMClassifier, LGBMRanker
import numpy as np
import pandas as pd
from sklearn.base import BaseEstimator, ClassifierMixin
from sklearn.linear_model import LogisticRegression
from threadpoolctl import threadpool_limits
from xgboost import XGBClassifier

from scripts.delay_budget_training import ALL_CANDIDATES as ROUND1_CANDIDATES
from scripts.delay_budget_training import feature_names as round1_feature_names
from scripts.delay_budget_training import prepare_input as round1_prepare_input, parameter_report
from scripts.delay_pending_features import NUMERIC_FEATURES, CATEGORICAL_FEATURES, prepare_pending_input
from scripts.train_delay_model import make_pipeline, positive_probability

NEW_CANDIDATES = ('logistic_pending', 'lightgbm_pending', 'xgboost_pending', 'lambdarank_budget', 'lambdarank_pending')
ALL_CANDIDATES = (*ROUND1_CANDIDATES, *NEW_CANDIDATES)
SELECTION_GROUPS = {'round1_candidates': ROUND1_CANDIDATES,
                    'pending_classifiers': NEW_CANDIDATES[:3],
                    'daily_rankers': NEW_CANDIDATES[3:], 'all_candidates': ALL_CANDIDATES}


class DailyRankClassifier(ClassifierMixin, BaseEstimator):
    """Expose a ranker's monotone bounded score through the existing pipeline.

    Sigmoid(margin) is a numerical interface conversion, not fitted probability
    calibration. Day groups contain mature training rows only; no evaluation
    set or early stopping is passed into the ranker.
    """
    def __init__(self, n_estimators=400, learning_rate=.05, num_leaves=15,
                 min_child_samples=60, reg_lambda=10., random_state=42, n_jobs=4):
        self.n_estimators = n_estimators
        self.learning_rate = learning_rate
        self.num_leaves = num_leaves
        self.min_child_samples = min_child_samples
        self.reg_lambda = reg_lambda
        self.random_state = random_state
        self.n_jobs = n_jobs

    def fit(self, X, y, group=None):
        labels, sizes = np.asarray(y), np.asarray(group)
        if (labels.ndim != 1 or not np.array_equal(np.unique(labels), [0, 1]) or sizes.ndim != 1
                or not np.issubdtype(sizes.dtype, np.integer) or (sizes <= 0).any() or sizes.sum() != len(labels)):
            raise ValueError('Daily ranker requires binary mature labels and valid complete training day groups')
        self.classes_ = np.array([0, 1])
        self.n_features_in_ = X.shape[1]
        self.ranker_ = LGBMRanker(**self.get_params(), objective='lambdarank', label_gain=[0, 1],
            lambdarank_truncation_level=20, subsample=.8, subsample_freq=1, colsample_bytree=.8,
            deterministic=True, force_col_wise=True, verbosity=-1)
        self.ranker_.fit(X, labels, group=sizes.tolist())
        return self

    def predict_proba(self, X):
        margin = np.asarray(self.ranker_.predict(X, num_threads=self.n_jobs), dtype=float)
        if margin.ndim != 1 or not np.isfinite(margin).all():
            raise ValueError('Ranker margins must be a finite one-dimensional array')
        score = np.empty(len(margin), dtype=float)
        positive = margin >= 0
        score[positive] = 1 / (1 + np.exp(-margin[positive]))
        exp_negative = np.exp(margin[~positive])
        score[~positive] = exp_negative / (1 + exp_negative)
        order = np.argsort(margin, kind='stable')
        distinct = np.diff(margin[order]) > 0
        if (np.diff(score[order])[distinct] <= 0).any():
            raise ValueError('Rank score saturation would collapse distinct margins')
        return np.column_stack([1 - score, score])


def feature_names(candidate):
    if candidate in ROUND1_CANDIDATES:
        return round1_feature_names(candidate)
    if candidate not in NEW_CANDIDATES:
        raise ValueError(f'Unknown candidate: {candidate}')
    return round1_feature_names('lightgbm_budget') if candidate == 'lambdarank_budget' else (list(NUMERIC_FEATURES), list(CATEGORICAL_FEATURES))


def prepare_input(frame, candidate):
    if candidate in ROUND1_CANDIDATES:
        return round1_prepare_input(frame, candidate)
    if candidate not in NEW_CANDIDATES:
        raise ValueError(f'Unknown candidate: {candidate}')
    return round1_prepare_input(frame, 'lightgbm_budget') if candidate == 'lambdarank_budget' else prepare_pending_input(frame)


def make_candidate(candidate, seed=42, n_jobs=4):
    if candidate not in NEW_CANDIDATES or n_jobs < 1:
        raise ValueError('Require predefined pending/ranking candidate and positive n_jobs')
    if candidate.startswith('lambdarank'):
        classifier = DailyRankClassifier(random_state=seed, n_jobs=n_jobs)
    elif candidate.startswith('logistic'):
        classifier = LogisticRegression(class_weight='balanced', max_iter=2000, random_state=seed)
    elif candidate.startswith('lightgbm'):
        classifier = LGBMClassifier(n_estimators=400, learning_rate=.05, num_leaves=31,
            min_child_samples=60, subsample=.8, subsample_freq=1, colsample_bytree=.8,
            reg_lambda=10., random_state=seed, n_jobs=n_jobs, verbosity=-1,
            deterministic=True, force_col_wise=True)
    else:
        classifier = XGBClassifier(n_estimators=400, learning_rate=.05, max_depth=4,
            min_child_weight=10., subsample=.8, colsample_bytree=.8, reg_lambda=10.,
            objective='binary:logistic', eval_metric='logloss', tree_method='hist', random_state=seed, n_jobs=n_jobs)
    pipeline = make_pipeline(classifier, scale_numeric=candidate.startswith('logistic'))
    numeric, categorical = feature_names(candidate)
    preprocessor = pipeline.named_steps['preprocessor']
    old = preprocessor.transformers
    preprocessor.set_params(transformers=[(old[0][0], old[0][1], numeric), (old[1][0], old[1][1], categorical)])
    return pipeline


def fit_version(train, scoring, candidate, seed=42, n_jobs=4):
    pipeline = make_candidate(candidate, seed, n_jobs)
    # Consecutive day groups are required by LambdaRank; sort without future outcomes.
    training = train.sort_values(['prediction_time', 'order_id'], kind='stable').reset_index(drop=True)
    day_sizes = training.groupby(training.prediction_time.dt.normalize(), sort=True).size().to_numpy(dtype=int)
    params = {'classifier__group': day_sizes} if candidate.startswith('lambdarank') else {}
    with threadpool_limits(limits=n_jobs), warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter('always')
        pipeline.fit(prepare_input(training, candidate), training.delayed, **params)
        if not candidate.startswith('logistic'):
            pipeline.set_params(classifier__n_jobs=1)
        values = positive_probability(pipeline, prepare_input(scoring, candidate))
    if not np.isfinite(values).all() or ((values < 0) | (values > 1)).any():
        raise ValueError('Invalid pending/ranking score')
    return pipeline, values, {'classifier_parameters': parameter_report(pipeline.named_steps['classifier'].get_params(deep=False)),
        'training_jobs': n_jobs,
        'prediction_jobs': n_jobs if candidate.startswith('logistic') else 1,
        'daily_training_groups': day_sizes.tolist() if params else None,
        'ranker_objective': 'lambdarank / binary gain [0,1] / truncation 20' if params else None,
        'fit_warnings': sorted({f'{w.category.__name__}: {w.message}' for w in caught})}
