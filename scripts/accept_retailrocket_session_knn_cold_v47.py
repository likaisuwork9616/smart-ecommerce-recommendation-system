"""Seal the artificial all-cold comparison and its validation."""
import argparse

from scripts import accept_retailrocket_session_knn_compare_v40 as prior
from scripts import run_retailrocket_session_knn_cold_v47 as run
from scripts.retailrocket_session_knn_diagnostics_v20 import _clone
from tests import test_retailrocket_session_knn_cold_v47 as fixture


def coverage():
    contract = run.SUITE + '.ContractTests.'
    integration = run.SUITE + '.IntegrationTests.'
    cases = (
        [contract + 'test_original_and_candidate_build_both_roots_with_equal_typed_authority'],
        [integration + 'test_all_entries_are_fresh_and_independent_publisher_checks_fixed48_outputs',
         integration + 'test_independent_verifier_rejects_build_outside_original_boundary'],
        [integration + 'test_stopped_audit_rejects_log_append'],
        [contract + 'test_cost_summary_uses_only_formal_pairs_and_four_independent_boundaries'],
    )
    return dict(zip(run.frozen.REQUIREMENTS, cases, strict=True))


audit = _clone(prior.audit, run=run, fixture=fixture, coverage=coverage)
acceptance = _clone(prior.acceptance, run=run, fixture=fixture, coverage=coverage, audit=audit)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    modes = parser.add_mutually_exclusive_group(required=True)
    modes.add_argument('--acceptance', action='store_true')
    modes.add_argument('--audit', action='store_true')
    args = parser.parse_args()
    with run.entry.exclusive():
        value = audit() if args.audit else acceptance()
    print(dict(audit=args.audit, tests=value['tests_run'], integration=value['integration'], seconds=value['seconds']))
