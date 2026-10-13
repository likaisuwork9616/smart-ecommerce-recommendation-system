"""Score approved orders with the saved Stage 4 pipeline and validation threshold."""
import argparse
import json
from pathlib import Path
import sys

import joblib
import numpy as np
import pandas as pd

try:
    from .delay_features import build_order_features, load_olist_tables
except ImportError:
    from delay_features import build_order_features, load_olist_tables

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def build_inference_features(artifact: dict, tables: dict) -> pd.DataFrame:
    """Use the exact static/history contract saved with the chosen artifact."""
    feature_set = artifact.get('feature_set', 'approval_static')
    if feature_set == 'route_promise_90d':
        from scripts.delay_route_features import build_route_order_features
        return build_route_order_features(tables)
    if feature_set == 'delivery_history_90d':
        from scripts.delay_history_features import build_history_order_features
        return build_history_order_features(tables)
    if feature_set == 'approval_static':
        return build_order_features(tables)
    raise ValueError(f'Unsupported feature set: {feature_set}')


def predict_features(artifact: dict, features: pd.DataFrame) -> pd.DataFrame:
    """Ignore extra columns (including labels); validate the saved feature contract."""
    if artifact.get('format_version') != 1:
        raise ValueError('Unsupported model artifact version; retrain the Stage 4 model.')
    names = artifact['feature_names']
    missing = sorted(set(names) - set(features.columns))
    if missing:
        raise ValueError(f'Missing required feature columns: {missing}')
    values = features[names].copy()
    for column in artifact['numeric_features']:
        values[column] = pd.to_numeric(values[column], errors='coerce').replace(
            [np.inf, -np.inf], np.nan)
    for column in artifact['categorical_features']:
        values[column] = values[column].astype(object).where(values[column].notna(), np.nan)
    pipeline = artifact['pipeline']
    positive_index = list(pipeline.classes_).index(1)
    scores = pipeline.predict_proba(values)[:, positive_index]
    threshold = float(artifact['threshold'])
    result = pd.DataFrame({
        'delay_score': scores,
        'threshold': threshold,
        'predicted_delayed': (scores >= threshold).astype(int),
    }, index=features.index)
    if 'order_id' in features:
        result.insert(0, 'order_id', features['order_id'])
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--profile', choices=['original', 'balanced'], default='original',
                        help='original: frozen first model; balanced: validation recall target with fewer alerts.')
    parser.add_argument('--model', type=Path, help='Custom model artifact; overrides --profile.')
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument('--order-id', help='An approved order ID from the local raw CSV files.')
    source.add_argument('--features-csv', type=Path, help='CSV containing every feature required by the selected model.')
    parser.add_argument('--data-dir', type=Path, default=ROOT / 'data/raw/olist')
    parser.add_argument('--output', type=Path, help='Optional output CSV path.')
    args = parser.parse_args()
    model_path = args.model or ROOT / 'models' / (
        'olist_delay_balanced.joblib' if args.profile == 'balanced' else 'olist_delay_model.joblib')
    artifact = joblib.load(model_path)
    if args.features_csv:
        features = pd.read_csv(args.features_csv)
    else:
        tables = load_olist_tables(args.data_dir)
        # History consults previously completed orders only, excluding the current outcome.
        features = build_inference_features(artifact, tables)
        features = features.loc[features['order_id'].eq(args.order_id)].copy()
        if features.empty:
            raise ValueError(f'Order not found: {args.order_id}')
        row = features.iloc[0]
        if (pd.isna(row['prediction_time']) or pd.isna(row['order_purchase_timestamp']) or
                row['prediction_time'] < row['order_purchase_timestamp'] or
                pd.isna(row['estimated_delivery_days']) or row['estimated_delivery_days'] < 0):
            raise ValueError('The order needs valid purchase, approval and estimated delivery dates.')
    if features.empty:
        raise ValueError('No feature rows to predict.')
    predictions = predict_features(artifact, features)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        predictions.to_csv(args.output, index=False)
    print(json.dumps({
        'profile': 'custom' if args.model else args.profile,
        'selected_model': artifact['selected_model'],
        'rows': len(predictions),
        'preview': predictions.head(10).to_dict(orient='records'),
        'note': 'delay_score is a model score; it is not a calibrated delivery probability.',
    }, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
