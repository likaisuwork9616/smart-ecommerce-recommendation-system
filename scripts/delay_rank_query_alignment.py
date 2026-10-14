"""Describe saved rankers' mature queries against retrospective daily cohorts.

No model is loaded, fitted, scored or selected. Position coverage describes
where fixed top-k can focus; it is not a measurement of actual pair weights.
"""
from __future__ import annotations

import hashlib

import numpy as np
import pandas as pd

from scripts.delay_outcome_clock import split_outcome_training_month

FOCUS_VALUES = (10, 20, 40)
MONTHS = ('2017-07', '2017-12')


def size_band(size):
    if isinstance(size, (bool, np.bool_)) or not isinstance(size, (int, np.integer)) or size < 0:
        raise ValueError('Daily size must be a nonnegative integer')
    if size == 0:
        return '0'
    return '1-99' if size < 100 else '100-199' if size < 200 else '200-399' if size < 400 else '400+'


def _relation(value, capacity):
    return 'below' if value < capacity else 'equal' if value == capacity else 'above'


def summarize_queries(records):
    """Aggregate query positions, keeping both configured and clipped k explicit."""
    for row in records:
        n, q, p = (row[key] for key in ('full_eligible_rows', 'training_rows', 'training_positive_rows'))
        for value in (n, q, p):
            if isinstance(value, (bool, np.bool_)) or not isinstance(value, (int, np.integer)) or value < 0:
                raise ValueError('Query counts must be nonnegative integers')
        if n == 0 or not 0 <= p <= q <= n:
            raise ValueError('Require positive complete cohort and nested mature query counts')
    queries = [row for row in records if row['training_rows'] > 0]
    mixed = [row for row in queries if 0 < row['training_positive_rows'] < row['training_rows']]
    rows = sum(row['training_rows'] for row in queries)
    positives = sum(row['training_positive_rows'] for row in queries)
    sizes = np.array([row['training_rows'] for row in queries], dtype=int)
    result = {
        'past_eligible_days': len(records), 'queries': len(queries),
        'days_without_mature_training_rows': len(records) - len(queries),
        'mixed_label_queries': len(mixed),
        'all_on_time_queries': sum(row['training_positive_rows'] == 0 for row in queries),
        'all_delayed_queries': sum(row['training_positive_rows'] == row['training_rows'] for row in queries),
        'full_retrospective_eligible_rows': sum(row['full_eligible_rows'] for row in records),
        'training_rows': rows, 'training_positive_rows': positives,
        'excluded_not_mature_rows': sum(row['full_eligible_rows'] - row['training_rows'] for row in records),
        'training_positive_rate': positives / rows if rows else None,
        'query_size_min': int(sizes.min()) if len(sizes) else None,
        'query_size_median': float(np.median(sizes)) if len(sizes) else None,
        'query_size_max': int(sizes.max()) if len(sizes) else None,
        'focus': {},
    }
    for k in FOCUS_VALUES:
        positions = sum(min(k, row['training_rows']) for row in queries)
        mixed_rows = sum(row['training_rows'] for row in mixed)
        mixed_positions = sum(min(k, row['training_rows']) for row in mixed)
        alignments = {}
        for reference in ('mature_query', 'retrospective_complete_cohort'):
            column = 'training_rows' if reference == 'mature_query' else 'full_eligible_rows'
            scopes = {}
            for scope, selected in (('all_queries', queries), ('mixed_label_queries', mixed)):
                relations = {name: {'queries': 0, 'training_rows': 0, 'training_positive_rows': 0}
                             for name in ('below', 'equal', 'above')}
                effective = {name: 0 for name in ('below', 'equal', 'above')}
                zero_capacity = 0
                for row in selected:
                    capacity = row[column] // 10
                    group = relations[_relation(k, capacity)]
                    group['queries'] += 1
                    group['training_rows'] += row['training_rows']
                    group['training_positive_rows'] += row['training_positive_rows']
                    effective[_relation(min(k, row['training_rows']), capacity)] += 1
                    zero_capacity += capacity == 0
                scopes[scope] = {'configured_k_relation': relations,
                                 'effective_focus_relation_queries': effective,
                                 'zero_capacity_queries': zero_capacity}
            alignments[reference] = scopes
        result['focus'][str(k)] = {
            'configured_k': k, 'effective_focus_positions': positions,
            'focus_position_fraction': positions / rows if rows else None,
            'queries_fully_covered_by_k': sum(row['training_rows'] <= k for row in queries),
            'mixed_query_effective_focus_positions': mixed_positions,
            'mixed_query_focus_position_fraction': mixed_positions / mixed_rows if mixed_rows else None,
            'alignment': alignments,
        }
    return result


