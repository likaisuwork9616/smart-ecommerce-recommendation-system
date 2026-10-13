"""Predeclared ranking candidates and historical-only daily-budget selection."""
from __future__ import annotations

import warnings

import numpy as np
import pandas as pd
from lightgbm import LGBMClassifier
from sklearn.ensemble import RandomForestClassifier
from xgboost import XGBClassifier
from threadpoolctl import threadpool_limits

from scripts.compare_waiting_strategies import CANDIDATES as LEGACY_CANDIDATES
from scripts.compare_waiting_strategies import feature_names as legacy_feature_names
from scripts.compare_waiting_strategies import prepare_input as legacy_prepare_input
from scripts.compare_calibration_budget import alert_metrics, batch_audit
from scripts.delay_budget_features import NUMERIC_FEATURES, CATEGORICAL_FEATURES, prepare_budget_input
from scripts.delay_calibration_policy import apply_alert_policy
from scripts.train_delay_model import make_pipeline, positive_probability

NEW_CANDIDATES = ('lightgbm_route', 'xgboost_route', 'lightgbm_budget', 'xgboost_budget',
                  'lightgbm_budget_weighted', 'random_forest_budget')
ALL_CANDIDATES = (*LEGACY_CANDIDATES, *NEW_CANDIDATES)
SELECTION_GROUPS = {'legacy_candidates': LEGACY_CANDIDATES,
                    'boosted_route_only': ('lightgbm_route', 'xgboost_route'),
                    'budget_features_only': ('lightgbm_budget', 'xgboost_budget', 'lightgbm_budget_weighted', 'random_forest_budget'),
                    'all_candidates': ALL_CANDIDATES}
PRIMARY_SELECTION = 'all_candidates'
CAP = .10
MIN_RECALL = .30


def parameter_report(parameters):
    """Represent estimator NaN defaults explicitly in strict JSON reports."""
    if isinstance(parameters, dict):
        return {k: parameter_report(v) for k, v in parameters.items()}
    if isinstance(parameters, (tuple, list)):
        return [parameter_report(v) for v in parameters]
    if isinstance(parameters, np.generic):
        parameters = parameters.item()
    if isinstance(parameters, float) and not np.isfinite(parameters):
        return 'NaN' if np.isnan(parameters) else ('Infinity' if parameters > 0 else '-Infinity')
    return parameters


def feature_names(candidate):
    if candidate in LEGACY_CANDIDATES:
        return legacy_feature_names(candidate)
    if candidate not in NEW_CANDIDATES:
        raise ValueError(f'Unknown candidate: {candidate}')
    if candidate.endswith('_route'):
        return legacy_feature_names('random_forest_route')
    return list(NUMERIC_FEATURES), list(CATEGORICAL_FEATURES)


def prepare_input(frame, candidate):
    if candidate in LEGACY_CANDIDATES:
        return legacy_prepare_input(frame, candidate)
    if candidate not in NEW_CANDIDATES:
        raise ValueError(f'Unknown candidate: {candidate}')
    return legacy_prepare_input(frame, 'random_forest_route') if candidate.endswith('_route') else prepare_budget_input(frame)


def make_candidate(candidate, seed=42, n_jobs=4):
    """Fixed parameters; no evaluation-based early stopping or search."""
    if candidate not in NEW_CANDIDATES or n_jobs < 1:
        raise ValueError('Require a new candidate and n_jobs >= 1')
    if candidate.startswith('lightgbm'):
        classifier = LGBMClassifier(n_estimators=400, learning_rate=.05, num_leaves=31,
            min_child_samples=60, subsample=.8, subsample_freq=1, colsample_bytree=.8,
            reg_lambda=10., class_weight='balanced' if candidate.endswith('_weighted') else None,
            random_state=seed, n_jobs=n_jobs, verbosity=-1, deterministic=True, force_col_wise=True)
    elif candidate.startswith('xgboost'):
        classifier = XGBClassifier(n_estimators=400, learning_rate=.05, max_depth=4,
            min_child_weight=10., subsample=.8, colsample_bytree=.8, reg_lambda=10.,
            objective='binary:logistic', eval_metric='logloss', tree_method='hist',
            random_state=seed, n_jobs=n_jobs)
    else:
        classifier = RandomForestClassifier(n_estimators=200, max_depth=14, min_samples_leaf=8,
            class_weight='balanced_subsample', random_state=seed, n_jobs=n_jobs)
    pipeline = make_pipeline(classifier, scale_numeric=False)
    numeric, categorical = feature_names(candidate)
    preprocessor = pipeline.named_steps['preprocessor']
    old = preprocessor.transformers
    preprocessor.set_params(transformers=[(old[0][0], old[0][1], numeric), (old[1][0], old[1][1], categorical)])
    return pipeline


