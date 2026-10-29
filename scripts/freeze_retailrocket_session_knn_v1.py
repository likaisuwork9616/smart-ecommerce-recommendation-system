"""Freeze/verify Stage 12 metadata and bytes. No fitting or data-row decoder."""
import argparse
import hashlib
import json
import re
from pathlib import Path
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
from scripts import archive_retailrocket_three_arm_v1 as prior

POLICY = 'docs/contracts/retailrocket_session_knn_paired_v1.json'
INVENTORY = 'reports/stage12/retailrocket_stage12_inventory_v1.json'
DOC = 'docs/STAGE12_TEMPORAL_AVAILABILITY_AND_KNN_SPEC_V1.md'
REPORT = 'reports/stage12/retailrocket_session_knn_v1_specification.json'
PRIVATE = 'shop-mysql-runtime/retailrocket_session_knn_spec_v1'
EVIDENCE = 'shop-mysql-runtime/verification/retailrocket-stage12-spec-v1'
NEW = [POLICY, INVENTORY, DOC, 'scripts/freeze_retailrocket_session_knn_v1.py',
       'tests/test_retailrocket_session_knn_spec.py', EVIDENCE + '/prepare_spec.py']
K1_EXECUTION = 'shop-mysql-runtime/retailrocket_session_knn_paired_v1'
K1_FORBIDDEN = ['shop-mysql-runtime/retailrocket_session_knn_final_v1'] + [
    K1_EXECUTION + '/' + suffix for suffix in ('final_refit', 'reserved_test', 'test_usage.jsonl')]


def path(root, name):
    return prior.inside(root, name)


def read(root, name):
    if not name.endswith('.json'):
        raise ValueError('Only metadata JSON may be decoded')
    return json.loads(path(root, name).read_text(encoding='utf-8'))


def describe(root, name):
    target = path(root, name)
    with target.open('rb') as stream:
        sha = hashlib.file_digest(stream, 'sha256').hexdigest()
    return {'path': name, 'bytes': target.stat().st_size, 'sha256': sha}


def check(root, record):
    if describe(root, record['path']) != {k: record[k] for k in ('path', 'bytes', 'sha256')}:
        raise ValueError('Frozen bytes differ: ' + record['path'])


def write_new(root, name, obj):
    target = path(root, name)
    target.parent.mkdir(parents=True, exist_ok=True)
    with target.open('x', encoding='utf-8', newline='\n') as stream:
        json.dump(obj, stream, ensure_ascii=False, indent=2, allow_nan=False)
        stream.write('\n')


