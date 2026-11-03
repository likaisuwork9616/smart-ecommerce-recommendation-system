"""Physical synthetic ledger, replay and bootstrap costs for a bounded diagnostic.

The only inputs are shape/configuration and a deadline callback. All generated
IDs, predictions, targets, and draws are artificial. Phase receipts cannot be
used as research acceptance or as a measurement of real paired-row recovery.
"""
from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone
from decimal import Decimal
import hashlib
import json
import math
from pathlib import Path
from time import perf_counter

import numpy as np

from scripts.retailrocket_directed_oracle import check_bootstrap
from scripts.retailrocket_session_knn_checkpoint_v2 import CheckpointStore, atomic_json
from scripts.retailrocket_session_knn_readback import FourFold, GROUPS, METRICS, dump, exact, scalar_count, terms


ARMS = ('P0', 'C1', 'D1', 'K1')
DIAGNOSTICS = ('history_size', 'unknown_seeds', 'eligible_neighbors', 'current_session_excluded',
               'selected_neighbor_count', 'boundary_ties_excluded', 'positive_candidates',
               'zero_fill_slots', 'fallback_reason')
REAL_SHAPE = (166897, 62235, 222754)


class _WatchedStore(CheckpointStore):
    """Keep actual checkpoint decoding and chain verification; check each row."""
    def __init__(self, *args, watch, **kwargs):
        super().__init__(*args, **kwargs)
        self.watch = watch

    def iter_records(self):
        for record in super().iter_records():
            self.watch()
            yield record


