"""Audit and summarize the saved V6-V16 engineering costs without reranking queries."""
import argparse
from datetime import datetime, timezone
from pathlib import Path
from time import perf_counter
import unittest
from uuid import uuid4

from scripts.run_retailrocket_session_knn_v2 import (
    ROOT, read, write, describe, verify_bindings, check_gates, environment)
from scripts.run_retailrocket_session_knn_gap_v7 import PRIVATE, public_json
from scripts.retailrocket_session_knn_cost_rollup_v17 import load_manifest, summarize_costs

BASE = 'reports/stage12/retailrocket_session_knn_v17_cost_'
INVENTORY = BASE + 'inventory_20261106.json'
INVENTORY_SHA256 = '28b382de0644665a071e85e93072381ba285c60c9f172f90639de7b66a968c26'
ACCEPT = BASE + 'acceptance_20261106.json'
REPORT = BASE + 'rollup_20261106.json'
SUITES = ('tests.test_retailrocket_session_knn_cost_rollup_v17',)
METHODS = ('scripts/retailrocket_session_knn_cost_rollup_v17.py',
           'scripts/run_retailrocket_session_knn_cost_rollup_v17.py',
           'tests/test_retailrocket_session_knn_cost_rollup_v17.py')


def inventory():
    if describe(ROOT / INVENTORY)['sha256'] != INVENTORY_SHA256:
        raise ValueError('The frozen V17 cost inventory changed')
    return read(ROOT / INVENTORY)


def acceptance():
    inventory()
    if (ROOT / ACCEPT).exists():
        raise FileExistsError(ROOT / ACCEPT)
    gates = check_gates()
    methods = [describe(ROOT / path) for path in METHODS]
    folder = PRIVATE / ('knn-v17-cost-tests-' + uuid4().hex)
    folder.mkdir()
    start = perf_counter()
    with (folder / 'tests.log').open('x', encoding='utf-8') as log:
        result = unittest.TextTestRunner(stream=log, verbosity=2).run(
            unittest.defaultTestLoader.loadTestsFromNames(SUITES))
    if not result.testsRun or not result.wasSuccessful() or result.skipped:
        raise ValueError(f'V17 acceptance failed: {folder / "tests.log"}')
    verify_bindings(methods)
    if check_gates() != gates:
        raise ValueError('Reference gates changed')
    receipt = dict(status='v17_cost_rollup_synthetic_accepted',
                   created_utc=datetime.now(timezone.utc).isoformat(),
                   tests_run=result.testsRun, failures=0, errors=0, skipped=0,
                   seconds=perf_counter() - start, suites=list(SUITES),
                   inventory=describe(ROOT / INVENTORY), method_files=methods,
                   log=describe(folder / 'tests.log'), environment=environment(),
                   gates=gates, new_selections=0, new_rankings=0, T_plan=None)
    public_json(ROOT / ACCEPT, receipt, exclusive=True)
    print(f"V17 cost acceptance: {receipt['tests_run']} tests, {receipt['seconds']:.3f} seconds")


def accepted():
    inventory()
    result = read(ROOT / ACCEPT)
    if (result['status'] != 'v17_cost_rollup_synthetic_accepted'
            or result['inventory'] != describe(ROOT / INVENTORY)
            or result['environment'] != environment() or result['gates'] != check_gates()
            or result['suites'] != list(SUITES) or result['tests_run'] <= 0
            or {x['path'] for x in result['method_files']} != set(METHODS)
            or any(result[k] != 0 for k in ('failures', 'errors', 'skipped', 'new_selections', 'new_rankings'))
            or result['T_plan'] is not None):
        raise ValueError('Current methods and inventory require acceptance')
    verify_bindings([*result['method_files'], result['log']])
    return result


def summarize():
    if (ROOT / REPORT).exists():
        raise FileExistsError('The V17 rollup is already published; inspect the saved report')
    acc = accepted()
    inv = inventory()
    start = perf_counter()
    loaded = load_manifest(ROOT, inv)
    summary = summarize_costs(**loaded)
    # Re-read the same manifest sources after aggregation. No model or ranking is run.
    load_manifest(ROOT, inv)
    accepted()
    folder = PRIVATE / ('knn-v17-cost-rollup-' + uuid4().hex)
    folder.mkdir()
    write(folder / 'normalized_rows.json', loaded)
    receipt = dict(status='v17_all_55_cell_costs_summarized',
                   created_utc=datetime.now(timezone.utc).isoformat(),
                   inventory=describe(ROOT / INVENTORY), acceptance=describe(ROOT / ACCEPT),
                   environment=environment(), seconds=perf_counter() - start,
                   source_bindings_reverified_before_after=True,
                   summary=summary, normalized_evidence=describe(folder / 'normalized_rows.json'),
                   scope=dict(new_keys=0, new_rankings=0, new_primary_fits=0,
                              new_primary_validation_runs=0, new_primary_bootstrap=0,
                              SQL_candidate_runs=0, reserved_test='locked'),
                   gates=acc['gates'], T_plan=None)
    public_json(ROOT / REPORT, receipt, exclusive=True)
    print({'report': REPORT, 'seconds': receipt['seconds']})


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument('--acceptance', action='store_true')
    mode.add_argument('--summarize', action='store_true')
    args = parser.parse_args()
    acceptance() if args.acceptance else summarize()
