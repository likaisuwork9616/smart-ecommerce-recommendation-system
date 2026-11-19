"""Publish aggregate-only August K1 evidence after the independent workers have exited."""
import argparse
from datetime import datetime
import hashlib
import json
import math
from pathlib import Path
import re

from scripts.retailrocket_popularity_oracle import GROUPS, METRICS
from scripts.verify_k1_aggregate_v1 import write_result
from scripts.verify_k1_sql_witness_v1 import ordinals


ROOT = Path(__file__).resolve().parents[1]
ATTEMPT = 'reports/stage12/retailrocket_session_knn_v1_validation_attempt.json'
SLOT = 'reports/stage10/recency_slot_validation_201508.json'
ARMS = ('P0', 'C1', 'D1', 'K1')
MEASURES = (*METRICS, 'visitor_macro_ndcg', 'catalog_coverage')
CORE = ('sources_before', 'cohort', 'predictions', 'sql_witness', 'aggregate', 'sources_after')
OUTCOMES = ('both', 'k1_only', 'c1_only', 'neither')
COUNT_FIELDS = ('queries', 'visitors', 'target_occurrences', 'reachable_target_occurrences',
                'all_targets_reachable_queries')


def require(condition, label):
    if not condition:
        raise ValueError('Inconsistent verification evidence: ' + label)


def digest(value):
    require(isinstance(value, str) and re.fullmatch('[0-9a-f]{64}', value), 'SHA-256 format')
    return value


def load(path):
    data = path.read_bytes()
    return json.loads(data), hashlib.sha256(data).hexdigest()


def close(a, b):
    return type(a) in (int, float) and type(b) in (int, float) and math.isclose(a, b, rel_tol=1e-12, abs_tol=1e-12)


def measurements(values, bound):
    result = {}
    for key in MEASURES:
        value = values[key]
        require(value is None or (type(value) in (int, float) and bound <= value <= 1), key)
        result[key] = value
    return result


def fold_summary(fold, hits):
    n = fold['queries']
    require(type(n) is int and n >= 0 and n == hits['queries'], 'paired queries')
    visitors = fold['visitors']
    require(type(visitors) is int and 0 <= visitors <= n, 'fold visitors')
    arms = {}
    for arm in ARMS:
        h = hits['hits'][arm]
        raw = fold['arms'][arm]
        require(type(h) is int and 0 <= h <= n and raw['queries'] == n and raw['visitors'] == visitors,
                'arm denominator ' + arm)
        vals = measurements(raw['metrics'], 0)
        require(close(vals['hit_rate'], h/n) if n else vals['hit_rate'] is None, 'hit counts ' + arm)
        recommended, available = raw['recommended_unique_items'], raw['candidate_union_items']
        require(type(recommended) is int and type(available) is int and 0 <= recommended <= available and
                (close(vals['catalog_coverage'], recommended/available) if available else vals['catalog_coverage'] is None),
                'catalogue denominator ' + arm)
        arms[arm] = {'hit_queries': h, 'metrics': vals, 'recommended_unique_items': recommended,
                     'candidate_union_items': available}
    paired = {k: hits['K1_vs_C1'][k] for k in OUTCOMES}
    require(all(type(value) is int and value >= 0 for value in paired.values()) and sum(paired.values()) == n
            and paired['both'] + paired['k1_only'] == arms['K1']['hit_queries']
            and paired['both'] + paired['c1_only'] == arms['C1']['hit_queries'], 'paired hit outcomes')
    comparisons = {}
    for arm in ARMS[:-1]:
        name = 'K1_minus_' + arm
        delta = measurements(fold['comparisons'][name]['delta_metrics'], -1)
        for metric, value in delta.items():
            a, b = arms['K1']['metrics'][metric], arms[arm]['metrics'][metric]
            require(value is None if a is None or b is None else close(value, a-b), name + '/' + metric)
        comparisons[name] = delta
    return {'queries': n, 'visitors': visitors, 'arms': arms, 'comparisons': comparisons,
            'paired_hit_queries_K1_vs_C1': paired,
            'net_extra_hit_queries_K1_minus_C1': paired['k1_only'] - paired['c1_only']}


