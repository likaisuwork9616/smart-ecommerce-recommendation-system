"""Verify synthetic RFM-description tests and accepted metadata; no real descriptor entry."""
from __future__ import annotations

import argparse
import hashlib
import json
import math
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if __package__ in (None, ''):
    sys.path.insert(0, str(ROOT))
from scripts import freeze_rfm_evaluation_spec as prior

base, artifacts, same = prior.base, prior.artifacts, prior.same
CODE = 'scripts/verify_rfm_description.py'
TEST = 'tests/test_verify_rfm_description.py'
CORE = 'scripts/rfm_description.py'
CORE_TEST = 'tests/test_rfm_description.py'
SPEC = 'reports/stage6/rfm_description_implementation_specification.json'
OUTPUT = 'reports/stage6/rfm_description_pipeline_verification.json'
PRIVATE = '.runtime/stage6_rfm_description_implementation_v1'
GUARD = PRIVATE + '/input_guard.json'
RECEIPT = '.runtime/stage6_rfm_description_unit.json'
MODULES = ['tests.test_rfm_description', 'tests.test_verify_rfm_description']
IMPLEMENTATION = (CORE, CORE_TEST, CODE, TEST)


def _require(condition, message):
    if condition is not True:
        raise ValueError(message)


def policy():
    return {
        'scope': 'readonly_RFM_description_implementation_synthetic_verification_only',
        'evaluation_contract': prior.SPEC,
        'real_dataset': 'metadata_and_binary_hashes_only_no_CSV_header_or_values_parsed',
        'verification': 'external_actual_two_suite_receipt_bound_to_complete_current_33_sources',
        'output': 'implementation_specification_aggregate_verification_private_guard_only',
        'no_real_description_entry': True, 'no_path_override': True,
        'cutpoint_estimation': False, 'scores_or_groups': False, 'resampling': False,
        'model_fits': 0, 'dashboard': False,
        'stage4': prior.method.policy()['stage4'], 'stage5': prior.method.policy()['stage5'],
    }


def _prior_metadata(root):
    evaluation = base.read_json(root / prior.SPEC)
    chain = prior.verify_sources(evaluation, root)
    result = chain['build_report']['results']
    expected = {
        'format_version': 1, 'specification': base.descriptor(root / prior.SPEC, root),
        'status': 'evaluation_contract_frozen_existing_dataset_bytes_verified_only',
        'metadata_checks': chain['checks'],
        'reused_accepted_population': {
            'source': prior.prior.OUTPUT,
            'customer_rows': chain['build_report']['acceptance']['rows']['customers.csv'],
            'order_decision_rows': chain['build_report']['acceptance']['rows']['order_decisions.csv'],
            'history_event_eligible_orders': result['history']['event_eligible_orders'],
            'window_event_eligible_orders': result['window']['event_eligible_orders'],
            'customer_states': result['customer_states'],
        },
        'execution': {'csv_values_parsed': False, 'csv_content_parsed': False, 'csv_header_parsed': False,
                      'new_descriptive_statistics_computed': False,
                      'cut_points_computed': False, 'scores_assigned': False, 'segments_assigned': False,
                      'model_fits': 0, 'dashboard': False, 'prior_readback_reexecuted': False,
                      'existing_dataset_rebuilt': False, 'new_model_performance_conclusion': False},
        'stage4': prior.prior.policy()['stage4'], 'stage5': prior.prior.policy()['stage5'],
    }
    _require(same(base.read_json(root / prior.OUTPUT), expected),
             'Prior evaluation audit, scope or metadata differs')
    _require(len(evaluation['sources']) == 27 and all(value is True for value in chain['checks'].values()),
             'Prior accepted evaluation source chain failed')
    return evaluation, chain


def _specification(root, evaluation):
    sources = [*evaluation['sources'], *[base.descriptor(root / path, root)
                for path in (prior.SPEC, prior.OUTPUT, *IMPLEMENTATION)]]
    paths = [item['path'] for item in sources]
    _require(len(sources) == 33 and len(set(paths)) == 33,
             'Exactly thirty-three complete distinct source bindings are required')
    return {'format_version': 1, 'policy': policy(),
            'evaluation_specification': base.descriptor(root / prior.SPEC, root),
            'sources': sources}


def source_bindings(root=ROOT):
    root = Path(root)
    evaluation, _ = _prior_metadata(root)
    return _specification(root, evaluation)['sources']


def specification(root=ROOT):
    root = Path(root)
    evaluation, _ = _prior_metadata(root)
    return _specification(root, evaluation)


