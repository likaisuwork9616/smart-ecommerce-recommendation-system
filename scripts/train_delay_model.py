"""Train an approval-time delay classifier with chronological, maturity-purged splits."""

from __future__ import annotations

import argparse
import hashlib
from importlib.metadata import version
import json
from pathlib import Path
import platform
import sys
import time
import warnings

import joblib
import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from sklearn.compose import ColumnTransformer
from sklearn.dummy import DummyClassifier
from sklearn.ensemble import RandomForestClassifier
from sklearn.impute import SimpleImputer
from sklearn.inspection import permutation_importance
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import (
    ConfusionMatrixDisplay,
    accuracy_score,
    average_precision_score,
    balanced_accuracy_score,
    confusion_matrix,
    f1_score,
    precision_recall_curve,
    precision_score,
    recall_score,
    roc_auc_score,
    roc_curve,
)
from sklearn.model_selection import train_test_split
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import OneHotEncoder, StandardScaler


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from scripts.delay_features import (  # noqa: E402
    CATEGORICAL_FEATURES,
    CSV_FILES,
    NUMERIC_FEATURES,
    build_delay_dataset,
)


DEFAULT_OUTPUT = PROJECT_ROOT / "reports" / "stage4"
METADATA_COLUMNS = [
    "order_id",
    "order_purchase_timestamp",
    "prediction_time",
    "label_available_time",
    "delayed",
]
LABEL_METADATA = {
    "positive_label": "actual delivery calendar date > estimated delivery calendar date",
    "prediction_time": "order approval timestamp (order_approved_at)",
    "label_available_time": "actual customer delivery timestamp",
    "stage3_difference": (
        "Stage 3 compares full delivery timestamps against estimated-date midnight; "
        "Stage 4 compares calendar dates, so delivery during the estimated day is on time."
    ),
    "maturity_purge": (
        "Training labels must be available strictly before validation boundary midnight; "
        "validation labels must be available strictly before test boundary midnight."
    ),
}


def prepare_features(frame: pd.DataFrame) -> pd.DataFrame:
    """Normalize pandas nullable types; learned imputations remain inside the pipeline."""
    names = list(NUMERIC_FEATURES) + list(CATEGORICAL_FEATURES)
    if len(names) != len(set(names)) or set(names).intersection(METADATA_COLUMNS):
        raise ValueError("Feature lists must be unique and exclude metadata/target columns")
    missing = set(names).difference(frame.columns)
    if missing:
        raise ValueError(f"Missing feature columns: {sorted(missing)}")
    features = frame[names].copy()
    for name in NUMERIC_FEATURES:
        features[name] = pd.to_numeric(features[name], errors="coerce").replace(
            [np.inf, -np.inf], np.nan
        )
    for name in CATEGORICAL_FEATURES:
        features[name] = features[name].astype(object).where(features[name].notna(), np.nan)
    return features


