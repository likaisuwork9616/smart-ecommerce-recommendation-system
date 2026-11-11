"""Two independent S1 pools, passive late timings, and a single strict publisher."""
import hashlib
from math import fsum, isfinite
from pathlib import Path
from statistics import median
from time import perf_counter_ns as _CLOCK
from types import SimpleNamespace

from scripts import freeze_retailrocket_session_knn_compare_v41 as frozen
from scripts import retailrocket_session_knn_snapshot_adapter_v30 as original
from scripts import retailrocket_session_knn_typed_publication_v39 as typed
from scripts import run_retailrocket_session_knn_compare_v40 as prior
from scripts.retailrocket_session_knn_diagnostics_v20 import _clone


entry = prior.entry
old = entry.old
read, write, ROOT = prior.read, prior.write, prior.ROOT
AUDITED = 'v41_independent_two_pool_typed_comparison_audit_complete'
ARMS = {'S': original, 'T': typed.adapter}
ROOTS = ('config', 'model')


class OriginalContext(original.WorkerContext):
    """Keep original late bytes and assignments, timing only calls five and six."""
    def __init__(self, *args):
        super().__init__(*args)
        self.late_checks = None

    def load(self, paths, config, support, watch, *, model, store, namespace, request, observer):
        arguments = dict(model=model, store=store, namespace=namespace, request=request, observer=observer)
        if self.calls:
            return super().load(paths, config, support, watch, **arguments)
        calls = 0
        late = []

        def canonical(value):
            nonlocal calls
            calls += 1
            if calls <= 4:
                return original.c1.canonical(value)
            index = calls - 5
            if index not in (0, 1) or value is not (config, model)[index]:
                raise ValueError('Original late canonical call order changed')
            start = _CLOCK()
            result = original.c1.canonical(value)
            end = _CLOCK()
            late.append(dict(root=ROOTS[index], start_ns=start, end_ns=end))
            return result

        try:
            parent_load = _clone(original.c1.WorkerContext.load, canonical=canonical)
            parent = SimpleNamespace(load=lambda *args, **kwargs: parent_load(self, *args, **kwargs))
            s1_load = _clone(original.WorkerContext.load, super=lambda: parent)
            result = s1_load(self, paths, config, support, watch, **arguments)
            if calls != 6 or len(late) != 2:
                raise ValueError('Expected four early and two original late canonical calls')
            self.late_checks = late
            return result
        except BaseException:
            self.invalidate()
            raise


def _run_arm(folder, request, label, mode, data, **kwargs):
    return ARMS[mode].run_fixed48(folder, request, label, 'C', data, **kwargs)


observed_run = _clone(entry.observed_run, run_fixed48=_run_arm)


def run_worker(folder, request):
    watch = entry.ThrottledWatch(folder, request['deadline_utc'])
    pools = {}
    try:
        old.hash_phase(folder, request, 'worker_initial_hash', watch)
        inputs = {arm: old.inputs(request) for arm in ARMS}
        reference, candidate = inputs.values()
        if (reference[1] is candidate[1] or reference[3] is candidate[3]
                or reference[3]['support'] is candidate[3]['support'] or reference[2] != candidate[2]):
            raise ValueError('Both arms require separate live roots and the same verified binding')
        contract = typed.adapter.context_contract(request, reference[2])
        pools['S'] = OriginalContext(contract, ROOT, ROOT)
        pools['T'] = typed.adapter.WorkerContext(contract, ROOT, ROOT)
        for item in request['metadata']['schedule']:
            arm = item['mode']
            watch.force()
            write(folder / (item['label'] + '_started.json'), item)
            entry.clear_caches()
            observed_run(folder, request, item, inputs[arm], pools[arm], watch)
            entry._check_db(inputs[arm][4])
            watch.force()
        write(folder / 'cache_receipt.json', {arm: pool.completed_summary() for arm, pool in pools.items()})
        write(folder / 'original_late_timing.json', pools['S'].late_checks)
        for pool in pools.values():
            pool.close()
        old.hash_phase(folder, request, 'worker_final_hash', watch)
        write(folder / 'worker_done.json', old.DONE)
    except BaseException as error:
        write(folder / 'worker_failure.json', dict(error_type=type(error).__name__))
        raise
    finally:
        for pool in pools.values():
            pool.close()


