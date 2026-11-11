"""Estimate model decoder phases using sparse, paired measurements."""
import argparse
import hashlib
import inspect
from pathlib import Path
from random import Random
from statistics import median
from time import perf_counter_ns

from scripts import diagnose_retailrocket_session_knn_decode_v43 as prior
from scripts.diagnose_retailrocket_session_knn_reference_v42 import _distribution, _duration
from scripts.run_retailrocket_session_knn_compare_v28 import exclusive
from scripts.run_retailrocket_session_knn_gap_v7 import public_json
from scripts.run_retailrocket_session_knn_v2 import ROOT, describe, read


REPORT_BASE = 'reports/stage12/retailrocket_session_knn_v44_decode_'
REPORTS = {mode: REPORT_BASE + mode + '_20261111.json' for mode in ('calibration', 'model')}
V43_SHA = '6f89069fc02493f4c91d8650593bd25c851627327dadc80d446a1ab4aa63c4ac'
BLOCK = 256
STRATUM = 64
SEEDS = tuple(range(4401, 4409))
WARMUP_SEED = 4400


def plan(length, seed):
    """Choose one character block per stratum with its inverse probability."""
    rng = Random(seed)
    windows = []
    for base in range(0, length, BLOCK * STRATUM):
        remaining = min(length - base, BLOCK * STRATUM)
        weight = (remaining + BLOCK - 1) // BLOCK
        start = base + BLOCK * rng.randrange(weight)
        windows.append((start, min(start + BLOCK, length), weight))
    return windows


class Sampler:
    def __init__(self, windows, length):
        self.windows = iter(windows)
        self.length = length
        self.window = next(self.windows, None)
        self.records = [[0, 0, 0, 0] for _ in windows]
        self.index = 0
        self.utf8_ns = 0

    def utf8(self, source):
        start = perf_counter_ns()
        text = source.decode('utf-8')
        self.utf8_ns = perf_counter_ns() - start
        return text

    def string(self, text, index):
        start = perf_counter_ns()
        value = prior.typed._string(text, index)
        elapsed = perf_counter_ns() - start
        record = self.records[self.index]
        record[0] += 1
        record[1] += elapsed
        return value

    def tuple(self, values):
        start = perf_counter_ns()
        value = tuple(values)
        elapsed = perf_counter_ns() - start
        record = self.records[self.index]
        record[2] += 1
        record[3] += elapsed
        return value

    def dispatch(self, index):
        # A string can jump over a boundary or a whole sample window.
        while self.window is not None and index >= self.window[1]:
            self.index += 1
            self.window = next(self.windows, None)
        if self.window is None:
            return self.length, prior.typed._string, tuple
        start, end, _ = self.window
        if index < start:
            return start, prior.typed._string, tuple
        return end, self.string, self.tuple


def sampled_decoder(sampler):
    """Change dispatch only at sample boundaries in a copy of the V39 parser."""
    source = inspect.getsource(prior.typed._decode)
    substitutions = (
        ("source.decode('utf-8')", '_sample_utf8(source)'),
        ('    while i<len(text):\n', '    boundary = 0\n    while i<len(text):\n'
                                    '        if i >= boundary:\n'
                                    '            boundary, scan_string, build_tuple = _dispatch(i)\n'),
        ('_string(text,i)', 'scan_string(text,i)'),
        ('tuple(stack.pop()[0])', 'build_tuple(stack.pop()[0])'),
    )
    for target, replacement in substitutions:
        if source.count(target) != 1:
            raise ValueError('Expected one original decoder callsite: ' + target)
        source = source.replace(target, replacement)
    namespace = dict(prior.typed._decode.__globals__, _sample_utf8=sampler.utf8, _dispatch=sampler.dispatch)
    exec(compile(source, __file__, 'exec'), namespace)
    return namespace['_decode']