def validate(policy, inventory, parent):
    checks = []
    def equal(label, actual, expected):
        # JSON identity distinguishes true from 1 and forbids nonfinite numbers.
        if json.dumps(actual, sort_keys=True, allow_nan=False) != json.dumps(expected, sort_keys=True, allow_nan=False):
            raise ValueError('Stage 12 specification mismatch: ' + label)
        checks.append(label)
    equal('protocol', policy['protocol_id'], 'retailrocket_session_knn_paired_v1')
    equal('version', policy['version'], 1)
    equal('candidate', policy['comparison']['challenger'], 'K1')
    equal('candidate count', policy['comparison']['challenger_count'], 1)
    equal('primary control', policy['comparison']['primary_control'], 'C1')
    equal('descriptive controls', policy['comparison']['descriptive_controls'], ['P0', 'D1'])
    equal('fixed validation', policy['fixed_validation'], parent['fixed_validation'])
    for key, expected in {'fit_roles':['train'], 'evaluation_roles':['validation'], 'search':False,
                         'fit_window_utc':['2015-05-04T00:00:00Z','2015-08-01T00:00:00Z'],
                         'evaluation_window_utc':['2015-08-01T00:00:00Z','2015-09-01T00:00:00Z'],
                         'deterministic':True, 'model_seeds':None, 'final_refit':False, 'test_ranking':False,
                         'reference_refits_or_rerankings':0, 'statistics_update_during_evaluation':False}.items():
        equal('comparison.'+key, policy['comparison'][key], expected)
    for key, expected in {'neighbor_count':500, 'similarity':'|H intersection T_s| / (|H| + |T_s| - |H intersection T_s|)',
                         'neighbor_order':['similarity descending','numeric visitorid ascending','integer session_start_ms ascending'],
                         'self_item_votes':True, 'repeat_items_in_H_or_T_count_once':True,
                         'session_end_or_recency_weight':False, 'time_decay':None, 'IDF':None, 'history_cap':None}.items():
        equal('model.'+key, policy['model'][key], expected)
    equal('full neighbor pool', policy['model']['index'], 'Exact item-to-train-session inverted index and full distinct T_s; no sampled sessions, recent-session cap, pruning or ANN.')
    equal('unknown seeds', policy['model']['unknown_seeds'], 'Retain all unknown items in H and in Jaccard union denominator; they contribute no train overlaps. Do not drop unknown seeds or the query.')
    equal('self-session rule', policy['model']['neighbor_eligibility'], 'All train sessions with positive overlap with H, excluding exact current (visitorid,session_start_ms). Other train sessions of the same visitor remain eligible.')
    equal('primary estimand', policy['evaluation']['primary_estimand'], 'mean_q(NDCG_K1(q)-NDCG_C1(q))')
    equal('no performance gate', policy['evaluation']['performance_pass_threshold'], None)
    for key in ('replicates','seed','numpy_version','bit_generator','draw','confidence_level','quantiles','quantile_method'):
        equal('bootstrap.'+key, policy['uncertainty'][key], parent['uncertainty'][key])
    equal('only primary interval', policy['uncertainty']['secondary_comparison_intervals'], False)
    equal('limits', policy['resources']['limits'], parent['resources_and_next_entry']['limits'])
    equal('scope', policy['scope_this_round'], {
        'event_or_query_rows_parsed':0, 'new_model_fits':0, 'new_ranked_queries':0, 'new_metric_runs':0,
        'new_bootstrap':0, 'final_refits':0, 'test_queries_scored':0, 'specification_only':True,
        'K1_implemented':False, 'train_cost_scan_executed':False, 'bulk_event_payloads_downloaded':0})
    for key, expected in {'state':'locked','enabled_this_round':False,'K1_test_authorized':False,
                         'future_final_selection_refit_test_protocol_required':True,
                         'create_test_output_or_usage_journal':False,'logical_tests_consumed_this_round':0}.items():
        equal('test.'+key, policy['reserved_test'][key], expected)
    equal('no accepted new source', inventory['new_temporal_sources_accepted'], 0)
    equal('same manifest names/sizes', inventory['retailrocket_file_names_and_sizes_match_existing'], True)
    equal('no remote hash claim', inventory['retailrocket_remote_payload_rehashed'], False)
    equal('source IDs', [s['id'] for s in inventory['sources']], ['retailrocket','multicategory','cosmetics'])
    for source in inventory['sources']:
        equal(source['id']+'.metadata HTTP', source['http_status'], [200,200])
        equal(source['id']+'.pagination', source['next_page_token'], '')
    selected = [c for c in inventory['candidates'] if c['decision']=='selected']
    equal('one selected inventory candidate', [c['method'] for c in selected], ['K1 exact session-kNN, Jaccard, k=500'])
    equal('ranking k', policy['ranking']['list_length'], 10)
    for key in ('negative_sampling','target_injection','inventory_filter'):
        equal('ranking.'+key, policy['ranking'][key], False)
    return checks


def locked(root, at_freeze=False):
    prior.check_locked(root)
    for name in K1_FORBIDDEN + ([K1_EXECUTION] if at_freeze else []):
        if path(root, name).exists():
            raise ValueError('Forbidden execution namespace: ' + name)


def collect(root):
    receipt = read(root, prior.REPORT)
    bound = {}
    # Carry forward transitive frozen dependencies; only historical navigation snapshots are mutable.
    for item in receipt['sources'] + receipt['external_dependencies']:
        if item['live_role'] != 'mutable_context_snapshot':
            record = {k:item[k] for k in ('path','bytes','sha256')}
            if record['path'] in bound and record != bound[record['path']]:
                raise ValueError('Conflicting historical source identity')
            bound[record['path']] = record
    inventory = read(root, INVENTORY)
    for item in inventory['evidence_files'] + [d for s in inventory['sources'] for d in s['body_identity']]:
        bound[item['path']] = item
    for name in NEW + [prior.REPORT, prior.PRIVATE+'/output_guard.json', prior.PRIVATE+'/archive_manifest.json']:
        current = describe(root, name)
        if name in bound and bound[name] != current:
            raise ValueError('Changed frozen source: '+name)
        bound[name] = current
    bound[receipt['archive']['path']] = receipt['archive']
    for name in sorted(bound):
        check(root, bound[name])
    return [bound[name] for name in sorted(bound)]