def _receipt(root, sources):
    receipt = base.read_json(root / RECEIPT)
    keys = {'modules', 'tests_by_module', 'tests_run', 'errors', 'failures', 'skipped',
            'successful', 'elapsed_seconds', 'source_bindings'}
    _require(type(receipt) is dict and set(receipt) == keys,
             'Synthetic verification receipt schema differs')
    _require(same(receipt['modules'], MODULES)
             and type(receipt['tests_by_module']) is dict
             and set(receipt['tests_by_module']) == set(MODULES)
             and all(type(value) is int and value > 0 for value in receipt['tests_by_module'].values()),
             'Both exact synthetic modules with positive test counts are required')
    _require(type(receipt['tests_run']) is int
             and receipt['tests_run'] == sum(receipt['tests_by_module'].values()),
             'Synthetic verification test counts differ')
    _require(all(type(receipt[key]) is int and receipt[key] == 0
                 for key in ('errors', 'failures', 'skipped')) and receipt['successful'] is True,
             'Synthetic verification did not pass without errors, failures or skips')
    _require(type(receipt['elapsed_seconds']) is float and math.isfinite(receipt['elapsed_seconds'])
             and receipt['elapsed_seconds'] >= 0, 'Synthetic verification duration is invalid')
    _require(same(receipt['source_bindings'], sources),
             'Synthetic verification receipt source bytes or complete binding list differ')
    return receipt


def _state(root):
    evaluation, chain = _prior_metadata(root)
    spec = _specification(root, evaluation)
    receipt = _receipt(root, spec['sources'])
    data = artifacts.json_bytes(spec)
    guard = {
        'format_version': 1,
        'specification': {'path': SPEC, 'bytes': len(data), 'sha256': hashlib.sha256(data).hexdigest()},
        'source_bindings': spec['sources'],
        'synthetic_verification_receipt': base.descriptor(root / RECEIPT, root),
        'prior_evaluation_input_guard': base.descriptor(root / prior.GUARD, root),
        'prior_private_provenance': chain['private'],
    }
    report = {
        'format_version': 1, 'specification': guard['specification'],
        'status': 'description_implementation_synthetic_verified_real_description_not_executed',
        'policy': policy(),
        'unit_tests': {key: value for key, value in receipt.items() if key != 'source_bindings'},
        'accepted_dataset_metadata': {'checks': chain['checks'], 'all_passed': True,
                                      'original_evaluation_source_count': 27},
        'execution': {'description_core_implemented': True, 'synthetic_tests_only': True,
                      'real_csv_header_parsed': False, 'real_csv_values_parsed': False,
                      'real_RFM_recomputed': False, 'real_descriptive_statistics_computed': False,
                      'cutpoints_estimated': False, 'scores_or_groups_created': False,
                      'resampling_executed': False, 'model_fits': 0, 'dashboard': False,
                      'old_builder_or_individual_readback_reexecuted': False,
                      'new_model_performance_conclusion': False},
        'decision': 'synthetic_only_accepted_next_decide_real_readonly_description_no_authorization_for_cutpoints_or_groups',
    }
    return spec, guard, report


def _preflight(root, state):
    paths = (root / SPEC, root / GUARD, root / OUTPUT)
    exists = [path.exists() for path in paths]
    _require(not any(exists) or all(exists),
             'Partial implementation outputs must not be regenerated or refrozen')
    if (root / PRIVATE).exists():
        _require((root / PRIVATE).is_dir()
                 and {path.name for path in (root / PRIVATE).iterdir()} == {'input_guard.json'},
                 'Unexpected implementation control namespace files')
    for path, payload in zip(paths, state):
        if path.exists():
            _require(path.read_bytes() == artifacts.json_bytes(payload),
                     'Refusing changed frozen implementation outputs')


def verify_sources(spec, root=ROOT):
    root = Path(root)
    expected = _state(root)
    _require(same(spec, expected[0]), 'Complete implementation specification or source bytes differ')
    for path, payload in zip((SPEC, GUARD, OUTPUT), expected):
        _require((root / path).read_bytes() == artifacts.json_bytes(payload),
                 'Frozen implementation provenance or output bytes differ')
    return expected[2]


def run(root=ROOT, *, verify_synthetic=False):
    root = Path(root)
    _require(verify_synthetic is True, 'Only verify-synthetic is supported; no real description action exists')
    before = _state(root)
    _preflight(root, before)
    after = _state(root)
    _require(same(before, after), 'Sources, accepted metadata or test receipt changed during verification')
    for path, payload in zip((SPEC, GUARD, OUTPUT), before):
        base.immutable_write(root / path, payload)
    verify_sources(before[0], root)
    return {'status': before[2]['status'], 'output': OUTPUT,
            'source_bindings': len(before[0]['sources']), 'tests_run': before[2]['unit_tests']['tests_run']}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--verify-synthetic', action='store_true', required=True)
    args = parser.parse_args(argv)
    print(json.dumps(run(**vars(args)), ensure_ascii=False, allow_nan=False))


if __name__ == '__main__':
    main()
