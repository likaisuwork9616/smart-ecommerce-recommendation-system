"""Seal the same-window comparison of original C1-S1 and V39 typed C1-S1."""
import argparse

from scripts import run_retailrocket_session_knn_compare_v40 as prior
from scripts.run_retailrocket_session_knn_v2 import ROOT, describe, read


BASE = 'reports/stage12/retailrocket_session_knn_v41_compare_'
SPEC = BASE + 'specification_20261111.json'
SEAL = BASE + 'seal_20261111.json'
METHOD = 'scripts/freeze_retailrocket_session_knn_compare_v41.py'
WINDOW_PREFIX = 'knn-v41-typed-real-'
PARENT_SHA = '28851e666fd7b7b0bbc87ae5bdf3040b72f2df380106eae85058169702cd7abd'
ARMS = {'S': 'original C1-S1', 'T': 'V39 late typed C1-S1'}
SCHEDULE = [dict(label='cold_' + arm, mode=arm) for arm in ARMS] + [
    dict(label=f'pair_{pair}_{arm}', mode=arm) for pair in range(1, 7) for arm in ('TS' if pair % 2 else 'ST')]
REQUIREMENTS = (
    'exact-original-cohort-schedule-equal-closure-and-methods',
    'two-isolated-cold-pools-and-six-hits-per-arm',
    'original-late-canonical-and-typed-passive-timing',
    'independent-typed-snapshot-scientific-and-stop-audit',
    'cold-inclusive-and-paired-arithmetic-from-raw-evidence',
    'preflight-activation-and-no-repeat-or-artificial-mixing',
)
verify_original_reference = prior.frozen.verify_original_reference


def specification_value():
    original = prior.frozen.specification()
    previous = describe(ROOT / prior.REPORT)
    if previous['sha256'] != PARENT_SHA:
        raise ValueError('Original48 predecessor report changed')
    sources, metadata = prior.source_contract()
    evidence = read(ROOT / prior.REPORT)
    if (evidence['reference']['records'] != original['reference']['records']
            or evidence['reference']['actual_committed_payload_sha256'] != original['reference']['actual_committed_payload_sha256']
            or len(sources) != evidence['sources']['descriptors']
            or len(metadata['context']['methods']) != evidence['sources']['methods']):
        raise ValueError('Original cohort or source scope differs from the prior real window')
    fields = ('cohort', 'dependencies', 'original_binding', 'reference', 'scope', 'gates', 'environment',
              'budget_seconds', 'limits', 'fingerprint_scheme', 'typed_reference_policy', 'typed_reference_scheme')
    return dict({key: original[key] for key in fields}, status='v41_direct_typed_comparison_protocol_frozen',
        arms=ARMS, schedule=SCHEDULE, namespace_prefix=WINDOW_PREFIX, predecessor=previous,
        retained_sources=len(sources), retained_methods=len(metadata['context']['methods']),
        requirements=list(REQUIREMENTS), real_runs=0, T_plan=None,
        activation=dict(runs=14, queries_per_run=48, engineering_checks=672,
            worker='One sequential worker, separate loader roots and separate original/typed pools, two cold runs then six alternating pairs.',
            costs='Same full entry observers. Clear the unrelated metric memoization at each entry boundary before timing. '
                  'Count all seven entries on each arm, including the first cold entry.',
            late='Use the unchanged original canonical implementation in S. Only add passive timings at its two original late calls. '
                 'T uses its already accepted reference-build and complete late timings. Compare the sum of replaced work separately from whole-cold time.',
            attribution='Cold runs are S then T in one worker. One cold per arm and shared host conditions leave order and noise uncertainty. '
                        'No adoption threshold or change of project defaults is part of this diagnostic.',
            evidence='Retain the V40 closure and binding, append new method/acceptance sources, verify one shared full closure per role boundary. '
                     'After the worker exits, one publisher verifies both snapshot sequences, original scientific frames and the typed reference authority.',
            gate='Commit this specification, then accept and commit the unchanged entry before the real window. '
                 'One real request. Saved evidence can be audited without rerunning queries.'))


def seal_value():
    return dict(status='v41_direct_typed_comparison_protocol_sealed', specification=describe(ROOT / SPEC),
                method=describe(ROOT / METHOD), real_runs=0)


def specification():
    value = read(ROOT / SPEC)
    if read(ROOT / SEAL) != seal_value() or value != specification_value():
        raise ValueError('Sealed C1-S1 / V39 comparison protocol changed')
    return value


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument('--freeze', action='store_true')
    mode.add_argument('--audit', action='store_true')
    args = parser.parse_args()
    with prior.entry.exclusive():
        if args.freeze and any((ROOT / path).exists() for path in (SPEC, SEAL)):
            raise FileExistsError('Immutable direct comparison protocol already exists')
        spec = specification_value() if args.freeze else specification()
        verify_original_reference(spec)
        if args.freeze:
            prior.public_json(ROOT / SPEC, spec, exclusive=True)
            prior.public_json(ROOT / SEAL, seal_value(), exclusive=True)
        print(dict(status=spec['status'], original_records=spec['reference']['records'],
                   retained_sources=spec['retained_sources'], retained_methods=spec['retained_methods'], real_runs=0))


if __name__ == '__main__':
    main()
