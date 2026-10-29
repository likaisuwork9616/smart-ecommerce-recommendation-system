"""One-shot G3 execution on verified RFM v2 and read-only complete readback."""
from pathlib import Path
import sys
import io
import json
import time
import unittest
from importlib.metadata import version

ROOT = Path(__file__).resolve().parents[1]
if __package__ in (None, ''):
    sys.path.insert(0, str(ROOT))
from scripts import rfm_g3_sources as sources
from scripts import rfm_g3 as core
from scripts import rfm_g3_outputs as outputs

base, typed, require = sources.base, sources.typed, sources.require
SPEC = 'reports/stage6/rfm_g3_v2_specification.json'
REPORT = 'reports/stage6/rfm_g3_v2.json'
PRIVATE = '.runtime/stage6_rfm_g3_v2'
INPUT, GUARD, FAILURE = [PRIVATE + '/' + p for p in ('input_guard.json', 'output_guard.json', 'failure.json')]
EXECUTION = PRIVATE + '/execution'
BUNDLE = EXECUTION + '/sensitivity'
LOG = '.runtime/stage6_rfm_g3_v2_tests.log'
NEW = ('scripts/rfm_g3.py', 'scripts/rfm_g3_outputs.py', 'scripts/run_rfm_g3.py',
       'tests/test_rfm_g3.py', 'tests/test_run_rfm_g3.py')
MODULES = ('tests.test_rfm_g3', 'tests.test_run_rfm_g3')


def policy():
    return {'version': 'G3_on_RFM_v2', 'prior': sources.v2.REPORT,
        'original_method': sources.v2.EVALUATION, 'actual_private_namespace': PRIVATE,
        'seeds': list(core.SEEDS), 'sampling': 'Generator(PCG64(seed)).choice(n,size=(4*n)//5,replace=False)',
        'reference': 'same_all_active_complete_IDs_canonical_ascending_for_all_five_seeds',
        'cuts': 'sample_only_exact_integer_P20_40_60_80_deduplicate_drop_ge_sample_max_ties_intact',
        'assignment': 'sample_cutpoints_applied_to_full_reference_R_direction_uses_actual_levels',
        'support_floor': 'max(100,(n+199)//200)_full_reference_denominator',
        'gates': {'levels': 'each_axis_2_to_5_and_same_as_reference_no_empty_bins',
                  'minimum_axis_agreement': 0.90, 'minimum_joint_ARI': 0.80,
                  'joint_degeneracy': 'single_group_or_all_singletons_fails',
                  'all_five_required': True},
        'different_levels_agreement': 'null_not_comparable_and_gate_fails',
        'small_cells': 'flag_every_reference_and_seed_joint_cell_below_floor_no_merge_no_stable_cell_claim',
        'readback': 'independent_exact_sample_membership_rank_assignment_support_and_rational_contingency_ARI',
        'ARI_readback_absolute_tolerance': 1e-12,
        'completion': 'private_bundle_public_aggregate_external_guard_and_full_readback_no_failure',
        'failure': 'retain_evidence_no_overwrite_retry_reseed_recut_or_threshold_change',
        'temporal': 'pending_data', 'business': 'pending_data',
        'training': False, 'dashboard': False, 'stage4_daily_budget': 0.1, 'stage5': 'pending_data'}


def environment(root):
    lock = (root / 'requirements-lock.txt').read_text(encoding='utf-8')
    versions = {name: version(name) for name in ('numpy', 'scikit-learn')}
    require(all(name + '==' + val in lock.splitlines() for name, val in versions.items()),
            'Installed numerical libraries differ from frozen lock')
    return {'python': sys.version.split()[0], **versions}


def state(root):
    prior = sources.accepted_snapshot(root)
    public = [*prior['public_sources'], *[base.descriptor(root / p, root) for p in NEW]]
    require(len(public) == len({x['path'] for x in public}), 'Duplicate G3 source path')
    return {'sources': public, 'prior_private_evidence': prior,
            'actual_input_verification_receipt': base.descriptor(root / sources.RECEIPT, root),
            'environment': environment(root)}


def prepare(root=ROOT):
    root = Path(root)
    require(all(not (root / p).exists() and not (root / p).is_symlink()
                for p in (SPEC, REPORT, PRIVATE, LOG)), 'Existing G3 state blocks a new prepare')
    before = state(root)
    suite = unittest.defaultTestLoader.loadTestsFromNames(MODULES)
    ids = sorted(sources.v2._test_ids(suite))
    stream = io.StringIO()
    start = time.perf_counter()
    result = unittest.TextTestRunner(stream=stream, verbosity=2).run(suite)
    elapsed = time.perf_counter() - start
    require(typed._same(before, state(root)), 'G3 sources changed during tests')
    (root / LOG).parent.mkdir(parents=True, exist_ok=True)
    with (root / LOG).open('x', encoding='utf-8', newline='\n') as log: log.write(stream.getvalue())
    require(result.wasSuccessful() and not result.skipped and result.testsRun == len(ids),
            'G3 synthetic verification failed; preserve log')
    tests = {'tests_run': result.testsRun, 'elapsed_seconds': elapsed, 'errors': len(result.errors),
             'failures': len(result.failures), 'skipped': len(result.skipped), 'test_ids': ids}
    spec = {'format_version': 1, 'policy': policy(), 'sources': before['sources'],
            'environment': before['environment'], 'synthetic_verification': tests}
    base.immutable_write(root / SPEC, spec)
    base.immutable_write(root / INPUT, {'specification': base.descriptor(root / SPEC, root),
        'test_log': base.descriptor(root / LOG, root), 'state': before})
    return {'status': 'G3_prepared_synthetic_passed_no_real_sensitivity', 'tests_run': result.testsRun}


