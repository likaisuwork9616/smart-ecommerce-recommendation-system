"""Freeze UCI RFM v1 policy and evidence; hashes/JSON only, no transaction loader."""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
from decimal import Decimal, ROUND_CEILING
import hashlib
import io
import json
from pathlib import Path
import sys
import time
import unittest

ROOT = Path(__file__).resolve().parents[1]
POLICY = 'docs/contracts/uci_rfm_v1.json'
DOCUMENT = 'docs/STAGE6_UCI_RFM_CONTRACT_V1.md'
CODE = 'scripts/freeze_uci_rfm_contract.py'
TEST = 'tests/test_uci_rfm_contract.py'
SPEC = 'reports/stage6/uci_rfm_v1_specification.json'
REPORT = 'reports/stage6/uci_rfm_v1_contract_acceptance.json'
PRIVATE = 'shop-mysql-runtime/uci_rfm_contract_v1'
INTAKE = 'reports/stage6/uci_retail_ii_intake.json'
INTAKE_VERIFY = 'reports/stage6/uci_retail_ii_verification.json'
INTAKE_GUARD = 'shop-mysql-runtime/uci_retail_ii_intake_v1/output_guard.json'


def within(root, relative):
    root = Path(root).resolve()
    path = root / relative
    if not path.resolve().is_relative_to(root):
        raise ValueError('Path must remain inside shop')
    return path


def read_json(path):
    return json.loads(Path(path).read_text(encoding='utf-8-sig'))


def descriptor(root, relative):
    path = within(root, relative)
    with path.open('rb') as source:
        digest = hashlib.file_digest(source, 'sha256').hexdigest()
    return {'path': relative, 'bytes': path.stat().st_size, 'sha256': digest}


def verify_descriptors(root, descriptors):
    seen = set()
    for expected in descriptors:
        name = expected['path']
        if name in seen:
            raise ValueError('Duplicate source path')
        seen.add(name)
        if descriptor(root, name) != expected:
            raise ValueError('Changed or incomplete evidence: ' + name)


def write_new(path, value):
    with Path(path).open('x', encoding='utf-8', newline='\n') as output:
        json.dump(value, output, ensure_ascii=False, indent=2, allow_nan=False)
        output.write('\n')


def timestamp(value):
    parsed = datetime.strptime(value, '%Y-%m-%d %H:%M:%S')
    if parsed.strftime('%Y-%m-%d %H:%M:%S') != value:
        raise ValueError('Noncanonical timestamp')
    return parsed


def in_window(value, window):
    """Contract boundary helper, exercised only with synthetic dates this turn."""
    return timestamp(window['start_inclusive']) <= timestamp(value) < timestamp(window['cutoff_exclusive'])


