"""Compare delay models with expanding-window development backtests only."""

from __future__ import annotations

import argparse
from collections import Counter
from importlib.metadata import PackageNotFoundError, version
import json
import math
from pathlib import Path
import platform
import sys
import time
import warnings

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from sklearn.base import clone
from sklearn.dummy import DummyClassifier
from sklearn.ensemble import ExtraTreesClassifier, HistGradientBoostingClassifier, RandomForestClassifier
from sklearn.linear_model import LogisticRegression
from threadpoolctl import threadpool_limits


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from scripts.delay_features import build_delay_dataset  # noqa: E402
from scripts.train_delay_model import (  # noqa: E402
    LABEL_METADATA,
    METADATA_COLUMNS,
    binary_metrics,
    choose_threshold,
    make_pipeline,
    positive_probability,
    prepare_features,
    source_manifest,
)


DEFAULT_OUTPUT = PROJECT_ROOT / "reports" / "stage4"
FIXED_TEST_START = pd.Timestamp("2018-05-26")
FOLDS = [
    {"name": "2017-12", "validation_start": "2017-10-01", "validation_end": "2017-11-01",
     "evaluation_start": "2017-12-01", "evaluation_end": "2018-01-01"},
    {"name": "2018-02", "validation_start": "2017-12-01", "validation_end": "2018-01-01",
     "evaluation_start": "2018-02-01", "evaluation_end": "2018-03-01"},
    {"name": "2018-04", "validation_start": "2018-02-01", "validation_end": "2018-03-01",
     "evaluation_start": "2018-04-01", "evaluation_end": "2018-05-01"},
]
MODEL_NAMES = (
    "dummy_most_frequent", "balanced_logistic_regression", "random_forest",
    "extra_trees", "hist_gradient_boosting", "xgboost", "lightgbm",
)
DISPLAY_NAMES = {
    "dummy_most_frequent": "Dummy (most frequent)",
    "balanced_logistic_regression": "Logistic regression",
    "random_forest": "Random forest",
    "extra_trees": "Extra trees",
    "hist_gradient_boosting": "Histogram gradient boosting",
    "xgboost": "XGBoost",
    "lightgbm": "LightGBM",
}
SUMMARY_METRICS = (
    "average_precision", "roc_auc", "f1", "recall", "precision",
    "balanced_accuracy", "accuracy", "ap_lift_over_prevalence",
)


def _validate_binary_target(target, name):
    series = pd.Series(target)
    if series.empty or not series.isin([0, 1]).all() or series.nunique() != 2:
        raise ValueError(f"{name} must contain both binary classes 0 and 1")


