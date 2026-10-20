"""Profile pre-May approval-time review targets; never train or score a model."""
from __future__ import annotations

import argparse
import ast
import csv
import hashlib
import json
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
EVENT = 'reports/stage4/event_source_availability.json'
EVENT_SHA = 'fc5fdf4018a8b3d3202d8b7efb325904f215de78e4fe4871e48fe3e79ca29ee8'
BASELINE = 'scripts/delay_features.py'
BASELINE_SHA = 'a21c70789b6e9831db8af196f29ac5084543f11495ab09edc150ac32e4b02cde'
CODE = 'scripts/audit_review_prediction_feasibility.py'
OUTPUT = 'reports/stage5/review_prediction_feasibility.json'
CUTOFF = pd.Timestamp('2018-05-01')
REVIEW_COLUMNS = ['review_id', 'order_id', 'review_score', 'review_creation_date',
                  'review_answer_timestamp']
DATES = ['order_purchase_timestamp', 'order_approved_at', 'order_delivered_carrier_date',
         'order_delivered_customer_date', 'order_estimated_delivery_date']


def descriptor(path, root=ROOT):
    path, root = Path(path).resolve(), Path(root).resolve()
    if not path.is_relative_to(root) or not path.is_file():
        raise ValueError('Source must be an existing project file')
    digest = hashlib.sha256()
    with path.open('rb') as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b''):
            digest.update(chunk)
    return {'path': path.relative_to(root).as_posix(), 'bytes': path.stat().st_size,
            'sha256': digest.hexdigest()}


