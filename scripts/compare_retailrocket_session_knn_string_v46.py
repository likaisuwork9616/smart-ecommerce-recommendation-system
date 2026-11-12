"""Pair the V39 decoder and V46 string candidate without internal timing."""
import argparse
from pathlib import Path
from time import perf_counter_ns

from scripts import diagnose_retailrocket_session_knn_string_v45 as prior
from scripts import retailrocket_session_knn_typed_string_v46 as candidate
from scripts.diagnose_retailrocket_session_knn_reference_v42 import _distribution, _duration
from scripts.run_retailrocket_session_knn_compare_v28 import exclusive
from scripts.run_retailrocket_session_knn_gap_v7 import public_json
from scripts.run_retailrocket_session_knn_v2 import ROOT, describe, read


REPORT = 'reports/stage12/retailrocket_session_knn_v46_string_model_20261112.json'
V45_SHA = '14eb51e111c6ded49c242a602187ea884361ecd3181ab45ab1632dc60e088517'
DECODERS = {'original': candidate.original._decode, 'candidate': candidate.decode}
ORDERS = (('original', 'candidate'), ('candidate', 'original')) * 4
SCOPE = dict(decode_replays=18, query_runs=0, fits=0, reserved_test='locked')


def inputs():
    predecessor = describe(ROOT / prior.REPORTS['model'])
    if predecessor['sha256'] != V45_SHA:
        raise ValueError('Expected the sealed V45 model report')
    previous = read(ROOT / prior.REPORTS['model'])
    bound, source, _ = prior.inputs('model')
    if previous['evidence'] != bound:
        raise ValueError('Exact V45 model canonical source required')
    evidence = dict(predecessor=predecessor, V45_inputs=bound,
                    methods=[describe(Path(__file__)), describe(Path(candidate.__file__))])
    return evidence, source


def replay(source, mode):
    decode = DECODERS[mode]
    start = perf_counter_ns()
    decoded = decode(source)
    end = perf_counter_ns()
    return dict(mode=mode, interval=[start, end]), decoded


def summarize(warmups, pairs):
    if ([sample['mode'] for sample in warmups] != list(DECODERS)
            or [tuple(sample['mode'] for sample in pair) for pair in pairs] != list(ORDERS)):
        raise ValueError('Expected two warmups and eight alternating pairs')
    samples = [*warmups, *(sample for pair in pairs for sample in pair)]
    if (any(_duration(sample['interval']) <= 0 for sample in samples)
            or any(left['interval'][1] > right['interval'][0] for left, right in zip(samples, samples[1:]))):
        raise ValueError('Expected positive nonoverlapping decode intervals')
    rows = []
    for order, pair in zip(ORDERS, pairs):
        elapsed = {sample['mode']: _duration(sample['interval']) for sample in pair}
        original_ns = elapsed['original']
        saving = original_ns - elapsed['candidate']
        rows.append(dict(first=order[0], original_ns=original_ns, candidate_ns=elapsed['candidate'],
                         saving_ns=saving, saving_percent=100 * saving / original_ns))
    metrics = {key: _distribution([row[key] for row in rows])
               for key in ('original_ns', 'candidate_ns', 'saving_ns', 'saving_percent')}
    return dict(pairs=rows, metrics=metrics, faster_pairs=sum(row['saving_ns'] > 0 for row in rows),
        saving_by_first={mode: _distribution([row['saving_ns'] for row in rows if row['first'] == mode])
                         for mode in DECODERS})


def measure():
    path = ROOT / REPORT
    if path.exists():
        raise FileExistsError('Immutable V46 model report already exists')
    evidence, source = inputs()
    original_warmup, expected = replay(source, 'original')
    prior.verify_tree(expected, evidence['V45_inputs'])

    def run(mode):
        sample, actual = replay(source, mode)
        if actual != expected:
            raise ValueError('Complete decoded tuple tree or encoded depth differs')
        return sample

    warmups = [original_warmup, run('candidate')]
    pairs = []
    for index, order in enumerate(ORDERS, start=1):
        pairs.append([run(mode) for mode in order])
        print(f'Completed full decoder pair {index}/{len(ORDERS)}', flush=True)
    if (evidence, source) != inputs():
        raise ValueError('Bound source or methods changed during comparison')
    report = dict(evidence=evidence, warmups=warmups, pairs=pairs, summary=summarize(warmups, pairs),
                  scope=SCOPE, verified_trees=SCOPE['decode_replays'])
    public_json(path, report, exclusive=True)
    return report


def audit():
    report = read(ROOT / REPORT)
    evidence, source = inputs()
    expected = DECODERS['original'](source)
    prior.verify_tree(expected, evidence['V45_inputs'])
    if (report['evidence'] != evidence or report['scope'] != SCOPE
            or report['verified_trees'] != SCOPE['decode_replays']
            or DECODERS['candidate'](source) != expected
            or report['summary'] != summarize(report['warmups'], report['pairs'])):
        raise ValueError('Saved timings or exact decoder comparison differ')
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    actions = parser.add_mutually_exclusive_group(required=True)
    actions.add_argument('--measure', action='store_true')
    actions.add_argument('--audit', action='store_true')
    args = parser.parse_args()
    with exclusive():
        report = audit() if args.audit else measure()
    print(dict(audited=args.audit, verified_trees=report['verified_trees'], summary=report['summary']))


if __name__ == '__main__':
    main()