def replay(source, length, seed=None):
    sampler = None if seed is None else Sampler(plan(length, seed), length)
    decoder = prior.typed._decode if sampler is None else sampled_decoder(sampler)
    start = perf_counter_ns()
    value = decoder(source)
    end = perf_counter_ns()
    sample = dict(seed=seed, interval=[start, end])
    if sampler is not None:
        sample.update(utf8_ns=sampler.utf8_ns, windows=sampler.records)
    return sample, value


def weighted(sample, length):
    windows = plan(length, sample['seed'])
    records = sample['windows']
    if (len(windows) != len(records) or type(sample['utf8_ns']) is not int or sample['utf8_ns'] < 0
            or any(len(record) != 4 or any(type(value) is not int or value < 0 for value in record)
                   or (record[0] == 0 and record[1] != 0) or (record[2] == 0 and record[3] != 0) for record in records)):
        raise ValueError('Invalid sparse sample record')
    elapsed = sample['utf8_ns'] + sum(record[1] + record[3] for record in records)
    if elapsed > _duration(sample['interval']):
        raise ValueError('Sampled spans exceed full decoder time')
    estimates = [sum(window[2] * record[i] for window, record in zip(windows, records)) for i in range(4)]
    return dict(string_calls=estimates[0], string_ns=estimates[1], tuple_calls=estimates[2], tuple_ns=estimates[3],
                sampled_strings=sum(record[0] for record in records), sampled_tuples=sum(record[2] for record in records),
                sampled_chars=sum(end - start for start, end, _ in windows))


def pair_summary(plain, sampled, length, clock_floor):
    estimate = weighted(sampled, length)
    plain_ns = _duration(plain['interval'])
    sampled_ns = _duration(sampled['interval'])
    if min(plain_ns, sampled_ns) <= 0:
        raise ValueError('Positive decoder times required')
    string_ns, tuple_ns = estimate['string_ns'], estimate['tuple_ns']
    array_ns = plain_ns - sampled['utf8_ns'] - string_ns - tuple_ns
    if array_ns < 0:
        raise ValueError('Sample estimates exceed the original decoder time')
    adjusted_string = max(0, string_ns - clock_floor * estimate['string_calls'])
    adjusted_tuple = max(0, tuple_ns - clock_floor * estimate['tuple_calls'])
    adjusted_array = plain_ns - sampled['utf8_ns'] - adjusted_string - adjusted_tuple
    return dict(estimate, plain_ns=plain_ns, sampled_ns=sampled_ns, overhead_ns=sampled_ns - plain_ns,
                overhead_percent=100 * (sampled_ns - plain_ns) / plain_ns, array_ns=array_ns,
                array_minus_string_ns=array_ns - string_ns,
                array_minus_string_clock_floor_ns=adjusted_array - adjusted_string)


def summarize(warmups, pairs, length, clock_floor):
    if (type(clock_floor) is not int or clock_floor < 0 or [run['seed'] for run in warmups] != [None, WARMUP_SEED]
            or len(pairs) != len(SEEDS)):
        raise ValueError('Unexpected warmups, timer floor or pair count')
    weighted(warmups[1], length)
    runs = [*warmups, *(run for pair in pairs for run in pair)]
    if any(left['interval'][1] > right['interval'][0] for left, right in zip(runs, runs[1:])):
        raise ValueError('Decode replay intervals overlap')
    rows = []
    for index, (seed, pair) in enumerate(zip(SEEDS, pairs)):
        order = [None, seed] if index % 2 == 0 else [seed, None]
        if [run['seed'] for run in pair] != order:
            raise ValueError('Unexpected seed or alternating pair order')
        plain, sampled = pair if index % 2 == 0 else pair[::-1]
        rows.append(pair_summary(plain, sampled, length, clock_floor))
    metrics = {name: _distribution([row[name] for row in rows]) for name in rows[0]}
    return dict(pairs=rows, metrics=metrics,
                array_slower_pairs=sum(row['array_minus_string_ns'] > 0 for row in rows),
                array_slower_clock_floor_pairs=sum(row['array_minus_string_clock_floor_ns'] > 0 for row in rows))


