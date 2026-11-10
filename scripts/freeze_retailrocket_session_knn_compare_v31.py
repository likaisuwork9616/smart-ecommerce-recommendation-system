"""Freeze the single C1-S1 original48 real comparison activation; never measure."""
import argparse
from datetime import datetime,timezone

from scripts.run_retailrocket_session_knn_v2 import ROOT,read,describe,verify_bindings,environment,check_gates
from scripts.run_retailrocket_session_knn_gap_v7 import public_json
from scripts import accept_retailrocket_session_knn_snapshot_v30 as s1
from scripts import freeze_retailrocket_session_knn_serialization_v29 as design
from scripts.retailrocket_session_knn_cost_window_v5 import LIMITS
from scripts.retailrocket_session_knn_snapshot_v30 import SCHEME

BASE='reports/stage12/retailrocket_session_knn_v31_compare_'
SPEC=BASE+'specification_20261110.json';SEAL=BASE+'seal_20261110.json'
METHOD='scripts/freeze_retailrocket_session_knn_compare_v31.py'
PARENT_ACCEPT_SHA='59af3b0b3e1b9e36d80f7facf2ab8a9b954bb03ef683d9077d35cfcb01c6de8e'
METHODS=(METHOD,'scripts/run_retailrocket_session_knn_compare_v31.py',
    'tests/test_retailrocket_session_knn_compare_v31.py','scripts/analyze_retailrocket_session_knn_compare_v31.py')
SUITES=('tests.test_retailrocket_session_knn_compare_v31',*s1.SUITES)


def parents():
    spec=s1.sealed_design();accepted=read(ROOT/s1.REPORT)
    if (describe(ROOT/s1.REPORT)['sha256']!=PARENT_ACCEPT_SHA
            or accepted['status']!='v30_C1_S1_core_and_independent_publisher_synthetic_accepted'
            or accepted['specification']!=describe(ROOT/design.SPEC) or accepted['case_to_passed_tests']!=s1.COVERAGE
            or accepted['methods']!=[describe(ROOT/p) for p in s1.METHODS]
            or accepted['scope']!=s1.scope() or accepted['operation_counts']!=s1.operation_counts()
            or any(accepted[k]!=0 for k in ('failures','errors','skipped'))):
        raise ValueError('Unchanged accepted S1 implementation required')
    s1.validate_results(accepted['passed_test_ids'],accepted['tests_run'],accepted['tests_by_module'])
    verify_bindings([*accepted['methods'],accepted['log'],*accepted['integration']['evidence']])
    parent=read(ROOT/spec['parent_real_entry_specification']['path'])
    return spec,accepted,parent


def evidence(accepted,parent):
    records=[describe(ROOT/METHOD),describe(ROOT/design.SPEC),describe(ROOT/design.SEAL),describe(ROOT/s1.REPORT),
        *accepted['methods'],accepted['log'],*accepted['integration']['evidence']]
    records.extend([describe(ROOT/'reports/stage12/retailrocket_session_knn_v28_compare_specification_20261109.json')])
    base=read(ROOT/design.SPEC)
    _,record=original_context(base);records.append(record)
    unique={}
    for item in records:
        if item['path'] in unique and unique[item['path']]!=item:raise ValueError('Conflicting evidence identity')
        unique[item['path']]=item
    return [unique[k] for k in sorted(unique)]


def original_context(base):
    inventory=read(ROOT/base['parent_inventory']['path'])
    report=read(ROOT/inventory['inputs'][0]['path'])
    path=report['namespace']+'/request.json'
    records=[x for x in report['evidence'] if x['path']==path]
    if len(records)!=1:raise ValueError('One sealed original V28 real request required')
    verify_bindings(records);request=read(ROOT/path)
    if request['sources']!=base['inherited_sources']:raise ValueError('Original real closure changed')
    sources={x['path']:x for x in request['sources']};methods=request['metadata']['context']['methods']
    if len(methods)!=17 or any(sources.get(x['path'])!=x for x in methods):
        raise ValueError('Every original per-borrow method identity must remain exact')
    return methods,records[0]


