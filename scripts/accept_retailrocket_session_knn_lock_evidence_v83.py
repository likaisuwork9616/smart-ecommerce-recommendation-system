"""Verify a V83 source seal and run only its offline fake case module."""

import argparse
import hashlib
import json
from pathlib import Path
import re
from types import SimpleNamespace
import unittest


ROOT = Path(__file__).resolve().parents[1]
SEAL = 'reports/mainline/v83_lock_evidence_tool_seal_20261118.json'
TEST_MODULE = 'tests.test_retailrocket_session_knn_lock_evidence_v83'
FAKE_SOURCES = frozenset({
    'scripts/__init__.py',
    'scripts/accept_retailrocket_session_knn_lock_evidence_v83.py',
    'scripts/retailrocket_session_knn_lock_trace_v83.py',
    'scripts/retailrocket_session_knn_lock_owner_v83.py',
    'tests/test_retailrocket_session_knn_lock_evidence_v83.py',
})


def _descriptor(path):
    data = (ROOT / path).read_bytes()
    return dict(path=path, bytes=len(data), sha256=hashlib.sha256(data).hexdigest())


def _read_seal(expected_sha):
    if re.fullmatch(r'[0-9a-f]{64}', expected_sha) is None:
        raise ValueError('Explicit V83 seal SHA-256 required')
    data = (ROOT / SEAL).read_bytes()
    if hashlib.sha256(data).hexdigest() != expected_sha:
        raise ValueError('V83 source seal SHA-256 differs')
    seal = json.loads(data)
    if (seal['schema'] != 'v83_fake_lock_evidence_tool_seal'
            or seal['scope'] != 'fake_clock_fake_lock_only'
            or seal['status'] != 'sealed_before_fake_validation'
            or seal['test_module'] != TEST_MODULE):
        raise ValueError('V83 fake-only seal required')
    files = seal['source_descriptors']
    if len(files) != len(FAKE_SOURCES) or {row['path'] for row in files} != FAKE_SOURCES:
        raise ValueError('V83 source roster differs')
    if (ROOT / 'tests/__init__.py').exists():
        raise ValueError('Unexpected test namespace initializer')
    _verify_sources(files)
    return seal


def _verify_sources(files):
    for row in files:
        if row != _descriptor(row['path']):
            raise ValueError('Sealed source differs: ' + row['path'])


def _leaves(suite):
    for item in suite:
        if isinstance(item, unittest.TestSuite):
            yield from _leaves(item)
        else:
            yield item


class _EvidenceResult(unittest.TestResult):
    def __init__(self):
        super().__init__()
        self.started = []
        self.passed = []

    def startTest(self, test):
        self.started.append(test.id())
        super().startTest(test)

    def addSuccess(self, test):
        self.passed.append(test.id())
        super().addSuccess(test)

    def addDuration(self, test, elapsed):
        # Duration is outside this fake acceptance's evidence contract.
        pass


def accept(seal_sha):
    seal = _read_seal(seal_sha)
    loader = unittest.TestLoader()
    suite = loader.loadTestsFromName(TEST_MODULE)
    ids = [test.id() for test in _leaves(suite)]
    if (loader.errors or not ids or len(ids) != len(set(ids))
            or any(not name.startswith(TEST_MODULE + '.') for name in ids)
            or ids != seal['test_ids']):
        raise ValueError('Loaded fake case roster differs from the seal')
    result = _EvidenceResult()
    # CPython 3.12 samples perf_counter around each case before addDuration.
    # Keep even that harness clock fixed and restore it after the suite.
    case_clock = unittest.case.time
    unittest.case.time = SimpleNamespace(perf_counter=lambda: 0.0)
    try:
        suite.run(result)
    finally:
        unittest.case.time = case_clock
    _verify_sources(seal['source_descriptors'])
    status = 'passed' if result.wasSuccessful() and result.started == result.passed == ids else 'failed'
    return dict(schema='v83_fake_lock_evidence_result', status=status, seal_sha256=seal_sha,
                required_test_ids=ids, started_test_ids=result.started, passed_test_ids=result.passed,
                tests_run=result.testsRun,
                failures=[dict(id=test.id(), traceback=detail) for test, detail in result.failures],
                errors=[dict(id=test.id(), traceback=detail) for test, detail in result.errors],
                skipped=[dict(id=test.id(), reason=why) for test, why in result.skipped],
                formal_cases_run=0, native_lock_or_process_probe_calls=0, performance_measurements=0)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--seal-sha256', required=True)
    result = accept(parser.parse_args().seal_sha256)
    print(json.dumps(result, ensure_ascii=True, sort_keys=True))
    return 0 if result['status'] == 'passed' else 1


if __name__ == '__main__':
    raise SystemExit(main())