def split_backtest_fold(
    frame: pd.DataFrame, validation_start, evaluation_start, evaluation_end,
    *, validation_end=None,
):
    """Return train/validation/evaluation frames and counts with strict label cutoffs.

    Prediction intervals are left-closed/right-open whole days. Validation can
    finish before evaluation starts, leaving a label-maturation waiting period.
    Evaluation retains retrospectively completed labels regardless of when
    delivery occurred; its prediction dates never cross the original holdout.
    """
    val_start, eval_start, eval_end = map(pd.Timestamp, (validation_start, evaluation_start, evaluation_end))
    val_end = pd.Timestamp(validation_end) if validation_end is not None else eval_start
    boundaries = (val_start, val_end, eval_start, eval_end)
    if any(pd.isna(boundary) or boundary.tzinfo is not None or boundary != boundary.normalize()
           for boundary in boundaries):
        raise ValueError("Boundaries must be timezone-naive dates at midnight")
    if not val_start < val_end <= eval_start < eval_end:
        raise ValueError("Require validation_start < validation_end <= evaluation_start < evaluation_end")
    if eval_end > FIXED_TEST_START:
        raise ValueError("Backtest evaluation must end by the original fixed test start (2018-05-26)")
    missing = set(METADATA_COLUMNS).difference(frame.columns)
    if missing:
        raise ValueError(f"Missing metadata columns: {sorted(missing)}")
    frame = frame.copy()
    for name in ("order_purchase_timestamp", "prediction_time", "label_available_time"):
        frame[name] = pd.to_datetime(frame[name], errors="raise")
        if frame[name].isna().any() or frame[name].dt.tz is not None:
            raise ValueError(f"{name} must contain non-null timezone-naive timestamps")
    if frame["order_id"].isna().any() or frame["order_id"].duplicated().any():
        raise ValueError("Expected one row per non-null order_id")
    if not frame["delayed"].isin([0, 1]).all():
        raise ValueError("delayed must contain only binary classes 0 and 1")
    if (frame["label_available_time"] < frame["prediction_time"]).any():
        raise ValueError("Delivery labels cannot be available before prediction time")
    frame = frame.sort_values(["prediction_time", "order_id"], kind="stable").reset_index(drop=True)
    prediction_time = frame["prediction_time"]
    candidates = {
        "train": frame[prediction_time < val_start],
        "validation": frame[(prediction_time >= val_start) & (prediction_time < val_end)],
        "evaluation": frame[(prediction_time >= eval_start) & (prediction_time < eval_end)],
    }
    cutoffs = {"train": val_start, "validation": eval_start, "evaluation": None}
    report = {
        "validation_start": val_start.isoformat(), "validation_end": val_end.isoformat(),
        "evaluation_start": eval_start.isoformat(), "evaluation_end": eval_end.isoformat(),
        "validation_wait": {
            "start": val_end.isoformat(), "end": eval_start.isoformat(),
            "days": int((eval_start - val_end).days),
            "prediction_rows_not_assigned": int(((prediction_time >= val_end) & (prediction_time < eval_start)).sum()),
        },
        "partitions": {},
    }
    splits = {}
    for name, before in candidates.items():
        cutoff = cutoffs[name]
        retained = before if cutoff is None else before[before["label_available_time"] < cutoff]
        removed = before.loc[~before.index.isin(retained.index)]
        _validate_binary_target(retained["delayed"], name)
        splits[name] = retained.copy()
        partition = {
            "rows_before_purge": len(before),
            "positive_rows_before_purge": int(before["delayed"].sum()),
            "positive_rate_before_purge": float(before["delayed"].mean()),
            "purged_rows": len(removed),
            "purged_positive_rows": int(removed["delayed"].sum()),
            "purged_positive_rate": float(removed["delayed"].mean()) if len(removed) else None,
            "rows": len(retained),
            "positive_rows": int(retained["delayed"].sum()),
            "positive_rate": float(retained["delayed"].mean()),
            "positive_retention_rate": float(retained["delayed"].sum() / before["delayed"].sum()),
            "prediction_time_min": retained["prediction_time"].min().isoformat(),
            "prediction_time_max": retained["prediction_time"].max().isoformat(),
            "label_available_time_max": retained["label_available_time"].max().isoformat(),
            "label_maturity_cutoff": cutoff.isoformat() if cutoff is not None else None,
        }
        if name == "evaluation":
            partition["labels_not_yet_available_at_evaluation_end"] = int(
                (retained["label_available_time"] >= eval_end).sum()
            )
            partition["late_known_at_original_holdout_count"] = int(
                (retained["label_available_time"] >= FIXED_TEST_START).sum()
            )
        report["partitions"][name] = partition
    return splits, report


def make_candidates(y_train, seed=42, n_jobs=4):
    """Create seven fresh pipelines; boosting weights use this purged train only."""
    _validate_binary_target(y_train, "training target")
    if n_jobs < 1:
        raise ValueError("n_jobs must be positive; unlimited CPU settings are not supported")
    from lightgbm import LGBMClassifier
    from xgboost import XGBClassifier

    target = np.asarray(y_train)
    positive_weight = float(np.sum(target == 0) / np.sum(target == 1))
    candidates = {
        "dummy_most_frequent": make_pipeline(DummyClassifier(strategy="most_frequent"), False),
        "balanced_logistic_regression": make_pipeline(
            LogisticRegression(class_weight="balanced", max_iter=2000, random_state=seed), True
        ),
        "random_forest": make_pipeline(
            RandomForestClassifier(n_estimators=200, max_depth=14, min_samples_leaf=8,
                                   class_weight="balanced_subsample", n_jobs=n_jobs, random_state=seed), False
        ),
        "extra_trees": make_pipeline(
            ExtraTreesClassifier(n_estimators=200, max_depth=14, min_samples_leaf=8,
                                 class_weight="balanced", n_jobs=n_jobs, random_state=seed), False
        ),
        "hist_gradient_boosting": make_pipeline(
            HistGradientBoostingClassifier(max_iter=200, max_leaf_nodes=15, min_samples_leaf=20,
                                           l2_regularization=1.0, class_weight="balanced",
                                           early_stopping=False, random_state=seed), False
        ),
        "xgboost": make_pipeline(
            XGBClassifier(n_estimators=200, max_depth=4, min_child_weight=10, learning_rate=0.05,
                          subsample=0.8, colsample_bytree=0.8, reg_lambda=1.0,
                          scale_pos_weight=positive_weight, objective="binary:logistic", eval_metric="logloss",
                          tree_method="hist", n_jobs=n_jobs, random_state=seed, verbosity=0), False
        ),
        "lightgbm": make_pipeline(
            LGBMClassifier(n_estimators=200, max_depth=6, num_leaves=15, min_child_samples=40,
                           learning_rate=0.05, subsample=0.8, subsample_freq=1,
                           colsample_bytree=0.8, reg_lambda=1.0, scale_pos_weight=positive_weight,
                           n_jobs=n_jobs, random_state=seed, verbosity=-1,
                           deterministic=True, force_col_wise=True), False
        ),
    }
    # HGB requires dense arrays. Dense XGBoost also preserves numeric zero values,
    # which would otherwise be implicit missing entries in a scipy sparse matrix.
    for name in ("hist_gradient_boosting", "xgboost"):
        candidates[name].set_params(
            preprocessor__sparse_threshold=0.0,
            preprocessor__categorical__onehot__sparse_output=False,
        )
    return candidates


