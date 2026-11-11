"""Freeze the V39 late typed candidate's original48 comparison protocol."""
import argparse
import hashlib

from scripts import accept_retailrocket_session_knn_typed_v39 as accepted
from scripts import freeze_retailrocket_session_knn_canonical_v36 as inherited
from scripts import retailrocket_session_knn_entry_v34 as common
from scripts import retailrocket_session_knn_typed_publication_v39 as typed
from scripts import run_retailrocket_session_knn_compare_v31 as prior
from scripts import run_retailrocket_session_knn_compare_v28 as entry
from scripts.retailrocket_session_knn_cost_window_v5 import LIMITS
from scripts.run_retailrocket_session_knn_gap_v7 import public_json
from scripts.run_retailrocket_session_knn_guards_v21 import _physical_frames
from scripts.run_retailrocket_session_knn_v2 import ROOT, check_gates, describe, environment, read


BASE = 'reports/stage12/retailrocket_session_knn_v40_compare_'
SPEC = BASE + 'specification_20261111.json'
SEAL = BASE + 'seal_20261111.json'
METHOD = 'scripts/freeze_retailrocket_session_knn_compare_v40.py'
PARENTS = {
    prior.SPEC: '1473ae19a439372433ffe079d2fbf8d20811558322be6fe3d168b76476311a66',
    inherited.SPEC: '4cc83800221321946c444e6729f157dbffbf07552a63b64c3c04f3030fdd6e58',
    accepted.REPORT: 'daf761c24d4d75285c0d3f9fe962ad27ed595523922f587140db62e702dabffa',
    accepted.SEAL: 'e44445b9eff575f491b9d45189804e0883a303dca8c8e92791beb3d531806012',
}
WINDOW_PREFIX = 'knn-v40-typed-real-'
BUDGET_SECONDS = 1800
REQUIREMENTS = (
    'exact-cohort-schedule-gates-and-additive-source-contract',
    'measurement-requires-sealed-entry-acceptance-and-refuses-retry',
    'same-role-entry-artificial-window-with-production-input-loader',
    'independent-typed-and-complete-scientific-publisher',
    'stopped-log-seal-release-and-read-only-audit',
    'mixed-policy-tampering-and-failed-window-refused',
)


def specification_value():
    parents = [describe(ROOT / path) for path in PARENTS]
    if any(record['sha256'] != PARENTS[record['path']] for record in parents):
        raise ValueError('Frozen parent comparison or typed acceptance changed')
    original = read(ROOT / prior.SPEC)
    preserved = read(ROOT / inherited.SPEC)['preserved']
    evidence = read(ROOT / accepted.REPORT)
    dependencies = dict(zip(('counts', 'catalog', 'config', 'model'), original['context_inputs']))
    methods = evidence['preserved_contract']['actual_methods']
    sources = common.merge_methods(preserved['current_sources'], methods)
    if (dependencies != preserved['dependencies'] or original['original_binding_sources'] != preserved['original_binding']
            or len(sources) != 2101 or len(methods) != 177
            or any(row not in methods for row in preserved['current_methods'])):
        raise ValueError('Inherited typed and original comparison identities differ')
    gates = check_gates()
    if environment() != evidence['environment'] or gates != evidence['gates']:
        raise ValueError('Accepted runtime and scientific gates required')
    return dict(status='v40_original48_typed_comparison_protocol_frozen', parents=parents,
        cohort=original['cohort'], dependencies=dependencies, original_binding=preserved['original_binding'],
        reference=original['original48_reference'], schedule=original['schedule'], decision=original['decision'],
        scope=original['scope'], gates=gates, environment=environment(), budget_seconds=BUDGET_SECONDS,
        limits=LIMITS, namespace_prefix=WINDOW_PREFIX, fingerprint_scheme=typed.s1.SCHEME,
        typed_reference_policy=typed.adapter.POLICY, typed_reference_scheme=typed.typed.SCHEME,
        retained_sources=len(sources), retained_methods=len(methods), retained_logical_bytes=sum(x['bytes'] for x in sources),
        activation=dict(reference='Fresh original R, without context reuse, in the same sequential window.',
            candidate='V39 late typed source-anchored C1-S1, with one cold build and six hits.',
            measurement='One V5 window, one worker, fourteen fresh stores, then a new independent publisher.',
            cost='Same full entry and load sampling for both arms; include cold and passive typed timings. '
                 'Comparison is of complete paths. It does not isolate the marginal effect of the typed change.',
            source='Retain the inherited closure, methods and 15 binding descriptors exactly. Append direct methods, '
                   'sealed activation and acceptance evidence. Keep full worker/publisher passes and lock-time checks.',
            publication='Require complete physical scientific bytes, accounting, order and independent typed source '
                        'reconstruction, then seal every file after all tracked writers stop.',
            once='Freeze and commit this protocol, then accept and commit the unchanged entry before measuring. '
                 'An existing real request or public result blocks another window. Audit only reads saved results.',
            runs=14, queries_per_run=48, engineering_checks=672),
        acceptance_requirements=list(REQUIREMENTS), measured_speedup=None, real_runs=0, T_plan=None)


def seal_value():
    return dict(status='v40_typed_comparison_protocol_sealed', specification=describe(ROOT / SPEC),
                method=describe(ROOT / METHOD), real_runs=0)


def specification():
    value = read(ROOT / SPEC)
    if read(ROOT / SEAL) != seal_value() or value != specification_value():
        raise ValueError('Sealed V40 comparison protocol changed')
    return value


def verify_original_reference(spec):
    cohort = spec['cohort']
    binding = read(ROOT / cohort['old_run'])['binding']['sources']
    frames = list(_physical_frames((ROOT / cohort['old_run']).parent))
    payload = b''.join(frames)
    reference = spec['reference']
    if (binding != spec['original_binding'] or len(frames) != reference['records']
            or len(payload) != reference['actual_committed_bytes']
            or hashlib.sha256(payload).hexdigest() != reference['actual_committed_payload_sha256']):
        raise ValueError('Original binding or physical 48-record reference changed')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument('--freeze', action='store_true')
    mode.add_argument('--audit', action='store_true')
    args = parser.parse_args()
    with entry.exclusive():
        if args.freeze and any((ROOT / path).exists() for path in (SPEC, SEAL)):
            raise FileExistsError('Immutable comparison protocol already exists')
        receipt, _ = common.quiet_contract(accepted.audit)
        spec = specification_value() if args.freeze else specification()
        verify_original_reference(spec)
        if args.freeze:
            public_json(ROOT / SPEC, spec, exclusive=True)
            public_json(ROOT / SEAL, seal_value(), exclusive=True)
        print(dict(status=spec['status'], original_records=spec['reference']['records'],
                   retained_sources=spec['retained_sources'], typed_acceptance_tests=receipt['tests_run'], real_runs=0))


if __name__ == '__main__':
    main()