def fit_version(train, scoring, candidate, seed=42, n_jobs=4):
    """Only training features/labels enter preprocessing and classifier fit."""
    pipeline = make_candidate(candidate, seed, n_jobs)
    with threadpool_limits(limits=n_jobs), warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter('always')
        pipeline.fit(prepare_input(train, candidate), train.delayed)
        pipeline.set_params(classifier__n_jobs=1)
        values = positive_probability(pipeline, prepare_input(scoring, candidate))
    if not np.isfinite(values).all() or ((values < 0) | (values > 1)).any():
        raise ValueError('Invalid ranking scores')
    return pipeline, values, {'classifier_parameters': parameter_report(pipeline.named_steps['classifier'].get_params(deep=False)),
        'training_jobs': n_jobs, 'prediction_jobs': 1,
        'fit_warnings': sorted({f'{w.category.__name__}: {w.message}' for w in caught})}


def score_validation(frame, scores, cutoff):
    """Full-day capacity first; known outcomes only for historical metrics."""
    known = (pd.to_datetime(frame.label_available_time) < pd.Timestamp(cutoff)).to_numpy()
    labels = pd.to_numeric(frame.loc[known, 'delayed'], errors='raise').to_numpy(dtype=float)
    if not np.array_equal(np.unique(labels), [0., 1.]):
        raise ValueError('Each historical validation month requires both known classes')
    values = np.asarray(scores)
    selected = apply_alert_policy(frame, values, 0., CAP, raw_scores=values)
    return {'known_outcome_metrics': alert_metrics(labels, values[known], selected[known]),
            'full_batch': batch_audit(frame, selected, CAP, known)}


def select_candidate(results, candidates, candidate_order=None):
    """Maximize worst historical month recall, then pooled TP/AP; fixed ties."""
    if not candidates or not set(candidates).issubset(results):
        raise ValueError('Require available candidates')
    order = ALL_CANDIDATES if candidate_order is None else candidate_order
    def key(candidate):
        r = results[candidate]
        return (-r['minimum_validation_month_recall'], -r['validation_true_positives'],
                -r['validation_pooled_average_precision'], order.index(candidate))
    return min(candidates, key=key)