def read_json(path):
    def unique(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise ValueError('Duplicate JSON key')
            result[key] = value
        return result
    def invalid(value):
        raise ValueError('Non-finite JSON value')
    return json.loads(Path(path).read_text(encoding='utf-8'), object_pairs_hook=unique,
                      parse_constant=invalid)


def verify_sources(items, root=ROOT):
    if len({item['path'] for item in items}) != len(items):
        raise ValueError('Duplicate bound source')
    for item in items:
        if descriptor(Path(root) / item['path'], root) != {
                key: item[key] for key in ('path', 'bytes', 'sha256')}:
            raise ValueError('Bound source changed: ' + item['path'])
    return len(items)


def immutable_write(path, payload):
    data = (json.dumps(payload, ensure_ascii=False, sort_keys=True, indent=2,
                       allow_nan=False) + '\n').encode('utf-8')
    path = Path(path)
    if path.exists() and path.read_bytes() != data:
        raise ValueError('Refusing to overwrite different audit bytes')
    if not path.exists():
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open('xb') as stream:
            stream.write(data)


def parse_clock(values):
    parsed = pd.to_datetime(values, format='%Y-%m-%d %H:%M:%S', errors='coerce')
    return parsed, {'missing': int(values.isna().sum()),
                    'invalid_nonmissing': int((values.notna() & parsed.isna()).sum())}


def approval_cohort(orders):
    if orders.order_id.isna().any() or orders.order_id.duplicated().any():
        raise ValueError('Order IDs must be present and unique')
    result, quality = orders.copy(), {}
    for name in DATES:
        result[name], quality[name] = parse_clock(orders[name])
    purchase, approval = result.order_purchase_timestamp, result.order_approved_at
    valid = purchase.notna() & approval.notna() & approval.ge(purchase)
    quality['approval_before_purchase'] = int(approval.lt(purchase).sum())
    quality['valid_purchase_approval_rows'] = int(valid.sum())
    cohort = result.loc[valid & approval.lt(CUTOFF)].copy()
    quality['pre_may_valid_approval_rows'] = len(cohort)
    quality['final_status_filter_applied'] = False
    return cohort, quality


def first_answer_profile(cohort, reviews):
    """Establish the first answer before checking t; never repick a later review."""
    reviews = reviews[REVIEW_COLUMNS].copy()
    quality = {'rows': len(reviews), 'missing_order_id': int(reviews.order_id.isna().sum()),
               'missing_review_id': int(reviews.review_id.isna().sum()),
               'distinct_order_ids': int(reviews.order_id.nunique()),
               'distinct_review_ids': int(reviews.review_id.nunique()),
               'reused_review_id_groups': int((reviews.groupby('review_id').size() > 1).sum()),
               'duplicate_review_id_rows': int(reviews.review_id.duplicated(keep=False).sum()),
               'duplicate_review_id_excess_rows': int(reviews.review_id.duplicated().sum()),
               'duplicate_pair_rows': int(reviews.duplicated(['review_id', 'order_id'], keep=False).sum()),
               'multi_review_orders': int((reviews.groupby('order_id').size() > 1).sum()),
               'extra_review_rows_beyond_one_per_order': int(reviews.order_id.duplicated().sum()),
               'orders_with_different_recorded_scores': int((reviews.groupby('order_id').review_score.nunique() > 1).sum())}
    for name in ('review_creation_date', 'review_answer_timestamp'):
        reviews[name], quality[name] = parse_clock(reviews[name])
    scores = pd.to_numeric(reviews.review_score, errors='coerce')
    valid_scores = scores.isin([1, 2, 3, 4, 5])
    quality['invalid_or_missing_score_rows'] = int((~valid_scores).sum())
    reviews['score_valid'] = valid_scores
    reviews['score'] = scores
    reviews['duplicate_pair'] = reviews.duplicated(['review_id', 'order_id'], keep=False)
    groups = {key: group for key, group in reviews.groupby('order_id', sort=False)}
    records = []
    for order in cohort.itertuples(index=False):
        group = groups.get(order.order_id)
        state, answer, score, creation = 'no_review', pd.NaT, None, pd.NaT
        if group is not None:
            state = 'missing_answer_prevents_first'
            if group.duplicate_pair.any() or group.review_id.isna().any():
                state = 'duplicate_or_missing_review_key'
            elif group.review_answer_timestamp.notna().all():
                answer = group.review_answer_timestamp.min()
                first = group.loc[group.review_answer_timestamp.eq(answer)]
                state = 'ambiguous_first_answer_tie'
                if len(first) == 1:
                    row = first.iloc[0]
                    state = 'invalid_review_score'
                    if group.score_valid.all():
                        state = 'invalid_review_creation_clock'
                        if group.review_creation_date.notna().all():
                            state = 'review_creation_after_its_answer'
                            if group.review_creation_date.le(group.review_answer_timestamp).all():
                                state = 'first_answer_not_after_approval'
                                if answer > order.order_approved_at:
                                    state, score, creation = 'future_first_answer', int(row.score), row.review_creation_date
        records.append({'order_id': order.order_id, 'label_state': state,
                        'label_available_event_proxy': answer, 'first_creation': creation, 'score': score})
    joined = cohort.merge(pd.DataFrame(records), on='order_id', validate='one_to_one')
    known = joined.label_state.eq('future_first_answer')
    selected = joined.loc[known]
    summary = {'cohort_orders': len(joined),
               'exclusive_label_states': {str(k): int(v) for k, v in joined.label_state.value_counts().sort_index().items()},
               'descriptive_future_first_answer_labels': int(known.sum()),
               'descriptive_low_1_2': int(selected.score.le(2).sum()),
               'descriptive_other_3_5': int(selected.score.ge(3).sum()),
               'creation_before_approval_but_first_answer_after': int(selected.first_creation.lt(selected.order_approved_at).sum()),
               'unlabeled_or_quarantined': int((~known).sum()),
               'review_rows_orphan_to_all_orders': None,
               'no_review_is_negative': False,
               'first_answer_chosen_before_approval_filter': True,
               'all_earliest_timestamp_ties_quarantined': True,
               'label_availability_clock': 'answer event time proxy, not verified source observation or ingestion time'}
    comparisons = {}
    for name in ('order_approved_at', 'order_delivered_carrier_date', 'order_delivered_customer_date'):
        clock = selected[name]
        comparisons[name] = {'same_labeled_pre_may_cohort': len(selected),
                             'missing_anchor': int(clock.isna().sum()),
                             'first_answer_before_anchor': int(selected.label_available_event_proxy.lt(clock).sum()),
                             'first_answer_equal_anchor': int(selected.label_available_event_proxy.eq(clock).sum()),
                             'first_answer_after_anchor': int(selected.label_available_event_proxy.gt(clock).sum())}
    return joined, quality, summary, comparisons


def temporal_support(joined):
    rows = []
    known = joined.label_state.eq('future_first_answer')
    for text in ('2017-12-01', '2018-02-01', '2018-04-01'):
        start = pd.Timestamp(text)
        end = start + pd.offsets.MonthBegin(1)
        history = joined.order_approved_at.lt(start)
        available = known & joined.label_available_event_proxy.lt(start)
        window = joined.order_approved_at.ge(start) & joined.order_approved_at.lt(end)
        evaluation_known = known & joined.label_available_event_proxy.lt(CUTOFF)
        rows.append({'proposed_fit_event_cutoff_exclusive': start.isoformat(),
                     'proposed_evaluation_start': start.isoformat(),
                     'proposed_evaluation_end_exclusive': end.isoformat(),
                     'historical_valid_approvals': int(history.sum()),
                     'historical_label_event_before_fit': int((history & available).sum()),
                     'historical_future_label_not_yet_before_fit': int((history & known & ~available).sum()),
                     'historical_unlabeled_or_quarantined': int((history & ~known).sum()),
                     'evaluation_valid_approvals': int(window.sum()),
                     'evaluation_label_event_before_may_cutoff': int((window & evaluation_known).sum()),
                     'evaluation_unknown_at_may_cutoff': int((window & ~evaluation_known).sum())})
    return rows


def feature_inventory(tables, cohort, feature_names):
    ids = set(cohort.order_id)
    items = tables['order_items'].loc[lambda x: x.order_id.isin(ids)]
    payments = tables['order_payments'].loc[lambda x: x.order_id.isin(ids)]
    summaries = {}
    for name, frame in tables.items():
        summaries[name] = {'rows_read': len(frame),
                           'missing_by_field': {column: int(frame[column].isna().sum()) for column in frame.columns}}
    for name, frame, key in (('customers', tables['customers'], 'customer_id'),
                             ('products', tables['products'], 'product_id'),
                             ('sellers', tables['sellers'], 'seller_id')):
        summaries[name]['duplicate_primary_key_rows'] = int(frame[key].duplicated(keep=False).sum())
    summaries['order_items']['duplicate_order_item_key_rows'] = int(tables['order_items'].duplicated(['order_id', 'order_item_id'], keep=False).sum())
    summaries['order_payments']['duplicate_order_sequence_key_rows'] = int(tables['order_payments'].duplicated(['order_id', 'payment_sequential'], keep=False).sum())
    joins = {'cohort_orders': len(cohort),
             'orders_with_customer': int(cohort.customer_id.isin(tables['customers'].customer_id).sum()),
             'orders_with_items': int(cohort.order_id.isin(items.order_id).sum()),
             'orders_with_payments': int(cohort.order_id.isin(payments.order_id).sum()),
             'cohort_item_rows': len(items), 'cohort_payment_rows': len(payments),
             'cohort_items_with_product': int(items.product_id.isin(tables['products'].product_id).sum()),
             'cohort_items_with_seller': int(items.seller_id.isin(tables['sellers'].seller_id).sum())}
    sources = {
        'orders': ['estimated_delivery_days', 'approval_wait_hours', 'purchase_month', 'purchase_dayofweek', 'purchase_hour'],
        'order_items': ['item_count', 'seller_count', 'product_count', 'total_price', 'total_freight_value', 'freight_ratio', 'primary_category', 'primary_seller_state', 'product_weight_g_mean', 'product_volume_cm3_mean', 'interstate_item_ratio'],
        'order_payments': ['payment_total', 'payment_count', 'payment_installments_max', 'payment_type'],
        'customers': ['customer_state']}
    readiness = [{'feature': name, 'primary_source': next(source for source, names in sources.items() if name in names),
                  'availability': 'conditional_on_approval_time_source_observation_and_version_evidence',
                  'computed_or_imputed': False} for name in feature_names]
    return {'source_profiles': summaries, 'cohort_join_coverage': joins,
            'existing_21_feature_candidates': readiness, 'feature_values_built': 0,
            'availability_proven_by_final_snapshot': False,
            'join_dependencies': {'product_attributes_and_category': ['order_items', 'products'],
                                  'seller_state': ['order_items', 'sellers'],
                                  'interstate_ratio': ['order_items', 'sellers', 'customers']},
            'excluded_features': ['current_review_id_score_dates_text', 'actual_shipping_or_delivery',
                                  'final_order_status', 'raw_identity_fields', 'future_seller_customer_reviews'],
            'history_aggregates': 'deferred until dual-time availability and version rules are accepted'}


def run(root=ROOT):
    root = Path(root)
    event_desc = descriptor(root / EVENT, root)
    if event_desc['sha256'] != EVENT_SHA or descriptor(root / BASELINE, root)['sha256'] != BASELINE_SHA:
        raise ValueError('Previously inspected source/code snapshot changed')
    event = read_json(root / EVENT)
    raw = event['raw_sources']
    if len(raw) != 9:
        raise ValueError('Expected exactly nine frozen raw sources')
    sources = [event_desc, *raw, descriptor(root / BASELINE, root), descriptor(root / CODE, root)]
    verify_sources(sources, root)
    for item in raw:
        with (root / item['path']).open(encoding='utf-8-sig', newline='') as stream:
            if next(csv.reader(stream)) != item['columns']:
                raise ValueError('Raw schema changed')
        count = sum(len(chunk) for chunk in pd.read_csv(root / item['path'], usecols=[0], chunksize=100000))
        if count != item['rows']:
            raise ValueError('Raw row count changed')
    tables = {}
    for name in ('orders', 'customers', 'order_items', 'order_payments', 'products', 'sellers'):
        path = root / f'data/raw/olist/olist_{name}_dataset.csv'
        tables[name] = pd.read_csv(path, dtype={'order_id': str, 'customer_id': str, 'product_id': str, 'seller_id': str})
    reviews = pd.read_csv(root / 'data/raw/olist/olist_order_reviews_dataset.csv', usecols=REVIEW_COLUMNS,
                          dtype={'review_id': str, 'order_id': str, 'review_score': str})
    cohort, order_quality = approval_cohort(tables['orders'])
    joined, review_quality, label, comparisons = first_answer_profile(cohort, reviews)
    label['review_rows_orphan_to_all_orders'] = int((~reviews.order_id.isin(tables['orders'].order_id)).sum())
    tree = ast.parse((root / BASELINE).read_text(encoding='utf-8'))
    constants = {node.targets[0].id: ast.literal_eval(node.value) for node in tree.body
                 if isinstance(node, ast.Assign) and isinstance(node.targets[0], ast.Name)
                 and node.targets[0].id in ('NUMERIC_FEATURES', 'CATEGORICAL_FEATURES')}
    names = constants['NUMERIC_FEATURES'] + constants['CATEGORICAL_FEATURES']
    if len(names) != 21 or len(set(names)) != 21:
        raise ValueError('Unexpected existing candidate feature contract')
    report = {'format_version': 1, 'analysis': 'approval_time_low_review_prediction_feasibility',
              'status': 'retrospective_proposal_only_operational_clocks_pending_data',
              'source_snapshot_role': 'source_audited_proposal_not_model_preregistration_or_live_validator',
              'sources': sources, 'cutoff_exclusive': CUTOFF.isoformat(),
              'prediction_question': {'time': 'order_approved_at', 'population': 'valid purchase/approval; approval >= purchase; approval < 2018-05-01; no final-status filter',
                                      'target': 'earliest recorded answer score 1-2 versus 3-5; first establish earliest, then require answer > approval',
                                      'unit': 'one order', 'absence': 'unknown, never a negative',
                                      'creation_date_semantics_verified': False},
              'order_quality': order_quality, 'review_quality': review_quality,
              'label_feasibility': label, 'same_cohort_clock_comparisons': comparisons,
              'features': feature_inventory(tables, cohort, names),
              'proposed_temporal_support_only': temporal_support(joined),
              'temporal_contract': {'timestamps': 'naive event times only; source timezone, ingestion and historical revisions unverified',
                                     'strict_history': 'approval < F AND first valid future answer event < F; event at F excluded, where F is the proposed model-fit event cutoff',
                                     'window': 'complete approval month [start,end), never random row split',
                                     'label_maturity': 'horizon H and censoring C remain undecided; maximum observed answer is not completeness evidence',
                                     'preprocessing': 'future imputation, encoding, history construction, tuning and threshold selection train-only in inner chronological validation',
                                     'calendar': 'previously inspected development calendar; no new untouched final test claimed'},
              'protected_stage4': {'status': 'pending_data', 'daily_alert_fraction': 0.1, 'seeds': [11, 29, 42, 73, 101],
                                   'stage5_sampling_or_fold_rule_inferred': False, 'event_signals': 'pending_data'},
              'verification': {'bound_sources_before_and_after': verify_sources(sources, root),
                               'raw_tables_schema_and_rows_checked': 9, 'review_text_columns_loaded': 0,
                               'new_model_loads': 0, 'new_fit': 0, 'new_predictions': 0,
                               'new_performance_metrics': 0, 'new_model_selection': 0,
                               'new_dashboard': 0, 'original_holdout_scored': False},
              'decision': 'allow_documented_retrospective_stage5_design_only_no_training_no_performance_claims'}
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', default=OUTPUT)
    args = parser.parse_args()
    path = (ROOT / args.output).resolve()
    allowed = path == ROOT / OUTPUT or path.is_relative_to((ROOT / '.runtime').resolve())
    if not path.is_relative_to(ROOT) or not allowed:
        raise ValueError('Output must be the fixed public aggregate report or inside .runtime')
    report = run()
    if path in {ROOT / item['path'] for item in report['sources']}:
        raise ValueError('Output must not replace an input')
    verify_sources(report['sources'])
    immutable_write(path, report)
    verify_sources(report['sources'])
    print(json.dumps({'status': report['status'], 'cohort_orders': report['label_feasibility']['cohort_orders'],
                      'label_states': report['label_feasibility']['exclusive_label_states'],
                      'output': path.relative_to(ROOT).as_posix()}, ensure_ascii=False))


if __name__ == '__main__':
    main()