def _phase(events, name):
    matches = [event for event in events if event['phase'] == name]
    if len(matches) != 1:
        raise ValueError('One observed event required: ' + name)
    return matches[0]


def original_late_timing(folder, events):
    checks = read(folder / 'original_late_timing.json')
    if type(checks) is not list or len(checks) != 2:
        raise ValueError('Two original late canonical timings required')
    lower = _phase(events, 'cache.original_prepare_catalog')['end_ns']
    upper = next(event['start_ns'] for event in events if event['phase'] == 'snapshot.fingerprint')
    if not upper <= _phase(events, 'cache.cold_build')['end_ns'] <= _phase(events, 'cache.use')['start_ns']:
        raise ValueError('Original late checks must precede the first snapshot and borrow')
    for root, check in zip(ROOTS, checks):
        if (type(check) is not dict or set(check) != {'root', 'start_ns', 'end_ns'} or check['root'] != root
                or not typed._interval(check, lower, upper)):
            raise ValueError('Original late canonical timing left the charged cold boundary')
        lower = check['end_ns']
    return checks


def _typed_proof(folder, request, contract, observer):
    # The existing V39 auditor sees only the typed arm; all S raw events
    # and both complete ledgers are checked below with their actual arm labels.
    metadata = request['metadata']
    scope = dict(request, metadata=dict(metadata, schedule=[row for row in metadata['schedule'] if row['mode'] == 'T']))

    def typed_read(path):
        value = read(path)
        return value['T'] if Path(path) == folder / 'cache_receipt.json' else value

    return _clone(typed.audit_typed_runs, read=typed_read)(folder, scope, contract, observer)


def _cache_use(events, phases, expected, arm, cold):
    use = _phase(events, 'cache.use')['metadata']
    legacy = typed.adapter.strip_use(use) if arm == 'T' else use
    if legacy != expected:
        raise ValueError('Cache use differs from the independently rebuilt snapshot')
    for name in ('cache.identity', 'cache.pre_use_digest', 'cache.final_guard', 'cache.use'):
        if phases.get(name, {}).get('calls') != 1:
            raise ValueError('Required identity, pre-use, borrow or final guard count differs')
    for name in ('cache.cold_build', 'cache.original_load_context', 'cache.original_prepare_catalog'):
        if phases.get(name, {}).get('calls', 0) != int(cold):
            raise ValueError('Each arm requires exactly one cold load and prepare')
    count = 3 if cold else 2
    for name, expected_count in (('fingerprint', count), ('validation', count), ('json', count),
                                 ('utf8', count), ('sha256', count), ('release', 2 * count)):
        if phases.get('snapshot.' + name, {}).get('calls') != expected_count:
            raise ValueError('Complete snapshot phase count differs')
    owners = []
    for event in events:
        if event['phase'].startswith('snapshot.') and event['metadata'].get('scheme') != original.SCHEME:
            raise ValueError('Snapshot phase scheme differs')
        if event['phase'] == 'snapshot.fingerprint':
            parent = events[event['parent']]
            owners.append(parent['phase'])
    expected_owners = ['cache.pre_use_digest', 'cache.final_guard']
    if cold:
        expected_owners.insert(0, 'cache.cold_build')
    if owners != expected_owners:
        raise ValueError('Original snapshot integrity boundaries differ')
    if _phase(events, 'verifier.setup_envelope')['end_ns'] > _phase(events, 'cache.final_guard')['start_ns']:
        raise ValueError('Final guard overlaps original setup')
    return use