def decide_ranking_fold(validation_months, validation_scores, evaluation, evaluation_scores, cutoff,
                        candidate_order=None, selection_groups=None):
    """Freeze selections using three earlier monthly model versions only."""
    order = ALL_CANDIDATES if candidate_order is None else tuple(candidate_order)
    groups = SELECTION_GROUPS if selection_groups is None else selection_groups
    boundary = pd.Timestamp(cutoff)
    if len(validation_months) != 3 or len(validation_scores) != 3:
        raise ValueError('Require three full historical OOT months')
    months, identities = [], set()
    for frame in validation_months:
        dates = pd.to_datetime(frame.prediction_time).dt.to_period('M')
        if frame.empty or dates.nunique() != 1 or dates.iloc[0].end_time >= boundary:
            raise ValueError('Historical validation months must end before selection')
        if frame.order_id.isna().any() or frame.order_id.duplicated().any() or identities & set(frame.order_id):
            raise ValueError('Historical order identities must be unique and disjoint')
        identities.update(frame.order_id)
        months.append(str(dates.iloc[0]))
    if len(set(months)) != 3 or months != sorted(months):
        raise ValueError('Require three ordered distinct historical months')
    e_dates = pd.to_datetime(evaluation.prediction_time)
    if evaluation.empty or e_dates.dt.to_period('M').nunique() != 1 or e_dates.min().to_period('M').start_time != boundary:
        raise ValueError('Evaluation must be the month beginning at cutoff')
    if evaluation.order_id.isna().any() or evaluation.order_id.duplicated().any() or identities & set(evaluation.order_id):
        raise ValueError('Evaluation identities must be unique and disjoint')
    results = {}
    for candidate in order:
        by_month = {month: score_validation(frame, scores[candidate], boundary)
                    for month, frame, scores in zip(months, validation_months, validation_scores, strict=True)}
        cms = [np.array(m['known_outcome_metrics']['confusion_matrix']) for m in by_month.values()]
        pooled_cm = np.sum(cms, axis=0)
        # Pooled AP is a secondary tie-breaker; min monthly recall drives selection.
        ys, ps = [], []
        for frame, scores in zip(validation_months, validation_scores, strict=True):
            known = (pd.to_datetime(frame.label_available_time) < boundary).to_numpy()
            ys.extend(pd.to_numeric(frame.loc[known, 'delayed'], errors='raise').tolist())
            ps.extend(np.asarray(scores[candidate])[known].tolist())
        from sklearn.metrics import average_precision_score
        minimum = min(m['known_outcome_metrics']['recall'] for m in by_month.values())
        results[candidate] = {'validation_by_month': by_month,
            'minimum_validation_month_recall': minimum,
            'all_validation_months_meet_30_percent': minimum >= MIN_RECALL,
            'validation_true_positives': int(pooled_cm[1, 1]),
            'validation_false_positives': int(pooled_cm[0, 1]),
            'validation_pooled_average_precision': float(average_precision_score(ys, ps))}
    selections = {name: select_candidate(results, candidates, order) for name, candidates in groups.items()}
    # Frozen. No evaluation scores or outcomes have entered selection above.
    for candidate in order:
        values = np.asarray(evaluation_scores[candidate])
        selected = apply_alert_policy(evaluation, values, 0., CAP, raw_scores=values)
        results[candidate]['development_evaluation'] = alert_metrics(evaluation.delayed, values, selected)
        results[candidate]['evaluation_batch'] = batch_audit(evaluation, selected, CAP)
    return {'selected_models': selections, 'models': results}


def summarize(folds, candidate_order=None, selection_groups=None):
    order = ALL_CANDIDATES if candidate_order is None else tuple(candidate_order)
    groups = SELECTION_GROUPS if selection_groups is None else selection_groups
    summary = []
    for name in (*order, *groups):
        choices = [f['experiment']['selected_models'][name] if name in groups else name for f in folds]
        entries = [f['experiment']['models'][c] for f, c in zip(folds, choices, strict=True)]
        tn, fp, fn, tp = np.sum([np.array(e['development_evaluation']['confusion_matrix']).ravel() for e in entries], axis=0).tolist()
        summary.append({'model_or_selection': name, 'selected_candidates': choices, 'rows': tn + fp + fn + tp,
            'false_positives': fp, 'true_positives': tp, 'false_negatives': fn, 'true_negatives': tn,
            'alerts': fp + tp, 'precision': tp / (tp + fp), 'recall': tp / (tp + fn),
            'minimum_development_month_recall': min(e['development_evaluation']['recall'] for e in entries),
            'minimum_validation_month_recall': min(e['minimum_validation_month_recall'] for e in entries),
            'validation_folds_below_30_percent': [f['name'] for f, e in zip(folds, entries, strict=True) if not e['all_validation_months_meet_30_percent']],
            'development_recall_by_month': {f['name']: e['development_evaluation']['recall'] for f, e in zip(folds, entries, strict=True)}})
    return summary