def chronological_split(frame: pd.DataFrame):
    """Approximate 60/20/20 by row count, without splitting any prediction date."""
    frame = frame.copy()
    for name in METADATA_COLUMNS[:-1]:
        if name not in frame:
            raise ValueError(f"Missing metadata column: {name}")
    for name in ("order_purchase_timestamp", "prediction_time", "label_available_time"):
        frame[name] = pd.to_datetime(frame[name], errors="raise")
        if frame[name].isna().any():
            raise ValueError(f"Missing timestamps in {name}")
    if frame["order_id"].isna().any() or frame["order_id"].duplicated().any():
        raise ValueError("Expected one row per non-null order_id")
    if "delayed" not in frame or not frame["delayed"].isin([0, 1]).all():
        raise ValueError("delayed must contain only 0 and 1")
    if (frame["label_available_time"] < frame["prediction_time"]).any():
        raise ValueError("Delivery labels cannot be available before order approval")
    frame["delayed"] = frame["delayed"].astype(int)
    frame = frame.sort_values(["prediction_time", "order_id"], kind="stable").reset_index(drop=True)
    if len(frame) < 10:
        raise ValueError("Too few orders for chronological train/validation/test splits")

    dates = frame["prediction_time"].dt.normalize()
    validation_start = dates.iloc[int(len(frame) * 0.6)]
    test_start = dates.iloc[int(len(frame) * 0.8)]
    if validation_start >= test_start:
        raise ValueError("Not enough distinct prediction dates for three chronological splits")
    frame["dataset_split"] = np.select(
        [dates < validation_start, dates < test_start], ["train", "validation"], default="test"
    )
    frame["label_purged"] = (
        ((frame["dataset_split"] == "train") & (frame["label_available_time"] >= validation_start))
        | ((frame["dataset_split"] == "validation") & (frame["label_available_time"] >= test_start))
    )
    splits = {}
    split_report = {
        "method": "chronological prediction dates, row-count targets 60%/20%/20%",
        "validation_start": validation_start.isoformat(),
        "test_start": test_start.isoformat(),
        "boundary_inclusion": "Boundary dates belong entirely to the later split",
        "label_maturity_policy": LABEL_METADATA["maturity_purge"],
        "partitions": {},
    }
    for name in ("train", "validation", "test"):
        before = frame[frame["dataset_split"] == name]
        subset = before[~before["label_purged"]].copy()
        if subset.empty or subset["delayed"].nunique() != 2:
            raise ValueError(f"{name} must contain both classes after maturity purging")
        splits[name] = subset
        split_report["partitions"][name] = {
            "rows_before_purge": len(before),
            "purged_rows": len(before) - len(subset),
            "rows": len(subset),
            "positive_rows": int(subset["delayed"].sum()),
            "positive_rate": float(subset["delayed"].mean()),
            "prediction_time_min": subset["prediction_time"].min().isoformat(),
            "prediction_time_max": subset["prediction_time"].max().isoformat(),
            "label_available_time_max": subset["label_available_time"].max().isoformat(),
        }
    return frame, splits, split_report


def make_pipeline(classifier, scale_numeric: bool) -> Pipeline:
    numeric_steps = [
        ("imputer", SimpleImputer(strategy="median", add_indicator=True, keep_empty_features=True))
    ]
    if scale_numeric:
        numeric_steps.append(("scaler", StandardScaler()))
    preprocessor = ColumnTransformer(
        [
            ("numeric", Pipeline(numeric_steps), list(NUMERIC_FEATURES)),
            (
                "categorical",
                Pipeline(
                    [
                        ("imputer", SimpleImputer(strategy="most_frequent", keep_empty_features=True)),
                        ("onehot", OneHotEncoder(handle_unknown="ignore", min_frequency=20)),
                    ]
                ),
                list(CATEGORICAL_FEATURES),
            ),
        ],
        remainder="drop",
    )
    return Pipeline([("preprocessor", preprocessor), ("classifier", classifier)])


def positive_probability(pipeline: Pipeline, features: pd.DataFrame) -> np.ndarray:
    positive_column = np.flatnonzero(pipeline.classes_ == 1)
    if len(positive_column) != 1:
        raise ValueError("Fitted classifier has no unambiguous positive class")
    return pipeline.predict_proba(features)[:, positive_column[0]]


def binary_metrics(target, probabilities, threshold: float) -> dict:
    prediction = np.asarray(probabilities) >= threshold
    tn, fp, fn, tp = confusion_matrix(target, prediction, labels=[0, 1]).ravel()
    return {
        "rows": len(target),
        "positive_rate": float(np.mean(target)),
        "threshold": float(threshold),
        "average_precision": float(average_precision_score(target, probabilities)),
        "roc_auc": float(roc_auc_score(target, probabilities)),
        "f1": float(f1_score(target, prediction, zero_division=0)),
        "recall": float(recall_score(target, prediction, zero_division=0)),
        "precision": float(precision_score(target, prediction, zero_division=0)),
        "balanced_accuracy": float(balanced_accuracy_score(target, prediction)),
        "accuracy": float(accuracy_score(target, prediction)),
        "predicted_positive_rows": int(prediction.sum()),
        "confusion_matrix": [[int(tn), int(fp)], [int(fn), int(tp)]],
        "confusion_matrix_order": "rows=true [on_time, delayed], columns=predicted [on_time, delayed]",
    }


def choose_threshold(target, probabilities):
    precision, recall, thresholds = precision_recall_curve(target, probabilities)
    denominator = precision[:-1] + recall[:-1]
    f1 = np.divide(
        2 * precision[:-1] * recall[:-1], denominator,
        out=np.zeros_like(denominator), where=denominator > 0,
    )
    best_positions = np.flatnonzero(np.isclose(f1, f1.max(), rtol=1e-12, atol=1e-12))
    threshold = float(thresholds[best_positions[-1]])
    return threshold, {
        "data": "validation only",
        "objective": "maximize validation F1 over unique validation prediction scores",
        "tie_break": "highest threshold among equal F1 values (numerical tolerance 1e-12)",
        "prediction_rule": "delay_score >= threshold",
        "candidate_thresholds": len(thresholds),
        "selected_threshold": threshold,
    }


