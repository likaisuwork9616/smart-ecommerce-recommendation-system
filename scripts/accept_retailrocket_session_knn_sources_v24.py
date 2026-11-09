"""Synthetically accept the sealed fixed48 source/setup observation primitives.

No real-data measurement command is provided in this acceptance-only entry.
Supervised worker/publisher integration needs a separate accepted entry point.
"""
import argparse
from contextlib import contextmanager
from datetime import datetime, timezone
import sys
from time import perf_counter
import unittest
from uuid import uuid4

from scripts.run_retailrocket_session_knn_v2 import ROOT, read, describe, verify_bindings, environment, check_gates
from scripts.run_retailrocket_session_knn_gap_v7 import PRIVATE, public_json
from scripts.retailrocket_session_knn_checkpoint_v2 import _lock

BASE = 'reports/stage12/retailrocket_session_knn_v24_sources_'
SPEC = BASE+'specification_20261109.json'
# Exact SHA is the preregistered file, not a reconstructed JSON serialization.
SPEC_SHA = '74dcbb7ba8eb40319fb353ae76dc797376469c0a6c53552e22d56c8c4c8b7c4d'
REPORT = BASE+'acceptance_20261109.json'
METHODS = ('scripts/retailrocket_session_knn_sources_v24.py',
           'scripts/accept_retailrocket_session_knn_sources_v24.py',
           'tests/test_retailrocket_session_knn_sources_v24.py')
SUITES = ('tests.test_retailrocket_session_knn_sources_v24',
          'tests.test_retailrocket_session_knn_detailed_cost_v6',
          'tests.test_retailrocket_session_knn_priority_v23')


def specification():
    spec = read(ROOT/SPEC)
    expected = [('warm_R','R'),('warm_D','D')]
    for i in range(6):
        expected.extend((f'pair_{i+1}_{mode}',mode) for mode in ('RD' if i%2==0 else 'DR'))
    if (describe(ROOT/SPEC)['sha256'] != SPEC_SHA
            or spec['status'] != 'v24_source_setup_diagnostics_specification_frozen'
            or spec['scope']['actual_real_runs_authorized_this_round'] != 0
            or spec['measurement_plan']['schedule'] != [dict(label=l,mode=m) for l,m in expected]
            or spec['measurement_plan']['queries_per_run'] != 48
            or spec['measurement_plan']['total_checks'] != 672):
        raise ValueError('Expected the sealed source/setup acceptance-only scope')
    verify_bindings(spec['evidence'])
    if spec['environment'] != environment() or spec['gates'] != check_gates():
        raise ValueError('Sealed engineering environment or reference gates changed')
    return spec


@contextmanager
def exclusive():
    PRIVATE.mkdir(parents=True, exist_ok=True)
    with (PRIVATE/'knn-v24-source-tools.guard').open('a+b') as guard:
        if guard.seek(0,2) == 0:
            guard.write(b'0');guard.flush()
        _lock(guard)
        yield


def acceptance():
    with exclusive():
        if (ROOT/REPORT).exists():
            raise FileExistsError('The immutable V24 tool acceptance already exists')
        spec = specification()
        methods = [describe(ROOT/name) for name in METHODS]
        folder = PRIVATE/('knn-v24-source-tools-'+uuid4().hex)
        folder.mkdir()
        started = perf_counter()
        with (folder/'tests.log').open('x', encoding='utf-8') as log:
            result = unittest.TextTestRunner(stream=log, verbosity=2).run(
                unittest.defaultTestLoader.loadTestsFromNames(SUITES))
        if not result.wasSuccessful() or result.skipped or not result.testsRun:
            print((folder/'tests.log').read_text(encoding='utf-8'), file=sys.stderr)
            raise ValueError('Source/setup observer synthetic acceptance failed')
        verify_bindings(methods)
        if specification() != spec:
            raise ValueError('Sources, scope or gates changed during acceptance')
        report = {'status':'v24_source_setup_core_tools_synthetic_accepted',
            'created_utc':datetime.now(timezone.utc).isoformat(), 'specification':describe(ROOT/SPEC),
            'tests_run':result.testsRun, 'failures':0, 'errors':0, 'skipped':0,
            'seconds':perf_counter()-started, 'suites':list(SUITES), 'methods':methods,
            'log':describe(folder/'tests.log'), 'environment':environment(), 'gates':spec['gates'],
            'accepted_scope':['private event tree and public aggregate','original descriptor/binding call observers',
                'store create/open/writer acquisition and lifecycle','original context/catalog and setup verifier envelope',
                'fixed48 run adapter over original V22 bytecode','independent publisher callable envelope'],
            'pending_scope':['integrated supervised real worker/publisher entry, including absolute deadline and resource envelope',
                'real original48 RD/DR schedule and continuous load observation','real observation overhead and phase durations'],
            'scope':spec['scope'], 'real_rankings':0, 'real_benchmark_windows':0,
            'original_large_model_or_data_rehashed':False, 'T_plan':None,
            'interpretation':'Artificial fixtures only. The synthetic48 adapter fixture exercises checkpoint/run/publisher control flow; '
                'the separate multi-arm fixture compares original complete prediction bytes and workload. '
                'No synthetic throughput, wall measurement or call count is a real-data performance result.'}
        public_json(ROOT/REPORT, report, exclusive=True)
        print({'report':REPORT,'tests_run':result.testsRun,'seconds':report['seconds'],'real_windows':0})


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--acceptance', action='store_true', required=True)
    parser.parse_args()
    acceptance()
