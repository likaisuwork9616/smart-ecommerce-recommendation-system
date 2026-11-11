"""Seal and re-audit the direct-comparison entry's artificial acceptance."""
import argparse

from scripts import accept_retailrocket_session_knn_compare_v40 as prior
from scripts import run_retailrocket_session_knn_compare_v41 as run
from scripts.retailrocket_session_knn_diagnostics_v20 import _clone
from tests import test_retailrocket_session_knn_compare_v41 as fixture


def coverage():
    contract = run.SUITE + '.ContractTests.'
    integrated = run.SUITE + '.IntegrationTests.'
    cases = (
        [contract + 'test_retains_v40_sources_methods_original_cohort_and_schedule'],
        [integrated + 'test_two_independent_pools_and_complete_independent_scientific_checks'],
        [integrated + 'test_late_timing_is_ordered_and_cost_includes_reference_build',
         integrated + 'test_raw_publisher_rejects_invalid_original_late_timing'],
        [integrated + 'test_two_independent_pools_and_complete_independent_scientific_checks',
         integrated + 'test_raw_publisher_rejects_mixed_typed_policy', integrated + 'test_closed_log_manifest_refuses_late_write'],
        [contract + 'test_aggregate_charges_both_colds_and_signed_pair_deltas',
         integrated + 'test_release_and_read_only_audit_recompute_from_same_artifacts'],
        [contract + 'test_missing_acceptance_and_existing_request_fail_before_supervision'],
    )
    return dict(zip(run.frozen.REQUIREMENTS, cases, strict=True))


audit = _clone(prior.audit, run=run, fixture=fixture, coverage=coverage)
acceptance = _clone(prior.acceptance, run=run, fixture=fixture, coverage=coverage, audit=audit)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument('--acceptance', action='store_true')
    mode.add_argument('--audit', action='store_true')
    args = parser.parse_args()
    with run.entry.exclusive():
        value = audit() if args.audit else acceptance()
    print(dict(audit=args.audit, tests=value['tests_run'], requirements=len(value['coverage']),
               integration=value['integration'], real_runs=0, seconds=value['seconds']))