def build_training_alignment(dataset, source):
    """Rebuild existing monthly training identities and compare saved query sizes."""
    if (dataset.order_id.isna().any() or dataset.order_id.duplicated().any()
            or source.get('experiment') != 'rank_pair_focus'):
        raise ValueError('Require the frozen unique eligible cohort and pair-focus source')
    monthly = {entry['month']: entry for entry in source['monthly_training']}
    new = source['new_candidate_order']
    output = {
        'analysis': 'mature_training_query_position_alignment',
        'new_fit_count': 0, 'model_load_count': 0, 'model_prediction_count': 0,
        'interpretation': (
            'The full past-day count uses the unchanged eventually-delivered eligible cohort retrospectively. '
            'It is not the count of all approved orders known at fit time. Mature training queries are subsets. '
            'min(k,query_size) measures position coverage, not generated pair counts, pair weights or causal effects. '
            'All-on-time and all-delayed queries have no different-label pairs.'
        ),
        'months': {},
    }
    prediction = pd.to_datetime(dataset.prediction_time, errors='raise')
    for month in MONTHS:
        entry = monthly[month]
        split, metadata = split_outcome_training_month(dataset, entry['split']['model_fit_time'],
                                                       wait_days=0, clock='deadline')
        for model in entry['models'].values():
            if model['training_split'] != metadata:
                raise ValueError('Frozen mature training split changed')
        training = split['train'].sort_values(['prediction_time', 'order_id'], kind='stable').reset_index(drop=True)
        daily = training.groupby(training.prediction_time.dt.normalize(), sort=True).delayed.agg(['size', 'sum'])
        order_hash = hashlib.sha256('\n'.join(training.order_id.astype(str)).encode('utf-8')).hexdigest()
        sizes = daily['size'].astype(int).tolist()
        for candidate in new:
            model = entry['models'][candidate]
            if (model['training_order_sha256'] != order_hash or model['daily_training_groups'] != sizes):
                raise ValueError('Saved training order or daily groups changed')
        past = dataset.loc[prediction < pd.Timestamp(metadata['model_fit_time'])]
        full = past.groupby(pd.to_datetime(past.prediction_time).dt.normalize(), sort=True).size()
        records = []
        for day, full_size in full.items():
            q = int(daily.loc[day, 'size']) if day in daily.index else 0
            positive = int(daily.loc[day, 'sum']) if day in daily.index else 0
            records.append({
                'day': day.date().isoformat(), 'full_eligible_rows': int(full_size),
                'training_rows': q, 'training_positive_rows': positive,
                'excluded_not_mature_rows': int(full_size) - q,
                'mature_query_capacity_at_10_percent': q // 10,
                'retrospective_complete_capacity_at_10_percent': int(full_size) // 10,
                'complete_volume_bin': size_band(int(full_size)), 'query_volume_bin': size_band(q),
            })
        summary = summarize_queries(records)
        expected = entry['models'][new[0]]['daily_training_query_counts']
        if any(summary[key] != expected[key] for key in expected):
            raise ValueError('Saved mixed-label query counts changed')
        output['months'][month] = {
            'model_fit_time': metadata['model_fit_time'],
            'training_order_sha256': order_hash,
            'training_identity_fingerprint': metadata['partitions']['train']['order_id_fingerprint'],
            'checked_training_splits': len(entry['models']),
            'checked_saved_query_metadata_candidates': list(new),
            'summary': summary, 'daily_queries': records,
            'by_complete_day_volume': {
                band: summarize_queries([row for row in records if row['complete_volume_bin'] == band])
                for band in ('1-99', '100-199', '200-399', '400+')
            },
        }
    return output
