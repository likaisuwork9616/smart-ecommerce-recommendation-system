"""Guarded one-shot Stage 6 retrospective RFM build and read-only verification."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if __package__ in (None, ''):
    sys.path.insert(0, str(ROOT))
from scripts import audit_rfm_feasibility as base
from scripts import freeze_rfm_dataset_spec as frozen
from scripts import rfm_dataset_builder as builder
from scripts import rfm_dataset_artifacts as artifacts

CODE = 'scripts/build_rfm_dataset.py'
TEST = 'tests/test_build_rfm_dataset.py'
SPEC = 'reports/stage6/rfm_dataset_build_specification.json'
OUTPUT = 'reports/stage6/rfm_dataset_build.json'
PRIVATE = '.runtime/stage6_rfm_dataset_v1'
CONTROL = '.runtime/stage6_rfm_dataset_build_v1'
GUARD = CONTROL + '/output_guard.json'
IMPLEMENTATION = (
    'scripts/rfm_dataset_builder.py', 'tests/test_rfm_dataset_builder.py',
    'scripts/rfm_dataset_artifacts.py', 'tests/test_rfm_dataset_artifacts.py',
    CODE, TEST,
)
ACCEPTANCE_FLAGS = ('all_values_read_back', 'canonical_ids',
                    'schema_types_nulls', 'customer_order_semantics')
_same = artifacts._same


def policy():
    return {
        'scope': 'one_shot_retrospective_snapshot_RFM_dataset_no_segmentation',
        'frozen_contract': frozen.SPEC,
        'source_guard': 'complete_contract_and_execution_specification_equality_before_after_reads_and_writes',
        'private_output': PRIVATE + '/', 'private_control': CONTROL + '/',
        'build': 'output_control_and_public_report_must_not_exist_no_resume_or_overwrite',
        'verify': 'read_only_existing_bundle_guard_and_public_aggregate_no_source_table_rebuild',
        'approval_delivery_ledger': 'raw_parseable_times_may_be_at_or_after_T_exclusion_evidence_only_not_features',
        'measured_zero_product': 'nonnegative_valid_active_order_can_have_M_zero_empty_sum_imputation_only_for_clean_inactive',
        'operational_as_of_accepted': False, 'source_completeness_accepted': False,
        'refund_net_money_supported': False,
        'segmentation': False, 'training': False, 'dashboard': False,
        'stage4': {'status': 'pending_data', 'daily_budget': 0.1,
                   'seeds': [11, 29, 42, 73, 101]},
        'stage5': {'status': 'pending_data',
                   'H60_roles_scores_and_window_purposes_unchanged': True},
    }


def _contract(root):
    """Reconstruct the entire historical binding, not a caller-shortened list."""
    stored = base.read_json(root / frozen.SPEC)
    if not _same(frozen.specification(root), stored):
        raise ValueError('Complete frozen contract or source list differs')
    frozen.verify_sources(stored, root)
    audit = base.read_json(root / frozen.OUTPUT)
    if (not _same(audit.get('specification'), base.descriptor(root / frozen.SPEC, root))
            or not _same(audit.get('policy'), stored['policy'])):
        raise ValueError('Frozen support audit binding differs')
    return stored


def specification(root=ROOT):
    root = Path(root)
    contract = _contract(root)
    sources = [*contract['sources'], *[
        base.descriptor(root / rel, root)
        for rel in (frozen.SPEC, frozen.OUTPUT, *IMPLEMENTATION)]]
    paths = [item['path'] for item in sources]
    if len(sources) != 20 or len(paths) != len(set(paths)):
        raise ValueError('Exactly twenty distinct frozen build sources are required')
    return {'format_version': 1, 'policy': policy(),
            'dataset_contract': base.descriptor(root / frozen.SPEC, root),
            'sources': sources}


def verify_sources(spec, root=ROOT):
    root = Path(root)
    if not _same(spec, specification(root)) or not _same(base.read_json(root / SPEC), spec):
        raise ValueError('Complete build specification or source bytes differ')


def _accepted(acceptance, dataset):
    if any(acceptance.get(key) is not True for key in ACCEPTANCE_FLAGS):
        raise ValueError('Private bundle readback acceptance failed')
    rows = {'customers.csv': len(dataset['customers']),
            'order_decisions.csv': len(dataset['orders'])}
    if (not _same(acceptance.get('rows'), rows)
            or type(acceptance.get('cells_compared')) is not int
            or acceptance['cells_compared'] != sum(rows.values()) * 16):
        raise ValueError('Private bundle readback population differs')


def _support_matches(summary, root):
    previous = base.read_json(root / frozen.OUTPUT)['results']
    for key in ('history', 'window', 'window_quarantine'):
        if not _same(summary[key], previous[key]):
            raise ValueError('Built population differs from frozen support: ' + key)
    if not _same(summary['customer_states'], previous['customer_state_support_only']):
        raise ValueError('Built customer states differ from frozen support')
    if not summary['invariants'] or not all(value is True for value in summary['invariants'].values()):
        raise ValueError('Builder population, amount or clock invariant failed')


def _public_payload(dataset, acceptance, root):
    return {
        'format_version': 1,
        'specification': base.descriptor(root / SPEC, root),
        'policy': policy(),
        'status': 'retrospective_RFM_dataset_built_readback_accepted_no_segmentation',
        'results': dataset['summary'], 'acceptance': acceptance,
        'limitations': [
            'Retrospective final snapshot; not operational as-of or complete lifetime.',
            'Original ingestion, revision, refund, settlement and upstream completion evidence remain unavailable.',
            'Raw future approval/delivery timestamps in the private order ledger are exclusion evidence, not model features.',
            'No segmentation, model fit, Dashboard or new model performance conclusion.',
        ],
    }


def _preflight(root):
    if any((root / rel).exists() or (root / rel).is_symlink()
           for rel in (PRIVATE, CONTROL, OUTPUT)):
        raise ValueError('Build output, control or report already exists; use read-only --verify')


def _load_spec(root):
    proposed = specification(root)
    if not _same(base.read_json(root / SPEC), proposed):
        raise ValueError('Build specification differs; stop instead of refreezing')
    return proposed


def run(root=ROOT, *, specification_only=False, build=False, verify=False):
    root = Path(root)
    if sum((specification_only, build, verify)) != 1:
        raise ValueError('Choose exactly one of specification-only, build or verify')
    if specification_only:
        base.immutable_write(root / SPEC, specification(root))
        return {'status': 'RFM_build_entry_frozen_no_dataset_created', 'output': SPEC}
    spec = _load_spec(root)
    contract = base.read_json(root / frozen.SPEC)
    source_bindings = spec['sources']
    output = root / PRIVATE
    if build:
        _preflight(root)
        tables = base.read_tables(root)
        verify_sources(spec, root)
        dataset = builder.build_dataset(tables, contract)
        _support_matches(dataset['summary'], root)
        verify_sources(spec, root)
        acceptance = artifacts.write_bundle(dataset, contract, source_bindings, output)
        _accepted(acceptance, dataset)
        verify_sources(spec, root)
        private_guard = artifacts.bundle_guard(output)
        acceptance = artifacts.verify_bundle(output, contract, source_bindings,
                                             expected_guard=private_guard)
        _accepted(acceptance, dataset)
        if not _same(artifacts.read_bundle(output, contract, source_bindings), dataset):
            raise ValueError('Private readback differs from the complete built dataset')
        verify_sources(spec, root)
        if not _same(artifacts.bundle_guard(output), private_guard):
            raise ValueError('Private bundle changed during final readback')
        guard = {
            'format_version': 1,
            'build_specification': base.descriptor(root / SPEC, root),
            'dataset_contract': spec['dataset_contract'],
            'source_bindings': source_bindings,
            'private_bundle_guard': private_guard,
            'readback_acceptance': acceptance,
        }
        base.immutable_write(root / GUARD, guard)
        base.immutable_write(root / OUTPUT, _public_payload(dataset, acceptance, root))
    else:
        guard = base.read_json(root / GUARD)
        expected_keys = {'format_version', 'build_specification', 'dataset_contract',
                         'source_bindings', 'private_bundle_guard', 'readback_acceptance'}
        if (type(guard) is not dict or set(guard) != expected_keys
                or not _same(guard['format_version'], 1)
                or not _same(guard['build_specification'], base.descriptor(root / SPEC, root))
                or not _same(guard['dataset_contract'], spec['dataset_contract'])
                or not _same(guard['source_bindings'], source_bindings)):
            raise ValueError('Private output guard binding differs')
        acceptance = artifacts.verify_bundle(output, contract, source_bindings,
                                             expected_guard=guard['private_bundle_guard'])
        dataset = artifacts.read_bundle(output, contract, source_bindings)
        _accepted(acceptance, dataset)
        if not _same(guard['readback_acceptance'], acceptance):
            raise ValueError('Private guard acceptance differs')
        _support_matches(dataset['summary'], root)
        if not _same(base.read_json(root / OUTPUT), _public_payload(dataset, acceptance, root)):
            raise ValueError('Public aggregate report differs from private readback')
        verify_sources(spec, root)
    return {'status': 'RFM_dataset_built_accepted' if build else 'RFM_dataset_verified_read_only',
            'output': OUTPUT, 'private_output': PRIVATE + '/',
            'customers': len(dataset['customers']), 'order_decisions': len(dataset['orders'])}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    actions = parser.add_mutually_exclusive_group(required=True)
    actions.add_argument('--specification-only', action='store_true')
    actions.add_argument('--build', action='store_true')
    actions.add_argument('--verify', action='store_true')
    args = parser.parse_args(argv)
    print(json.dumps(run(**vars(args)), ensure_ascii=False, allow_nan=False))


if __name__ == '__main__':
    main()