def verify(root=ROOT):
    if path(root, PRIVATE+'/failure.json').exists():
        raise ValueError('Partial freeze preserved; inspect failure, do not overwrite v1')
    guard = read(root, PRIVATE+'/output_guard.json')
    for record in guard.values():
        check(root, record)
    receipt = read(root, REPORT)
    for record in receipt['sources']:
        check(root, record)
    checks = validate(read(root,POLICY), read(root,INVENTORY), read(root,'docs/contracts/retailrocket_directed_paired_v1.json'))
    if checks != receipt['consistency_checks']:
        raise ValueError('Consistency checks changed')
    locked(root)
    return {'status':'Stage12_specification_bytes_and_gates_verified','sources_verified':len(receipt['sources']),
            'checks_passed':len(checks),'research_recomputed':False,'reserved_test':'locked'}


def freeze(root=ROOT):
    root = Path(root).resolve()
    if path(root, PRIVATE).exists() or path(root, REPORT).exists():
        raise ValueError('v1 namespace is not empty; use --verify, never overwrite')
    started = time.monotonic()
    locked(root, at_freeze=True)
    policy, inventory = read(root,POLICY), read(root,INVENTORY)
    checks = validate(policy, inventory, read(root,'docs/contracts/retailrocket_directed_paired_v1.json'))
    write_new(root, PRIVATE+'/started.json', {'state':'started','scope':'metadata freeze only','test_enabled':False})
    try:
        result = subprocess.run([sys.executable,'-B','-m','unittest','tests.test_retailrocket_session_knn_spec','-v'],
                                cwd=root, capture_output=True, text=True, encoding='utf-8', timeout=120)
        log = result.stdout + result.stderr
        log_path = path(root, EVIDENCE+'/tests.log')
        with log_path.open('x',encoding='utf-8',newline='\n') as stream:
            stream.write(log)
        if result.returncode != 0:
            raise ValueError('Metadata tests failed; see tests.log')
        count_match = re.search(r'Ran (\d+) tests? in ', log)
        if count_match is None:
            raise ValueError('Missing unittest count')
        sources = collect(root)
        sources.append(describe(root,EVIDENCE+'/tests.log'))
        locked(root, at_freeze=True)
        snapshot = {'state':'locked','K1_test_authorized':False,'logical_test_runs_consumed_this_round':0,
                    'reference_gates':[describe(root,n) for n in prior.GATES], 'K1_forbidden':K1_FORBIDDEN,
                    'execution_absent_at_freeze':K1_EXECUTION}
        write_new(root,PRIVATE+'/initial_locked_scope.json',snapshot)
        sources.append(describe(root,PRIVATE+'/initial_locked_scope.json'))
        receipt = {'status':'K1_specification_frozen_no_model_or_scores','date_asia_taipei':'2026-10-29',
                   'protocol':describe(root,POLICY),'candidate_inventory':describe(root,INVENTORY),
                   'sources':sources,'sources_verified':len(sources),'consistency_checks':checks,
                   'tests':{'command':'python -B -m unittest tests.test_retailrocket_session_knn_spec -v',
                            'returncode':result.returncode,'tests_run':int(count_match.group(1)),
                            'log':describe(root,EVIDENCE+'/tests.log'),
                            'scope':'Synthetic metadata / freeze I/O guards only, not K1 algorithm acceptance'},
                   'scope_this_round':policy['scope_this_round'],'reserved_test':policy['reserved_test'],
                   'verification_kind':'Full SHA/size of inherited frozen research/dependencies and new metadata. No new semantic oracle, CSV/JSONL parsing or ZIP unpacking.',
                   'elapsed_seconds':time.monotonic()-started}
        write_new(root,REPORT,receipt)
        write_new(root,PRIVATE+'/output_guard.json',{'report':describe(root,REPORT),
            'initial_scope':describe(root,PRIVATE+'/initial_locked_scope.json'), 'started':describe(root,PRIVATE+'/started.json')})
        return {'status':receipt['status'],'sources_verified':len(sources),'checks_passed':len(checks),
                'tests_returncode':result.returncode,'reserved_test':'locked'}
    except Exception as exc:
        write_new(root,PRIVATE+'/failure.json',{'state':'failed','error':type(exc).__name__+': '+str(exc)})
        raise


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    action = parser.add_mutually_exclusive_group(required=True)
    action.add_argument('--freeze',action='store_true')
    action.add_argument('--verify',action='store_true')
    args = parser.parse_args()
    print(json.dumps(freeze() if args.freeze else verify(), indent=2))
