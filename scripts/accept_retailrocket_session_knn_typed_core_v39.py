"""Seal original-oracle differential acceptance of the V39 comparator core only."""
import argparse
from collections import Counter
from contextlib import redirect_stdout, redirect_stderr
from datetime import datetime, timezone
import math
from time import perf_counter
import unittest
from uuid import uuid4

from scripts.run_retailrocket_session_knn_v2 import ROOT, read, describe, verify_bindings, environment
from scripts.run_retailrocket_session_knn_gap_v7 import PRIVATE, public_json
from scripts import freeze_retailrocket_session_knn_typed_v38 as design
from scripts import retailrocket_session_knn_entry_v34 as common

REPORT='reports/stage12/retailrocket_session_knn_v39_typed_core_acceptance_20261110.json'
METHOD='scripts/accept_retailrocket_session_knn_typed_core_v39.py'
SUITES=('tests.test_retailrocket_session_knn_typed_v39', 'tests.test_retailrocket_session_knn_typed_contract_v38')
SEEDS=(METHOD,'scripts/retailrocket_session_knn_typed_v39.py','tests/test_retailrocket_session_knn_typed_v39.py',
       'tests/test_retailrocket_session_knn_typed_contract_v38.py')


def methods():
    return common.source_inventory(SEEDS,dynamic_seeds=common.DYNAMIC_TARGET_SEEDS)


def expected():
    names=design.parent.prior.ids(unittest.defaultTestLoader.loadTestsFromNames(SUITES))
    if not names or len(names)!=len(set(names)):raise ValueError('Unique differential/original tests required')
    return names


def base():
    design.audit()
    return dict(specification=describe(ROOT/design.SPEC),seal=describe(ROOT/design.SEAL),
                methods=methods(),suites=list(SUITES),environment=environment(),
                scope=dict(comparator_core_implemented=True,worker_publication_accepted=False,new_real_query_runs=0,
                           full_validation_complete=False,reserved_test='locked'),
                interpretation='New comparator/reference core differential tests plus original oracle characterization. Not complete worker/publisher acceptance or performance measurement.',
                measured_speedup=None,T_plan=None)


def acceptance():
    if (ROOT/REPORT).exists():raise FileExistsError('Immutable core acceptance exists; use --audit')
    value=base();folder=PRIVATE/('knn-v39-core-tests-'+uuid4().hex);folder.mkdir();start=perf_counter()
    tests=expected()
    from tests import test_retailrocket_session_knn_typed_v39 as fixture
    fixture.reset_evidence()
    with (folder/'tests.log').open('x',encoding='utf-8') as log,redirect_stdout(log),redirect_stderr(log):
        result=unittest.TextTestRunner(stream=log,verbosity=2,resultclass=design.parent.prior.Result).run(
            unittest.defaultTestLoader.loadTestsFromNames(SUITES))
    if not result.wasSuccessful() or result.skipped or Counter(result.passed)!=Counter(tests):
        raise ValueError('Differential core acceptance failed: '+str(folder/'tests.log'))
    verify_bindings(value['methods'])
    evidence=fixture.differential_evidence()
    report=dict(value,status='v39_typed_comparator_core_differential_accepted',
        created_utc=datetime.now(timezone.utc).isoformat(),tests_run=result.testsRun,passed_test_ids=result.passed,
        failures=0,errors=0,skipped=0,seconds=perf_counter()-start,log=describe(folder/'tests.log'),
        differential=evidence)
    public_json(ROOT/REPORT,report,exclusive=True)
    print(dict(report=REPORT,tests=result.testsRun,
               differential={k:v for k,v in evidence.items() if k not in ('vectors','interpretation')},
               worker_publication_accepted=False))
    return report


def audit():
    value=read(ROOT/REPORT);shape=base()
    if (value['status']!='v39_typed_comparator_core_differential_accepted'
            or any(value[k]!=v for k,v in shape.items())
            or Counter(value['passed_test_ids'])!=Counter(expected())
            or value['tests_run']!=len(value['passed_test_ids'])
            or any(type(value[k]) is not int or value[k]!=0 for k in ('failures','errors','skipped'))
            or type(value['seconds']) not in (int,float) or not math.isfinite(value['seconds']) or value['seconds']<0):
        raise ValueError('Core acceptance changed')
    verify_bindings([*value['methods'],value['log']])
    if not value['differential']:raise ValueError('Differential evidence absent')
    print(dict(audit=True,tests=value['tests_run'],worker_publication_accepted=False))
    return value


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__);mode=parser.add_mutually_exclusive_group(required=True)
    for name in ('acceptance','audit'):mode.add_argument('--'+name,action='store_true')
    args=parser.parse_args()
    if args.acceptance:acceptance()
    else:audit()
