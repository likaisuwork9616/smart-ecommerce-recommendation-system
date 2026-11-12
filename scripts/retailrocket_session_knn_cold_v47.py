"""Fresh V39 and V46 worker contexts and independent fixed48 verification."""
import hashlib
from math import isfinite
from statistics import median
from types import SimpleNamespace

from scripts import compare_retailrocket_session_knn_string_v46 as decoder
from scripts import retailrocket_session_knn_compare_v41 as prior
from scripts.retailrocket_session_knn_diagnostics_v20 import _clone


entry, old = prior.entry, prior.old
ROOT, read, write = prior.ROOT, prior.read, prior.write
typed, adapter, original = prior.typed.typed, prior.typed.adapter, prior.original
ARMS = {'R': 'V39', 'C': 'V46 decoder in V39 worker'}
ORDERS = ('CR', 'RC') * 3
SCHEDULE = [dict(label='warm_' + arm, mode=arm) for arm in ARMS] + [
    dict(label=f'pair_{index}_{arm}', mode=arm) for index, order in enumerate(ORDERS, 1) for arm in order]
AUDITED = 'v47_cold_comparison_independently_verified'
METRICS = ('decode', 'reference_build', 'cold_build', 'entry')


class CandidateLoad(adapter._Load):
    # Replace only the decoder inside the original timed reference factory.
    buffer_root = _clone(adapter._Load.buffer_root, typed=SimpleNamespace(
        ORIGINAL_CANONICAL=typed.ORIGINAL_CANONICAL,
        _build_verified_reference=_clone(typed._build_verified_reference, _decode=decoder.candidate.decode)))


class CandidateContext(adapter.WorkerContext):
    load = _clone(adapter.WorkerContext.load, _Load=CandidateLoad)


def _fixed48(folder, request, label, mode, data, **kwargs):
    return adapter.run_fixed48(folder, request, label, 'C', data, **kwargs)


observed_run = _clone(entry.observed_run, run_fixed48=_fixed48)


def model_bytes(request, watch):
    record = request['metadata']['context']['dependencies']['model']
    value = adapter.c1.json.loads(adapter.c1.verified_buffer(ROOT, record, watch))['receipt']
    return typed.ORIGINAL_CANONICAL(value)


def run_worker(folder, request):
    watch = entry.ThrottledWatch(folder, request['deadline_utc'])
    try:
        old.hash_phase(folder, request, 'worker_initial_hash', watch)
        receipts = {}
        for item in request['metadata']['schedule']:
            watch.force()
            label, arm = item['label'], item['mode']
            write(folder / (label + '_started.json'), item)
            data = old.inputs(request)
            contract = adapter.context_contract(request, data[2])
            context = adapter.WorkerContext if arm == 'R' else CandidateContext
            pool = context(contract, ROOT, ROOT)
            try:
                entry.clear_caches()
                observed_run(folder, request, item, data, pool, watch)
                if pool.poisoned or pool.active is not None or len(pool.calls) != 1:
                    raise ValueError('One completed fresh context required per entry')
                receipts[label] = dict(mode=arm, use=pool.calls[0])
            finally:
                pool.close()
            entry._check_db(data[4])
            watch.force()
        write(folder / 'cache_receipt.json', receipts)

        # Decoder pairs follow all cold entries, outside each cold interval.
        source = model_bytes(request, watch)
        expected = None
        decodes = {}
        for item in request['metadata']['schedule']:
            watch.force()
            mode = 'original' if item['mode'] == 'R' else 'candidate'
            sample, value = decoder.replay(source, mode)
            if expected is None:
                expected = value
            elif value != expected:
                raise ValueError('Full model decode output differs from V39')
            decodes[item['label']] = sample
        write(folder / 'decode_receipt.json', decodes)
        old.hash_phase(folder, request, 'worker_final_hash', watch)
        write(folder / 'worker_done.json', old.DONE)
    except BaseException as error:
        write(folder / 'worker_failure.json', dict(error_type=type(error).__name__))
        raise