def fit_evaluate_candidate(pipeline, splits, seed=42, n_jobs=4, *, tune_threshold=True):
    """Fit a fresh clone on train, tune on validation, then score evaluation once."""
    if n_jobs < 1:
        raise ValueError("n_jobs must be positive")
    for name in ("train", "validation", "evaluation"):
        _validate_binary_target(splits[name]["delayed"], name)
    features = {name: prepare_features(part) for name, part in splits.items()}
    targets = {name: part["delayed"] for name, part in splits.items()}
    fitted = clone(pipeline)
    result = {
        "status": "failed", "parameters": fitted.named_steps["classifier"].get_params(deep=False),
        "preprocessing": {
            "fit_data": "purged train only", "refit_train_plus_validation": False,
            "numeric_scaling": "scaler" in fitted.named_steps["preprocessor"].transformers[0][1].named_steps,
            "dense_output": fitted.named_steps["preprocessor"].sparse_threshold == 0.0,
            "categorical_min_frequency": 20,
        },
        "random_state": seed, "thread_limit": n_jobs, "timing": {},
    }
    started = time.perf_counter()
    with warnings.catch_warnings(record=True) as captured:
        warnings.simplefilter("always")
        try:
            with threadpool_limits(limits=n_jobs):
                step_started = time.perf_counter()
                fitted.fit(features["train"], targets["train"])
                result["timing"]["fit_seconds"] = time.perf_counter() - step_started
                step_started = time.perf_counter()
                validation_scores = positive_probability(fitted, features["validation"])
                result["timing"]["validation_predict_seconds"] = time.perf_counter() - step_started
                if tune_threshold:
                    threshold, threshold_policy = choose_threshold(targets["validation"], validation_scores)
                else:
                    threshold, threshold_policy = 0.5, {
                        "data": "not tuned", "selected_threshold": 0.5,
                        "objective": "fixed most-frequent dummy reference",
                        "prediction_rule": "delay_score >= 0.5",
                    }
                result["threshold"] = threshold
                result["threshold_policy"] = threshold_policy
                result["validation"] = binary_metrics(targets["validation"], validation_scores, threshold)
                step_started = time.perf_counter()
                evaluation_scores = positive_probability(fitted, features["evaluation"])
                result["timing"]["evaluation_predict_seconds"] = time.perf_counter() - step_started
                if not np.isfinite(evaluation_scores).all() or not np.isfinite(validation_scores).all():
                    raise ValueError("Classifier produced non-finite scores")
                result["evaluation"] = binary_metrics(targets["evaluation"], evaluation_scores, threshold)
                result["evaluation"]["ap_lift_over_prevalence"] = (
                    result["evaluation"]["average_precision"] / result["evaluation"]["positive_rate"]
                )
                result["status"] = "ok"
        except Exception as exc:
            result.update(error_type=type(exc).__name__, error=str(exc))
    warning_counts = Counter((item.category.__name__, str(item.message)) for item in captured)
    result["warnings"] = [
        {"category": category, "message": message, "count": count}
        for (category, message), count in warning_counts.items()
    ]
    result["timing"]["total_seconds"] = time.perf_counter() - started
    return result


