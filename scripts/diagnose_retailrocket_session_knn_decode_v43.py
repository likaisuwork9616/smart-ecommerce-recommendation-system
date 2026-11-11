"""Measure the original V39 model decoder's string, array, and tuple work."""
import argparse
import hashlib
import inspect
import json
from pathlib import Path
from time import perf_counter_ns

from scripts import diagnose_retailrocket_session_knn_reference_v42 as prior
from scripts.run_retailrocket_session_knn_v2 import ROOT, describe, read


typed = prior.typed
REPORT = 'reports/stage12/retailrocket_session_knn_v43_decode_cost_20261111.json'
V42_SHA = '6ecdba2556197b555e16e18fe91204cef7c9f20b44b7dc88f277711fc0927bc0'
PHASES = ('utf8', 'string_scan', 'tuple_build', 'array_parse')
DIRECT = PHASES[:3]
SCOPE = dict(decode_replays=14, verified_trees=14, query_runs=0, fits=0, reserved_test='locked')


class Timer:
    def __init__(self, function):
        self.function = function
        self.calls = 0
        self.elapsed_ns = 0

    def __call__(self, *args):
        start = perf_counter_ns()
        result = self.function(*args)
        self.elapsed_ns += perf_counter_ns() - start
        self.calls += 1
        return result


def timed_decoder():
    """Insert timers into a private copy of the original decoder."""
    timers = dict(utf8=Timer(lambda source: source.decode('utf-8')),
                  string_scan=Timer(typed._string), tuple_build=Timer(tuple))
    source = inspect.getsource(typed._decode)
    target = "source.decode('utf-8')"
    if source.count(target) != 1:
        raise ValueError('Expected one original UTF-8 callsite')
    namespace = dict(typed._decode.__globals__, _timed_utf8=timers['utf8'],
                     _string=timers['string_scan'], tuple=timers['tuple_build'])
    modified = source.replace(target, '_timed_utf8(source)')
    exec(compile(modified, __file__, 'exec'), namespace)
    return namespace['_decode'], timers


def replay(source, mode):
    if mode == 'plain':
        decode, timers = typed._decode, {}
    elif mode == 'observed':
        decode, timers = timed_decoder()
    else:
        raise ValueError('Unknown model decode replay mode')
    start = perf_counter_ns()
    decoded = decode(source)
    end = perf_counter_ns()
    sample = dict(mode=mode, interval=[start, end],
                  elapsed_ns={name: timer.elapsed_ns for name, timer in timers.items()},
                  calls={name: timer.calls for name, timer in timers.items()})
    return sample, decoded


def tree_counts(root):
    pending = [root]
    counts = dict(utf8=1, string_scan=0, tuple_build=0)
    while pending:
        value = pending.pop()
        if type(value) is tuple:
            counts['tuple_build'] += 1
            pending.extend(value)
        elif type(value) is str:
            counts['string_scan'] += 1
        elif type(value) is not bool:
            raise ValueError('Unexpected model token in original decoded tree')
    return counts


def phases(sample, counts):
    total = prior._duration(sample['interval'])
    measured = sample['elapsed_ns']
    if total <= 0:
        raise ValueError('Positive decoder time required')
    if sample['mode'] == 'plain' and measured == {} and sample['calls'] == {}:
        return total, {}
    if (sample['mode'] != 'observed' or sample['calls'] != counts or set(measured) != set(DIRECT)
            or any(type(value) is not int or value < 0 for value in measured.values())):
        raise ValueError('Observed phases must match the original tree operation counts')
    residual = total - sum(measured.values())
    if residual < 0:
        raise ValueError('Observed subphases exceed the full decoder interval')
    return total, dict(measured, array_parse=residual)


