"""Time the V39 worker's two reference builds using the V41 source authority."""
import argparse
from functools import partial
import json
from pathlib import Path
from statistics import median
from time import perf_counter_ns
from types import SimpleNamespace

from scripts import retailrocket_session_knn_typed_adapter_v39 as adapter
from scripts import retailrocket_session_knn_typed_v39 as typed
from scripts import run_retailrocket_session_knn_compare_v41 as prior
from scripts.retailrocket_session_knn_diagnostics_v20 import _clone
from scripts.run_retailrocket_session_knn_v2 import ROOT, check_gates, describe, environment, read


REPORT = 'reports/stage12/retailrocket_session_knn_v42_reference_cost_20261111.json'
V41_SHA = '3912ac1ffb443a14c52da75b4dd9e51fd828429424c860ba81e40a0adb119647'
ROOTS = ('config', 'model')
PARTS = {'decode': typed._decode, 'grammar': typed._grammar, 'reference': typed._reference}
ORDERS = (('plain', 'observed'), ('observed', 'plain')) * 3
SCOPE = dict(build_replays=14, reference_roots=28, verified_live_roots=28, query_runs=0, fits=0, reserved_test='locked')


class Trace:
    def __init__(self):
        self.events = {}

    def call(self, key, function, *args, **kwargs):
        if key in self.events:
            raise ValueError('Repeated reference build phase: ' + key)
        start = perf_counter_ns()
        result = function(*args, **kwargs)
        self.events[key] = [start, perf_counter_ns()]
        return result

    def builder(self, source, *, source_role, **kwargs):
        parts = {function.__name__: partial(self.call, source_role + '.' + part, function)
                 for part, function in PARTS.items()}
        original = _clone(typed._build_verified_reference, **parts)
        return self.call(source_role, original, source, source_role=source_role, **kwargs)

    def build(self, state):
        dispatch = SimpleNamespace(_build_verified_reference=self.builder, ORIGINAL_CANONICAL=typed.ORIGINAL_CANONICAL)
        build = _clone(adapter._Load.buffer_root, typed=dispatch,
                       _authority=partial(self.call, 'authority_check', adapter._authority))
        return build(state, 'item_counts.csv', b'')


def cycle(raw, dependencies, mode):
    """Replay the exact timed buffer_root interval, with fresh original early checks."""
    if mode not in ('plain', 'observed'):
        raise ValueError('Unknown reference build mode')
    config, model = json.loads(raw['config']), json.loads(raw['model'])['receipt']
    source_config, source_model = json.loads(raw['config']), json.loads(raw['model'])['receipt']
    pool = SimpleNamespace(contract={'dependencies': dependencies}, poisoned=False, _typed_comparing=False)
    state = adapter._Load(pool, config, model)
    if state.canonical(config) != state.canonical(source_config) or state.canonical(model) != state.canonical(source_model):
        raise ValueError('Original four early canonical checks differ')

    trace = Trace()
    if mode == 'observed':
        trace.build(state)
    else:
        state.buffer_root('item_counts.csv', b'')

    # The original full live checks run outside the measured build interval.
    if state.canonical(config) != state.source_bytes[0] or state.canonical(model) != state.source_bytes[1]:
        raise ValueError('Original late validation differs from source bytes')
    authority = pool._typed_authority
    sample = dict(mode=mode, build=[state.build['start_ns'], state.build['end_ns']], spans=trace.events,
                  late_roots=[row['root'] for row in state.checks if row['completed'] and row['equal']])
    return sample, authority


def _duration(span):
    if (type(span) is not list or len(span) != 2 or any(type(value) is not int for value in span)
            or not 0 <= span[0] <= span[1]):
        raise ValueError('Invalid passive timing interval')
    return span[1] - span[0]


def _inside_order(children, parent):
    lower, upper = parent
    for child in children:
        _duration(child)
        if not lower <= child[0] <= child[1] <= upper:
            raise ValueError('Reference build phases overlap or left the enclosing span')
        lower = child[1]


def phases(sample):
    spans = sample['spans']
    total = _duration(sample['build'])
    if sample['late_roots'] != list(ROOTS) or not total:
        raise ValueError('Complete two-root build and late equality required')
    if sample['mode'] == 'plain' and spans == {}:
        return total, {}
    expected = {*ROOTS, 'authority_check', *(root + '.' + part for root in ROOTS for part in PARTS)}
    if sample['mode'] != 'observed' or set(spans) != expected:
        raise ValueError('Exact observed phase coverage required')
    outer = [spans[key] for key in (*ROOTS, 'authority_check')]
    _inside_order(outer, sample['build'])
    values = {}
    for root in ROOTS:
        names = [root + '.' + part for part in PARTS]
        _inside_order([spans[name] for name in names], spans[root])
        measured = {name: _duration(spans[name]) for name in names}
        values.update(measured)
        values[root + '.other'] = _duration(spans[root]) - sum(measured.values())
    values['authority_check'] = _duration(spans['authority_check'])
    values['adapter_other'] = total - sum(_duration(span) for span in outer)
    return total, values