def _shape(config):
    fixed = config['fixed_validation']
    q, v, c = (fixed[k] for k in ('queries', 'visitors', 'candidate_union_items'))
    if any(type(n) is not int for n in (q, v, c)) or not 1 <= v <= q or c < 1:
        raise ValueError('Invalid synthetic query/visitor/catalog shape')
    multi = fixed.get('multi_item_target_queries', 0)
    occurrences = fixed.get('target_occurrences', q+multi)
    complete = fixed.get('all_targets_reachable_queries', q)
    reachable = fixed.get('reachable_target_occurrences', occurrences-(q-complete))
    new = fixed.get('new_visitor_queries', q//2)
    current_multi = fixed.get('multi_item_current_queries', 0)
    models = fixed.get('target_model_query_counts', {'all_positive': q, 'mixed': 0, 'all_zero': 0})
    if (set(models) != set(GROUPS['target_model']) or sum(models.values()) != q
            or any(type(n) is not int or n < 0 for n in (*models.values(), multi, occurrences, complete,
                                                          reachable, new, current_multi))
            or max(multi, complete, new, current_multi) > q or models['mixed'] > multi
            or occurrences < q+multi or (not multi and occurrences != q)):
        raise ValueError('Invalid synthetic target or slice counts')
    extras = occurrences-q
    quotient, remainder = divmod(extras, multi) if multi else (0, 0)
    incomplete = q-complete
    missing_extras = occurrences-reachable-incomplete
    if not 0 <= missing_extras <= min(multi, incomplete)*quotient+min(remainder, incomplete):
        raise ValueError('Synthetic reachable-target margins cannot be represented')
    if quotient+int(bool(remainder))+1 > c:
        raise ValueError('Synthetic catalog too small for distinct target baskets')
    return dict(queries=q, visitors=v, catalog=c, multi=multi, target_extra=quotient,
                target_remainder=remainder, complete=complete, reachable=reachable,
                incomplete=incomplete, missing_extras=missing_extras, new=new,
                current_multi=current_multi, occurrences=occurrences, models=models)


def _row(index, shape, neighbor_count=None):
    q, v, catalog = (shape[k] for k in ('queries', 'visitors', 'catalog'))
    # Equal-width canonical numeric visitor strings are also in SQLite text order.
    visitor = str(10**len(str(v))+index*v//q)
    key = [visitor, 0, index+1]
    extra = (shape['target_extra']+int(index < shape['target_remainder'])) if index < shape['multi'] else 0
    prior_extra = min(index, shape['multi'])*shape['target_extra']+min(index, shape['target_remainder'])
    missing = (1+min(extra, max(0, shape['missing_extras']-prior_extra))
               if index < shape['incomplete'] else 0)
    reachable = 1+extra-missing
    base = (index*13) % catalog
    targets = [str((base+j) % catalog) for j in range(reachable)]
    targets.extend(str(catalog+j) for j in range(missing))
    history = [str(base)]
    if index < shape['current_multi'] and catalog > 1:
        history.append(str((base+1) % catalog))
    models = shape['models']
    model_group = ('mixed' if index < models['mixed'] else 'all_positive'
                   if index < models['mixed']+models['all_positive'] else 'all_zero')
    slices = {'visitor_history': 'new' if index < shape['new'] else 'seen',
              'current_basket': 'multiple' if index < shape['current_multi'] else 'single',
              'target_basket': 'multiple' if extra else 'single',
              'train_activity': GROUPS['train_activity'][index % len(GROUPS['train_activity'])],
              'target_model': model_group}
    neighbors = (0, 1, 3, 8)[index % 4] if neighbor_count is None else neighbor_count
    predictions, binary, precise = {}, {}, {}
    for arm_index, arm in enumerate(ARMS):
        offset = 0 if arm == 'P0' or arm == 'K1' and not neighbors else arm_index
        items = [str((base+j+offset) % catalog) for j in range(min(10, catalog))]
        prediction = {'ids': items, 'candidate_count': catalog}
        if arm != 'P0':
            positive = len(items) if arm != 'K1' or neighbors else 0
            prediction.update(fit_id='synthetic-'+arm, scores=[[1, j+1] if positive else [0, 1]
                              for j in range(len(items))], p0_counts=[1]*len(items), supported_seeds=len(history),
                              positive_candidates=positive, zero_fill_slots=len(items)-positive,
                              fallback_reason=None if positive else 'no_eligible_positive_neighbor')
        if arm == 'D1':
            prediction['outgoing_seeds'] = len(history)
        if arm == 'K1':
            selected = [{'key': [str(1000000+j), 0], 'intersection': 1, 'union': 2,
                         'similarity': [1, 2]} for j in range(neighbors)]
            pool_hash = hashlib.sha256()
            for row in selected:
                pool_hash.update((dump([row['key'], 1, 2])+'\n').encode())
            prediction.update(history_size=len(history), unknown_seeds=0, raw_posting_visits=neighbors,
                              current_session_excluded=0, eligible_neighbors=neighbors,
                              neighbor_pool_sha256=pool_hash.hexdigest(), selected_neighbors=selected,
                              selected_neighbor_count=neighbors, boundary_similarity=[1, 2] if neighbors == 500 else None,
                              boundary_ties_total=neighbors if neighbors == 500 else 0, boundary_ties_excluded=0,
                              vote_memberships=neighbors*2)
        predictions[arm] = prediction
        binary[arm], decimal_terms = terms(items, targets)
        precise[arm] = {metric: str(value) for metric, value in decimal_terms.items()}
    delta = {'K1_minus_'+arm: {metric: binary['K1'][metric]-binary[arm][metric] for metric in METRICS}
             for arm in ('C1', 'P0', 'D1')}
    expected = {'key': key, 'history': history, 'history_sha256': hashlib.sha256(dump(history).encode()).hexdigest(),
                'targets': targets, 'candidate_count': catalog, 'reachable_targets': reachable, 'slices': slices,
                'predictions': predictions, 'terms': binary, 'delta': delta}
    return key, {'expected': expected, 'precise': precise,
                 'delta_hex': {arm: {m: value.hex() for m, value in metrics.items()} for arm, metrics in delta.items()}}


def _global(store, shape, watch):
    catalog = {str(i): 0 for i in range(shape['catalog'])}
    main, conditional = FourFold(catalog), FourFold(catalog)
    groups = {name: {bucket: FourFold(catalog) for bucket in buckets} for name, buckets in GROUPS.items()}
    diagnostics = {k: Counter() for k in DIAGNOSTICS}
    cross, roster, deltas = Counter(), hashlib.sha256(), []
    scalars = candidates = 0
    for record in store.iter_records():
        payload = record['payload']
        row = payload['expected']
        exact(record['key'], row['key'])
        predictions = row['predictions']
        precise = {a: {m: Decimal(value) for m, value in metrics.items()} for a, metrics in payload['precise'].items()}
        delta = {a: {m: float.fromhex(value) for m, value in metrics.items()} for a, metrics in payload['delta_hex'].items()}
        exact(delta, row['delta'])
        visitor, _, timestamp = row['key']
        query = {'v': visitor, 't': timestamp, 'targets': row['targets']}
        reachable = row['reachable_targets']
        main.add(query, predictions, precise, delta, reachable)
        if reachable == len(query['targets']):
            conditional.add(query, predictions, precise, delta, reachable)
        for name, bucket in row['slices'].items():
            groups[name][bucket].add(query, predictions, precise, delta, reachable)
        for name in diagnostics:
            value = predictions['K1'][name]
            diagnostics[name][str(value)] += 1
        cross[dump([predictions['K1']['fallback_reason'] is not None, predictions['C1']['positive_candidates'] == 0,
                    predictions['D1']['positive_candidates'] == 0, row['slices']['target_model']])] += 1
        roster.update((dump(row['key'])+'\n').encode())
        deltas.append((visitor, delta['K1_minus_C1']['ndcg']))
        scalars += scalar_count(row)
        candidates += row['candidate_count']
    watch()
    observed = main.result()['arms']['K1']
    conditional_summary = conditional.result()
    slices = {}
    for name, buckets in groups.items():
        slices[name] = {}
        for name_value, fold in buckets.items():
            watch()
            slices[name][name_value] = fold.result()['queries']
    for field, expected in [('queries', shape['queries']), ('visitors', shape['visitors']),
                            ('candidate_union_items', shape['catalog']), ('target_occurrences', shape['occurrences']),
                            ('reachable_target_occurrences', shape['reachable'])]:
        exact(observed[field], expected)
    exact(conditional_summary['queries'], shape['complete'])
    exact(slices['target_model'], shape['models'])
    exact(slices['visitor_history']['new'], shape['new'])
    exact(slices['current_basket']['multiple'], shape['current_multi'])
    exact(slices['target_basket']['multiple'], shape['multi'])
    return {'queries': observed['queries'], 'visitors': observed['visitors'], 'catalog': observed['candidate_union_items'],
            'target_occurrences': observed['target_occurrences'], 'reachable_target_occurrences': observed['reachable_target_occurrences'],
            'conditional_queries': conditional_summary['queries'], 'slices': slices, 'nested_scalars': scalars,
            'candidate_count_sum': candidates, 'diagnostics_counted': len(diagnostics), 'cross_cells': len(cross),
            'roster_sha256': roster.hexdigest()}, deltas


def _bootstrap_fixtures(folder, deltas, watch):
    grouped = defaultdict(list)
    for visitor, value in deltas:
        grouped[visitor].append(value)
    visitors = sorted(grouped, key=int)
    sizes = np.asarray([len(grouped[v]) for v in visitors], dtype=np.int64)
    sums = [math.fsum(grouped[v]) for v in visitors]
    generator = np.random.Generator(np.random.PCG64(42))
    with (folder/'synthetic_reference.jsonl').open('x', encoding='utf-8') as reference, \
            (folder/'synthetic_output.jsonl').open('x', encoding='utf-8') as output:
        for replicate in range(2000):
            watch()
            before = generator.bit_generator.state
            drawn = generator.integers(0, len(visitors), size=len(visitors), dtype=np.int64)
            weight = np.bincount(drawn, minlength=len(visitors))
            denominator = int(np.dot(weight, sizes))
            delta = math.fsum(int(w)*s for w, s in zip(weight, sums))/denominator
            identity = {'replicate': replicate, 'rng_before': before, 'rng_after': generator.bit_generator.state,
                        'draw_sha256': hashlib.sha256(drawn.astype('<i8', copy=False).tobytes()).hexdigest(),
                        'query_denominator': denominator}
            reference.write(dump(identity)+'\n')
            output.write(dump(dict(identity, delta=delta))+'\n')
    return {'replicates': 2000, 'visitors_per_draw': len(visitors), 'indices': 2000*len(visitors)}


def run_proxy(folder, config, watch):
    """Create a fresh synthetic_proxy namespace under folder, measuring each phase.

    fixed_validation selects shape. Optional deadline_utc and budget_seconds can
    shorten the 30-minute ceiling. The outer supervisor owns hard termination.
    """
    shape = _shape(config)
    budget = config.get('budget_seconds', 1800)
    if isinstance(budget, bool) or not isinstance(budget, (int, float)) or not 0 < budget <= 1800:
        raise ValueError('Synthetic proxy budget must be within 1800 seconds')
    now = datetime.now(timezone.utc)
    deadline = now+timedelta(seconds=budget)
    if 'deadline_utc' in config:
        requested = datetime.fromisoformat(config['deadline_utc'])
        if requested.tzinfo is None:
            raise ValueError('Synthetic proxy deadline requires timezone')
        deadline = min(deadline, requested)
    directory = Path(folder)/'synthetic_proxy'
    directory.mkdir(exist_ok=False)
    phases = {}

    def guard():
        watch()
        if datetime.now(timezone.utc) >= deadline:
            raise TimeoutError('Synthetic proxy absolute deadline')

    def phase(name, fn, summarize):
        atomic_json(directory/(name+'_started.json'), {'phase': name, 'kind': 'synthetic_engineering_cost',
                                                       'started_utc': datetime.now(timezone.utc).isoformat()})
        started = perf_counter()
        completed, error, evidence = False, None, None
        try:
            guard()
            value = fn()
            evidence = summarize(value)
            guard()
            completed = True
            return value
        except BaseException as exc:
            error = type(exc).__name__
            raise
        finally:
            phases[name] = {'phase': name, 'seconds': perf_counter()-started, 'completed': completed,
                            'error_type': error, 'evidence': evidence if completed else None}
            atomic_json(directory/(name+'_receipt.json'), phases[name])

    binding = {'kind': 'synthetic_engineering_only', 'shape': shape, 'sources': []}

    def build():
        store = _WatchedStore.create(directory/'ledger', binding, deadline.isoformat(), budget,
                                     expected_queries=shape['queries'], required_stages=('synthetic_reconstruction',), watch=guard)
        with store.writer():
            store.seal_stage('synthetic_reconstruction', {'kind': 'generated_shape_fixture', 'real_model': False})
            for ordinal in range(shape['queries']):
                guard()
                key, payload = _row(ordinal, shape)
                store.append_verified(ordinal, key, payload)
            store.flush_chunk()
        return store

    def ledger_inventory(store):
        chunks = sorted((store.folder/'chunks').glob('*.json'))
        last = json.loads(chunks[-1].read_bytes())
        if last['last_ordinal']+1 != shape['queries']:
            raise ValueError('Synthetic ledger construction did not commit the full roster')
        return {'records': last['last_ordinal']+1, 'chunks': len(chunks),
                'payload_bytes': sum(path.stat().st_size for path in (store.folder/'payloads').iterdir())}

    store = phase('build_ledger', build, ledger_inventory)
    global_counts, deltas = phase('global_replay', lambda: _global(store, shape, guard), lambda output: output[0])
    draw_shape = phase('bootstrap_fixture_setup', lambda: _bootstrap_fixtures(directory, deltas, guard), dict)
    boot = phase('bootstrap_replay', lambda: check_bootstrap(directory/'synthetic_output.jsonl',
                 directory/'synthetic_reference.jsonl', deltas, guard),
                 lambda result: {'replicates': result['replicates'], 'visitors': result['visitors']})
    exact(boot['replicates'], 2000)
    exact(boot['visitors'], shape['visitors'])

    def recover():
        reopened = _WatchedStore.open(directory/'ledger', binding, watch=guard)
        summary = reopened.recover()
        exact(summary['records'], shape['queries'])
        return {'chunks': summary['chunks'], 'records': summary['records']}

    recovery = phase('recover_ledger_chain', recover, dict)
    # Keep the max-neighbor byte/serialization stress independent of the
    # deterministic compact-neighbor distribution used by full-shape folds.
    def stress():
        counts = (0, 1, 499, 500)
        sizes = {}
        for neighbors in counts:
            guard()
            _, payload = _row(0, shape, neighbors)
            path = directory/f'synthetic_neighbor_payload_{neighbors}.json'
            atomic_json(path, payload)
            exact(len(json.loads(path.read_bytes())['expected']['predictions']['K1']['selected_neighbors']), neighbors)
            sizes[str(neighbors)] = path.stat().st_size
        return sizes

    stress_bytes = phase('neighbor_payload_io_stress', stress, dict)
    files = list((directory/'ledger').rglob('*'))
    result = {'kind': 'synthetic_engineering_only', 'real_acceptance': False, 'reserved_test': 'locked',
              'full_readback_started': False, 'T_plan': None, 'phases': phases, 'observed_global': global_counts,
              'same_query_visitor_catalog_shape': (shape['queries'], shape['visitors'], shape['catalog']) == REAL_SHAPE,
              'neighbor_count_cycle': [0, 1, 3, 8], 'neighbor_stress_payload_bytes': stress_bytes,
              'full_production_payload_shape_coverage': False, 'real_source_and_prefix_resume_measured': False,
              'missing': ['real_paired_row_checks', 'real_payload_size_and_joint_query_tail',
                          'real_source_rehash_and_control_stream_prefix', 'uncommitted_real_query_tail_rework'],
              'bootstrap': draw_shape, 'recovered': recovery,
              'ledger_bytes': sum(file.stat().st_size for file in files if file.is_file()),
              'ledger_payload_bytes': sum(file.stat().st_size for file in (directory/'ledger'/'payloads').iterdir()),
              'fixture_inputs': 'artificial IDs, values and joint distributions; only declared margins reproduced'}
    guard()
    atomic_json(directory/'engineering_summary.json', result)
    return result