def inputs(mode):
    evidence = dict(method=describe(Path(__file__)))
    if mode == 'calibration':
        data = {'support': {f'item_{i}': i % 139 for i in range(36000)}, 'label': '範例🍀'}
        source = prior.typed.ORIGINAL_CANONICAL(data)
        evidence['synthetic'] = dict(bytes=len(source), sha256=hashlib.sha256(source).hexdigest())
    else:
        calibration_path = ROOT / REPORTS['calibration']
        audit('calibration')
        predecessor = describe(ROOT / prior.REPORT)
        if predecessor['sha256'] != V43_SHA:
            raise ValueError('V43 decoder report differs')
        v43 = read(ROOT / prior.REPORT)
        bound, source = prior.inputs()
        if v43['evidence'] != bound:
            raise ValueError('Exact V43 model canonical bytes required')
        evidence.update(predecessor=predecessor, V43=bound, calibration=describe(calibration_path),
                        reference_statistics=bound['reference_statistics'], original_calls=v43['calls'])
    return evidence, source


def verify_tree(decoded, evidence):
    root, depth = decoded
    counts = prior.tree_counts(root)
    if 'reference_statistics' in evidence:
        statistics = dict(prior.typed._grammar(root), encoded_depth=depth)
        if statistics != evidence['reference_statistics'] or counts != evidence['original_calls']:
            raise ValueError('Exact V43 model tree statistics and call counts required')
    return counts


def measure(mode):
    path = ROOT / REPORTS[mode]
    if path.exists():
        raise FileExistsError('Immutable sparse timing report already exists')
    evidence, source = inputs(mode)
    length = len(source.decode('utf-8'))
    ticks = []
    for _ in range(4097):
        start = perf_counter_ns()
        elapsed = perf_counter_ns() - start
        ticks.append(elapsed)
    clock_floor = int(median(ticks))
    plain_warmup, expected = replay(source, length)
    counts = verify_tree(expected, evidence)

    def run(seed):
        sample, decoded = replay(source, length, seed)
        if decoded != expected:
            raise ValueError('Complete decoded tree or encoded depth differs')
        return sample

    warmups = [plain_warmup, run(WARMUP_SEED)]
    pairs = []
    for index, seed in enumerate(SEEDS):
        order = (None, seed) if index % 2 == 0 else (seed, None)
        pairs.append([run(value) for value in order])
        print(f'Completed {mode} decode pair {index + 1}/{len(SEEDS)}', flush=True)
    if (evidence, source) != inputs(mode):
        raise ValueError('Bound source evidence changed during sparse timing')
    result = dict(mode=mode, evidence=evidence, length=length, original_calls=counts,
                  warmups=warmups, pairs=pairs, clock_floor_ns=clock_floor, verified_trees=18,
                  summary=summarize(warmups, pairs, length, clock_floor), query_runs=0, fits=0)
    public_json(path, result, exclusive=True)
    return result


def audit(mode):
    result = read(ROOT / REPORTS[mode])
    evidence, source = inputs(mode)
    length = len(source.decode('utf-8'))
    counts = verify_tree(prior.typed._decode(source), evidence)
    if (result['mode'] != mode or result['evidence'] != evidence or result['length'] != length
            or result['original_calls'] != counts or result['verified_trees'] != 18
            or result['query_runs'] != 0 or result['fits'] != 0
            or result['summary'] != summarize(result['warmups'], result['pairs'], length, result['clock_floor_ns'])):
        raise ValueError('Saved sparse timings or bound evidence differ')
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    action = parser.add_mutually_exclusive_group(required=True)
    action.add_argument('--measure', choices=REPORTS)
    action.add_argument('--audit', choices=REPORTS)
    args = parser.parse_args()
    with exclusive():
        result = audit(args.audit) if args.audit else measure(args.measure)
    print(dict(mode=result['mode'], audited=bool(args.audit), metrics=result['summary']['metrics']))


if __name__ == '__main__':
    main()