def reference_cutpoints(values):
    """Integer R seconds/F/M units; synthetic rule oracle, not a real-data runner."""
    if not values or any(type(v) is not int or v < 0 for v in values):
        raise ValueError('Expected nonnegative integer values')
    ordered = sorted(values)
    n = len(ordered)
    # ceil(n*k/5), exact integer arithmetic (never binary floating point).
    cuts = {ordered[(n*k+4)//5-1] for k in range(1, 5)}
    return sorted(c for c in cuts if c < ordered[-1])


def score(value, cutpoints, axis):
    if axis not in ('R', 'F', 'M') or cutpoints != sorted(set(cutpoints)):
        raise ValueError('Invalid axis or cutpoints')
    j = sum(value > c for c in cutpoints)
    return len(cutpoints)+1-j if axis == 'R' else j+1


def minimum_support(n):
    if type(n) is not int or n < 0:
        raise ValueError('Invalid population size')
    return max(50, int((Decimal(n)/100).to_integral_value(rounding=ROUND_CEILING)))


def validate_policy(p):
    """Reject inconsistent calendars, future-dependent eligibility or scope claims."""
    checks = []
    def require(ok, label):
        if not ok:
            raise ValueError('Invalid policy: ' + label)
        checks.append(label)
    require(p['contract_id'] == 'uci_online_retail_ii_retrospective_rfm_v1' and p['contract_version'] == 1, 'v1 identity')
    windows = p['windows']
    require([w['id'] for w in windows] == ['T1','T2'], 'exactly two ordered windows')
    require([(w['start_inclusive'],w['cutoff_exclusive']) for w in windows] == [
        ('2009-12-01 00:00:00','2010-12-01 00:00:00'),
        ('2010-12-01 00:00:00','2011-12-01 00:00:00')], 'fixed December annual windows')
    for w in windows:
        require((timestamp(w['cutoff_exclusive'])-timestamp(w['start_inclusive'])).days == w['days'] == 365, w['id']+' equal 365 days')
    require(windows[0]['cutoff_exclusive'] == windows[1]['start_inclusive'], 'no window overlap or gap')
    require(p['history_start'] == windows[0]['start_inclusive'], 'history origin')
    require('filter_history_start_le_timestamp_lt_T' in p['processing_order'][1] and 'universe' in p['processing_order'][2], 'prefix before grouping or universe')
    require('only_this_prefix' in p['processing_order'][3], 'header conflict prefix scope')
    require(not p['prior_exposure']['pristine_holdout_available'], 'no unseen holdout claim')
    require(p['prior_exposure']['full_file_quality_and_monthly_amounts_inspected'], 'prior exposure disclosure')
    require(not p['prior_exposure']['exploratory_june_cutoff_selected_for_this_study'], 'no June probe role confusion')
    require(p['source']['purchase_invoice_regex'] == '[0-9]{6}' and p['source']['customer_key_regex'] == '[0-9]{5}', 'ASCII key shapes')
    require(p['duplicate_policy']['main'] == 'one_per_exact_eight_field_group', 'primary exact-value dedup')
    require(p['duplicate_policy']['sensitivity'] == 'max_per_sheet_multiplicity_per_exact_group', 'cross-sheet multiset sensitivity')
    require('no_imputation' in p['source']['missing_customer'], 'no invented identity')
    require('no_future_cancellation' in p['invoice_policy']['refund_matching'], 'no future netting')
    require('regardless_of_sign' in p['invoice_policy']['cancellations'], 'C-positive also excluded')
    require('quarantine_entire_numeric' in p['invoice_policy']['conflict_action'], 'whole invoice conflict quarantine')
    require('masks_all_primary_R_F_M_to_null' in p['universe_and_rfm']['window_quarantine'], 'quality mask is not zero')
    require(p['money']['integer_units_per_GBP'] == 1000 and p['money']['maximum_price_decimal_places'] == 3, 'preserve source sub-penny precision')
    require(not p['money']['net_revenue_supported'] and not p['money']['cost_profit_LTV_supported'], 'gross proxy scope')
    require('R_F_and_invoice_eligibility_unchanged' in p['money']['sensitivity_scope'], 'monetary-only code sensitivity')
    require([(a['duplicates'],a['money']) for a in p['arms']] == [
        ('one_per_exact_eight_field_group','all_paid_codes'),
        ('max_per_sheet_multiplicity_per_exact_group','all_paid_codes'),
        ('one_per_exact_eight_field_group','standard_code_shape_only'),
        ('max_per_sheet_multiplicity_per_exact_group','standard_code_shape_only')], 'four predeclared arms')
    e = p['evaluation']
    require(e['reference'] == 'main_T1_active_complete_only', 'cutpoints only reference T1')
    require(e['cutpoint_probabilities'] == [0.2,0.4,0.6,0.8], 'fixed quantile candidates')
    require('no_T2_refit_or_best_arm_selection' in e['apply'], 'frozen common thresholds no selection')
    require(e['minimum_reference_active_complete'] == e['minimum_paired_for_correlations_and_ARI'] == 200, 'minimum statistical support')
    require(e['support_minimum'] == 'max_50_and_ceiling_0_01_times_that_snapshot_active_complete_population', 'predeclared small group floor')
    require('no_arbitrary_stability_pass_threshold' in e['temporal_pass_fail'], 'temporal change is descriptive')
    require(not e['new_training_or_G3_resampling'], 'no new model or seed search')
    s = p['execution_scope_this_turn']
    require(s['metadata_and_source_hash_validation_only'] and not s['parse_actual_transaction_rows'] and not s['builder_implemented'], 'metadata-only freeze scope')
    require(all(s[k] == 0 for k in ['new_RFM_values','new_cutpoints','models_fitted','temporal_scores']), 'zero claimed execution results')
    require(p['planned_outputs']['private_root'] == 'shop-mysql-runtime/uci_rfm_dataset_v1', 'future outputs confined')
    require(p['unchanged_project_limits']['olist_under_supported_joint_groups'] == 25 and p['unchanged_project_limits']['stage4_daily_alert_budget'] == 0.1, 'existing project limits retained')
    return checks


def collect_sources(root):
    intake = read_json(within(root, INTAKE))
    verified = read_json(within(root, INTAKE_VERIFY))
    guard = read_json(within(root, INTAKE_GUARD))
    if verified['status'] != 'passed' or not intake['source']['published_rows_match']:
        raise ValueError('Intake evidence not accepted')
    evidence = [*intake['source']['files'], *verified['sources'], guard['report'], guard['database'], *guard['sources']]
    unique = {}
    for item in evidence:
        if item['path'] in unique and unique[item['path']] != item:
            raise ValueError('Conflicting prior source descriptors')
        unique[item['path']] = item
    verify_descriptors(root, list(unique.values()))
    for path in [INTAKE, INTAKE_VERIFY, INTAKE_GUARD, POLICY, DOCUMENT, CODE, TEST]:
        current = descriptor(root, path)
        if path in unique and unique[path] != current:
            raise ValueError('Changed source')
        unique[path] = current
    return [unique[name] for name in sorted(unique)]


def test_ids(suite):
    result = []
    for item in suite:
        result.extend(test_ids(item) if isinstance(item, unittest.TestSuite) else [item.id()])
    return result


def write_bundle(root, spec, acceptance, log):
    private = within(root, PRIVATE)
    if private.exists() or within(root, SPEC).exists() or within(root, REPORT).exists():
        raise FileExistsError('Existing or partial freeze: preserve it; use --verify')
    private.mkdir(parents=True)
    try:
        (private/'tests.log').write_text(log, encoding='utf-8', newline='\n')
        write_new(within(root, SPEC), spec)
        acceptance = dict(acceptance, specification=descriptor(root, SPEC))
        write_new(within(root, REPORT), acceptance)
        guard = {'specification':descriptor(root,SPEC), 'acceptance':descriptor(root,REPORT),
                 'test_log':descriptor(root,PRIVATE+'/tests.log'), 'sources':spec['sources']}
        write_new(private/'output_guard.json', guard)
    except Exception as error:
        write_new(private/'failure.json', {'status':'incomplete_freeze_preserve_all_outputs','error_type':type(error).__name__})
        raise


def verify(root=ROOT):
    guard = read_json(within(root, PRIVATE+'/output_guard.json'))
    spec = read_json(within(root, SPEC))
    acceptance = read_json(within(root, REPORT))
    policy = read_json(within(root, POLICY))
    checks = validate_policy(policy)
    verify_descriptors(root, [guard['specification'],guard['acceptance'],guard['test_log'],*guard['sources']])
    if spec['sources'] != guard['sources'] or spec['policy_file'] != descriptor(root,POLICY):
        raise ValueError('Source binding disagreement')
    if acceptance['specification'] != guard['specification'] or acceptance['status'] != 'frozen_contract_verified_no_dataset_execution':
        raise ValueError('Acceptance binding disagreement')
    if acceptance['policy_checks'] != checks or acceptance['execution_scope'] != policy['execution_scope_this_turn']:
        raise ValueError('Acceptance scope changed')
    return {'status':'saved_contract_and_sources_verified', 'source_files':len(spec['sources']),
            'policy_checks':len(checks), 'transaction_rows_recomputed':False, 'tests_rerun':False}


def freeze(root=ROOT):
    if within(root,PRIVATE).exists() or within(root,SPEC).exists() or within(root,REPORT).exists():
        return verify(root)
    policy = read_json(within(root,POLICY))
    checks = validate_policy(policy)
    sources = collect_sources(root)
    if str(root) not in sys.path:
        sys.path.insert(0,str(root))
    suite = unittest.defaultTestLoader.loadTestsFromName('tests.test_uci_rfm_contract')
    ids = test_ids(suite)
    buffer = io.StringIO()
    started = time.perf_counter()
    result = unittest.TextTestRunner(stream=buffer,verbosity=2).run(suite)
    elapsed = round(time.perf_counter()-started,6)
    if not result.wasSuccessful() or result.skipped:
        print(buffer.getvalue())
        raise ValueError('Contract tests failed or skipped; not frozen')
    verify_descriptors(root,sources)
    spec = {'format_version':1,'contract_id':policy['contract_id'],
            'frozen_at_utc':datetime.now(timezone.utc).isoformat(),
            'policy_file':descriptor(root,POLICY),'method_document':descriptor(root,DOCUMENT),
            'sources':sources,'status':'frozen_before_UCI_RFM_build_and_temporal_scoring',
            'amendment':'new_version_new_namespace_new_test_receipt_preserve_v1_disclose_prior_exposure'}
    acceptance = {'format_version':1,'status':'frozen_contract_verified_no_dataset_execution',
                  'policy_checks':checks,'source_files_verified':len(sources),
                  'synthetic_tests':{'tests_run':result.testsRun,'failures':len(result.failures),'errors':len(result.errors),
                                     'skips':len(result.skipped),'elapsed_seconds':elapsed,'test_ids':ids},
                  'execution_scope':policy['execution_scope_this_turn'],
                  'limitations':['Contract consistency and source bytes only; actual builder and full independent data reconciliation remain required.',
                                 'Prior intake values are not newly measured frozen-cohort counts.',
                                 'No pristine holdout, operational as-of or business efficacy acceptance.']}
    write_bundle(root,spec,acceptance,buffer.getvalue())
    verified = verify(root)
    return dict(verified, frozen_now=True, tests_run=result.testsRun, test_elapsed_seconds=elapsed)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument('--freeze',action='store_true')
    group.add_argument('--verify',action='store_true')
    args = parser.parse_args()
    print(json.dumps(freeze() if args.freeze else verify(),ensure_ascii=False))