def validation_importance(pipeline, features, target, seed):
    indices = np.arange(len(features))
    if len(indices) > 5000:
        indices, _ = train_test_split(
            indices, train_size=5000, stratify=target, random_state=seed
        )
    sample = features.iloc[indices]
    sample_target = target.iloc[indices]
    importance = permutation_importance(
        pipeline, sample, sample_target, scoring="average_precision",
        n_repeats=3, random_state=seed, n_jobs=1,
    )
    rows = [
        {"feature": name, "ap_delta_mean": float(mean), "ap_delta_std": float(std)}
        for name, mean, std in zip(features.columns, importance.importances_mean, importance.importances_std)
    ]
    rows.sort(key=lambda item: item["ap_delta_mean"], reverse=True)
    return {
        "method": "permutation importance of original feature columns",
        "data": "stratified validation sample only; test data is not used",
        "sample_rows": len(sample),
        "n_repeats": 3,
        "random_state": seed,
        "scoring": "average_precision",
        "interpretation": "validation AP decrease when a feature is shuffled; not a causal effect",
        "values": rows,
    }


def save_figures(image_dir, comparisons, importance, target, probabilities, test_metrics):
    image_dir.mkdir(parents=True, exist_ok=True)
    paths = []

    def save(figure, suffix):
        path = image_dir / f"stage4_{suffix}.png"
        figure.tight_layout()
        figure.savefig(path, dpi=160, bbox_inches="tight")
        plt.close(figure)
        paths.append(str(path))

    successful = {name: item for name, item in comparisons.items() if item["status"] == "ok"}
    figure, ax = plt.subplots(figsize=(9, 5))
    names = list(successful)
    scores = [successful[name]["validation_at_0_5"]["average_precision"] for name in names]
    bars = ax.bar(names, scores, color="#2878a5")
    ax.bar_label(bars, fmt="%.3f", padding=3)
    ax.set(title="Model comparison: validation average precision", ylabel="Average precision")
    ax.set_ylim(0, min(1, max(scores) * 1.25 + 0.02))
    save(figure, "validation_model_comparison")

    precision, recall, _ = precision_recall_curve(target, probabilities)
    figure, ax = plt.subplots(figsize=(7, 5))
    ax.plot(recall, precision, label=f"Test AP = {test_metrics['average_precision']:.3f}")
    ax.axhline(np.mean(target), color="gray", linestyle="--", label="Test delayed rate")
    ax.scatter(test_metrics["recall"], test_metrics["precision"], color="#c44e52", zorder=3,
               label="Threshold selected on validation")
    ax.set(xlabel="Recall", ylabel="Precision", title="Selected model: test precision-recall")
    ax.legend()
    save(figure, "test_precision_recall")

    false_positive_rate, true_positive_rate, _ = roc_curve(target, probabilities)
    figure, ax = plt.subplots(figsize=(7, 5))
    ax.plot(false_positive_rate, true_positive_rate, label=f"Test ROC AUC = {test_metrics['roc_auc']:.3f}")
    ax.plot([0, 1], [0, 1], color="gray", linestyle="--")
    ax.set(xlabel="False positive rate", ylabel="True positive rate", title="Selected model: test ROC")
    ax.legend()
    save(figure, "test_roc")

    figure, ax = plt.subplots(figsize=(6, 5))
    ConfusionMatrixDisplay(
        np.asarray(test_metrics["confusion_matrix"]), display_labels=["On time", "Delayed"]
    ).plot(ax=ax, cmap="Blues", colorbar=False, values_format="d")
    ax.set_title("Test confusion matrix: validation-selected threshold")
    save(figure, "test_confusion_matrix")

    rows = list(reversed(importance["values"][:20]))
    figure, ax = plt.subplots(figsize=(10, 7))
    ax.barh(
        [row["feature"] for row in rows], [row["ap_delta_mean"] for row in rows],
        xerr=[row["ap_delta_std"] for row in rows], color="#2878a5",
    )
    ax.axvline(0, color="gray", linewidth=0.8)
    ax.set(
        xlabel="Validation AP decrease after shuffling (mean ± standard deviation)",
        title=f"Validation permutation importance: {importance['sample_rows']:,} rows, 3 repeats",
    )
    save(figure, "validation_permutation_importance")
    return paths


