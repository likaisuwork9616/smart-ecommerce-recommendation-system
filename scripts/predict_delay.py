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


def build_inference_features(artifact: dict, tables: dict, geolocation=None) -> pd.DataFrame:
    """Use the exact static/history contract saved with the chosen artifact."""
    feature_set = artifact.get('feature_set', 'approval_static')
    from scripts.delay_handover_count_training import FEATURE_SET as HANDOVER_COUNT_FEATURE_SET
    if feature_set == HANDOVER_COUNT_FEATURE_SET:
        from scripts.delay_handover_count_training import build_count_order_features
        return build_count_order_features(tables, geolocation)
    from scripts.delay_handover_features import FEATURE_SET as HANDOVER_FEATURE_SET
    if feature_set == HANDOVER_FEATURE_SET:
        from scripts.delay_handover_features import build_handover_order_features
        return build_handover_order_features(tables, geolocation)
    if feature_set.startswith('backlog_'):
        from scripts.delay_backlog_features import FEATURE_SET_DESIGNS, build_backlog_order_features
        if feature_set not in FEATURE_SET_DESIGNS:
            raise ValueError(f'Unsupported feature set: {feature_set}')
        backbone, variant = FEATURE_SET_DESIGNS[feature_set]
        return build_backlog_order_features(tables, backbone, variant, geolocation)
    if feature_set.startswith('route_load_'):
        from scripts.delay_route_load_training import FEATURE_SET_DESIGNS
        from scripts.delay_route_load_features import build_route_load_order_features
        if feature_set not in FEATURE_SET_DESIGNS:
            raise ValueError(f'Unsupported feature set: {feature_set}')
        backbone, variant = FEATURE_SET_DESIGNS[feature_set]
        return build_route_load_order_features(tables, backbone, variant, geolocation)
    if feature_set.startswith('ablation_'):
        from scripts.delay_ablation_features import FEATURE_SET_VARIANTS, build_ablation_order_features
        if feature_set not in FEATURE_SET_VARIANTS:
            raise ValueError(f'Unsupported feature set: {feature_set}')
        return build_ablation_order_features(tables, FEATURE_SET_VARIANTS[feature_set], geolocation)
    if feature_set in ('geo_engineered_approval', 'dispatch_geo_engineered_approval'):
        from scripts.delay_engineering_features import build_engineering_order_features
        if geolocation is None:
            raise ValueError('Engineering inference requires the static geolocation reference table')
        return build_engineering_order_features(tables, geolocation,
            include_dispatch=feature_set == 'dispatch_geo_engineered_approval')
    if feature_set == 'pending_seller_route_budget_90d':
        from scripts.delay_pending_features import build_pending_order_features
        return build_pending_order_features(tables)
    if feature_set == 'seller_route_budget_90d':
        from scripts.delay_budget_features import build_budget_order_features
        return build_budget_order_features(tables)
    if feature_set == 'route_promise_90d':
        from scripts.delay_route_features import build_route_order_features
        return build_route_order_features(tables)
    if feature_set == 'delivery_history_90d':
        from scripts.delay_history_features import build_history_order_features
        return build_history_order_features(tables)
    if feature_set == 'approval_static':
        return build_order_features(tables)
    raise ValueError(f'Unsupported feature set: {feature_set}')


def predict_features(artifact: dict, features: pd.DataFrame, *, complete_daily_batches=False) -> pd.DataFrame:
    """Ignore extra columns (including labels); validate the saved feature contract."""
    if artifact.get('format_version') != 1:
        raise ValueError('Unsupported model artifact version; retrain the Stage 4 model.')
    cap = artifact.get('daily_alert_cap')
    if cap is not None and not complete_daily_batches:
        raise ValueError('Capped models require complete_daily_batches=True and complete closed calendar-day batches.')
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
    raw_scores = pipeline.predict_proba(values)[:, positive_index]
    scores = raw_scores
    if artifact.get('calibrator') is not None:
        from scripts.delay_calibration_policy import transform_scores
        scores = transform_scores(artifact['calibrator'], raw_scores)
    threshold = float(artifact['threshold'])
    selected = scores >= threshold
    if cap is not None:
        from scripts.delay_calibration_policy import apply_alert_policy
        selected = apply_alert_policy(features, scores, threshold, cap, raw_scores=raw_scores)
    result = pd.DataFrame({
        'delay_score': scores,
        'threshold': threshold,
        'predicted_delayed': selected.astype(int),
    }, index=features.index)
    if 'order_id' in features:
        result.insert(0, 'order_id', features['order_id'])
    if artifact.get('calibrator') is not None:
        result['raw_delay_score'] = raw_scores
    if cap is not None:
        result['prediction_time'] = pd.to_datetime(features['prediction_time'])
        result['threshold_eligible'] = (scores >= threshold).astype(int)
        result['budget_suppressed'] = ((scores >= threshold) & ~selected).astype(int)
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
    parser.add_argument('--complete-daily-batches', action='store_true',
                        help='Acknowledge that CSV contains every scored order of each closed calendar day; required for capped models.')
    args = parser.parse_args()
    model_path = args.model or ROOT / 'models' / (
        'olist_delay_balanced.joblib' if args.profile == 'balanced' else 'olist_delay_model.joblib')
    artifact = joblib.load(model_path)
    if artifact.get('daily_alert_cap') is not None and (args.order_id or not args.complete_daily_batches):
        parser.error('Capped models require --features-csv and --complete-daily-batches; single-order prediction cannot enforce daily capacity.')
    if args.features_csv:
        features = pd.read_csv(args.features_csv, float_precision='round_trip',
                               dtype={name: object for name in artifact['categorical_features']})
    else:
        tables = load_olist_tables(args.data_dir)
        # History consults previously completed orders only, excluding the current outcome.
        geolocation = None
        from scripts.delay_ablation_features import GEOGRAPHIC_FEATURE_SETS
        from scripts.delay_route_load_training import GEOGRAPHIC_FEATURE_SETS as ROUTE_LOAD_GEO_SETS
        from scripts.delay_backlog_features import GEOGRAPHIC_FEATURE_SETS as BACKLOG_GEO_SETS
        from scripts.delay_handover_features import FEATURE_SET as HANDOVER_FEATURE_SET
        from scripts.delay_handover_count_training import FEATURE_SET as HANDOVER_COUNT_FEATURE_SET
        if artifact.get('feature_set') in ({'geo_engineered_approval', 'dispatch_geo_engineered_approval', HANDOVER_FEATURE_SET, HANDOVER_COUNT_FEATURE_SET} | GEOGRAPHIC_FEATURE_SETS | ROUTE_LOAD_GEO_SETS | BACKLOG_GEO_SETS):
            from scripts.delay_engineering_features import GEO_FILENAME
            geolocation = pd.read_csv(args.data_dir / GEO_FILENAME)
        features = build_inference_features(artifact, tables, geolocation)
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
    predictions = predict_features(artifact, features, complete_daily_batches=args.complete_daily_batches)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        predictions.to_csv(args.output, index=False)
    print(json.dumps({
        'profile': 'custom' if args.model else args.profile,
        'selected_model': artifact['selected_model'],
        'rows': len(predictions),
        'preview': json.loads(predictions.head(10).to_json(orient='records', date_format='iso')),
        'daily_alert_cap': artifact.get('daily_alert_cap'),
        'note': ('delay_score uses historical calibration; calibration on new model versions is not guaranteed.'
                 if artifact.get('calibrator') is not None else
                 'delay_score is a model score; it is not a calibrated delivery probability.'),
    }, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
