"""Audit current cold caller ownership; do not remove any temporal content guard."""
import argparse
import ast
from collections import Counter
from contextlib import redirect_stdout, redirect_stderr
from datetime import datetime, timezone
import hashlib
import math
from time import perf_counter
import unittest
from uuid import uuid4

from scripts.run_retailrocket_session_knn_v2 import ROOT, read, describe, verify_bindings
from scripts.run_retailrocket_session_knn_gap_v7 import PRIVATE, public_json
from scripts import freeze_retailrocket_session_knn_canonical_v36 as prior

BASE = 'reports/stage12/retailrocket_session_knn_v37_ownership_'
INVENTORY = BASE + 'inventory_20261110.json'
SPEC = BASE + 'decision_20261110.json'
SEAL = BASE + 'seal_20261110.json'
METHOD = 'scripts/freeze_retailrocket_session_knn_ownership_v37.py'
TEST = 'tests/test_retailrocket_session_knn_ownership_v37.py'
SUITES = ('tests.test_retailrocket_session_knn_ownership_v37', prior.SUITE)

# Whole-file identities plus exact AST spans make this a reviewable source audit,
# not an inference that a successful endpoint hash proves continuous immutability.
TARGETS = {
    'scripts/run_retailrocket_session_knn_v2.py': ('read',),
    'scripts/run_retailrocket_session_knn_sources_v25.py': ('inputs',),
    'scripts/run_retailrocket_session_knn_diagnostics_v35.py': ('inputs', 'run_cold_cycle'),
    'scripts/run_retailrocket_session_knn_compare_v28.py': ('run_worker',),
    'scripts/run_retailrocket_session_knn_compare_v31.py': ('worker',),
    'scripts/retailrocket_session_knn_snapshot_adapter_v30.py': ('context_contract', 'WorkerContext.load'),
    'scripts/retailrocket_session_knn_diagnostics_v35.py': ('WorkerContext.load',),
    'scripts/retailrocket_session_knn_pair_v4.py': ('verify_selected',),
    'scripts/retailrocket_session_knn_reuse_v27.py': (
        'canonical', 'WorkerContext.__init__', 'WorkerContext._identity',
        'WorkerContext.load', 'WorkerContext.finish', 'make_verifier'),
    'scripts/retailrocket_session_knn_readback_v2.py': ('load_context',),
    'scripts/retailrocket_session_knn_sql_v2.py': ('FrozenCatalog', 'prepare_catalog'),
    'scripts/retailrocket_session_knn_sources_v24.py': ('Observation.__init__', 'Observation.span'),
    'scripts/retailrocket_session_knn_monitor_v3.py': ('ThrottledWatch',),
}
FINDINGS = [
    dict(id='json_roots', verdict='mutable', anchors=['read', 'inputs'],
         finding='Production input loaders parse JSON into ordinary mutable dict/list graphs. Fresh parsing establishes provenance, not recursive immutability or transfer of exclusive ownership.'),
    dict(id='retained_aliases', verdict='not_exclusive', anchors=['run_worker', 'WorkerContext.__init__', 'WorkerContext.load', 'make_verifier'],
         finding='Worker data, verifier arguments/closures and active borrower retain references. The constructor retains the contract by reference; no recursive copy/freeze or alias revocation is performed.'),
    dict(id='support_alias', verdict='shared_mutable', anchors=['WorkerContext.load', 'load_context'],
         finding='support must be the identical model[support] object. The original loader reads this shared dict with watch callbacks; an equal detached copy is explicitly rejected.'),
    dict(id='watch_edge', verdict='ownership_not_enforced', anchors=['WorkerContext.load', 'load_context', 'prepare_catalog', 'ThrottledWatch'],
         finding='The production ThrottledWatch checks budget/deadline and does not receive config/model explicitly. The admitted load API accepts a callable without enforcing this exact class, method identity or capture-free capability; synthetic watch mutations are admitted.'),
    dict(id='observer_edge', verdict='ownership_not_enforced', anchors=['Observation.__init__', 'Observation.span', 'WorkerContext.load'],
         finding='The normal Observation writes events and calls its supplied clock. The load API does not restrict observer type, span entry/exit or custom clock capabilities. Span callbacks run between early comparison and late capture.'),
    dict(id='initialization_reentry', verdict='not_a_busy_guard', anchors=['WorkerContext.load'],
         finding='The active borrower is checked and assigned only after cold construction and pre-use digest. It does not establish exclusion of reentrant callbacks during initialization. This is a source-level limitation, not a claim that production reentry was observed.'),
    dict(id='original_callees', verdict='read_only_body_is_insufficient', anchors=['WorkerContext._identity', 'load_context', 'prepare_catalog'],
         finding='Original function identities are checked and their bodies read caller inputs; they call watch. No direct assignment in a callee body is not proof that callbacks or retained aliases cannot mutate the graph.'),
    dict(id='snapshot_boundary', verdict='separate_owned_value', anchors=['FrozenCatalog', 'prepare_catalog', 'WorkerContext.load'],
         finding='Prepared catalog copies numeric/string maps and uses mapping proxies and tuples; complete snapshot validation remains. That separate snapshot does not freeze the original config/model/support graph.'),
    dict(id='bytes_boundary', verdict='value_only', anchors=['canonical', 'WorkerContext.load', 'WorkerContext.finish'],
         finding='Canonical bytes are immutable values, not a lock on their input graph. MappingProxyType protects only writes through that view; backing aliases and mutable descendants remain. List-to-tuple deep freezing changes typed canonical identity.'),
    dict(id='source_lock_boundary', verdict='not_memory_ownership', anchors=['WorkerContext._identity', 'WorkerContext.finish'],
         finding='Fresh writer lock, create/post-lock full source checks, source/method identity and process ownership remain required. They protect source/store/process identity, not recursive in-memory alias exclusion.'),
    dict(id='temporal_boundary', verdict='late_observation_required', anchors=['WorkerContext.load', 'WorkerContext.finish'],
         finding='Original late canonical captures state after load/prepare. V36 ABA counterexamples prove that retaining early bytes alone weakens the original final comparison. Discrete guards do not promise continuous mutation detection.'),
]
PREREQUISITES = {
    'graph_ownership': [
        'Prove provenance and exclusive ownership of both roots and every mutable descendant, including support and schema/window lists.',
        'Exclude mutation-capable aliases outside the proved owner region from early comparison through the original late boundary; internal proven read-only nonescaping parameter aliases may remain.',
        'Preserve original complete typed canonical identity; list-to-tuple conversion or detached-copy comparison is not equivalent.',
        'Define how every admitted input type obtains the invariant; an immutable=True assertion or equal endpoint digest is not proof.',
    ],
    'callback_capabilities': [
        'Audit unchanged original callees together with every transitive callback, not merely direct assignment syntax.',
        'Bind and enforce watch implementation and captures or remove mutation capability without removing required watch calls.',
        'Bind observer span entry/exit, supplied clock and all reentrant hooks; a normal production default alone is insufficient.',
        'Keep caller-visible references inaccessible to other admitted mutation routes during the proved interval; worker PID alone does not establish this.',
    ],
    'temporal_equivalence': [
        'Keep a complete content observation at the original after-prepare point before cache.use/borrow/query; missing ownership proof forbids deleting the two calls.',
        'Reject all V36 late ABA and late unsupported/NaN cases with original or stronger timing, with full poison cleanup.',
        'Retain every final live config/model check and distinguish transient restoration before versus across existing boundaries.',
        'Any new typed comparator at the late point needs its own canonical-equivalence specification and acceptance; it is not ownership-based byte reuse.',
    ],
    'identity_accounting': [
        'Retain all original and current source/method identities append-only, complete request/config/model key and original 15 binding checks.',
        'Retain create and post-lock full verification, one-cold/six-hit snapshot checks and independent publisher rebuild/stopped-log seal.',
        'Charge all ownership/copy/freeze/comparison work inside the same entry and cold timings; no hidden preload or cross-worker cache.',
        'Bind a new policy in methods/spec/request/events/receipt/publisher and pass mapped synthetic acceptance before a separately frozen sequential original48 comparison.',
    ],
}


