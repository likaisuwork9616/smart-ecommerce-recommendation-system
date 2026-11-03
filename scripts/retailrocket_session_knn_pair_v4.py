"""V4 exact selected-row verifier and checkpoint cost separation.

V1/V2/V3 remain frozen. Only internal exact-ranking/metric memoization changes;
scientific expected rows, Decimal strings and delta bits keep their V3 schema.
"""
from bisect import bisect_left
from datetime import datetime,timezone
import hashlib
import json
import math
from pathlib import Path
import sqlite3
from time import perf_counter

from scripts import retailrocket_session_knn_checkpoint_v2 as cp
from scripts import retailrocket_session_knn_readback_v2 as core
from scripts import retailrocket_session_knn_sql_v2 as old_sql
from scripts import retailrocket_session_knn_sql_v4 as sql
from scripts.retailrocket_session_knn_checks_v4 import exact,terms
from scripts.retailrocket_session_knn_pair_probe_v3 import _key_csv,_key_json
from scripts.retailrocket_session_knn_readback import (rows,ids,read_rows,num,close,GROUPS,METRICS,FIELDS,dump,
    exact as old_exact,terms as old_terms)


class TimedStore(cp.CheckpointStore):
    def __init__(self,*args,**kwargs):
        super().__init__(*args,**kwargs)
        self.commit_seconds=0.0
        self.commit_events=[]

    def flush_chunk(self):
        started=perf_counter();pending=self._pending_count;success=False;manifest=None
        try:
            manifest=super().flush_chunk();success=True
            return manifest
        finally:
            seconds=perf_counter()-started
            if pending:
                self.commit_seconds+=seconds
                self.commit_events.append({'seconds':seconds,'completed':success,
                    'records':pending,'payload_bytes':manifest['payload']['bytes'] if manifest else None})


