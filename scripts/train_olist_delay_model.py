"""Train and evaluate Olist delivery-delay classifiers.

The target is defined only for delivered orders:
    delayed = order_delivered_customer_date > order_estimated_delivery_date

All predictors are restricted to information available when the order is placed.
"""

from __future__ import annotations

import json
from pathlib import Path

import joblib
import matplotlib

matplotlib.use("Agg")

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from sklearn.compose import ColumnTransformer
from sklearn.impute import SimpleImputer
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import (
    ConfusionMatrixDisplay,
    PrecisionRecallDisplay,
    RocCurveDisplay,
    accuracy_score,
    average_precision_score,
    confusion_matrix,
    f1_score,
    precision_score,
    recall_score,
    roc_auc_score,
)
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import OneHotEncoder, StandardScaler
from sklearn.tree import DecisionTreeClassifier
from sklearn.ensemble import RandomForestClassifier


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = PROJECT_ROOT / "data" / "raw" / "olist"
PROCESSED_DIR = PROJECT_ROOT / "data" / "processed"
MODEL_DIR = PROJECT_ROOT / "models"
REPORT_DIR = PROJECT_ROOT / "reports"
IMAGE_DIR = REPORT_DIR / "images"

RANDOM_STATE = 42


def load_and_build_features() -> tuple[pd.DataFrame, list[str], list[str]]:
    """Build one leakage-safe modeling row per delivered order."""
    orders = pd.read_csv(
        DATA_DIR / "olist_orders_dataset.csv",
        parse_dates=[
            "order_purchase_timestamp",
            "order_delivered_customer_date",
            "order_estimated_delivery_date",
        ],
    )
    items = pd.read_csv(DATA_DIR / "olist_order_items_dataset.csv")
    payments = pd.read_csv(DATA_DIR / "olist_order_payments_dataset.csv")
    customers = pd.read_csv(DATA_DIR / "olist_customers_dataset.csv")
    sellers = pd.read_csv(DATA_DIR / "olist_sellers_dataset.csv")
    products = pd.read_csv(DATA_DIR / "olist_products_dataset.csv")
    translations = pd.read_csv(DATA_DIR / "product_category_name_translation.csv")

    orders = orders.loc[
        (orders["order_status"] == "delivered")
        & orders["order_delivered_customer_date"].notna()
        & orders["order_estimated_delivery_date"].notna()
        & orders["order_purchase_timestamp"].notna()
    ].copy()
    orders["delayed"] = (
        orders["order_delivered_customer_date"]
        > orders["order_estimated_delivery_date"]
    ).astype("int8")
    orders["purchase_month"] = orders["order_purchase_timestamp"].dt.month.astype(str)
    orders["purchase_weekday"] = (
        orders["order_purchase_timestamp"].dt.day_name().str[:3]
    )
    orders["purchase_hour"] = orders["order_purchase_timestamp"].dt.hour
    orders["estimated_delivery_days"] = (
        orders["order_estimated_delivery_date"]
        - orders["order_purchase_timestamp"]
    ).dt.total_seconds() / 86400

    products = products.merge(
        translations, on="product_category_name", how="left"
    )
    products["product_category"] = products[
        "product_category_name_english"
    ].fillna(products["product_category_name"])
    products["product_volume_cm3"] = (
        products["product_length_cm"]
        * products["product_height_cm"]
        * products["product_width_cm"]
    )

    item_detail = (
        items.merge(
            products[
                [
                    "product_id",
                    "product_category",
                    "product_weight_g",
                    "product_volume_cm3",
                ]
            ],
            on="product_id",
            how="left",
        )
        .merge(
            sellers[["seller_id", "seller_state"]],
            on="seller_id",
            how="left",
        )
    )

    item_numeric_features = (
        item_detail.groupby("order_id", as_index=False)
        .agg(
            item_count=("order_item_id", "count"),
            product_count=("product_id", "nunique"),
            seller_count=("seller_id", "nunique"),
            total_price=("price", "sum"),
            mean_item_price=("price", "mean"),
            total_freight=("freight_value", "sum"),
            mean_product_weight_g=("product_weight_g", "mean"),
            mean_product_volume_cm3=("product_volume_cm3", "mean"),
        )
    )
    # The first listed item provides a deterministic representative category
    # and seller state without slow Python-level aggregation per order.
    item_descriptors = (
        item_detail.sort_values(["order_id", "order_item_id"])
        .drop_duplicates("order_id")
        [["order_id", "product_category", "seller_state"]]
    )
    item_features = item_numeric_features.merge(
        item_descriptors, on="order_id", how="left"
    )
    item_features["freight_to_price_ratio"] = (
        item_features["total_freight"]
        / item_features["total_price"].replace(0, np.nan)
    )

    payment_numeric_features = (
        payments.groupby("order_id", as_index=False)
        .agg(
            payment_value=("payment_value", "sum"),
            payment_installments=("payment_installments", "max"),
            payment_method_count=("payment_type", "nunique"),
        )
    )
    payment_descriptor = (
        payments.sort_values(
            ["order_id", "payment_value"], ascending=[True, False]
        )
        .drop_duplicates("order_id")
        [["order_id", "payment_type"]]
    )
    payment_features = payment_numeric_features.merge(
        payment_descriptor, on="order_id", how="left"
    )

    customer_features = customers[
        ["customer_id", "customer_state"]
    ].drop_duplicates("customer_id")

    dataset = (
        orders[
            [
                "order_id",
                "customer_id",
                "order_purchase_timestamp",
                "delayed",
                "purchase_month",
                "purchase_weekday",
                "purchase_hour",
                "estimated_delivery_days",
            ]
        ]
        .merge(item_features, on="order_id", how="inner")
        .merge(payment_features, on="order_id", how="left")
        .merge(customer_features, on="customer_id", how="left")
    )

    numeric_features = [
        "purchase_hour",
        "estimated_delivery_days",
        "item_count",
        "product_count",
        "seller_count",
        "total_price",
        "mean_item_price",
        "total_freight",
        "freight_to_price_ratio",
        "payment_value",
        "payment_installments",
        "payment_method_count",
        "mean_product_weight_g",
        "mean_product_volume_cm3",
    ]
    categorical_features = [
        "purchase_month",
        "purchase_weekday",
        "payment_type",
        "product_category",
        "customer_state",
        "seller_state",
    ]

    dataset = dataset.replace([np.inf, -np.inf], np.nan)
    return dataset, numeric_features, categorical_features