def source_manifest(raw_dir):
    manifest = []
    for filename in sorted(CSV_FILES.values()):
        path = raw_dir / filename
        digest = hashlib.sha256()
        with path.open("rb") as source:
            for chunk in iter(lambda: source.read(1024 * 1024), b""):
                digest.update(chunk)
        manifest.append({"filename": path.name, "bytes": path.stat().st_size, "sha256": digest.hexdigest()})
    return manifest


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-dir", type=Path, default=PROJECT_ROOT / "data" / "raw" / "olist")
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--model-path", type=Path, default=PROJECT_ROOT / "models" / "olist_delay_model.joblib")
    parser.add_argument("--seed", type=int, default=42)
    args = parser.parse_args(argv)
    raw_dir, output_dir, model_path = args.data_dir.resolve(), args.output_dir.resolve(), args.model_path.resolve()
    default_output = output_dir == DEFAULT_OUTPUT.resolve()
    image_dir = PROJECT_ROOT / "reports" / "images" if default_output else output_dir / "images"
    data_dir = PROJECT_ROOT / "data" / "processed" if default_output else output_dir / "data"
    output_dir.mkdir(parents=True, exist_ok=True)
    data_dir.mkdir(parents=True, exist_ok=True)
    model_path.parent.mkdir(parents=True, exist_ok=True)

    dataset = build_delay_dataset(raw_dir)
    normalized = prepare_features(dataset)
    dataset[normalized.columns] = normalized
    dataset, splits, split_report = chronological_split(dataset)
    features = {name: prepare_features(part) for name, part in splits.items()}
    targets = {name: part["delayed"] for name, part in splits.items()}
    dataset_path = data_dir / "olist_delay_features.csv"
    dataset.to_csv(dataset_path, index=False)
    print(f"Orders: {len(dataset):,}; split sizes after purge: "
          + ", ".join(f"{name}={len(part):,}" for name, part in splits.items()), flush=True)

    candidates = {
        "dummy_most_frequent": (DummyClassifier(strategy="most_frequent"), False),
        "balanced_logistic_regression": (
            LogisticRegression(class_weight="balanced", max_iter=2000, random_state=args.seed), True
        ),
        "random_forest": (
            RandomForestClassifier(
                n_estimators=200, max_depth=14, min_samples_leaf=8,
                class_weight="balanced_subsample", n_jobs=-1, random_state=args.seed,
            ), False
        ),
    }
    comparisons, fitted, validation_probabilities = {}, {}, {}
    for name, (classifier, scale_numeric) in candidates.items():
        started = time.perf_counter()
        try:
            pipeline = make_pipeline(classifier, scale_numeric)
            with warnings.catch_warnings(record=True) as captured:
                warnings.simplefilter("always")
                pipeline.fit(features["train"], targets["train"])
            fit_seconds = time.perf_counter() - started
            probabilities = positive_probability(pipeline, features["validation"])
            comparisons[name] = {
                "status": "ok",
                "fit_seconds": fit_seconds,
                "classifier_parameters": classifier.get_params(deep=False),
                "fit_warning_types": sorted({item.category.__name__ for item in captured}),
                "validation_at_0_5": binary_metrics(targets["validation"], probabilities, 0.5),
            }
            fitted[name], validation_probabilities[name] = pipeline, probabilities
            print(f"{name}: validation AP={comparisons[name]['validation_at_0_5']['average_precision']:.4f}", flush=True)
        except Exception as exc:
            comparisons[name] = {"status": "failed", "error_type": type(exc).__name__, "error": str(exc)[:500]}
            print(f"{name}: failed ({type(exc).__name__})", flush=True)
    learned_candidates = [name for name in fitted if name != "dummy_most_frequent"]
    if not learned_candidates:
        raise RuntimeError("No learned candidate trained successfully; the dummy reference cannot be selected")

    selected = max(
        learned_candidates, key=lambda name: comparisons[name]["validation_at_0_5"]["average_precision"]
    )
    pipeline = fitted[selected]
    threshold, threshold_policy = choose_threshold(targets["validation"], validation_probabilities[selected])
    validation_metrics = binary_metrics(targets["validation"], validation_probabilities[selected], threshold)
    print(f"Selected {selected}; validation F1 threshold={threshold:.6f}. Computing validation importance...", flush=True)
    importance = validation_importance(pipeline, features["validation"], targets["validation"], args.seed)

    # Selection, preprocessing and threshold are frozen before the single test prediction pass.
    test_probabilities = positive_probability(pipeline, features["test"])
    test_metrics = binary_metrics(targets["test"], test_probabilities, threshold)
    test_baseline = binary_metrics(targets["test"], np.zeros(len(targets["test"])), 0.5)
    predictions = splits["test"][METADATA_COLUMNS].copy()
    predictions["delay_score"] = test_probabilities
    predictions["predicted_delayed"] = (test_probabilities >= threshold).astype(int)
    predictions["threshold"] = threshold
    predictions["model"] = selected
    predictions_path = data_dir / "olist_delay_test_predictions.csv"
    predictions.to_csv(predictions_path, index=False)

    metadata = {
        "label_metadata": LABEL_METADATA,
        "random_state": args.seed,
        "split": split_report,
        "feature_policy": "Only explicitly listed approval-time features; no metadata or target columns",
        "preprocessing_fit": "purged training split only; validation/test never fit preprocessing",
        "final_refit": False,
        "model_selection": {
            "data": "validation only", "metric": "average_precision",
            "tie_break": "first candidate in the recorded candidate order",
            "candidate_order": list(candidates), "eligible_candidates": learned_candidates,
            "dummy_role": "validation reference only; never eligible for model or threshold selection",
            "selected_model": selected,
            "validation_ap_above_dummy": (
                comparisons[selected]["validation_at_0_5"]["average_precision"]
                > comparisons["dummy_most_frequent"]["validation_at_0_5"]["average_precision"]
                if "dummy_most_frequent" in fitted else None
            ),
        },
        "threshold_policy": threshold_policy,
        "score_semantics": "delay_score is an uncalibrated positive-class predict_proba score",
        "test_policy": (
            "Only the selected frozen learned pipeline makes one test prediction pass; "
            "the all-on-time baseline is computed from a constant zero score without fitting another model"
        ),
        "versions": {
            "python": platform.python_version(),
            **{name: version(name) for name in ("pandas", "numpy", "scikit-learn", "scipy", "joblib", "matplotlib")},
        },
        "raw_source_files": source_manifest(raw_dir),
    }
    artifact = {
        "format_version": 1,
        "pipeline": pipeline,
        "threshold": threshold,
        "selected_model": selected,
        "feature_names": list(features["train"].columns),
        "numeric_features": list(NUMERIC_FEATURES),
        "categorical_features": list(CATEGORICAL_FEATURES),
        "label_metadata": LABEL_METADATA,
        "metadata": metadata,
    }
    joblib.dump(artifact, model_path, compress=3)
    image_paths = save_figures(
        image_dir, comparisons, importance, targets["test"], test_probabilities, test_metrics
    )
    report = {
        "format_version": 1,
        "dataset": {"rows": len(dataset), "positive_rows": int(dataset["delayed"].sum()),
                    "positive_rate": float(dataset["delayed"].mean())},
        "features": {"numeric": list(NUMERIC_FEATURES), "categorical": list(CATEGORICAL_FEATURES)},
        "metadata": metadata,
        "model_comparison": comparisons,
        "selected_model": selected,
        "threshold": threshold,
        "validation": validation_metrics,
        "test": test_metrics,
        "test_baseline": test_baseline,
        "validation_permutation_importance": importance,
        "outputs": {"model": str(model_path), "dataset": str(dataset_path),
                    "test_predictions": str(predictions_path), "images": image_paths},
    }
    metrics_path = output_dir / "metrics.json"
    metrics_path.write_text(json.dumps(report, indent=2, ensure_ascii=False, allow_nan=False), encoding="utf-8")
    print(f"Test AP={test_metrics['average_precision']:.4f}, ROC AUC={test_metrics['roc_auc']:.4f}, "
          f"F1={test_metrics['f1']:.4f}, recall={test_metrics['recall']:.4f}, precision={test_metrics['precision']:.4f}")
    print(f"Metrics: {metrics_path}\nModel: {model_path}")
    return report


if __name__ == "__main__":
    main()