def summarize_results(folds):
    summary = []
    for name in MODEL_NAMES:
        results = [fold.get("model_results", {}).get(name, {}) for fold in folds]
        successful = [item for item in results if item.get("status") == "ok"]
        complete = len(successful) == len(FOLDS)
        item = {"model": name, "display_name": DISPLAY_NAMES[name],
                "status": "ok" if complete else "incomplete", "successful_folds": len(successful)}
        if complete:
            item["metrics"] = {
                metric: {"mean": float(np.mean([result["evaluation"][metric] for result in successful])),
                         "std": float(np.std([result["evaluation"][metric] for result in successful], ddof=0))}
                for metric in SUMMARY_METRICS
            }
            item["fit_seconds_total"] = float(sum(result["timing"]["fit_seconds"] for result in successful))
        else:
            item["failed_folds"] = [
                fold["name"] for fold, result in zip(folds, results) if result.get("status") != "ok"
            ]
        summary.append(item)
    summary.sort(key=lambda item: (
        item["status"] != "ok",
        -item.get("metrics", {}).get("average_precision", {}).get("mean", -1),
    ))
    rank = 0
    for item in summary:
        if item["status"] == "ok":
            rank += 1
            item["development_ap_rank"] = rank
    return summary


def save_comparison_figure(summary, image_path, status):
    image_path.parent.mkdir(parents=True, exist_ok=True)
    completed = list(reversed([item for item in summary if item["status"] == "ok"]))
    figure, ax = plt.subplots(figsize=(10, 6))
    if completed:
        means = [item["metrics"]["average_precision"]["mean"] for item in completed]
        deviations = [item["metrics"]["average_precision"]["std"] for item in completed]
        colors = ["#999999" if item["model"] == "dummy_most_frequent" else "#2878a5" for item in completed]
        bars = ax.barh([item["display_name"] for item in completed], means, xerr=deviations, color=colors)
        ax.bar_label(bars, fmt="%.3f", padding=4)
        ax.set_xlim(0, min(1, max(mean + deviation for mean, deviation in zip(means, deviations)) * 1.2 + 0.03))
    else:
        ax.text(0.5, 0.5, "No model completed all folds", transform=ax.transAxes, ha="center")
    ax.set(xlabel="Mean evaluation average precision (error bars: population standard deviation)",
           title=f"Development backtest: three monthly evaluations ({status})")
    figure.text(0.5, 0.01, "Validation thresholds; train-only preprocessing; original fixed test orders excluded.",
                ha="center", fontsize=9)
    figure.tight_layout(rect=[0, 0.04, 1, 1])
    figure.savefig(image_path, dpi=160, bbox_inches="tight")
    plt.close(figure)