def temporal_train_test_split(
    dataset: pd.DataFrame, test_size: float = 0.20
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Use the newest orders as test data to mimic future predictions."""
    ordered = dataset.sort_values("order_purchase_timestamp").reset_index(drop=True)
    split_index = int(len(ordered) * (1 - test_size))
    return ordered.iloc[:split_index].copy(), ordered.iloc[split_index:].copy()


def make_preprocessor(
    numeric_features: list[str], categorical_features: list[str]
) -> ColumnTransformer:
    numeric_pipeline = Pipeline(
        [
            ("imputer", SimpleImputer(strategy="median")),
            ("scaler", StandardScaler()),
        ]
    )
    categorical_pipeline = Pipeline(
        [
            ("imputer", SimpleImputer(strategy="most_frequent")),
            (
                "onehot",
                OneHotEncoder(
                    handle_unknown="ignore",
                    min_frequency=10,
                    sparse_output=True,
                ),
            ),
        ]
    )
    return ColumnTransformer(
        [
            ("numeric", numeric_pipeline, numeric_features),
            ("categorical", categorical_pipeline, categorical_features),
        ]
    )


def evaluate_models(
    train: pd.DataFrame,
    test: pd.DataFrame,
    numeric_features: list[str],
    categorical_features: list[str],
) -> tuple[pd.DataFrame, dict[str, Pipeline], dict[str, np.ndarray]]:
    feature_columns = numeric_features + categorical_features
    X_train = train[feature_columns]
    y_train = train["delayed"]
    X_test = test[feature_columns]
    y_test = test["delayed"]

    estimators = {
        "Logistic Regression": LogisticRegression(
            class_weight="balanced",
            max_iter=2000,
            solver="liblinear",
            random_state=RANDOM_STATE,
        ),
        "Decision Tree": DecisionTreeClassifier(
            class_weight="balanced",
            max_depth=12,
            min_samples_leaf=20,
            random_state=RANDOM_STATE,
        ),
        "Random Forest": RandomForestClassifier(
            n_estimators=250,
            class_weight="balanced_subsample",
            max_depth=18,
            min_samples_leaf=5,
            max_features="sqrt",
            n_jobs=-1,
            random_state=RANDOM_STATE,
        ),
    }

    fitted_models: dict[str, Pipeline] = {}
    probabilities: dict[str, np.ndarray] = {}
    rows = []

    for name, estimator in estimators.items():
        pipeline = Pipeline(
            [
                (
                    "preprocessor",
                    make_preprocessor(numeric_features, categorical_features),
                ),
                ("classifier", estimator),
            ]
        )
        pipeline.fit(X_train, y_train)
        prediction = pipeline.predict(X_test)
        probability = pipeline.predict_proba(X_test)[:, 1]

        fitted_models[name] = pipeline
        probabilities[name] = probability
        rows.append(
            {
                "model": name,
                "accuracy": accuracy_score(y_test, prediction),
                "precision": precision_score(y_test, prediction, zero_division=0),
                "recall": recall_score(y_test, prediction, zero_division=0),
                "f1": f1_score(y_test, prediction, zero_division=0),
                "roc_auc": roc_auc_score(y_test, probability),
                "average_precision": average_precision_score(y_test, probability),
            }
        )

    metrics = pd.DataFrame(rows).sort_values(
        ["roc_auc", "f1"], ascending=False
    ).reset_index(drop=True)
    return metrics, fitted_models, probabilities


def save_evaluation_plots(
    metrics: pd.DataFrame,
    models: dict[str, Pipeline],
    probabilities: dict[str, np.ndarray],
    test: pd.DataFrame,
    feature_columns: list[str],
    best_model_name: str,
) -> None:
    y_test = test["delayed"]
    X_test = test[feature_columns]
    best_model = models[best_model_name]
    best_prediction = best_model.predict(X_test)

    plot_metrics = metrics.set_index("model")[
        ["precision", "recall", "f1", "roc_auc", "average_precision"]
    ]
    ax = plot_metrics.plot(kind="bar", figsize=(11, 6), ylim=(0, 1))
    ax.set_title("Delivery Delay Model Comparison")
    ax.set_ylabel("Score")
    ax.tick_params(axis="x", rotation=15)
    ax.legend(loc="lower right")
    plt.tight_layout()
    plt.savefig(IMAGE_DIR / "olist_delay_model_comparison.png", dpi=200)
    plt.close()

    fig, axes = plt.subplots(1, 2, figsize=(11, 4.5))
    ConfusionMatrixDisplay(
        confusion_matrix=confusion_matrix(y_test, best_prediction),
        display_labels=["On time", "Delayed"],
    ).plot(ax=axes[0], colorbar=False, cmap="Blues")
    axes[0].set_title(f"{best_model_name}: Confusion Matrix")
    RocCurveDisplay.from_predictions(
        y_test,
        probabilities[best_model_name],
        ax=axes[1],
        name=best_model_name,
    )
    axes[1].plot([0, 1], [0, 1], linestyle="--", color="gray")
    axes[1].set_title("ROC Curve")
    plt.tight_layout()
    plt.savefig(IMAGE_DIR / "olist_delay_best_model_evaluation.png", dpi=200)
    plt.close()

    fig, ax = plt.subplots(figsize=(6, 5))
    PrecisionRecallDisplay.from_predictions(
        y_test,
        probabilities[best_model_name],
        ax=ax,
        name=best_model_name,
    )
    ax.set_title("Precision-Recall Curve")
    plt.tight_layout()
    plt.savefig(IMAGE_DIR / "olist_delay_precision_recall_curve.png", dpi=200)
    plt.close()


def get_feature_importance(model: Pipeline) -> pd.DataFrame:
    feature_names = model.named_steps["preprocessor"].get_feature_names_out()
    classifier = model.named_steps["classifier"]
    if hasattr(classifier, "feature_importances_"):
        importance = classifier.feature_importances_
        signed_effect = np.full(len(importance), np.nan)
        direction = np.full(len(importance), "not directional", dtype=object)
    else:
        signed_effect = classifier.coef_[0]
        importance = np.abs(signed_effect)
        direction = np.where(
            signed_effect > 0, "higher delay risk", "lower delay risk"
        )

    result = pd.DataFrame(
        {
            "feature": feature_names,
            "importance": importance,
            "signed_effect": signed_effect,
            "direction": direction,
        }
    ).sort_values("importance", ascending=False)
    return result.reset_index(drop=True)


def save_feature_importance_plot(feature_importance: pd.DataFrame) -> None:
    top_features = feature_importance.head(20).sort_values("importance")
    fig, ax = plt.subplots(figsize=(9, 7))
    ax.barh(top_features["feature"], top_features["importance"])
    ax.set_title("Top 20 Features for Delivery Delay Prediction")
    ax.set_xlabel("Model importance")
    plt.tight_layout()
    plt.savefig(IMAGE_DIR / "olist_delay_feature_importance.png", dpi=200)
    plt.close()


def build_risk_segments(
    test: pd.DataFrame, delay_probability: np.ndarray
) -> pd.DataFrame:
    scored = test.copy()
    scored["predicted_delay_probability"] = delay_probability
    segment_frames = []

    for column in [
        "product_category",
        "customer_state",
        "seller_state",
        "purchase_month",
    ]:
        summary = (
            scored.groupby(column, dropna=False)
            .agg(
                orders=("order_id", "count"),
                actual_delay_rate=("delayed", "mean"),
                predicted_delay_probability=("predicted_delay_probability", "mean"),
            )
            .reset_index()
            .rename(columns={column: "segment_value"})
        )
        summary = summary.loc[summary["orders"] >= 100].copy()
        summary.insert(0, "segment_type", column)
        segment_frames.append(summary)

    return (
        pd.concat(segment_frames, ignore_index=True)
        .sort_values(
            ["predicted_delay_probability", "orders"],
            ascending=[False, False],
        )
        .reset_index(drop=True)
    )


def dataframe_to_markdown(
    frame: pd.DataFrame, float_digits: int = 4
) -> str:
    """Render a small DataFrame as Markdown without optional dependencies."""
    display = frame.copy()
    for column in display.select_dtypes(include="number").columns:
        display[column] = display[column].map(
            lambda value: f"{value:.{float_digits}f}"
        )
    headers = [str(column) for column in display.columns]
    lines = [
        "| " + " | ".join(headers) + " |",
        "| " + " | ".join(["---"] * len(headers)) + " |",
    ]
    for row in display.itertuples(index=False, name=None):
        lines.append("| " + " | ".join(map(str, row)) + " |")
    return "\n".join(lines)


def write_summary(
    dataset: pd.DataFrame,
    train: pd.DataFrame,
    test: pd.DataFrame,
    metrics: pd.DataFrame,
    best_model_name: str,
    feature_importance: pd.DataFrame,
    risk_segments: pd.DataFrame,
) -> None:
    best_metrics = metrics.loc[metrics["model"] == best_model_name].iloc[0]
    top_features = feature_importance.head(10)
    positive_features = feature_importance.loc[
        feature_importance["signed_effect"] > 0
    ].sort_values("signed_effect", ascending=False).head(10)
    top_segments = risk_segments.head(10)

    lines = [
        "# Stage 4：Olist 訂單延遲預測結果",
        "",
        "## 資料與切分",
        "",
        f"- 可用已送達訂單：{len(dataset):,}",
        f"- 整體延遲率：{dataset['delayed'].mean():.2%}",
        f"- 訓練集：{len(train):,} 筆（較早的 80% 訂單）",
        f"- 測試集：{len(test):,} 筆（較新的 20% 訂單）",
        f"- 測試集延遲率：{test['delayed'].mean():.2%}（Average Precision 的隨機基準）",
        "- 所有特徵皆為下單時可取得資訊；實際送達日期只用於建立標籤。",
        "",
        "## 模型比較",
        "",
        dataframe_to_markdown(metrics, float_digits=4),
        "",
        f"最佳模型：**{best_model_name}**（依 ROC-AUC，其次 F1）",
        "",
        f"- Accuracy：{best_metrics['accuracy']:.4f}",
        f"- Precision：{best_metrics['precision']:.4f}",
        f"- Recall：{best_metrics['recall']:.4f}",
        f"- F1-score：{best_metrics['f1']:.4f}",
        f"- ROC-AUC：{best_metrics['roc_auc']:.4f}",
        f"- Average Precision：{best_metrics['average_precision']:.4f}",
        "",
        "## 最重要的預測因素",
        "",
        dataframe_to_markdown(top_features, float_digits=5),
        "",
        "係數絕對值代表影響強度；方向欄用來區分提高或降低延遲風險。",
        "",
        "## 最強的延遲風險上升訊號",
        "",
        dataframe_to_markdown(positive_features, float_digits=5),
        "",
        "## 測試集中的高風險訂單群",
        "",
        dataframe_to_markdown(top_segments, float_digits=4),
        "",
        "## 結論",
        "",
        "- 模型可作為延遲風險排序工具；在類別不平衡情況下，ROC-AUC、PR-AUC、Recall 與 F1 比 Accuracy 更有參考價值。",
        f"- 最佳模型 Average Precision 為 {best_metrics['average_precision']:.2%}，高於測試集延遲率基準 {test['delayed'].mean():.2%}，但仍有明顯改善空間。",
        "- 高風險訂單可提前交由客服或物流團隊追蹤，但模型分數不應視為確定會延遲。",
        "- 測試集採時間切分，因此結果更接近用歷史訂單預測未來訂單的實際情境。",
    ]
    (REPORT_DIR / "stage4_delay_prediction_summary.md").write_text(
        "\n".join(lines), encoding="utf-8"
    )


def main() -> None:
    for directory in [PROCESSED_DIR, MODEL_DIR, REPORT_DIR, IMAGE_DIR]:
        directory.mkdir(parents=True, exist_ok=True)

    dataset, numeric_features, categorical_features = load_and_build_features()
    train, test = temporal_train_test_split(dataset)
    feature_columns = numeric_features + categorical_features

    metrics, models, probabilities = evaluate_models(
        train, test, numeric_features, categorical_features
    )
    best_model_name = metrics.iloc[0]["model"]
    best_model = models[best_model_name]

    feature_importance = get_feature_importance(best_model)
    risk_segments = build_risk_segments(
        test, probabilities[best_model_name]
    )

    dataset.to_csv(PROCESSED_DIR / "olist_delay_model_dataset.csv", index=False)
    metrics.to_csv(REPORT_DIR / "olist_delay_model_metrics.csv", index=False)
    feature_importance.to_csv(
        REPORT_DIR / "olist_delay_feature_importance.csv", index=False
    )
    risk_segments.to_csv(
        REPORT_DIR / "olist_delay_risk_segments.csv", index=False
    )
    test.assign(
        predicted_delay_probability=probabilities[best_model_name]
    ).to_csv(REPORT_DIR / "olist_delay_test_predictions.csv", index=False)

    joblib.dump(best_model, MODEL_DIR / "olist_delay_best_model.joblib")
    metadata = {
        "best_model": best_model_name,
        "feature_columns": feature_columns,
        "numeric_features": numeric_features,
        "categorical_features": categorical_features,
        "train_end": str(train["order_purchase_timestamp"].max()),
        "test_start": str(test["order_purchase_timestamp"].min()),
        "test_end": str(test["order_purchase_timestamp"].max()),
        "delayed_definition": (
            "order_delivered_customer_date > order_estimated_delivery_date"
        ),
    }
    (MODEL_DIR / "olist_delay_model_metadata.json").write_text(
        json.dumps(metadata, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    save_evaluation_plots(
        metrics,
        models,
        probabilities,
        test,
        feature_columns,
        best_model_name,
    )
    save_feature_importance_plot(feature_importance)
    write_summary(
        dataset,
        train,
        test,
        metrics,
        best_model_name,
        feature_importance,
        risk_segments,
    )

    print(f"Rows: {len(dataset):,}")
    print(f"Delay rate: {dataset['delayed'].mean():.2%}")
    print(metrics.to_string(index=False))
    print(f"\nBest model: {best_model_name}")
    print("\nTop features:")
    print(feature_importance.head(10).to_string(index=False))
    print("\nTop risk segments:")
    print(risk_segments.head(10).to_string(index=False))


if __name__ == "__main__":
    main()