def comparison(runs):
    if set(runs) != {row['label'] for row in frozen.SCHEDULE}:
        raise ValueError('All fourteen measured entries required')
    cost = {}
    for row in frozen.SCHEDULE:
        label, arm = row['label'], row['mode']
        run = runs[label]
        value = run['accounting']['costs']
        if run['mode'] != arm or any(type(value[key]) not in (int, float) or not isfinite(value[key]) or value[key] <= 0
                                     for key in ('entry_seconds', 'primary_seconds')):
            raise ValueError('Expected finite positive timing for the exact arm')
        cost[label] = value

    def difference(stem, order):
        s, t = (cost[stem + '_' + arm] for arm in ARMS)
        difference = t['entry_seconds'] - s['entry_seconds']
        return dict(order=order, S_entry_seconds=s['entry_seconds'], T_entry_seconds=t['entry_seconds'],
                    T_minus_S_seconds=difference, T_minus_S_percent=100 * difference / s['entry_seconds'],
                    T_minus_S_primary_seconds=t['primary_seconds'] - s['primary_seconds'])

    pairs = [dict(difference(f'pair_{pair}', 'TS' if pair % 2 else 'ST'), pair=pair) for pair in range(1, 7)]
    totals = {arm: fsum(cost[row['label']]['entry_seconds'] for row in frozen.SCHEDULE if row['mode'] == arm) for arm in ARMS}
    total_delta = totals['T'] - totals['S']
    return dict(cold=difference('cold', 'ST'), hit_pairs=pairs, all7_entry_seconds=totals,
        all7_T_minus_S_seconds=total_delta, all7_T_minus_S_percent=100 * total_delta / totals['S'],
        hit_pair_median_T_minus_S_seconds=median(row['T_minus_S_seconds'] for row in pairs),
        hit_pair_median_T_minus_S_percent=median(row['T_minus_S_percent'] for row in pairs),
        hit_pair_order_medians={order: median(row['T_minus_S_seconds'] for row in pairs if row['order'] == order)
                                for order in ('ST', 'TS')},
        hit_pair_median_T_minus_S_primary_seconds=median(row['T_minus_S_primary_seconds'] for row in pairs),
        typed_faster_hit_pairs=sum(row['T_minus_S_seconds'] < 0 for row in pairs))