def verify_selected(primary, paths, config, store, model, database, ordinals, watch=lambda:None, fault=lambda point:None, *, baseline=False):
    """Identical scientific payloads; resume only contiguous verified records."""
    setup_started = perf_counter()
    if len(ordinals)>64:
        raise ValueError('V4 engineering verifier is limited to 64 frozen selected queries')
    source, p0, c1, d1 = (paths[key] for key in ('dataset', 'P0', 'C1', 'D1'))
    audit, support = model['fit_audit'], model['support']
    counts, catalog = core.load_context(paths, config, support, watch)
    prepared = sql.prepare_catalog(catalog, counts, watch)
    first_times = sorted(catalog.values())
    if any(Path(str(database) + suffix).exists() for suffix in ('-wal', '-shm', '-journal')):
        raise ValueError('Copied model has an unexpected SQLite journal')
    db = sqlite3.connect(Path(database).resolve().as_uri() + '?mode=ro&immutable=1', uri=True)
    db.execute('PRAGMA temp_store=MEMORY')
    db.set_progress_handler(lambda: (watch() or 0), 10000)
    observations = []
    predictor = old_sql.predict if baseline else sql.predict
    exact_check = old_exact if baseline else exact
    metric_terms = old_terms if baseline else terms
    try:
        controls = [iter(read_rows(p0 / name, FIELDS[name]))
                    for name in ('ranked_queries.csv', 'query_metrics.csv', 'query_slices.csv')]
        controls += [iter(rows(c1 / 'queries.jsonl', watch)), iter(rows(d1 / 'queries.jsonl', watch))]
        outputs = iter(rows(primary / 'queries.jsonl', watch))
        previous = None
        committed = store.recover()['records']
        saved = iter(store.iter_records())
        prefix_started = perf_counter()
        prefix_seconds = 0.0
        ordinal = -1
        lo, hi = config['validation_window_ms']
        setup_seconds = perf_counter() - setup_started
        for raw in read_rows(source / 'queries.csv', config['schemas']['queries.csv']):
            query_started = perf_counter()
            watch()
            if raw['role'] != 'validation':
                continue
            ordinal += 1
            v = raw['visitorid']; num(v)
            s, t, nt, index = (num(raw[field]) for field in
                               ('session_start_ms', 'query_ms', 'next_view_ms', 'basket_index'))
            key = (v, s, t)
            if ordinal >= len(ordinals):
                raise ValueError('Extra subset query outside frozen ordinals')
            exact_check(ordinals[ordinal]['key'], list(key))
            if ordinal < committed:
                record = next(saved)
                exact_check(record['key'], list(key))
                prefix = [next(stream, None) for stream in controls]
                actual = next(outputs, None)
                if any(row is None for row in prefix) or actual is None:
                    raise ValueError('Missing immutable prefix source row')
                for row in prefix[:3]:
                    if _key_csv(row) != key or row['role'] != 'validation':
                        raise ValueError('Prefix control CSV identity differs')
                for row in [*prefix[3:], actual]:
                    if _key_json(row) != key:
                        raise ValueError('Prefix control JSON identity differs')
                exact_check(actual, record['payload']['expected'])
                previous = key
                prefix_seconds = perf_counter() - prefix_started
                continue

            if previous is not None and key <= previous:
                raise ValueError('Oracle duplicate/unordered query')
            previous = key
            if not lo <= t < nt < hi or s > t or nt - t > 1800000 or t + 1800000 > hi:
                raise ValueError('Oracle validation clock/horizon')
            for field, value in [('status', 'labelled'), ('next_role', 'validation'),
                                 ('next_in_session', '1'), ('mature', '1'), ('cross_role', '0')]:
                if raw[field] != value:
                    raise ValueError('Oracle query label state')
            current = db.execute('SELECT k,n FROM h WHERE v=? AND s=? AND t=?', key).fetchone()
            if current is None or current[0] != index:
                raise ValueError('Oracle missing current basket')
            history = set()
            for (text,) in db.execute('SELECT items FROM h WHERE v=? AND s=? AND t<=? ORDER BY t', key):
                watch(); history.update(json.loads(text))
            history = sorted(history, key=int); targets = ids(raw['target_items'])
            successor = db.execute(
                'SELECT t,k,role,items FROM h WHERE v=? AND s=? AND t>? ORDER BY t LIMIT 1', key).fetchone()
            if successor is None or successor[:3] != (nt, index + 1, 'validation'):
                raise ValueError('Oracle next-basket identity')
            exact_check(sorted(targets, key=int), sorted(json.loads(successor[3]), key=int))
            reachable = sum(item in catalog and catalog[item] < t for item in targets)
            candidate = bisect_left(first_times, t)
            if (len(targets) != num(raw['target_count']) or reachable != num(raw['reachable_target_count'])
                    or candidate != num(raw['candidate_count'])
                    or raw['all_targets_reachable'] != str(int(reachable == len(targets)))):
                raise ValueError('Oracle full query denominators')
            values = [next(stream, None) for stream in controls]; actual = next(outputs, None)
            if any(value is None for value in values) or actual is None:
                raise ValueError('Oracle missing paired row')
            rank, metric, slices, one, three = values
            for row in (rank, metric, slices):
                if _key_csv(row) != key or row['role'] != 'validation':
                    raise ValueError('Oracle original P0 key/role')
            if rank['fit_id'] != config['control_fit_ids']['P0']:
                raise ValueError('Oracle P0 fit')
            p0ids = json.loads(rank['top10_items'])
            exact_check(json.loads(rank['top10_scores']), [counts.get(item, 0) for item in p0ids])
            p0pred = {'ids': p0ids, 'candidate_count': num(rank['candidate_count'])}
            p0terms = {metric_name: float(metric[metric_name]) for metric_name in ('dcg', 'idcg', *METRICS)}
            p0terms.update(target_count=num(metric['target_count']), hits=num(metric['hits']),
                           first_hit_rank=num(metric['first_hit_rank']) if metric['first_hit_rank'] else None)
            if num(metric['reachable_target_count']) != reachable or metric['all_targets_reachable'] != raw['all_targets_reachable']:
                raise ValueError('Oracle P0 target denominator')
            train = num(raw['train_view_events']); known = sum(item in support for item in targets)
            activity = '0' if not train else '1' if train == 1 else '2-5' if train <= 5 else '6+'
            if raw['visitor_seen_before_fit'] not in ('0', '1') or raw['train_activity_slice'] != activity:
                raise ValueError('Oracle visitor/activity state')
            names = {'visitor_history': 'seen' if raw['visitor_seen_before_fit'] == '1' else 'new',
                     'current_basket': 'multiple' if current[1] > 1 else 'single',
                     'target_basket': 'multiple' if len(targets) > 1 else 'single',
                     'train_activity': activity,
                     'target_model': 'all_positive' if known == len(targets) else 'all_zero' if not known else 'mixed'}
            identity = {'key': list(key), 'history': history,
                        'history_sha256': hashlib.sha256(dump(history).encode()).hexdigest(),
                        'targets': targets, 'candidate_count': candidate,
                        'reachable_targets': reachable, 'slices': names}
            for reference in (one, three):
                for field, value in identity.items():
                    exact_check(reference[field], value)
                exact_check(reference['predictions']['P0'], p0pred); exact_check(reference['terms']['P0'], p0terms)
            exact_check({field: slices[field] for field in GROUPS}, names)
            exact_check(one['predictions']['C1'], three['predictions']['C1'])
            exact_check(one['terms']['C1'], three['terms']['C1'])
            for arm in ('C1', 'D1'):
                if three['predictions'][arm]['fit_id'] != config['control_fit_ids'][arm]:
                    raise ValueError('Oracle control fit')
            workload = {}
            def query_watch():
                watch(); fault('query_work')
            rank_stages={}
            rank_started=perf_counter()
            predictions = dict(three['predictions'], K1=predictor(
                db, support, audit['fit_id'], prepared.counts, prepared, t, history, (v, s),
                query_watch, workload=workload, **({} if baseline else {'timings':rank_stages})))
            rank_seconds=perf_counter()-rank_started
            binary = {}; precise = {}
            for arm in ('P0', 'C1', 'D1', 'K1'):
                prediction = predictions[arm]
                if (prediction['candidate_count'] != candidate or len(prediction['ids']) != min(10, candidate)
                        or any(item not in catalog or catalog[item] >= t for item in prediction['ids'])):
                    raise ValueError('Oracle complete causal control/K1 list')
                independently, precise[arm] = metric_terms(prediction['ids'], targets)
                if any(type(actual['terms'][arm][metric_name]) is not float
                       or not math.isfinite(actual['terms'][arm][metric_name])
                       for metric_name in ('dcg', 'idcg', *METRICS)):
                    raise ValueError('Oracle expected finite binary64 metric fields')
                close(actual['terms'][arm], independently)
                binary[arm] = actual['terms'][arm] if arm == 'K1' else three['terms'][arm]
                if arm != 'K1':
                    exact_check(actual['terms'][arm], binary[arm])
            delta = {'K1_minus_' + arm: {name: binary['K1'][name] - binary[arm][name] for name in METRICS}
                     for arm in ('C1', 'P0', 'D1')}
            expected = dict(identity, predictions=predictions, terms=binary, delta=delta)
            exact_check(actual, expected)
            if predictions['K1']['fallback_reason'] is not None:
                exact_check(predictions['K1']['ids'], predictions['P0']['ids'])
            payload = {'expected': expected,
                       'precise': {arm: {name: str(value) for name, value in metrics.items()}
                                   for arm, metrics in precise.items()},
                       'delta_hex': {arm: {name: value.hex() for name, value in metrics.items()}
                                     for arm, metrics in delta.items()}}
            verified_seconds = perf_counter() - query_started
            append_started = perf_counter()
            commits_before = store.commit_seconds
            fault('before_append')
            store.append_verified(ordinal, list(key), payload)
            fault('query_verified')
            append_seconds = perf_counter() - append_started
            observations.append({'subset_ordinal': ordinal,
                'original_ordinal': ordinals[ordinal]['original_ordinal'],
                'key_sha256': hashlib.sha256(dump(list(key)).encode()).hexdigest(),
                'verification_seconds': verified_seconds, 'checkpoint_append_seconds': append_seconds,
                'seconds': perf_counter() - query_started, 'append_without_commit_seconds': max(0.0, append_seconds-(store.commit_seconds-commits_before)),
                'chunk_commit_seconds': store.commit_seconds-commits_before, 'sql_workload': workload,
                'rank_seconds':rank_seconds,'rank_stages_seconds':rank_stages})
        tail_started = perf_counter()
        if any(next(stream, None) is not None for stream in [*controls, outputs]):
            raise ValueError('Oracle extra paired row')
        if ordinal + 1 != config['fixed_validation']['queries'] or ordinal + 1 != len(ordinals):
            raise ValueError('Incomplete frozen subset query coverage')
        store.flush_chunk()
        core.seal_consistent(store, 'queries', {'queries': ordinal + 1, 'paired_streams_eof_checked': True})
        fault('after_queries_sealed')
        return {'setup_seconds': setup_seconds, 'queries': observations, 'committed_prefix_rows': committed,
                'prefix_replay_seconds': prefix_seconds, 'chunk_commits': list(store.commit_events),
                'tail_flush_and_eof_seal_seconds': perf_counter() - tail_started,
                'verified_subset_queries': ordinal + 1}
    finally:
        for stream in [*locals().get('controls', []), locals().get('outputs')]:
            if stream is not None and hasattr(stream, 'close'):
                stream.close()
        db.close()


def run_synthetic_acceptance(primary,paths,config,store,model,database,ordinals,watch=lambda:None,fault=lambda point:None):
    """Full global/bootstrap only for artificial test fixtures, never a real CLI."""
    if config.get('synthetic_acceptance_only') is not True:
        raise ValueError('Only explicitly artificial fixtures may run global synthetic acceptance')
    if (store.folder/'candidate.json').exists():store.supersede_candidate()
    verify_selected(primary,paths,config,store,model,database,ordinals,watch,fault)
    result=core.replay_global(primary,paths,config,store,model,watch,fault)
    fault('before_candidate')
    store.write_candidate(result)
    return result