def resource(out, stage, passed):
    r, signature = load(out / ('resource_' + stage + '.json'))
    require(r['stage'] == stage and r['status'] == ('passed' if passed else 'incomplete'), stage + ' exit')
    times = {k: datetime.fromisoformat(r[k]) for k in ('started_utc', 'ended_utc', 'deadline_utc')}
    require(all(v.utcoffset() is not None for v in times.values()), stage + ' UTC offsets')
    require(times['started_utc'] <= times['ended_utc'] and
            (not passed or times['ended_utc'] <= times['deadline_utc']), stage + ' deadline')
    counters = {k: r[k] for k in ('samples', 'sampled_peak_tree_rss_bytes', 'sampled_peak_run_disk_bytes')}
    require(all(type(v) is int and v >= 0 for v in counters.values()), stage + ' sampled resources')
    return {**{k: v.isoformat() for k, v in times.items()}, **counters, 'status': r['status'],
            'receipt_sha256': signature}


def compare_slot(slot, roster, main, bound_sources):
    require(slot['baseline'] == 'C1' and slot['role'] == '2015-08 exposed development validation'
            and slot['roster_sha256'] == roster and slot['counts']['queries'] == main['queries'],
            'recency slot roster and baseline')
    c1_src = 'shop-mysql-runtime/retailrocket_cooccurrence_paired_v1/queries.jsonl'
    require(slot['source_sha256'][c1_src] == bound_sources[c1_src], 'recency slot C1 query source')
    counts = slot['counts']
    require(counts['c1_hits'] == main['arms']['C1']['hit_queries'] and
            counts['recency_hits'] - counts['c1_hits'] == counts['gained'] - counts['lost'] == slot['net_extra_hit_queries'],
            'recency paired counts')
    slot_metrics = {}
    for metric in ('ndcg', 'mrr', 'hit_rate'):
        require(close(slot['metrics']['c1'][metric], main['arms']['C1']['metrics'][metric]), 'recency C1 ' + metric)
        val = slot['metrics']['recency'][metric]
        require(type(val) in (float, int) and 0 <= val <= 1, 'recency metric')
        slot_metrics[metric] = val
    require(close(slot_metrics['hit_rate'], counts['recency_hits']/main['queries']), 'recency hit rate')
    return {'source_report': SLOT, 'comparison': 'descriptive on the same August roster',
            'queries': main['queries'], 'hit_queries': counts['recency_hits'], 'metrics': slot_metrics,
            'net_hit_queries_K1_minus_recency': main['arms']['K1']['hit_queries'] - counts['recency_hits'],
            'ndcg_difference_K1_minus_recency': main['arms']['K1']['metrics']['ndcg'] - slot_metrics['ndcg']}


def diagnostics(aggregate, n):
    histograms = {}
    reasons = {'positive_evidence', 'no_supported_seed', 'only_self_session_overlap',
               'no_eligible_positive_neighbor', 'no_positive_causal_vote'}
    for name in ('history_size', 'unknown_seeds', 'eligible_neighbors', 'current_session_excluded',
                 'selected_neighbor_count', 'boundary_ties_excluded', 'positive_candidates',
                 'zero_fill_slots', 'fallback_reason'):
        hist = aggregate['diagnostics'][name]
        require(all(type(v) is int and v >= 0 for v in hist.values()) and sum(hist.values()) == n, name)
        require(set(hist) <= reasons if name == 'fallback_reason' else
                all(re.fullmatch('0|[1-9][0-9]*', key) for key in hist), 'histogram labels')
        histograms[name] = dict(hist)
    cross = []
    for encoded, count in aggregate['fallback_cold_cross_tabs'].items():
        label = json.loads(encoded)
        require(type(label) is list and len(label) == 4 and all(type(b) is bool for b in label[:3]) and
                label[3] in GROUPS['target_model'] and type(count) is int and count >= 0, 'fallback/cold label')
        cross.append(dict(K1_fallback=label[0], C1_fallback=label[1], D1_fallback=label[2],
                          target_model=label[3], queries=count))
    require(sum(row['queries'] for row in cross) == n and sum(r['queries'] for r in cross if not r['K1_fallback'])
            == histograms['fallback_reason'].get('positive_evidence', 0), 'fallback/cold totals')
    return {'query_histograms': histograms, 'fallback_by_target_support': cross}