def _json_safe(value):
    if isinstance(value, dict):
        return {key: _json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_safe(item) for item in value]
    if isinstance(value, np.generic):
        return _json_safe(value.item())
    if isinstance(value, float) and not math.isfinite(value):
        return "NaN" if math.isnan(value) else str(value)
    return value


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-dir", type=Path, default=PROJECT_ROOT / "data" / "raw" / "olist")
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--n-jobs", type=int, default=4)
    args = parser.parse_args(argv)
    if args.n_jobs < 1:
        parser.error("--n-jobs must be positive")
    if not 0 <= args.seed < 2**32:
        parser.error("--seed must be an integer from 0 to 2**32 - 1")
    raw_dir, output_dir = args.data_dir.resolve(), args.output_dir.resolve()
    image_dir = PROJECT_ROOT / "reports" / "images" if output_dir == DEFAULT_OUTPUT.resolve() else output_dir / "images"
    output_dir.mkdir(parents=True, exist_ok=True)
    report_path = output_dir / "model_comparison.json"
    image_path = image_dir / "stage4_backtest_model_comparison.png"
    versions = {"python": platform.python_version()}
    for package in ("pandas", "numpy", "scikit-learn", "scipy", "xgboost", "lightgbm", "threadpoolctl"):
        try:
            versions[package] = version(package)
        except PackageNotFoundError:
            versions[package] = "not_installed"
    report = {
        "format_version": 1, "status": "failed", "seed": args.seed, "n_jobs": args.n_jobs,
        "versions": versions,
        "label_metadata": {
            **LABEL_METADATA,
            "maturity_purge": (
                "Training labels must be available strictly before validation_start; "
                "validation labels must be available strictly before evaluation_start."
            ),
        },
        "policies": {
            "purpose": "development comparison; not a new independent final test",
            "preprocessing": "fit exclusively on each purged training fold; no train+validation refit",
            "training": "prediction_time < validation_start and label_available_time < validation_start",
            "validation": "prediction_time in [validation_start, validation_end), labels available strictly before evaluation_start",
            "maturity_wait": "Default folds leave one whole calendar month after validation for labels to mature",
            "evaluation": "fixed monthly prediction intervals; completed outcomes scored retrospectively with no label-maturity purge",
            "original_fixed_test_start": FIXED_TEST_START.isoformat(),
            "original_test_protection": "No original fixed-test prediction orders, metrics or saved predictions are used or modified",
            "late_labels": "Some historical evaluation orders are delivered on/after the original test start; only prediction dates are bounded",
            "threshold": "six learned models maximize validation F1; Dummy remains at 0.5 as the most-frequent reference",
            "ranking": "unweighted mean evaluation AP across all three successful folds; population std (ddof=0)",
            "score": "positive-class predict_proba values are uncalibrated delay scores",
            "threading": "threadpoolctl limit covers fit/predict; ensembles receive n_jobs explicitly",
            "model_promotion": "No model artifact, original metrics.json or original test predictions are updated",
        },
        "limitations": [
            "The cohort contains eligible completed deliveries only; cancelled/unfinished orders are not represented.",
            "Label-maturity purging preferentially excludes long deliveries and positives; before/after counts quantify this selection bias.",
            "A one-month maturation wait reduces but does not eliminate validation bias or threshold uncertainty.",
            "Evaluation prevalence differs by month, so AP and threshold metrics vary with the cohort.",
            "Three development months and their standard deviations are not confidence intervals or guarantees of future performance.",
            "Training is frozen before validation; waiting-period orders do not update the fold model.",
            "The original Stage 4 fixed test was already evaluated; this script does not reuse it for development ranking.",
        ],
        "folds": [], "summary": [],
        "outputs": {"report": str(report_path), "image": str(image_path)},
    }
    try:
        dataset = build_delay_dataset(raw_dir)
        report["source_files"] = source_manifest(raw_dir)
        dataset = dataset[pd.to_datetime(dataset["prediction_time"]) < FIXED_TEST_START].copy()
        report["dataset_rows_before_original_test"] = len(dataset)
        for specification in FOLDS:
            fold = {"name": specification["name"], "status": "failed", "model_results": {}}
            report["folds"].append(fold)
            try:
                splits, counts = split_backtest_fold(
                    dataset, specification["validation_start"], specification["evaluation_start"],
                    specification["evaluation_end"], validation_end=specification["validation_end"],
                )
                fold.update(counts)
                fold["train_negative_to_positive_weight"] = float(
                    (splits["train"]["delayed"] == 0).sum() / splits["train"]["delayed"].sum()
                )
                candidates = make_candidates(splits["train"]["delayed"], args.seed, args.n_jobs)
                for name, pipeline in candidates.items():
                    print(f"{fold['name']} / {name}: fitting...", flush=True)
                    result = fit_evaluate_candidate(
                        pipeline, splits, args.seed, args.n_jobs,
                        tune_threshold=name != "dummy_most_frequent",
                    )
                    fold["model_results"][name] = result
                    if result["status"] == "ok":
                        print(f"  AP={result['evaluation']['average_precision']:.4f}; F1={result['evaluation']['f1']:.4f}", flush=True)
                    else:
                        print(f"  FAILED: {result.get('error_type')}: {result.get('error')}", flush=True)
                fold["status"] = "ok" if all(item["status"] == "ok" for item in fold["model_results"].values()) else "failed"
            except Exception as exc:
                fold.update(error_type=type(exc).__name__, error=str(exc))
                print(f"Fold {fold['name']} FAILED: {type(exc).__name__}: {exc}", flush=True)
        report["summary"] = summarize_results(report["folds"])
        report["status"] = "ok" if all(fold["status"] == "ok" for fold in report["folds"]) else "failed"
    except Exception as exc:
        report.update(error_type=type(exc).__name__, error=str(exc))
        print(f"Comparison FAILED: {type(exc).__name__}: {exc}", flush=True)
    save_comparison_figure(report["summary"], image_path, report["status"])
    report_path.write_text(json.dumps(_json_safe(report), indent=2, ensure_ascii=False, allow_nan=False), encoding="utf-8")
    print(f"Report: {report_path}\nImage: {image_path}\nStatus: {report['status']}", flush=True)
    return 0 if report["status"] == "ok" else 1


if __name__ == "__main__":
    raise SystemExit(main())