def summarize(warmups, pairs, counts):
    if ([sample['mode'] for sample in warmups] != ['plain', 'observed']
            or [tuple(sample['mode'] for sample in pair) for pair in pairs] != list(prior.ORDERS)):
        raise ValueError('Expected one warmup per mode and six alternating pairs')
    samples = [*warmups, *(sample for pair in pairs for sample in pair)]
    if any(left['interval'][1] > right['interval'][0] for left, right in zip(samples, samples[1:])):
        raise ValueError('Decoder replay intervals overlap')
    for sample in warmups:
        phases(sample, counts)
    totals = {'plain': [], 'observed': []}
    parts = {name: [] for name in PHASES}
    shares = {name: [] for name in PHASES}
    for pair in pairs:
        for sample in pair:
            total, exclusive = phases(sample, counts)
            totals[sample['mode']].append(total)
            for name, elapsed in exclusive.items():
                parts[name].append(elapsed)
                shares[name].append(100 * elapsed / total)
    deltas = [observed - plain for plain, observed in zip(totals['plain'], totals['observed'])]
    distribution = prior._distribution
    return dict(decode_ns={name: distribution(values) for name, values in totals.items()},
                phase_ns={name: distribution(values) for name, values in parts.items()},
                phase_share_percent={name: distribution(values) for name, values in shares.items()},
                observed_minus_plain_ns=deltas, paired_observed_minus_plain_ns=distribution(deltas))


def inputs():
    predecessor = describe(ROOT / prior.REPORT)
    if predecessor['sha256'] != V42_SHA:
        raise ValueError('V42 reference build report differs')
    report = read(ROOT / prior.REPORT)
    evidence, raw = prior.inputs()
    if report['evidence'] != evidence:
        raise ValueError('V42 source authority or method bytes changed')
    model = evidence['authority']['canonical']['model']
    source = typed.ORIGINAL_CANONICAL(json.loads(raw['model'])['receipt'])
    if (len(source) != model['bytes'] or hashlib.sha256(source).hexdigest() != model['sha256']
            or model['scheme'] != typed.SCHEME):
        raise ValueError('Exact model canonical bytes used by V42 required')
    return dict(predecessor=predecessor, model=model,
                raw_model=evidence['authority']['raw_sources']['model'],
                reference_statistics=evidence['authority']['reference_statistics']['model'],
                V42_model_decode_ns=report['summary']['phase_ns']['model.decode'],
                method=describe(Path(__file__)), environment=evidence['environment'], gates=evidence['gates']), source


def measure():
    if (ROOT / REPORT).exists():
        raise FileExistsError('Immutable decode diagnostic already exists')
    evidence, source = inputs()
    plain_warmup, expected = replay(source, 'plain')
    root, depth = expected
    counts = tree_counts(root)
    stats = dict(typed._grammar(root), encoded_depth=depth)
    if stats != evidence['reference_statistics']:
        raise ValueError('Original model tree statistics differ from V42')

    def run(mode):
        sample, decoded = replay(source, mode)
        if decoded != expected:
            raise ValueError('Full decoded tuple tree or encoded depth differs')
        phases(sample, counts)
        return sample

    warmups = [plain_warmup, run('observed')]
    pairs = []
    for index, order in enumerate(prior.ORDERS, start=1):
        pairs.append([run(mode) for mode in order])
        print(f'Completed model decode pair {index}/{len(prior.ORDERS)}', flush=True)
    if (evidence, source) != inputs():
        raise ValueError('Bound model source or methods changed during the diagnostic')
    result = dict(evidence=evidence, calls=counts, warmups=warmups, pairs=pairs, scope=SCOPE,
                  summary=summarize(warmups, pairs, counts))
    prior.prior.public_json(ROOT / REPORT, result, exclusive=True)
    return result


def audit():
    result = read(ROOT / REPORT)
    evidence, source = inputs()
    root, depth = typed._decode(source)
    counts = tree_counts(root)
    if (result['evidence'] != evidence or result['calls'] != counts
            or dict(typed._grammar(root), encoded_depth=depth) != evidence['reference_statistics']
            or result['summary'] != summarize(result['warmups'], result['pairs'], counts) or result['scope'] != SCOPE):
        raise ValueError('Saved decoder timings or model evidence differ')
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument('--measure', action='store_true')
    mode.add_argument('--audit', action='store_true')
    args = parser.parse_args()
    with prior.prior.entry.exclusive():
        result = audit() if args.audit else measure()
    print(dict(audit=args.audit, scope=result['scope'], decode_ns=result['summary']['decode_ns']))


if __name__ == '__main__':
    main()
