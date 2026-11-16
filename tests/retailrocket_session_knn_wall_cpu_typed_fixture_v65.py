"""New literal sources for real typed workers; no work occurs on import.

The worker, source-authority, snapshot, SQL and checkpoint implementations remain
the original code. Test subclasses only bind passive/legacy clocks locally.
"""
from contextlib import contextmanager
from copy import deepcopy
import hashlib
import sys
from pathlib import Path

from scripts import retailrocket_session_knn_checkpoint_v2 as checkpoint
from scripts import retailrocket_session_knn_cold_v47 as cold
from scripts import retailrocket_session_knn_reuse_v27 as reuse
from scripts import retailrocket_session_knn_typed_adapter_v39 as adapter
from scripts import retailrocket_session_knn_typed_v39 as typed
from scripts import retailrocket_session_knn_typed_string_v46 as candidate
from scripts import run_retailrocket_session_knn_v2 as io
from tests import retailrocket_session_knn_wall_cpu_fixture_v64 as literal
from tests import test_retailrocket_session_knn_wall_cpu_entry_v64 as entry


ROOT = Path(__file__).resolve().parents[1]
METHOD_NAMES = (
    'scripts/retailrocket_session_knn_reuse_v27.py',
    'scripts/retailrocket_session_knn_typed_adapter_v39.py',
    'scripts/retailrocket_session_knn_typed_v39.py',
    'scripts/retailrocket_session_knn_typed_string_v46.py',
    'scripts/retailrocket_session_knn_cold_v47.py',
    'scripts/retailrocket_session_knn_snapshot_adapter_v30.py',
    'scripts/retailrocket_session_knn_snapshot_v30.py',
    'scripts/retailrocket_session_knn_pair_v4.py',
    'scripts/retailrocket_session_knn_sql_v4.py',
    'scripts/retailrocket_session_knn_sources_v24.py',
    'scripts/retailrocket_session_knn_wall_cpu_adapter_v64.py')
UNICODE_VALUES = ['繁體中文與 emoji 😀', '"反斜線\\換行\n定位\t退格\b',
                  '\x00\x01\x1f', 'literal \\u2603', '', -0.0, True, None,
                  {'巢狀': [1, 10**30, 0.125, False]}]


def describe(path):
    path = Path(path).resolve()
    data = path.read_bytes()
    return dict(path=path.relative_to(ROOT).as_posix(), bytes=len(data),
                sha256=hashlib.sha256(data).hexdigest())


def build_fixture(root):
    fixture = literal.build_fixture(root)
    # These additional fields are actually consumed by the complete typed roots,
    # while scientific predictions continue to use the literal support/catalog.
    fixture['config']['typed_fixture_values'] = deepcopy(UNICODE_VALUES)
    fixture['model']['typed_fixture_values'] = deepcopy(UNICODE_VALUES)
    (fixture['root']/'configuration.json').write_bytes(checkpoint.encoded(fixture['config']))
    (fixture['root']/'model.json').write_bytes(checkpoint.encoded(dict(receipt=fixture['model'])))
    names = [row['path'] for row in fixture['binding']['sources']]
    fixture['binding'] = dict(fixture['binding'], configuration=deepcopy(fixture['config']),
        sources=checkpoint.bind_sources(fixture['root'], names),
        method='v65_literal_sources_for_real_typed_workers')
    by_name = {row['path']: row for row in fixture['binding']['sources']}
    methods = [io.describe(ROOT/name) for name in METHOD_NAMES]
    dependencies = {key: by_name[path] for key, path in (
        ('counts', 'P0/item_counts.csv'), ('catalog', 'dataset/catalog.csv'),
        ('config', 'configuration.json'), ('model', 'model.json'))}
    request = entry.request_for_entry()
    request['sources'] = [*fixture['binding']['sources'], *methods]
    request['metadata'].update(context=dict(dependencies=dependencies, methods=methods),
                               environment=io.environment())
    fixture['request'] = request
    fixture['contract'] = adapter.context_contract(request, fixture['binding'])
    return fixture


class FakeClock(entry.SharedFakeClock):
    def __init__(self):
        super().__init__()
        self.passive_calls = 0

    def passive(self):
        self.passive_calls += 1
        return self.ns()


def worker_class(decoder, clock):
    """Retain real worker/load code and change only its passive clock binding."""
    if decoder == 'V39':
        base, load_base = adapter.WorkerContext, adapter._Load
    elif decoder == 'V46':
        base, load_base = cold.CandidateContext, cold.CandidateLoad
    else:
        raise ValueError('Expected V39 or V46')

    class InvocationLoad(load_base):
        __init__ = literal.clone(adapter._Load.__init__, _PASSIVE_CLOCK=clock.passive)

    class InvocationWorker(base):
        load = literal.clone(base.load, _Load=InvocationLoad)

    return InvocationWorker, InvocationLoad


def store_class(clock):
    # C3 places ObservedStore before the injected detailed/budget/timed classes.
    # Genuine ReuseStore.create/_check_sources and ObservedStore.writer remain
    # in the MRO; the worker's exact original store admission checks still run.
    detailed = literal.detailed_store_class(clock.seconds)

    class InvocationStore(reuse.ReuseStore, detailed):
        pass

    return InvocationStore


@contextmanager
def typed_call_counts():
    """Test-only call observation, no wrappers, clocks, SQL or sampled timings.

    V39 and V46 decode share a code object; their original function globals
    distinguish which actual decoder body is entered. The callback returns
    before the observed body runs, preserving capture_runtime's call depth.
    """
    before = sys.getprofile()
    if before is not None:
        raise ValueError('Synthetic call evidence requires no preexisting profiler')
    counts = dict(V39_decode=0, V46_decode=0, verified_reference=0, late_compare=0)
    def observe(frame, event, argument):
        if event != 'call':
            return
        code = frame.f_code
        if code is typed._decode.__code__:
            if frame.f_globals is typed._decode.__globals__:
                counts['V39_decode'] += 1
            elif frame.f_globals is candidate.decode.__globals__:
                counts['V46_decode'] += 1
            else:
                raise AssertionError('Unexpected decoder namespace')
        elif code is typed._build_verified_reference.__code__:
            counts['verified_reference'] += 1
        elif code is typed.compare_with_stats.__code__:
            counts['late_compare'] += 1
    sys.setprofile(observe)
    try:
        yield counts
    finally:
        sys.setprofile(before)