def summarize(out, root=ROOT):
    out, root = Path(out), Path(root)
    rows, signatures, resources = {}, {}, {}
    dense_done = (out / 'k1_dense.json').exists()
    stages = (*CORE, 'dense') if dense_done else CORE
    for stage in stages:
        rows[stage], signatures[stage] = load(out / ('k1_' + stage + '.json'))
        require(rows[stage]['status'] == 'passed', stage)
        resources[stage] = resource(out, stage, True)
    before, after = rows['sources_before'], rows['sources_after']
    for k in ('primary_sha256', 'entry_spec_sha256', 'attempt_sha256', 'prepared', 'preserved_files', 'engine_sha256'):
        require(before[k] == after[k], 'pre/post source guard ' + k)
    require(before['prepared']['reserved_test'] == 'locked', 'reserved test gate')
    attempt, attempt_hash = load(root / ATTEMPT)
    spec_path = attempt['specification']['path']
    spec, spec_hash = load(root / spec_path)
    require(attempt_hash == before['attempt_sha256'] and
            before['entry_spec_sha256'] == spec_hash == attempt['specification']['sha256'], 'original source bindings')
    primary = {Path(r['path']).name: digest(r['sha256']) for r in attempt['preservation']['execution_artifacts']}
    bound = {r['path']: digest(r['sha256']) for r in [*spec['direct_input_bindings'], *attempt['preservation']['execution_artifacts']]}
    config = spec['configuration']
    fixed = config['fixed_validation']
    require(primary == before['primary_sha256'] and len(primary) == before['preserved_files'], 'original artifacts')
    n = fixed['queries']
    qsha = primary['queries.jsonl']
    cohort, pred, sql, stats = (rows[k] for k in ('cohort', 'predictions', 'sql_witness', 'aggregate'))
    roster = digest(cohort['roster_sha256'])
    for r in (cohort, pred, stats):
        require(r['queries'] == n and r['queries_sha256'] == qsha and r['roster_sha256'] == roster, 'full query identity')
    require(cohort['paired_streams_eof'] is True and cohort['test_ranked_queries'] == 0 and
            pred['query_eof_verified'] is True, 'complete August-only query streams')
    require(all(cohort[k] == fixed[k] for k in COUNT_FIELDS), 'frozen cohort denominators')
    fit = pred['fit_audit']
    require(fit == sql['fit_audit'] == attempt['primary_fit_audit_unaccepted'] and
            all(fit[k] == v for k, v in config['train_cost_audit'].items()), 'independent training reconstructions')
    expected_names = {'baskets.csv', 'catalog.csv', 'support.csv', 'item_counts.csv',
                      'train_sessions.jsonl', 'fit_audit.json', 'sessions.jsonl', 'postings.jsonl'}
    require(len(pred['source_sha256']) == 9 and {Path(path).name for path in pred['source_sha256']} == expected_names and
            all(bound[path] == value for path, value in pred['source_sha256'].items()), 'train source bindings')
    require(sql['source_gate_sha256'] == signatures['sources_before'] and
            sql['index_counts'] == {'train_sessions': fit['train_sessions'],
                                    'session_item_memberships': fit['distinct_session_item_memberships']}, 'SQL reconstruction')
    require(sql['queries_sha256'] == qsha and sql['queries_scanned'] == n and sql['test_ranked_queries'] == 0
            and sql['ordinals_zero_based'] == ordinals(n) and sql['queries_sql_checked'] == len(ordinals(n)), 'SQL witness scope')
    require(stats['prerequisite_sha256'] == {'k1_cohort.json': signatures['cohort'],
                                             'k1_predictions.json': signatures['predictions']}, 'aggregate prerequisites')
    preserved = attempt['preservation']['execution_artifacts']
    expected_inputs = [attempt['specification']] + [r for r in preserved if Path(r['path']).name in
                       {'queries.jsonl', 'fit_audit.json', 'aggregate.json', 'bootstrap.jsonl'}]
    extra = {('dataset', 'catalog.csv'), ('P0', 'item_counts.csv'), ('C1', 'support.csv'), ('C1', 'bootstrap.jsonl')}
    expected_inputs += [r for r in spec['direct_input_bindings'] if (r['role'], Path(r['path']).name) in extra]
    descriptors = lambda records: sorted((r['path'], r['bytes'], r['sha256']) for r in records)
    require(len(expected_inputs) == 9 and descriptors(stats['inputs']) == descriptors(expected_inputs), 'aggregate inputs')
    ag = stats['aggregate']
    hits = stats['paired_hits']
    main, conditional = (fold_summary(ag[key], hits[key]) for key in ('main', 'conditional'))
    uncertainty = ag['uncertainty']
    primary_delta = main['comparisons']['K1_minus_C1']['ndcg']
    interval = uncertainty['interval']
    require(ag['roster_sha256'] == roster and main['queries'] == n and main['visitors'] == fixed['visitors']
            and conditional['queries'] == fixed['all_targets_reachable_queries'], 'aggregate population')
    require(stats['bootstrap_replicates'] == uncertainty['replicates'] == 2000 and uncertainty['visitors'] == fixed['visitors']
            and uncertainty['reason'] is None and close(uncertainty['mean_delta'], primary_delta)
            and type(interval) is list and len(interval) == 2 and -1 <= interval[0] <= interval[1] <= 1,
            'paired visitor bootstrap')
    slices = {}
    floor = fixed['support_floor_queries']
    require(ag['support_floor_queries'] == floor, 'slice support rule')
    for field, groups in GROUPS.items():
        slices[field] = {g: fold_summary(ag['slices'][field][g], hits['slices'][field][g]) for g in groups}
        require(sum(f['queries'] for f in slices[field].values()) == n, 'slice population ' + field)
        for group, fold in slices[field].items():
            size = fold['queries']
            support = 'empty' if not size else 'descriptive_only' if size < floor else 'sufficient_query_count'
            require(ag['slices'][field][group]['support'] == support, 'slice support ' + field)
            fold['support'] = support
    slot, slot_hash = load(root / SLOT)
    reference = compare_slot(slot, roster, main, bound)
    reference['source_report_sha256'] = slot_hash
    dense = {'status': 'not_run'}
    if dense_done:
        d = rows['dense']
        require(d['queries'] == n and d['queries_sha256'] == qsha and d['roster_sha256'] == roster
                and d['fit_id'] == fit['fit_id'] and d['train_sessions'] == fit['train_sessions']
                and d['train_memberships'] == fit['distinct_session_item_memberships'], 'dense full roster and fit')
        require(d['query_eof_verified'] is True and d['test_ranked_queries'] == 0 and
                d['session_query_comparisons'] == n * d['train_sessions']
                and d['membership_intersections_checked'] == n * d['train_memberships']
                and d['vote_memberships_scanned'] == n * d['train_memberships']
                and d['catalog_query_comparisons'] == n * d['catalog_size']
                and 0 < d['causal_candidate_scores_checked'] <= d['catalog_query_comparisons']
                and sum(d['voting_modes'].values()) == n, 'dense full coverage')
        modes = {k: d['voting_modes'][k] for k in ('dense_uint32', 'full_membership_scan_python_int') if k in d['voting_modes']}
        require(sum(modes.values()) == n and all(type(v) is int and v >= 0 for v in modes.values()), 'exact vote methods')
        dense = {'status': 'passed', **{k: d[k] for k in ('queries', 'train_sessions', 'train_memberships',
                 'session_query_comparisons', 'membership_intersections_checked', 'causal_candidate_scores_checked',
                 'vote_memberships_scanned', 'catalog_query_comparisons', 'catalog_size')}, 'voting_modes': modes}
    elif (out / 'dense.started').exists() or (out / 'resource_dense.json').exists():
        resources['dense'] = resource(out, 'dense', False)
        dense = {'status': 'incomplete', 'verified_full_window': False}
        progress = out / 'k1_dense.progress.json'
        if progress.exists():
            partial, partial_hash = load(progress)
            checked = partial['queries']
            require(type(checked) is int and 0 <= checked <= n, 'last dense progress')
            dense.update(last_reported_queries=checked, progress_receipt_sha256=partial_hash)
    first = datetime.fromisoformat(resources['sources_before']['started_utc'])
    last = datetime.fromisoformat(resources['sources_after']['ended_utc'])
    require(all(first <= datetime.fromisoformat(r['started_utc']) and
            datetime.fromisoformat(r['ended_utc']) <= last for r in resources.values()), 'source guard time coverage')
    return {
        'status': 'august_development_semantic_readback_passed',
        'scope': {'training_utc_ms': config['train_window_ms'], 'evaluation_utc_ms': config['validation_window_ms'],
                  'prior_execution': 'original partial preserved', 'new_primary_fits': 0, 'new_primary_bootstrap_sets': 0,
                  'reserved_test': 'locked', 'reserved_test_ranked_queries': 0},
        'source_evidence': {'attempt': ATTEMPT, 'attempt_sha256': attempt_hash, 'specification': spec_path,
                            'specification_sha256': spec_hash, 'preserved_files': len(primary), 'primary_sha256': primary,
                            'verified_before_and_after': True},
        'cohort': {**{k: cohort[k] for k in COUNT_FIELDS}, 'roster_sha256': roster, 'queries_sha256': qsha},
        'training': {**{k: fit[k] for k in config['train_cost_audit']}, 'fit_id': digest(fit['fit_id'])},
        'verification': {'exact_nested_k1_predictions': n, 'original_control_arms': list(ARMS[:-1]),
                         'sql_witness': {'full_train_reconstruction': True, 'fixed_sql_queries': sql['queries_sql_checked'],
                                         'verified_predictions_sha256': digest(sql['verified_predictions_sha256']),
                                         'database_sha256': digest(sql['database_sha256'])},
                         'dense_cross_check': dense, 'receipt_sha256': signatures},
        'results': {'main': main, 'all_targets_reachable': conditional, 'slices': slices,
                    'slice_support_floor_queries': ag['support_floor_queries'],
                    'K1_diagnostics': diagnostics(ag, n),
                    'primary_ndcg_K1_minus_C1': {'mean': primary_delta, 'paired_visitor_percentile_95_interval': interval,
                                                'visitors': uncertainty['visitors'], 'replicates': uncertainty['replicates']},
                    'recency_slot_reference': reference},
        'execution': {'verified_stages_wall_seconds': (last-first).total_seconds(), 'resources_by_stage': resources},
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out', required=True, type=Path, help='private verified run directory')
    parser.add_argument('--report', required=True, type=Path, help='new aggregate JSON file')
    args = parser.parse_args()
    if args.report.exists():
        raise FileExistsError(args.report)
    write_result(args.report, summarize(args.out))


if __name__ == '__main__':
    main()