def source_inventory():
    records = []
    for path, wanted in TARGETS.items():
        data = (ROOT/path).read_bytes(); lines = data.splitlines(keepends=True)
        tree = ast.parse(data.decode('utf-8-sig'), filename=path)
        nodes = {}
        def visit(body, prefix=''):
            for node in body:
                if isinstance(node, (ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
                    name = prefix + node.name; nodes[name] = node
                    visit(node.body, name + '.')
        visit(tree.body); spans = []
        for name in wanted:
            if name not in nodes: raise ValueError('Missing audited source anchor: '+path+':'+name)
            node = nodes[name]; start = min([node.lineno] + [n.lineno for n in node.decorator_list])
            chunk = b''.join(lines[start-1:node.end_lineno])
            spans.append(dict(name=name, start_line=start, end_line=node.end_lineno,
                              bytes=len(chunk), sha256=hashlib.sha256(chunk).hexdigest()))
        records.append(dict(source=describe(ROOT/path), anchors=spans))
    names = {x['name'] for row in records for x in row['anchors']}
    if any(name not in names for finding in FINDINGS for name in finding['anchors']):
        raise ValueError('Unbound ownership finding')
    return records


def inherited():
    prior.audit()
    spec = read(ROOT/prior.SPEC); preserved = spec['preserved']
    counts = dict(current_sources=len(preserved['current_sources']), current_methods=len(preserved['current_methods']),
                  original_sources=len(preserved['original_sources']), original_methods=len(preserved['original_methods']),
                  original_binding=len(preserved['original_binding']), initialization_dependencies=len(preserved['dependencies']))
    if counts != dict(current_sources=2092, current_methods=168, original_sources=1937,
                      original_methods=26, original_binding=15, initialization_dependencies=4):
        raise ValueError('Preserved source/method contract changed')
    return dict(records=[describe(ROOT/p) for p in (prior.INVENTORY, prior.SPEC, prior.SEAL)], counts=counts,
                verification_scope='Re-audited sealed V36 source/event/test evidence and exact local code anchors; no new full 12GB closure hash or real context replay.')


def scope():
    return dict(candidate_implemented=False, candidate_tests_run=0, new_real_context_replays=0,
                new_query_runs=0, model_fits=0, full_validation_complete=False, reserved_test='locked',
                covered_cells=55, distinct_comparable_queries=170, distinct_historical_queries=232)


def expected_tests():
    suite = unittest.defaultTestLoader.loadTestsFromNames(SUITES)
    names = prior.ids(suite)
    if len([x for x in names if x.startswith(SUITES[0]+'.')]) < 12 or len(names) != len(set(names)):
        raise ValueError('Ownership coverage missing or duplicated')
    if len([x for x in names if x.startswith(SUITES[1]+'.')]) != 6:
        raise ValueError('All six original temporal counterexamples required')
    return names


def inventory():
    if (ROOT/INVENTORY).exists(): raise FileExistsError('Immutable ownership inventory exists; use --audit')
    inherited_value = inherited(); sources = source_inventory(); methods = [describe(ROOT/p) for p in (METHOD, TEST)]
    expected = expected_tests(); folder = PRIVATE/('knn-v37-ownership-'+uuid4().hex); folder.mkdir()
    start = perf_counter()
    with (folder/'tests.log').open('x', encoding='utf-8') as log, redirect_stdout(log), redirect_stderr(log):
        result = unittest.TextTestRunner(stream=log, verbosity=2, resultclass=prior.Result).run(
            unittest.defaultTestLoader.loadTestsFromNames(SUITES))
    if not result.wasSuccessful() or result.skipped or Counter(result.passed) != Counter(expected):
        raise ValueError('Ownership/original temporal verification failed: '+str(folder/'tests.log'))
    verify_bindings(methods + [row['source'] for row in sources])
    value = dict(status='v37_current_cold_ownership_not_immutable_verified',
                 created_utc=datetime.now(timezone.utc).isoformat(), inherited=inherited_value,
                 methods=methods, source_audit=sources, findings=FINDINGS,
                 verification=dict(suites=list(SUITES), tests_run=result.testsRun, passed_test_ids=result.passed,
                                   failures=0, errors=0, skipped=0, seconds=perf_counter()-start,
                                   log=describe(folder/'tests.log'),
                                   interpretation='Tiny original API ownership and temporal regression checks; not candidate acceptance or a performance measurement.'),
                 conclusion='Existing admitted caller graph is mutable and not exclusively owned. Current API cannot justify cold canonical 6 to 4 by immutable ownership.',
                 production_limit='No claim that saved production runs actually suffered mutation. Normal defaults are read-only with respect to config/model, but the API does not enforce a closed ownership/capability envelope.',
                 scope=scope(), measured_speedup=None, T_plan=None)
    public_json(ROOT/INVENTORY, value, exclusive=True)
    print(dict(inventory=INVENTORY, tests=result.testsRun, immutable_ownership_proved=False, new_query_runs=0))


def audit_inventory():
    value = read(ROOT/INVENTORY); v = value['verification']
    verify_bindings(value['methods'] + [v['log']] + [r['source'] for r in value['source_audit']])
    if (value['inherited'] != inherited() or value['source_audit'] != source_inventory()
            or value['methods'] != [describe(ROOT/p) for p in (METHOD, TEST)] or value['findings'] != FINDINGS
            or value['status'] != 'v37_current_cold_ownership_not_immutable_verified'
            or value['scope'] != scope() or value['measured_speedup'] is not None or value['T_plan'] is not None
            or v['suites'] != list(SUITES) or Counter(v['passed_test_ids']) != Counter(expected_tests())
            or v['tests_run'] != len(v['passed_test_ids'])
            or any(type(v[k]) is not int or v[k] != 0 for k in ('failures', 'errors', 'skipped'))
            or type(v['seconds']) not in (int, float) or not math.isfinite(v['seconds']) or v['seconds'] < 0
            or value['conclusion'] != 'Existing admitted caller graph is mutable and not exclusively owned. Current API cannot justify cold canonical 6 to 4 by immutable ownership.'
            or value['production_limit'] != 'No claim that saved production runs actually suffered mutation. Normal defaults are read-only with respect to config/model, but the API does not enforce a closed ownership/capability envelope.'
            or v['interpretation'] != 'Tiny original API ownership and temporal regression checks; not candidate acceptance or a performance measurement.'):
        raise ValueError('Ownership inventory contract differs')
    return value


def decision(inv):
    return dict(status='v37_ownership_based_six_to_four_not_admitted', inventory=describe(ROOT/INVENTORY),
                inherited=inv['inherited'], methods=inv['methods'], verification_log=inv['verification']['log'],
                finding='Current config/model/support alias graph and callback API do not satisfy immutable ownership. Keep six cold canonical calls and the original late complete observation.',
                admitted=False, candidate_implemented=False,
                call_accounting=dict(cold_canonical=6, initial_live_source=4, original_late_live=2,
                                     all7_generic_canonical=41, all7_live_snapshot_fingerprints=15, all7_digests=22),
                safe_existing_design=dict(specification=describe(ROOT/prior.SPEC),
                    policy='C1-S1-cold-canonical-source-anchor-v1', status='still_design_only',
                    behavior='V36 retains full live canonical at the original late boundary and compares with validated source bytes before borrow; no ownership shortcut is admitted.'),
                prerequisites_for_future_ownership_candidate=PREREQUISITES, prerequisite_count=16,
                prohibited_shortcuts=['PID or writer-lock ownership as recursive memory ownership',
                    'Read-only callee body while leaving callbacks or caller aliases unrestricted',
                    'MappingProxy-only wrapper, retained bytes, copied graph or equal endpoint hash as proof',
                    'Deep freeze changing list/tuple semantic identity or skipping original caller checks',
                    'New boolean ownership flag without an enforced invariant',
                    'Moving complete content checks after borrow/query or relying only on independent publication'],
                next_engineering_option='If serialization reduction is still desired, separately specify a complete canonical-equivalent typed comparator at the original late boundary, or design and enforce a new exclusive-ownership API. Neither is implemented or accepted here.',
                preserved='All source/method identities, complete identity key, original create/post-lock checks, final live content checks, complete snapshot checks and independent publisher/stopped-log validation remain unchanged. No old method or result is edited.',
                interpretation='Feasibility verification of current API only; no performance adoption, no estimated saving from V35 timing, no original48 replay.',
                scope=scope(), measured_speedup=None, T_plan=None)


def freeze():
    if (ROOT/SPEC).exists() or (ROOT/SEAL).exists(): raise FileExistsError('Immutable ownership decision exists')
    inv = audit_inventory(); value = dict(decision(inv), created_utc=datetime.now(timezone.utc).isoformat())
    public_json(ROOT/SPEC, value, exclusive=True)
    public_json(ROOT/SEAL, dict(status='v37_ownership_feasibility_sealed', inventory=describe(ROOT/INVENTORY),
                              decision=describe(ROOT/SPEC), six_to_four_admitted=False,
                              tests_run=inv['verification']['tests_run'], new_query_runs=0), exclusive=True)
    print(dict(decision=SPEC, six_to_four_admitted=False, cold_canonical=6, future_prerequisites=16))


def audit():
    inv = audit_inventory()
    if (ROOT/SPEC).exists():
        value = read(ROOT/SPEC); seal = read(ROOT/SEAL)
        verify_bindings([seal['inventory'], seal['decision']])
        if {k:v for k,v in value.items() if k != 'created_utc'} != decision(inv):
            raise ValueError('Ownership decision differs')
        if seal != dict(status='v37_ownership_feasibility_sealed', inventory=describe(ROOT/INVENTORY),
                        decision=describe(ROOT/SPEC), six_to_four_admitted=False,
                        tests_run=inv['verification']['tests_run'], new_query_runs=0):
            raise ValueError('Ownership decision seal differs')
    print(dict(audit=True, tests=inv['verification']['tests_run'], cold_canonical=6, six_to_four_admitted=False))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__); mode = parser.add_mutually_exclusive_group(required=True)
    for name in ('inventory', 'decision', 'audit'): mode.add_argument('--'+name, action='store_true')
    args = parser.parse_args()
    if args.inventory: inventory()
    elif args.decision: freeze()
    else: audit()
