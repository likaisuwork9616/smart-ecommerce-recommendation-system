"""Bind a fully verified v2 dataset/G2 reference without changing prior assets."""
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if __package__ in (None, ''):
    sys.path.insert(0, str(ROOT))
from scripts import rebuild_rfm_v2 as v2

base, typed, require = v2.base, v2.typed, v2.require
CODE = 'scripts/rfm_g3_sources.py'
RECEIPT = '.runtime/stage6_rfm_g3_v2_input_verification.json'


def snapshot(root=ROOT):
    root = Path(root)
    spec = v2._prepared(root)
    require(not (root / v2.FAILURE).exists(), 'Prior v2 failure prevents G3')
    expected = {'specification': base.descriptor(root / v2.SPEC, root),
                'input_guard': base.descriptor(root / v2.INPUT, root),
                'dataset': typed.bundle_guard(root / v2.RUN / 'dataset'),
                'description': base.descriptor(root / v2.RUN / 'description.json', root),
                'candidate': v2.output.bundle_guard(root / v2.RUN / 'candidate'),
                'report': base.descriptor(root / v2.REPORT, root)}
    require(typed._same(base.read_json(root / v2.GUARD), expected), 'Prior v2 guard differs')
    report = base.read_json(root / v2.REPORT)
    require(report['G2']['aggregate']['gate_status']['G2'] == 'passed'
            and report['execution'] == {'dataset_builder_calls': 1, 'G1_core_calls': 1,
                'G2_core_calls': 1, 'model_fits': 0, 'G3_executed': False}, 'Completed G2 reference required')
    return {'public_sources': [*spec['sources'], *[base.descriptor(root / p, root)
                for p in (v2.SPEC, v2.REPORT, CODE)]],
            'private_state': expected,
            'output_guard': base.descriptor(root / v2.GUARD, root)}


def verify_v2(root=ROOT):
    root = Path(root)
    require(not (root / RECEIPT).exists(), 'Do not overwrite the actual v2 verification receipt')
    before = snapshot(root)
    result = v2.verify(root)
    require(typed._same(before, snapshot(root)), 'Prior sources changed during full verification')
    receipt = {'status': 'v2_full_read_only_verification_passed', 'source_snapshot': before,
               'verification': result, 'builder_G1_G2_reexecuted': False}
    base.immutable_write(root / RECEIPT, receipt)
    return result


def accepted_snapshot(root=ROOT):
    root = Path(root)
    current = snapshot(root)
    receipt = base.read_json(root / RECEIPT)
    require(receipt['status'] == 'v2_full_read_only_verification_passed'
            and receipt['builder_G1_G2_reexecuted'] is False
            and receipt['verification']['G2'] == 'passed'
            and typed._same(current, receipt['source_snapshot']), 'Full v2 verification evidence differs')
    return current


def load_reference(root=ROOT):
    root = Path(root)
    before = accepted_snapshot(root)
    spec = base.read_json(root / v2.SPEC)
    dataset = typed.read_bundle(root / v2.RUN / 'dataset', base.read_json(root / v2.contract.SPEC), spec['sources'])
    provenance = {'execution_specification': base.descriptor(root / v2.SPEC, root), 'source_bindings': spec['sources']}
    reference = v2.output.read_outputs(root / v2.RUN / 'candidate', provenance)
    rows = [r for r in dataset['customers'] if r['activity_state'] == 'active_complete']
    require([r['customer_unique_id'] for r in rows] == sorted(reference['assignments_by_id']),
            'Complete active customer IDs differ from frozen G2')
    require(typed._same(before, accepted_snapshot(root)), 'Prior source changed during G3 loading')
    return rows, {k: reference[k] for k in ('aggregate', 'assignments_by_id')}, base.read_json(root / v2.EVALUATION)


if __name__ == '__main__':
    import json
    print(json.dumps(verify_v2(), ensure_ascii=False))