def make_spec(spec,accepted,parent):
    return dict(status='v31_C1_S1_original48_real_entry_specification_frozen',created_utc=datetime.now(timezone.utc).isoformat(),
        parent_specification=describe(ROOT/design.SPEC),parent_acceptance=describe(ROOT/s1.REPORT),
        parent_real_entry_specification=describe(ROOT/'reports/stage12/retailrocket_session_knn_v28_compare_specification_20261109.json'),
        evidence=evidence(accepted,parent),inherited_sources=spec['inherited_sources'],
        original_binding_sources=spec['original_binding_sources'],cohort=parent['cohort'],context_inputs=parent['context_inputs'],
        original_semantic_methods=parent['original_semantic_methods'],original_context_methods=original_context(spec)[0],
        original48_reference=parent['original48_reference'],
        fingerprint_scheme=SCHEME,schedule=parent['schedule'],decision=parent['decision'],
        environment=environment(),gates=check_gates(),budget_seconds=1800,limits=LIMITS,
        activation=dict(candidate='C1-S1-schema-snapshot-v1',authorized_real_runs=14,queries_per_run=48,engineering_checks=672,
            gate='Commit this frozen specification, then pass and commit the unchanged new entry/methods/tests synthetic acceptance before the single --measure window.'),
        execution=dict(topology='One V5 supervisor covers one sequential worker and the later independent publisher under one absolute deadline.',
            reference='Fresh original R in this same window; do not use historical V28 C1 costs as a fair baseline.',
            worker='Original48 R/C warmups plus six alternating RC/CR pairs,14 fresh stores; only one worker and one borrowed C1-S1 snapshot, one cold plus six hits.',
            context='All1261 original closure and15 original binding identities stay exact. Append new versioned scheme/spec/method/acceptance evidence, with full request/namespace/process/config/model and all method identities in the original key.',
            source_checks='Worker/publisher before and after full closure; original create and forced post-OS-lock full binding for every run; all14 publisher opens and proofs.',
            publisher='A new interpreter after normal worker exit rebuilds the original counts/catalog/model context and fingerprints it itself. No worker snapshot/encoded bytes/token is received.',
            integrity='Scheme required in request, cache.use, completed receipt and publisher. Keep all15 live worker fingerprints and every original identity/config/model check.',
            timing='Same fine observers on R/C. Charge all validation/copy/JSON/UTF8/SHA/release and cold/pre/post guards inside full entry; retain cold warmup in seven-run sums. Publish worker/publisher/window/public serialization separately.',
            telemetry='Original200ms target sampler for each entry and publisher, raw brackets/gaps and sequential nonoverlap retained. Observe Ollama processes only; no Ollama token/GPU speed measurement.',
            restart='Same OS exclusive guard as the previous original48 comparison. Exactly one real namespace; any existing failed/completed request or report forbids automatic retry. --release only re-audits saved evidence.'),
        acceptance=dict(methods=list(METHODS),suites=list(SUITES),required_parent_cases=70,
            requirements='All new real-entry tests plus all167 V30-selected regressions pass without failures/errors/skips. Audit the artificial14-store48-query window using the new worker and publisher, physical bytes, source/scheme/events/load/cost/seals/failure refusal.',
            real_runs=0),scope=parent['scope'],measured_speedup=None,T_plan=None)


def validate(spec,base,accepted,parent):
    expected=make_spec(base,accepted,parent);expected['created_utc']=spec['created_utc']
    if spec!=expected:raise ValueError('Frozen S1 activation differs from original scope/methods/fair gates')
    if len(spec['inherited_sources'])!=1261 or len(spec['original_binding_sources'])!=15:
        raise ValueError('The original1261/15 identities must remain exact')


def audit():
    base,accepted,parent=parents();seal=read(ROOT/SEAL)
    verify_bindings([seal['specification'],*seal['evidence']]);spec=read(ROOT/SPEC)
    validate(spec,base,accepted,parent)
    if seal['evidence']!=spec['evidence'] or seal['real_runs']!=0:raise ValueError('Activation seal changed')
    return spec


def freeze():
    if (ROOT/SPEC).exists() or (ROOT/SEAL).exists():raise FileExistsError('Immutable S1 activation already exists')
    base,accepted,parent=parents();spec=make_spec(base,accepted,parent);validate(spec,base,accepted,parent)
    public_json(ROOT/SPEC,spec,exclusive=True)
    public_json(ROOT/SEAL,dict(status='v31_C1_S1_real_activation_sealed',specification=describe(ROOT/SPEC),
        evidence=spec['evidence'],real_runs=0),exclusive=True)
    print(dict(specification=describe(ROOT/SPEC),original_closure=1261,original_binding=15,authorized_real_runs=14,real_runs=0))


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__);mode=parser.add_mutually_exclusive_group(required=True)
    mode.add_argument('--specification',action='store_true');mode.add_argument('--audit',action='store_true')
    if parser.parse_args().audit:print(dict(status=audit()['status'],real_runs=0,audit=True))
    else:freeze()
