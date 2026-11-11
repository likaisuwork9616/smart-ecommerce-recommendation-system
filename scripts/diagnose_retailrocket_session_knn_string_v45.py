"""Split the V39 string scan using the exact V44 sample windows."""
import argparse
import inspect
from pathlib import Path
from statistics import median
from time import perf_counter_ns

from scripts import diagnose_retailrocket_session_knn_decode_v44 as prior
from scripts.diagnose_retailrocket_session_knn_reference_v42 import _distribution, _duration
from scripts.run_retailrocket_session_knn_compare_v28 import exclusive
from scripts.run_retailrocket_session_knn_gap_v7 import public_json
from scripts.run_retailrocket_session_knn_v2 import ROOT, describe, read


typed = prior.prior.typed
REPORTS = {mode: f'reports/stage12/retailrocket_session_knn_v45_string_{mode}_20261111.json'
           for mode in prior.REPORTS}
V44_SHA = {
    'calibration': '60ea60683b9a0d118d8d803e009b5d5f003eeed3eb11237785ac23ae0246ae5f',
    'model': '795f452f18bdb985fc6711e108e52accaab541a3279febbd968be3eb8d71ce86',
}
PHASES = ('character_check', 'scanstring', 'return_tail')
REPLAYS = 2 + 2 * len(prior.SEEDS)


def split_string():
    """Insert timestamps around the same scanstring call in a private copy."""
    source = inspect.getsource(typed._string)
    call = '            value,end=json.decoder.scanstring(text,start+1,True)\n'
    result = '            return value,end\n'
    if source.count(call) != 1 or source.count(result) != 1:
        raise ValueError('Expected the original scanstring call and return')
    source = source.replace(call, '            checked = _clock()\n' + call + '            scanned = _clock()\n')
    source = source.replace(result, '            return value,end,checked,scanned\n')
    namespace = dict(typed._string.__globals__, _clock=perf_counter_ns)
    exec(compile(source, __file__, 'exec'), namespace)
    return namespace['_string']


class StringSampler(prior.Sampler):
    def __init__(self, windows, length):
        super().__init__(windows, length)
        self.split_string = split_string()

    tuple = staticmethod(tuple)

    def string(self, text, index):
        start = perf_counter_ns()
        value, end, checked, scanned = self.split_string(text, index)
        finished = perf_counter_ns()
        record = self.records[self.index]
        record[0] += 1
        record[1] += checked - start
        record[2] += scanned - checked
        record[3] += finished - scanned
        return value, end


def replay(source, length, seed):
    if seed is None:
        return prior.replay(source, length)
    sampler = StringSampler(prior.plan(length, seed), length)
    decoder = prior.sampled_decoder(sampler)
    start = perf_counter_ns()
    decoded = decoder(source)
    end = perf_counter_ns()
    return dict(seed=seed, interval=[start, end], windows=sampler.records), decoded


def phases(sample, length, expected):
    windows = prior.plan(length, sample['seed'])
    records = sample['windows']
    if (len(records) != len(windows) or any(len(row) != 4 or any(type(x) is not int or x < 0 for x in row)
            or (row[0] == 0 and any(row[1:])) for row in records)
            or [row[0] for row in records] != expected):
        raise ValueError('Invalid split timing or sampled string counts differ from V44')
    if sum(sum(row[1:]) for row in records) > _duration(sample['interval']):
        raise ValueError('Sampled string intervals exceed the decoder interval')
    estimates = [sum(window[2] * row[index] for window, row in zip(windows, records)) for index in range(4)]
    return estimates[0], dict(zip(PHASES, estimates[1:])), sum(expected)


def summarize(warmups, pairs, length, expected, clock_floor):
    if ([row['seed'] for row in warmups] != [None, prior.WARMUP_SEED] or len(pairs) != len(prior.SEEDS)
            or type(clock_floor) is not int or clock_floor < 0):
        raise ValueError('Unexpected warmups, pair count or clock interval')
    phases(warmups[1], length, expected[prior.WARMUP_SEED])
    replays = [*warmups, *(row for pair in pairs for row in pair)]
    if any(first['interval'][1] > second['interval'][0] for first, second in zip(replays, replays[1:])):
        raise ValueError('Replay intervals overlap')
    rows = []
    for index, (seed, pair) in enumerate(zip(prior.SEEDS, pairs)):
        order = [None, seed] if index % 2 == 0 else [seed, None]
        if [row['seed'] for row in pair] != order:
            raise ValueError('Unexpected seed or alternating pair order')
        plain, sampled = pair if index % 2 == 0 else pair[::-1]
        plain_ns, sampled_ns = (_duration(row['interval']) for row in (plain, sampled))
        if min(plain_ns, sampled_ns) <= 0:
            raise ValueError('Positive decoder times required')
        calls, costs, timed_calls = phases(sampled, length, expected[seed])
        string_ns = sum(costs.values())
        if string_ns <= 0:
            raise ValueError('Positive sampled string estimate required')
        check, scan = costs['character_check'], costs['scanstring']
        rows.append(dict(plain_ns=plain_ns, sampled_ns=sampled_ns, sampled_calls=timed_calls, estimated_calls=calls,
            overhead_ns=sampled_ns - plain_ns, overhead_percent=100 * (sampled_ns - plain_ns) / plain_ns,
            string_ns=string_ns, phase_ns=costs, phase_percent={name: 100 * value / string_ns for name, value in costs.items()},
            check_minus_scan_ns=check - scan,
            check_minus_scan_charging_clock_to_check_ns=max(0, check - calls * clock_floor) - scan))
    keys = ('plain_ns', 'sampled_ns', 'overhead_ns', 'overhead_percent', 'sampled_calls', 'estimated_calls',
            'string_ns', 'check_minus_scan_ns', 'check_minus_scan_charging_clock_to_check_ns')
    return dict(pairs=rows, metrics={key: _distribution([row[key] for row in rows]) for key in keys},
        phase_ns={name: _distribution([row['phase_ns'][name] for row in rows]) for name in PHASES},
        phase_percent={name: _distribution([row['phase_percent'][name] for row in rows]) for name in PHASES},
        check_slower_pairs=sum(row['check_minus_scan_ns'] > 0 for row in rows),
        check_slower_charging_clock_to_check_pairs=sum(row['check_minus_scan_charging_clock_to_check_ns'] > 0 for row in rows))