def _distribution(values):
    return dict(min=min(values), median=median(values), max=max(values))


def summarize(warmups, pairs):
    if ([sample['mode'] for sample in warmups] != ['plain', 'observed']
            or [tuple(sample['mode'] for sample in pair) for pair in pairs] != list(ORDERS)):
        raise ValueError('Frozen warmup and alternating pair order differs')
    samples = [*warmups, *(sample for pair in pairs for sample in pair)]
    if any(left['build'][1] > right['build'][0] for left, right in zip(samples, samples[1:])):
        raise ValueError('Replay build intervals overlap')
    for sample in warmups:
        phases(sample)
    totals = {'plain': [], 'observed': []}
    parts = {}
    shares = {}
    pair_deltas = []
    for pair in pairs:
        pair_totals = {}
        for sample in pair:
            total, exclusive = phases(sample)
            mode = sample['mode']
            totals[mode].append(total)
            pair_totals[mode] = total
            for name, value in exclusive.items():
                parts.setdefault(name, []).append(value)
                shares.setdefault(name, []).append(100 * value / total)
        pair_deltas.append(pair_totals['observed'] - pair_totals['plain'])
    return dict(build_ns={mode: _distribution(times) for mode, times in totals.items()},
                phase_ns={name: _distribution(times) for name, times in parts.items()},
                phase_share_percent={name: _distribution(percent) for name, percent in shares.items()},
                observed_minus_plain_ns=pair_deltas, paired_observed_minus_plain_ns=_distribution(pair_deltas))


def inputs():
    predecessor = describe(ROOT / prior.REPORT)
    if predecessor['sha256'] != V41_SHA:
        raise ValueError('V41 direct comparison report differs')
    report = read(ROOT / prior.REPORT)
    authority = report['typed_validation']['authority']
    adapter._authority(authority)
    gates = check_gates()
    spec = prior.frozen.specification()
    dependencies = {root: spec['dependencies'][root] for root in ROOTS}
    if (gates != spec['gates'] or environment() != spec['environment'] or authority['raw_sources'] != dependencies
            or authority['policy'] != adapter.POLICY or authority['reference_scheme'] != typed.SCHEME):
        raise ValueError('V41 environment, gates or two source descriptors differ')
    bound_methods = [Path(__file__), Path(adapter.__file__), Path(typed.__file__),
                     Path(adapter.c1.__file__), ROOT / 'scripts/retailrocket_session_knn_diagnostics_v20.py']
    evidence = dict(predecessor=predecessor, authority=authority, gates=gates, environment=environment(),
                    methods=[describe(path) for path in bound_methods],
                    V41_worker_reference_build_seconds=report['cold_replaced_work']['T_reference_build_seconds'])
    raw = {name: adapter.c1.verified_buffer(ROOT, record) for name, record in dependencies.items()}
    return evidence, raw


def measure():
    if (ROOT / REPORT).exists():
        raise FileExistsError('Immutable reference build diagnostic already exists')
    evidence, raw = inputs()

    def run(mode):
        sample, authority = cycle(raw, evidence['authority']['raw_sources'], mode)
        if authority != evidence['authority']:
            raise ValueError('Replayed reference differs from V41 source authority')
        print('Completed reference build replay: ' + mode, flush=True)
        return sample

    warmups = [run('plain'), run('observed')]
    pairs = [[run(mode) for mode in order] for order in ORDERS]
    if (evidence, raw) != inputs():
        raise ValueError('Bound evidence changed during the diagnostic')
    result = dict(evidence=evidence, warmups=warmups, pairs=pairs, summary=summarize(warmups, pairs), scope=SCOPE)
    prior.public_json(ROOT / REPORT, result, exclusive=True)
    return result


def audit():
    result = read(ROOT / REPORT)
    evidence, _ = inputs()
    if (result['evidence'] != evidence or result['summary'] != summarize(result['warmups'], result['pairs'])
            or result['scope'] != SCOPE):
        raise ValueError('Saved reference diagnostic differs from the bound inputs or timings')
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument('--measure', action='store_true')
    mode.add_argument('--audit', action='store_true')
    args = parser.parse_args()
    with prior.entry.exclusive():
        result = audit() if args.audit else measure()
    print(dict(audit=args.audit, scope=result['scope'], build_ns=result['summary']['build_ns']))


if __name__ == '__main__':
    main()