def independent_authority(deps, watch, observer):
    with observer.span('publisher.typed_authority'):
        values = {name: adapter.c1.json.loads(adapter.c1.verified_buffer(ROOT, deps[name], watch))
                  for name in prior.ROOTS}
        values['model'] = values['model']['receipt']
        refs, stats = {}, {}
        for name, value in values.items():
            encoded = typed.ORIGINAL_CANONICAL(value)
            ref = typed.build_reference(encoded)
            if decoder.candidate.decode(encoded) != (ref.root, ref.statistics()['encoded_depth']):
                raise ValueError('Candidate differs from independently reconstructed tuple tree')
            equal, stats[name] = typed.compare_with_stats(value, ref)
            if equal is not True:
                raise ValueError('Independent typed comparison did not pass')
            refs[name] = ref
        return (dict(raw_sources={name: deps[name] for name in refs},
            canonical={name: ref.source_descriptor for name, ref in refs.items()},
            reference_statistics={name: ref.statistics() for name, ref in refs.items()},
            policy=adapter.POLICY, reference_scheme=typed.SCHEME), stats)


def build_timing(events, use, authority, stats):
    proof = use['typed_reference']  # strip_use already checks field types and shape.
    cold = prior._phase(events, 'cache.cold_build')
    load = prior._phase(events, 'cache.original_load_context')
    prepare = prior._phase(events, 'cache.original_prepare_catalog')
    fingerprint = next(event for event in events if event['phase'] == 'snapshot.fingerprint')
    cache_use = prior._phase(events, 'cache.use')
    build = proof['build']
    if proof['authority'] != authority or not prior.typed._interval(build, cold['start_ns'], load['start_ns']):
        raise ValueError('Reference authority or charged build interval differs')
    lower = prepare['end_ns']
    for check in proof['checks']:
        if check['statistics'] != stats[check['root']] or not prior.typed._interval(check, lower, fingerprint['start_ns']):
            raise ValueError('Late check left the original charged boundary')
        lower = check['end_ns']
    if not lower <= fingerprint['start_ns'] <= cold['end_ns'] <= cache_use['start_ns']:
        raise ValueError('Typed check, snapshot and borrow order differs')
    return (build['end_ns'] - build['start_ns']) / 1e9


def attach_decode_times(runs, decodes, after):
    if set(decodes) != set(runs):
        raise ValueError('Decoder replays must match all cold labels')
    last = after
    for item in SCHEDULE:
        label, arm = item['label'], item['mode']
        sample = decodes[label]
        start, end = sample['interval']
        if (sample['mode'] != ('original' if arm == 'R' else 'candidate')
                or type(start) is not int or type(end) is not int or not last <= start < end):
            raise ValueError('Decode-only role or interval differs')
        last = end
        runs[label]['decode_seconds'] = (end - start) / 1e9


def comparison(runs):
    if set(runs) != {item['label'] for item in SCHEDULE}:
        raise ValueError('Expected all cold entries')
    costs = {}
    for item in SCHEDULE:
        label = item['label']
        run = runs[label]
        costs[label] = dict(decode=run['decode_seconds'], reference_build=run['reference_build_seconds'],
            cold_build=run['diagnostic']['phases']['cache.cold_build']['inclusive_wall_ns'] / 1e9,
            entry=run['accounting']['costs']['entry_seconds'])
        if run['mode'] != item['mode'] or any(not isfinite(value) or value <= 0 for value in costs[label].values()):
            raise ValueError('Exact arm and finite positive cost required')
    pairs = []
    for index, order in enumerate(ORDERS, 1):
        r, c = (costs[f'pair_{index}_{arm}'] for arm in ARMS)
        pairs.append(dict(pair=index, order=order, original=r, candidate=c,
            saving_seconds={key: r[key] - c[key] for key in METRICS},
            saving_percent={key: 100 * (r[key] - c[key]) / r[key] for key in METRICS}))
    medians = {key: dict(original=median(pair['original'][key] for pair in pairs),
        candidate=median(pair['candidate'][key] for pair in pairs),
        saving_seconds=median(pair['saving_seconds'][key] for pair in pairs),
        saving_percent=median(pair['saving_percent'][key] for pair in pairs),
        faster_pairs=sum(pair['saving_seconds'][key] > 0 for pair in pairs),
        order_medians={order: median(pair['saving_seconds'][key] for pair in pairs if pair['order'] == order)
                       for order in ('RC', 'CR')}) for key in METRICS}
    decode_saving = medians['decode']['saving_seconds']
    return dict(warmups={arm: costs['warm_' + arm] for arm in ARMS}, pairs=pairs, medians=medians,
        saving_relative_to_decode_median={key: medians[key]['saving_seconds'] / decode_saving
                                        for key in METRICS[1:]} if decode_saving > 0 else None)