def prepared(root):
    current = state(root)
    spec = base.read_json(root / SPEC)
    guard = base.read_json(root / INPUT)
    expected = {'specification': base.descriptor(root / SPEC, root),
                'test_log': base.descriptor(root / LOG, root), 'state': current}
    require(typed._same(spec['policy'], policy()) and typed._same(spec['sources'], current['sources'])
            and typed._same(spec['environment'], current['environment'])
            and typed._same(guard, expected), 'Frozen G3 preparation differs')
    return spec


def provenance(root, spec):
    return {'specification': base.descriptor(root / SPEC, root), 'sources': spec['sources']}


def payload(root, spec, result, receipt):
    return {'format_version': 1, 'version': 'G3_on_RFM_v2',
            'status': 'five_seed_same_snapshot_sensitivity_completed_readback_accepted',
            'specification': base.descriptor(root / SPEC, root), 'policy': policy(),
            'environment': spec['environment'], 'synthetic_verification': spec['synthetic_verification'],
            'execution': {'G3_core_calls': 1, 'seeds_evaluated': 5, 'G2_core_calls': 0,
                          'dataset_rebuilt': False, 'model_fits': 0},
            'aggregate': result['aggregate'], 'readback_acceptance': receipt}


def run(root=ROOT):
    root = Path(root)
    spec = prepared(root)
    require({p.name for p in (root / PRIVATE).iterdir()} == {'input_guard.json'}
            and not (root / REPORT).exists(), 'Existing or partial G3 execution cannot be replayed')
    (root / EXECUTION).mkdir()
    try:
        rows, reference, evaluation = sources.load_reference(root)
        prepared(root)
        result = core.evaluate(rows, reference, evaluation)
        receipt = outputs.write_bundle(root / BUNDLE, rows, reference, evaluation, result, provenance(root, spec))
        prepared(root)
        base.immutable_write(root / REPORT, payload(root, spec, result, receipt))
        guard = {'specification': base.descriptor(root / SPEC, root),
                 'input_guard': base.descriptor(root / INPUT, root),
                 'bundle': outputs.bundle_guard(root / BUNDLE), 'report': base.descriptor(root / REPORT, root)}
        base.immutable_write(root / GUARD, guard)
        return verify(root)
    except Exception as exc:
        base.immutable_write(root / FAILURE, {'status': 'technical_failure_no_replay', 'exception_type': type(exc).__name__})
        raise


def verify(root=ROOT):
    root = Path(root)
    spec = prepared(root)
    require(not (root / FAILURE).exists(), 'G3 failure blocks acceptance')
    guard_version = base.descriptor(root / GUARD, root)
    guard = base.read_json(root / GUARD)
    def actual():
        return {'specification': base.descriptor(root / SPEC, root),
                'input_guard': base.descriptor(root / INPUT, root),
                'bundle': outputs.bundle_guard(root / BUNDLE), 'report': base.descriptor(root / REPORT, root)}
    require(typed._same(guard, actual()), 'G3 output guard differs')
    rows, reference, evaluation = sources.load_reference(root)
    result = outputs.read_bundle(root / BUNDLE, provenance(root, spec))
    receipt = outputs.verify_result(rows, reference, evaluation, result)
    require((root / REPORT).read_bytes() == typed.json_bytes(payload(root, spec, result, receipt)), 'G3 public report differs')
    prepared(root)
    require(typed._same(guard, actual()) and typed._same(guard_version, base.descriptor(root / GUARD, root))
            and not (root / FAILURE).exists(), 'G3 evidence changed during verification')
    return {'status': 'G3_verified_read_only_without_core_reexecution',
            'G3': result['aggregate']['gate_status']['G3'], 'reference_n': len(rows),
            'minimum_joint_ARI': result['aggregate']['minimum_joint_ARI'], 'report': REPORT}


if __name__ == '__main__':
    import argparse
    parser = argparse.ArgumentParser(description=__doc__)
    group = parser.add_mutually_exclusive_group(required=True)
    for name in ('prepare', 'run', 'verify'): group.add_argument('--' + name, action='store_true')
    args = parser.parse_args()
    result = prepare() if args.prepare else run() if args.run else verify()
    print(json.dumps(result, ensure_ascii=False, allow_nan=False))