def audit_saved_runs(folder, request, observer):
    prior._saved_publisher_request(folder, request)
    meta = request['metadata']
    cohort = meta['cohort']
    old.child_exit(folder, request, 'worker')
    if meta['schedule'] != frozen.SCHEDULE or read(folder / 'worker_done.json') != old.DONE:
        raise ValueError('Full direct-comparison schedule required')
    watch = entry.ThrottledWatch(folder, request['deadline_utc'])
    with observer.span('publisher.initial_hash'):
        observer.verify_bindings(request['sources'], watch)
    binding = read(ROOT / cohort['old_run'])['binding']
    probes = read(ROOT / cohort['probes'])['probes']
    reference = read(ROOT / cohort['reference'])
    frames = list(original._physical_frames((ROOT / cohort['old_run']).parent))
    payload = b''.join(frames)
    if (len(frames) != 48 or len(payload) != reference['actual_committed_bytes']
            or hashlib.sha256(payload).hexdigest() != reference['actual_committed_payload_sha256']):
        raise ValueError('Original full reference frames differ')
    for phase in ('worker_initial_hash', 'worker_final_hash'):
        events, _ = old.check_observation(folder / phase)
        if [event['metadata']['descriptor'] for event in events if event['phase'] == 'closure.descriptor'] != request['sources']:
            raise ValueError('Worker full source coverage differs')
    contract = typed.adapter.context_contract(request, binding)
    proof = _typed_proof(folder, request, contract, observer)
    selected = ROOT / cohort['selected_root']
    config = read(selected / 'configuration.json')
    model = read(ROOT / contract['dependencies']['model']['path'])['receipt']
    paths = {key: selected / key for key in ('dataset', 'P0', 'C1', 'D1')}
    with observer.span('publisher.independent_context'):
        counts, catalog = original.pair.core.load_context(paths, config, model['support'], watch)
        prepared = original.pair.sql.prepare_catalog(catalog, counts, watch)
        snapshot = original.fingerprint(prepared, observer, watch)

    runs, uses = {}, {arm: [] for arm in ARMS}
    previous = workload = late = None
    factory = original.StoreFactory(observer)
    method_bytes = sum(row['bytes'] for row in contract['methods'])
    dependencies = contract['dependencies']
    for item in meta['schedule']:
        watch.force()
        label, arm = item['label'], item['mode']
        root = folder / label
        if read(folder / (label + '_started.json')) != item:
            raise ValueError('Observed entry order or arm identity differs')
        run = read(root / 'verified_subset/run.json')
        if (run['binding'] != binding or run['expected_queries'] != 48
                or any(run[key] != request[key] for key in ('budget_seconds', 'deadline_utc'))):
            raise ValueError('Run identity or original binding differs')
        with observer.span('publisher.open_and_proof'):
            store = factory.open(root / 'verified_subset', binding, source_root=ROOT)
            ledger = observer.call('publisher.ledger_proof', original.ledger_proof, store, probes)
            if ledger != read(root / 'proof.json') or list(original._physical_frames(root / 'verified_subset')) != frames:
                raise ValueError('Complete scientific payload or proof differs')
        measured, raw, saved_entry = (read(root / name) for name in ('measured.json', 'observations.json', 'entry.json'))
        if saved_entry['label'] != label or saved_entry['mode'] != 'baseline' or read(root / 'profile.json'):
            raise ValueError('Original SQL method identity differs')
        accounting = original.summarize_run(measured, raw, saved_entry, probes)
        current = [row['sql_workload'] for row in measured['queries']]
        if workload is not None and current != workload:
            raise ValueError('SQL logical workload differs between entries')
        workload = current
        load, previous = old.load_summary(root, request, label, arm, previous)
        diagnostic = old.check_diagnostic(root, binding, measured)
        events = read(root / 'events.json')
        cold = not uses[arm]
        expected = dict(fingerprint_scheme=original.SCHEME, cold=cold, hit=not cold, snapshot_digest=snapshot,
            buffer_logical_bytes=sum(row['bytes'] for row in dependencies.values()) if cold else 0,
            context_source_logical_bytes=sum(dependencies[name]['bytes'] for name in ('counts', 'catalog')) if cold else 0,
            method_logical_bytes=method_bytes, method_verifications=len(contract['methods']),
            catalog_rows=len(prepared.first), count_rows=len(prepared.counts))
        uses[arm].append(_cache_use(events, diagnostic['phases'], expected, arm, cold))
        if arm == 'S' and cold:
            late = original_late_timing(folder, events)
        runs[label] = dict(mode=arm, accounting=accounting, diagnostic=diagnostic, load=load)

    receipts = read(folder / 'cache_receipt.json')
    if set(receipts) != set(ARMS):
        raise ValueError('Exactly two independent arm receipts required')
    for arm, records in uses.items():
        saved = typed.adapter.strip_summary(receipts[arm]) if arm == 'T' else receipts[arm]
        projected = [typed.adapter.strip_use(row) for row in records] if arm == 'T' else records
        expected = dict(fingerprint_scheme=original.SCHEME, candidate_runs=7, cold_builds=1, hits=6,
            buffer_logical_bytes=sum(row['buffer_logical_bytes'] for row in records),
            context_source_logical_bytes=sum(row['context_source_logical_bytes'] for row in records), call_observations=projected)
        if len(records) != 7 or saved != expected:
            raise ValueError('Complete per-arm cache receipt differs from the raw observations')
    with observer.span('publisher.final_hash'):
        observer.verify_bindings(request['sources'], watch)
    if prior.check_gates() != meta['gates']:
        raise ValueError('Scientific gates changed')
    result = dict(status=AUDITED, runs=runs, reference=reference, cache=receipts, typed_validation=proof,
                  original_late_checks=late, decision=comparison(runs), evidence=prior.common.publisher_evidence(folder))
    observer.call('publisher.result_write', write, folder / 'audited_result.json', result)


run_publisher = _clone(entry.run_publisher, audit_saved_runs=audit_saved_runs)
audit_completed = _clone(entry.audit_completed, decision=comparison)
