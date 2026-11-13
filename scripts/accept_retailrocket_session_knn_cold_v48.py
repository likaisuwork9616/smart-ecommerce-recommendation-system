"""Accept the isolated second window using the unchanged V47 verification."""
import argparse

from scripts import accept_retailrocket_session_knn_cold_v47 as previous
from scripts import run_retailrocket_session_knn_cold_v48 as run
from scripts.retailrocket_session_knn_diagnostics_v20 import _clone
from tests import test_retailrocket_session_knn_cold_v48 as fixture


def coverage():
    inherited = {key: [name.replace(run.previous.SUITE + '.', run.SUITE + '.', 1) for name in cases]
                 for key, cases in previous.coverage().items()}
    contract = run.SUITE + '.ContractTests.'
    inherited.update(unchanged_repeat_protocol=[contract + 'test_repeat_preserves_protocol_and_measurement_core',
        contract + 'test_cross_window_comparison_rejects_changed_authority_schedule_and_summary',
        contract + 'test_cross_window_summary_keeps_regressions_and_excludes_warmups'],
        isolated_repeat_window=[contract + 'test_repeat_namespace_and_existing_windows_are_isolated',
                               contract + 'test_measure_refuses_existing_request_or_result'])
    return inherited


audit = _clone(previous.audit, run=run, fixture=fixture, coverage=coverage)
acceptance = _clone(previous.acceptance, run=run, fixture=fixture, coverage=coverage, audit=audit)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    modes = parser.add_mutually_exclusive_group(required=True)
    modes.add_argument('--acceptance', action='store_true')
    modes.add_argument('--audit', action='store_true')
    args = parser.parse_args()
    with run.entry.exclusive():
        value = audit() if args.audit else acceptance()
    print(dict(audit=args.audit, tests=value['tests_run'], integration=value['integration'], seconds=value['seconds']))
