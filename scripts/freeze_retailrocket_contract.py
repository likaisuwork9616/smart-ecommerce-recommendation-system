"""Independently reconcile official CSV intake and bind the v1 research contract.

--verify checks preserved bytes only; it never rebuilds data or evaluates models.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import time
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RAW = ROOT/'data/raw/retailrocket'
CONTRACT = ROOT/'docs/contracts/retailrocket_recommendation_v1.json'
AUDIT = ROOT/'reports/stage8/retailrocket_source_audit_v1.json'
ACCEPTANCE = ROOT/'reports/stage8/retailrocket_contract_v1_acceptance.json'
PRIVATE = ROOT/'shop-mysql-runtime/retailrocket_contract_v1'


def descriptor(p):
    h = hashlib.sha256()
    with p.open('rb') as f:
        while b := f.read(1024*1024):
            h.update(b)
    return {'path':p.relative_to(ROOT).as_posix(),'bytes':p.stat().st_size,'sha256':h.hexdigest()}


def freeze():
    import pandas as pd

    started = time.monotonic()
    if PRIVATE.exists() or ACCEPTANCE.exists():
        raise FileExistsError('frozen namespace exists; use --verify')
    audit = json.loads(AUDIT.read_text(encoding='utf-8'))
    contract = json.loads(CONTRACT.read_text(encoding='utf-8'))
    checks = []
    def check(name, actual, expected):
        if actual != expected:
            raise ValueError(f'{name}: actual {actual!r}, expected {expected!r}')
        checks.append({'check':name,'passed':True})
    package = RAW/'ecommerce-dataset-v2.zip'
    check('official_zip_sha',descriptor(package)['sha256'],contract['source']['zip_sha256'])
    check('event_schema',contract['schemas']['events.csv'],['timestamp','visitorid','event','itemid','transactionid'])
    with zipfile.ZipFile(package) as z:
        with z.open('events.csv') as f:
            events = pd.read_csv(f,dtype={'timestamp':'int64','visitorid':'string','event':'string','itemid':'string','transactionid':'string'},keep_default_na=False)
        a = audit['events']
        check('independent_event_rows',len(events),a['rows'])
        check('independent_event_types',events['event'].value_counts().to_dict(),a['event_counts'])
        check('independent_visitors',int(events['visitorid'].nunique()),a['visitors'])
        check('independent_items',int(events['itemid'].nunique()),a['items'])
        check('independent_min_timestamp',int(events['timestamp'].min()),a['min_ms'])
        check('independent_max_timestamp',int(events['timestamp'].max()),a['max_ms'])
        check('independent_exact_duplicates',int(events.duplicated().sum()),a['exact_duplicate_excess'])
        check('independent_four_field_duplicates',int(events.duplicated(subset=['timestamp','visitorid','event','itemid']).sum()),a['four_field_duplicate_excess'])
        check('independent_missing_transactionid',int(events['transactionid'].eq('').sum()),a['missing']['transactionid'])
        check('independent_nonmonotonic_steps',int(events['timestamp'].diff().lt(0).sum()),a['raw_timestamp_backward_steps'])
        simultaneous=events.groupby(['visitorid','timestamp'])['itemid'].nunique()
        check('independent_simultaneous_multi_item_groups',int(simultaneous.gt(1).sum()),a['visitor_timestamp_groups_multiple_items'])
        tx=events.loc[events['event'].eq('transaction')]
        check('independent_transaction_ids',int(tx['transactionid'].nunique()),a['transaction_ids'])
        check('independent_transaction_multi_clock',int(tx.groupby('transactionid')['timestamp'].nunique().gt(1).sum()),a['transaction_ids_multiple_timestamps'])
        props=[]
        prop_parts={}
        for name in ('item_properties_part1.csv','item_properties_part2.csv'):
            n=0
            low=None
            high=None
            with z.open(name) as f:
                for chunk in pd.read_csv(f,dtype={'timestamp':'int64','itemid':'string','property':'string','value':'string'},keep_default_na=False,chunksize=500000):
                    n+=len(chunk)
                    lo=int(chunk['timestamp'].min())
                    hi=int(chunk['timestamp'].max())
                    low=lo if low is None else min(low,lo)
                    high=hi if high is None else max(high,hi)
                    props.append(chunk.loc[chunk['property'].isin(['available','categoryid'])].copy())
            check('independent_'+name+'_rows',n,audit['properties']['parts'][name]['rows'])
            check('independent_'+name+'_min',low,audit['properties']['parts'][name]['min_ms'])
            check('independent_'+name+'_max',high,audit['properties']['parts'][name]['max_ms'])
            prop_parts[name]=n
            print('independent '+name+' checked',flush=True)
        critical=pd.concat(props,ignore_index=True)
        check('independent_critical_duplicates',int(critical.duplicated().sum()),audit['properties']['critical_exact_duplicate_excess'])
        check('independent_critical_conflicts',int(critical.groupby(['itemid','property','timestamp'])['value'].nunique().gt(1).sum()),audit['properties']['critical_same_timestamp_conflict_keys'])
        check('independent_critical_counts',critical['property'].value_counts().to_dict(),audit['properties']['critical_rows'])
        with z.open('category_tree.csv') as f:
            tree=pd.read_csv(f,dtype='string',keep_default_na=False)
        check('independent_category_rows',len(tree),audit['category_tree']['rows'])
        check('independent_category_roots',int(tree['parentid'].eq('').sum()),audit['category_tree']['roots'])
        check('independent_orphan_category_values',int(critical.loc[critical['property'].eq('categoryid') & ~critical['value'].isin(tree['categoryid']),'value'].nunique()),audit['properties']['critical_category_values_not_in_tree'])
    parent=dict(zip(tree['categoryid'],tree['parentid']))
    cycle_nodes=set()
    for child in parent:
        seen=set()
        current=child
        while current in parent and parent[current]:
            if current in seen:
                cycle_nodes.add(current)
                break
            seen.add(current)
            current=parent[current]
    check('category_tree_cycles',len(cycle_nodes),0)
    # Structural view coverage only: no sessions, target pairs or ranking metrics.
    views=events.loc[events['event'].eq('view'),['timestamp','itemid']].sort_values('timestamp')
    prior={}
    for prop in ('available','categoryid'):
        versions=critical.loc[critical['property'].eq(prop),['timestamp','itemid','value']].sort_values('timestamp')
        joined=pd.merge_asof(views,versions,on='timestamp',by='itemid',direction='backward',allow_exact_matches=False)
        prior[prop]={'view_rows':len(joined),'no_strict_prior_value':int(joined['value'].isna().sum()),
                     'strict_prior_value_present':int(joined['value'].notna().sum())}
        if prop=='available':
            prior[prop]['prior_zero']=int(joined['value'].eq('0').sum())
            prior[prop]['prior_one']=int(joined['value'].eq('1').sum())
    roles=[]
    last_end=None
    for role in ('warmup','train','validation','reserved_test'):
        start,end=map(pd.Timestamp,contract['time_roles'][role])
        check(role+'_positive_interval',start<end,True)
        if last_end is not None:
            check(role+'_contiguous_boundary',start,last_end)
        last_end=end
        start_ms=start.value//1000000
        end_ms=end.value//1000000
        subset=events.loc[events['timestamp'].ge(start_ms)&events['timestamp'].lt(end_ms)]
        days=pd.to_datetime(subset['timestamp'],unit='ms',utc=True).dt.floor('D').nunique()
        expected_days=(end-start).days
        # May 3 is deliberately an observed partial-day warmup.
        check(role+'_every_day_has_an_event',int(days),expected_days)
        roles.append({'role':role,'start_utc':start.isoformat(),'end_exclusive_utc':end.isoformat(),
                      'raw_rows':len(subset),'event_counts':subset['event'].value_counts().to_dict(),
                      'observed_utc_days':int(days),'not_an_ingestion_completeness_proof':True})
    tail=events.loc[events['timestamp'].ge(pd.Timestamp(contract['time_roles']['reserved_test'][1]).value//1000000)]
    check('time_roles_and_tail_reconcile',sum(r['raw_rows'] for r in roles)+len(tail),len(events))
    check('no_property_features_in_primary',contract['properties_and_categories']['v1_model_features'],'none; source integrity and temporal availability diagnostics only')
    check('no_evaluation_negative_sampling',contract['candidate_catalog']['negative_sampling'].startswith('none'),True)
    check('source_scope_no_model',audit['scope']['models_trained'],0)
    check('builder_not_implemented',contract['builder_deliverables']['not_yet_implemented'],True)
    PRIVATE.mkdir(parents=True)
    sources=[descriptor(p) for p in (CONTRACT,AUDIT,ROOT/'scripts/freeze_retailrocket_contract.py',ROOT/'scripts/audit_retailrocket_source.py',RAW/'source_manifest.json',RAW/'metadata.response',RAW/'file_list.response',RAW/'license.response',package,ROOT/'shop-mysql-runtime/retailrocket_intake_v1/inventory.sqlite')]
    result={'status':'source_audit_independently_reconciled_contract_v1_frozen','date_asia_taipei':'2026-10-28',
            'verification':{'checks_passed':len(checks),'checks':checks,'independent_reader':'pandas directly from official ZIP; intake uses csv+SQLite',
                            'pandas_version':pd.__version__,'elapsed_seconds':round(time.monotonic()-started,3)},
            'raw_time_role_coverage':roles,'excluded_tail_raw_rows':len(tail),'critical_property_strict_prior_view_coverage':prior,
            'scope':{'source_structure_seen':True,'recommendation_samples_built':0,'model_fits':0,'ranking_metrics_computed':0,'reserved_test_scored':False},
            'sources':sources,'next_step':'implement the v1 builder and independent row-level acceptance before any baseline fit'}
    ACCEPTANCE.write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    (PRIVATE/'input_guard.json').write_text(json.dumps({'sources':sources,'acceptance':descriptor(ACCEPTANCE)},ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print(json.dumps({'status':result['status'],'checks_passed':len(checks),'roles':roles,'property_prior':prior},ensure_ascii=False,indent=2))


def verify():
    guard=json.loads((PRIVATE/'input_guard.json').read_text(encoding='utf-8'))
    for record in [*guard['sources'],guard['acceptance']]:
        p=(ROOT/record['path']).resolve()
        if not p.is_relative_to(ROOT) or descriptor(p)!=record:
            raise ValueError('frozen source drift: '+record['path'])
    print(json.dumps({'status':'contract_and_source_bytes_verified','files':len(guard['sources'])+1,'semantic_recompute':False}))


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--verify',action='store_true')
    args=parser.parse_args()
    verify() if args.verify else freeze()