def audit_saved_runs(folder, request, observer):
    prior.prior._saved_publisher_request(folder, request)
    meta = request['metadata']
    cohort = meta['cohort']
    old.child_exit(folder, request, 'worker')
    if meta['schedule'] != SCHEDULE or read(folder / 'worker_done.json') != old.DONE:
        raise ValueError('Expected the complete all-cold fixed48 schedule')
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
        raise ValueError('Original fixed48 reference frames differ')
    for phase in ('worker_initial_hash', 'worker_final_hash'):
        events, _ = old.check_observation(folder / phase)
        if [event['metadata']['descriptor'] for event in events if event['phase'] == 'closure.descriptor'] != request['sources']:
            raise ValueError('Worker full source coverage differs')
    contract = adapter.context_contract(request, binding)
    deps = contract['dependencies']
    authority, stats = independent_authority(deps, watch, observer)
    selected = ROOT / cohort['selected_root']
    config = read(selected / 'configuration.json')
    model = read(ROOT / deps['model']['path'])['receipt']
    paths = {key: selected / key for key in ('dataset', 'P0', 'C1', 'D1')}
    with observer.span('publisher.independent_context'):
        counts, catalog = original.pair.core.load_context(paths, config, model['support'], watch)
        prepared = original.pair.sql.prepare_catalog(catalog, counts, watch)
        snapshot = original.fingerprint(prepared, observer, watch)
    expected = dict(fingerprint_scheme=original.SCHEME, cold=True, hit=False, snapshot_digest=snapshot,
        buffer_logical_bytes=sum(row['bytes'] for row in deps.values()),
        context_source_logical_bytes=sum(deps[name]['bytes'] for name in ('counts', 'catalog')),
        method_logical_bytes=sum(row['bytes'] for row in contract['methods']), method_verifications=len(contract['methods']),
        catalog_rows=len(prepared.first), count_rows=len(prepared.counts))

    runs, uses = {}, {}
    previous = workload = None
    factory = original.StoreFactory(observer)
    for item in SCHEDULE:
        watch.force()
        label, arm = item['label'], item['mode']
        root = folder / label
        if read(folder / (label + '_started.json')) != item:
            raise ValueError('Observed cold entry order or arm differs')
        run = read(root / 'verified_subset/run.json')
        if (run['binding'] != binding or run['expected_queries'] != 48
                or any(run[key] != request[key] for key in ('budget_seconds', 'deadline_utc'))):
            raise ValueError('Cold run identity or binding differs')
        with observer.span('publisher.open_and_proof'):
            store = factory.open(root / 'verified_subset', binding, source_root=ROOT)
            ledger = observer.call('publisher.ledger_proof', original.ledger_proof, store, probes)
            if ledger != read(root / 'proof.json') or list(original._physical_frames(root / 'verified_subset')) != frames:
                raise ValueError('Complete scientific frames or proof differ')
        measured, raw, saved_entry = (read(root / name) for name in ('measured.json', 'observations.json', 'entry.json'))
        if saved_entry['label'] != label or saved_entry['mode'] != 'baseline' or read(root / 'profile.json'):
            raise ValueError('Original fixed48 entry or SQL mode differs')
        accounting = original.summarize_run(measured, raw, saved_entry, probes)
        current = [row['sql_workload'] for row in measured['queries']]
        if workload is not None and current != workload:
            raise ValueError('SQL logical workload differs between cold entries')
        workload = current
        load, previous = old.load_summary(root, request, label, arm, previous)
        diagnostic = old.check_diagnostic(root, binding, measured)
        events = read(root / 'events.json')
        use = prior._cache_use(events, diagnostic['phases'], expected, 'T', True)
        uses[label] = dict(mode=arm, use=use)
        runs[label] = dict(mode=arm, accounting=accounting, diagnostic=diagnostic, load=load,
                          reference_build_seconds=build_timing(events, use, authority, stats))
    if read(folder / 'cache_receipt.json') != uses:
        raise ValueError('Cold cache receipt differs from raw events')
    attach_decode_times(runs, read(folder / 'decode_receipt.json'), prior._phase(events, 'run.total')['end_ns'])
    with observer.span('publisher.final_hash'):
        observer.verify_bindings(request['sources'], watch)
    if prior.prior.check_gates() != meta['gates']:
        raise ValueError('Scientific gates changed')
    result = dict(status=AUDITED, runs=runs, cache=uses, reference=reference, authority=authority,
                  decision=comparison(runs), evidence=prior.prior.common.publisher_evidence(folder))
    observer.call('publisher.result_write', write, folder / 'audited_result.json', result)


run_publisher = _clone(entry.run_publisher, audit_saved_runs=audit_saved_runs)
audit_completed = _clone(entry.audit_completed, decision=comparison)