def inputs(mode):
    predecessor = describe(ROOT / prior.REPORTS[mode])
    if predecessor['sha256'] != V44_SHA[mode]:
        raise ValueError('V44 report differs')
    v44 = read(ROOT / prior.REPORTS[mode])
    bound, source = prior.inputs(mode)
    if v44['evidence'] != bound or v44['length'] != len(source.decode('utf-8')):
        raise ValueError('Exact V44 input and parser evidence required')
    old_replays = [*v44['warmups'], *(row for pair in v44['pairs'] for row in pair)]
    counts = {row['seed']: [window[0] for window in row['windows']] for row in old_replays if row['seed'] is not None}
    evidence = dict(method=describe(Path(__file__)), predecessor=predecessor, V44_inputs=bound,
                    length=v44['length'], original_calls=v44['original_calls'])
    if mode == 'model':
        audit('calibration')
        evidence['calibration'] = describe(ROOT / REPORTS['calibration'])
    return evidence, source, counts


def verify_tree(tree, evidence):
    if prior.verify_tree(tree, evidence['V44_inputs']) != evidence['original_calls']:
        raise ValueError('Original decoder call counts differ from V44')


def measure(mode):
    path = ROOT / REPORTS[mode]
    if path.exists():
        raise FileExistsError('Immutable string timing report already exists')
    evidence, source, counts = inputs(mode)
    length = evidence['length']
    clock_intervals = []
    for _ in range(4097):
        start = perf_counter_ns()
        elapsed = perf_counter_ns() - start
        clock_intervals.append(elapsed)
    clock_floor = int(median(clock_intervals))
    plain_warmup, expected = replay(source, length, None)
    verify_tree(expected, evidence)

    def run(seed):
        sample, decoded = replay(source, length, seed)
        if decoded != expected:
            raise ValueError('Complete decoded tree or encoded depth differs')
        return sample

    warmups = [plain_warmup, run(prior.WARMUP_SEED)]
    pairs = []
    for index, seed in enumerate(prior.SEEDS):
        order = (None, seed) if index % 2 == 0 else (seed, None)
        pairs.append([run(value) for value in order])
        print(f'Completed {mode} string timing pair {index + 1}/{len(prior.SEEDS)}', flush=True)
    if (evidence, source, counts) != inputs(mode):
        raise ValueError('Bound inputs changed during timing')
    result = dict(mode=mode, evidence=evidence, warmups=warmups, pairs=pairs, verified_trees=REPLAYS,
        clock_floor_ns=clock_floor, summary=summarize(warmups, pairs, length, counts, clock_floor), query_runs=0, fits=0)
    public_json(path, result, exclusive=True)
    return result


def audit(mode):
    result = read(ROOT / REPORTS[mode])
    evidence, source, counts = inputs(mode)
    verify_tree(typed._decode(source), evidence)
    summary = summarize(result['warmups'], result['pairs'], evidence['length'], counts, result['clock_floor_ns'])
    if (result['mode'] != mode or result['evidence'] != evidence or result['verified_trees'] != REPLAYS
            or result['query_runs'] != 0 or result['fits'] != 0 or result['summary'] != summary):
        raise ValueError('Saved split timing or bound evidence differs')
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    action = parser.add_mutually_exclusive_group(required=True)
    action.add_argument('--measure', choices=REPORTS)
    action.add_argument('--audit', choices=REPORTS)
    args = parser.parse_args()
    with exclusive():
        result = audit(args.audit) if args.audit else measure(args.measure)
    print(dict(mode=result['mode'], audited=bool(args.audit), metrics=result['summary']['metrics'],
               phase_ns=result['summary']['phase_ns']))


if __name__ == '__main__':
    main()
