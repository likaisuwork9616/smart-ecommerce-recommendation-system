"""Audit completed-history coverage of approval-time unfinished orders; no fit."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts import audit_mature_history_signals as preceding
from scripts import delay_history_representativeness as representation
from scripts import delay_representation_profiles as profiles
from scripts.delay_history_features import build_primary_sellers

SOURCE = ROOT/'reports/stage4/conditional_mature_signal_diagnostics.json'
SOURCE_SHA = '0fe02e7ffdfb7e4de1dea2add4f41bbae82eb95eac75906dfcb6429da0ac372d'
SOURCE_SPEC = ROOT/'reports/stage4/conditional_mature_signal_specification.json'
SOURCE_SPEC_SHA = 'c42d572ec13997c7489b718cb4e6b165f04fe5e9ad7f358790bc5cb278d40547'
INITIAL_SPEC = ROOT/'reports/stage4/completed_history_representativeness_initial_specification.json'
INITIAL_SPEC_SHA = '3e90b17caf8a030946b97715b705cedfebcb5b5c7d70fb27331514ccc7633485'
SPECIFICATION = ROOT/'reports/stage4/completed_history_representativeness_specification.json'
OUTPUT = ROOT/'reports/stage4/completed_history_representativeness_audit.json'
CACHE = ROOT/'data/processed/olist_completed_history_representativeness_approval_pre_may.csv'
ANALYSIS = 'approval_cohort_completed_history_representativeness_without_training'
TARGET = '2018-02/2018-02/evaluation'
CODE = ('scripts/audit_completed_history_representativeness.py',
        'scripts/delay_history_representativeness.py', 'scripts/delay_representation_profiles.py')
EXTRA_SOURCES = ('scripts/delay_pending_features.py','scripts/delay_engineering_features.py',
                 'requirements-lock.txt')
RAW_NAMES = {'orders':'olist_orders_dataset.csv','order_items':'olist_order_items_dataset.csv',
             'customers':'olist_customers_dataset.csv','sellers':'olist_sellers_dataset.csv'}


def contract():
    return {
        'seeds':[11,29,42,73,101], 'query_rows':70844, 'original_query_columns':175,
        'cutoff_exclusive':'2018-05-01',
        'phase_scope':'All12 frozen phases with their original answer cutoffs, full-day10% alerts and four-model/five-seed identities. Only three distinct development months enter descriptive consistency screens.',
        'history_population':'All raw approvals before cutoff with non-null purchase<=approval. Never filter final status or final legacy eligibility to construct the as-of approval cohort. Static seller/customer attributes retain the original export-time assumptions.',
        'approval_cohort':'For each query t and known own key, independent historical approval in [t-W,t), W90 for seller/route/joint and W30 for route30. Same-ID query/history approvals must agree. Unknown keys are not pooled; counters missing, known empty history counters zero.',
        'asof_partition':'approved=completed+pending+invalid_delivery. Valid completed has approval<=delivery<t. Already observed delivery<approval is invalid. Pending means no delivery observed strictly before t; delivery==t is pending for history and separately counted. No new reminder eligibility is evaluated.',
        'promise_partition':'Valid promise is non-null and calendar promise day>=approval day. Deadline=promise day+1day. Pending=active+overdue+invalid_promise; overdue when deadline<=t; invalid promise splits missing/negative, never treated as on-time. Promise-day sums use valid integer calendar offsets only.',
        'carrier':'pending_no_carrier_event counts no carrier timestamp<t, regardless of eventual final status; absence of a recorded event is not proof of physical non-shipment.',
        'clocks':'Future delivery/carrier at or after2018-05-01 censored before calculations. Each query still masks every event>=t. Event time only proxies availability; ingestion/revision/cancellation clocks are absent.',
        'legacy_metadata':'Frozen70844 query identities mark the prior final-delivered eligible population, solely for retrospective composition and source reconstruction. Legacy membership never defines the new as-of denominator or either primary audit ratio.',
        'delivery_bridge':'Original eligible completed delivery-window count=legacy completed from the same approval window+legacy completed with older approvals. The two windows are not directly interchangeable denominators.',
        'age_composition':'Both completed and pending use elapsed t-approval, not eventual delivery duration. Fixed [0,7),[7,14),[14,30),[30,60),[60,90] days; route30 last bin includes30 and omits older bins. Right-censored pending duration is not filled with future outcomes.',
        'promise_composition':'Report completed/pending valid promise counts and sums, separately from approval-age bins. Matching fixes current query conditions, not every historical order own promise/age.',
        'audit_ratios':{'pending_share':'pending/approved',
                        'overdue_pending_share':'valid-promise overdue pending/approved'},
        'ratio_denominator':'Same status-free approval cohort. Unknown key or zero approved gives missing ratio, never zero. No prior smoothing. Per-query means and occurrence-pooled ratios are distinct summaries.',
        'comparison_bases':{'seller90':'original seller90 mature support bins',
            'joint90':'original joint90 mature support bins',
            'route90':'original route30 AND route90 mature support bins'},
        'comparison_conditions':'Full state route x promise condition x Monday00 approval week x candidate-specific unchanged mature support bin(s). Three fixed schemes: original promise bins; exact integer promise days; exact days plus query weekday Mon0..Sun6. Never coarsen after sparse results.',
        'cohorts':'Same-identity all20 common misses versus all same-stratum known on-time queries (primary), or other known delayed (secondary). Five focus groups ALL/R/A/RA/SP->SC retain every seed own four-model common misses. Unknown query labels are not read.',
        'coverage':'finite overlap>=1 miss/1 control; cohort adequate>=3 finite misses/5 finite controls; supported additionally every required mature support>=20. All common misses remain denominator; missing/no control/low cohort/low local support are disjoint reasons.',
        'aggregation':'Stratum mean differences and within-stratum risk ordering use finite miss-n weights; controls standardized to the same weights. Equal-stratum sensitivity retained. Risk sign+1 for both audit ratios; ties abs<=1e-12 count0.5. Pairs/overlapping histories/seeds are not independent replications.',
        'context_profiles':'All16 fixed groups retain status-free history counters, age/promise composition and raw denominator totals across query cohorts; route30 is descriptive context. Histories overlap between queries; occurrence totals are not distinct orders. Distinct history coverage reported separately by basis.',
        'public_cell_detail':f'{TARGET}, five focus groups, six basis-ratios at all three schemes; compact aggregate cells, no identities or individual score/rank vectors.',
        'consistency_screen':'Exploratory only: each of all three schemes supported common n>=20 and weeks>=3, mean and ordering-minus0.5 same nonzero direction, all five own-seed summaries align, same direction in>=2 distinct development months. Positive/inverse both reported; no automatic training selection.',
        'redundancy':'Label-free exact-duplicate and Spearman comparisons against original101 numeric white list; existing pending counts and overdue numerators separately reconstructed. A coverage gap or nonduplicate ratio does not establish new information or incremental model benefit.',
        'prohibitions':['No model deserialization/replay/fit, new scores/alerts, quota, ensemble, seed/model/default choice or original holdout rescore.',
            'No use of future final status, future delivery duration or query label to construct prospective audit ratios.',
            'No causal attribution, significance/CI from reused pairs/windows or choosing matching thresholds after observing results.'],
        'privacy':'Only aggregate profiles and stratum context published. Raw history, audit cache, row identities and independent execution proofs stay Git ignored.'}


def make_specification():
    source=preceding.bound_json(SOURCE,SOURCE_SHA)
    old=preceding.bound_json(SOURCE_SPEC,SOURCE_SPEC_SHA)
    if source['status']!='ok' or source['specification']['sha256']!=SOURCE_SPEC_SHA or source['contract']!=old['contract']:
        raise ValueError('Require completed frozen conditional audit')
    files={}
    for item in old['protected_sources']+old['analysis_code']:
        name=Path(item['path']).as_posix()
        if name in files and files[name]!=item['sha256']:
            raise ValueError('Conflicting protected source hashes')
        files[name]=item['sha256']
    for path,digest in ((SOURCE,SOURCE_SHA),(SOURCE_SPEC,SOURCE_SPEC_SHA)):
        files[path.relative_to(ROOT).as_posix()]=digest
    files[INITIAL_SPEC.relative_to(ROOT).as_posix()]=INITIAL_SPEC_SHA
    for name in EXTRA_SOURCES:
        files[name]=preceding.sha256(ROOT/name)
    for name,digest in files.items():
        if preceding.sha256(ROOT/name)!=digest:
            raise ValueError(f'Changed protected source: {name}')
    return {'format_version':1,'analysis':ANALYSIS,'contract':contract(),
        'pre_publication_format_correction':{'initial_specification':INITIAL_SPEC.relative_to(ROOT).as_posix(),
            'initial_sha256':INITIAL_SPEC_SHA,
            'change':'Public support_by_basis metadata tuples normalized to JSON lists; strict roundtrip regression added. No counts, matching, thresholds, weights or analysis rules changed. Initial run stopped by code-hash protection before publishing any report or inspecting new outcome-conditional results.'},
        'source_report':{'path':SOURCE.relative_to(ROOT).as_posix(),'sha256':SOURCE_SHA},
        'phase_metadata':old['phase_metadata'],
        'protected_sources':[{'path':name,'sha256':digest} for name,digest in sorted(files.items())],
        'analysis_code':[{'path':name,'sha256':preceding.sha256(ROOT/name)} for name in CODE],
        'private_cache_path':CACHE.relative_to(ROOT).as_posix()}


def prepare_history(tables,queries):
    orders=tables['orders'].copy()
    if orders.order_id.isna().any() or orders.order_id.duplicated().any():
        raise ValueError('Raw order IDs must be non-null unique')
    clocks=('order_purchase_timestamp','order_approved_at','order_delivered_customer_date',
            'order_delivered_carrier_date','order_estimated_delivery_date')
    for name in clocks:
        orders[name]=pd.to_datetime(orders[name],errors='coerce',format='mixed')
        if orders[name].dt.tz is not None:
            raise ValueError('Require timezone-naive raw clocks')
    orders=orders.loc[orders.order_approved_at.lt(preceding.CUTOFF)].copy()
    pre=len(orders)
    missing=orders.order_purchase_timestamp.isna()
    reversed_time=~missing & orders.order_approved_at.lt(orders.order_purchase_timestamp)
    orders=orders.loc[~missing & ~reversed_time].copy()
    primary=build_primary_sellers(tables['order_items']).set_index('order_id').primary_seller_id
    for table,key in (('customers','customer_id'),('sellers','seller_id')):
        if tables[table][key].isna().any() or tables[table][key].duplicated().any():
            raise ValueError('Static lookup keys must be unique non-null')
    customer=tables['customers'].set_index('customer_id').customer_state
    seller=tables['sellers'].set_index('seller_id').seller_state
    orders['primary_seller_id']=orders.order_id.map(primary)
    seller_state=orders.primary_seller_id.map(seller)
    customer_state=orders.customer_id.map(customer)
    orders['state_route']=seller_state+'->'+customer_state
    orders['legacy_eligible']=orders.order_id.isin(set(queries.order_id))
    original=orders.set_index('order_id')
    if not queries.order_id.isin(original.index).all():
        raise ValueError('Every frozen query must retain valid raw approval history')
    for column,raw_column in (('prediction_time','order_approved_at'),
                              ('primary_seller_id','primary_seller_id'),('state_route','state_route')):
        actual=queries.order_id.map(original[raw_column])
        expected=queries[column].reset_index(drop=True)
        actual=actual.reset_index(drop=True)
        if not ((actual==expected)|(actual.isna()&expected.isna())).all():
            raise ValueError(f'Frozen query raw {column} changed')
    quality={'raw_pre_may_approval_rows':pre,'missing_purchase_rows_excluded':int(missing.sum()),
        'purchase_after_approval_rows_excluded':int(reversed_time.sum()),'valid_raw_approval_rows':len(orders),
        'legacy_eligible_rows':int(orders.legacy_eligible.sum()),
        'legacy_excluded_rows':int((~orders.legacy_eligible).sum()),
        'legacy_mature_events_before_cutoff':int((orders.legacy_eligible & orders.order_delivered_customer_date.lt(preceding.CUTOFF)).sum()),
        'final_status_retrospective_only':{str(key):int(value) for key,value in orders.order_status.fillna('missing').value_counts().sort_index().items()}}
    for column in ('order_delivered_customer_date','order_delivered_carrier_date'):
        orders[column]=orders[column].where(orders[column].lt(preceding.CUTOFF))
    renamed=orders.rename(columns={'order_approved_at':'prediction_time','order_purchase_timestamp':'purchase_time',
        'order_delivered_customer_date':'delivery_time','order_delivered_carrier_date':'carrier_time',
        'order_estimated_delivery_date':'promise_time'})
    columns=['order_id','prediction_time','purchase_time','delivery_time','carrier_time','promise_time',
             'primary_seller_id','state_route','legacy_eligible']
    return renamed[columns].reset_index(drop=True),quality


def verify_reconstruction(frame,audit):
    pairs=[('seller90','legacy_delivery_window','seller_completed_90d'),
        ('route90','legacy_delivery_window','route_completed_90d'),
        ('joint90','legacy_delivery_window','audit_seller_route_completed_90d'),
        ('route30','legacy_delivery_window','audit_route_completed_30d'),
        ('seller90','pending','seller_pending_90d'),('route90','pending','route_pending_90d'),
        ('route30','pending','route_pending_30d')]
    fields=0
    for basis,counter,old in pairs:
        actual=audit[f'audit_{basis}_{counter}'].fillna(0).to_numpy(float)
        np.testing.assert_array_equal(actual,frame[old].to_numpy(float),err_msg=old)
        fields+=len(frame)
    for basis,old in (('seller90','seller_pending_overdue_90d'),('route90','route_pending_overdue_90d'),
                       ('route30','route_pending_overdue_30d')):
        actual=(audit[f'audit_{basis}_pending_overdue']+audit[f'audit_{basis}_pending_negative_promise']).fillna(0)
        np.testing.assert_array_equal(actual.to_numpy(float),frame[old].to_numpy(float),err_msg=old)
        fields+=len(frame)
    return {'existing_counter_fields_reconstructed':len(pairs)+3,'existing_counter_cells_verified':fields,
        'negative_promise_overdue_difference':'Original pending overdue includes negative promise days. New valid-promise overdue excludes them; adding separately retained negative-promise pending exactly reconstructs the original.'}


def label_free_redundancy(frame,audit):
    numeric,_=preceding.feature_names(preceding.frozen.BASELINE)
    results={}
    for basis in profiles.COMPARISON_BASES:
        for metric in profiles.METRICS:
            values=profiles.query_metric(audit,basis,metric)
            duplicates=[]
            correlations=[]
            for name in numeric:
                other=pd.to_numeric(frame[name],errors='coerce').to_numpy(float)
                if np.array_equal(values,other,equal_nan=True): duplicates.append(name)
                valid=np.isfinite(values)&np.isfinite(other)
                if valid.sum()>=2 and len(np.unique(values[valid]))>1 and len(np.unique(other[valid]))>1:
                    coefficient=pd.Series(values[valid]).corr(pd.Series(other[valid]),method='spearman')
                    correlations.append({'feature':name,'spearman':float(coefficient),'paired_rows':int(valid.sum())})
            correlations.sort(key=lambda row:(-abs(row['spearman']),row['feature']))
            results[f'{basis}.{metric}']={'finite_queries':int(np.isfinite(values).sum()),
                'exact_original101_duplicates':duplicates,'top_absolute_spearman':correlations[:5]}
    return {'original_numeric_feature_count':len(numeric),'audit_ratios':results,
        'interpretation':'Label-free duplicate/association description only. Existing pending/overdue numerators are already in101; a different denominator, absent exact duplicate or lower correlation does not establish incremental prediction benefit.'}


def write_private_cache(frame,audit):
    if not audit.index.equals(frame.index) or not set(frame.columns).issubset(audit.columns):
        raise ValueError('Audit cache must preserve the row-aligned original columns')
    pd.testing.assert_frame_equal(audit[frame.columns],frame,check_exact=True)
    added=[name for name in audit.columns if name not in frame.columns]
    if not added or any(not name.startswith('audit_') for name in added):
        raise ValueError('Audit cache requires separate audit-only counters')
    combined=audit
    if CACHE.exists():
        existing=pd.read_csv(CACHE,float_precision='round_trip',dtype={name:object for name in
            ('order_id','primary_seller_id','state_route','customer_zip_prefix3','primary_seller_zip_prefix3')})
        for name in ('prediction_time','label_available_time'):
            existing[name]=pd.to_datetime(existing[name],errors='raise')
        pd.testing.assert_frame_equal(existing,combined,check_dtype=False,check_exact=True)
    else:
        combined.to_csv(CACHE,index=False)
    return {'path':CACHE.relative_to(ROOT).as_posix(),'sha256':preceding.sha256(CACHE),
        'rows':len(frame),'original_columns':len(frame.columns),'audit_columns':added,
        'git_ignored':True}


def build_report(specification_path):
    specification=json.loads(Path(specification_path).read_text(encoding='utf-8'))
    if specification!=make_specification():
        raise ValueError('Frozen specification/source/code changed')
    source=preceding.bound_json(SOURCE,SOURCE_SHA)
    mature=preceding.bound_json(preceding.ROOT/'reports/stage4/mature_history_signal_audit.json',
        '765db1ba25c5ce2e2b87511292fbb46519237a685e3dc1ee22a534dd2a3dd914')
    score_source=preceding.bound_json(preceding.SOURCE,preceding.SOURCE_SHA)
    dtype={name:object for name in ('order_id','primary_seller_id','state_route','customer_zip_prefix3','primary_seller_zip_prefix3')}
    frame=pd.read_csv(ROOT/mature['private_feature_cache']['path'],float_precision='round_trip',dtype=dtype)
    for name in ('prediction_time','label_available_time'):
        frame[name]=pd.to_datetime(frame[name],errors='raise')
    if frame.shape!=(70844,175) or list(frame.columns)!=mature['private_feature_cache']['columns'] or frame.prediction_time.ge(preceding.CUTOFF).any():
        raise ValueError('Fixed query cohort/columns changed')
    tables={name:pd.read_csv(ROOT/'data/raw/olist'/filename) for name,filename in RAW_NAMES.items()}
    history,population=prepare_history(tables,frame)
    if (population['raw_pre_may_approval_rows']!=mature['event_quality']['raw_pre_may_approval_rows']
            or population['legacy_eligible_rows']!=70844
            or population['legacy_mature_events_before_cutoff']!=68277):
        raise ValueError('Prior raw/legacy source cohort changed')
    print('Bound raw approval cohort prepared without final-status filtering',flush=True)
    audit,quality=representation.build_representation(frame,history)
    pd.testing.assert_frame_equal(audit[frame.columns],frame,check_exact=True)
    pd.testing.assert_frame_equal(frame,pd.read_csv(ROOT/mature['private_feature_cache']['path'],
        float_precision='round_trip',dtype=dtype,parse_dates=['prediction_time','label_available_time']),check_exact=True)
    reconstruction=verify_reconstruction(frame,audit)
    private=write_private_cache(frame,audit)
    print('Approval-window counters and original delivery/pending counters verified',flush=True)
    redundancy=label_free_redundancy(frame,audit)
    ledger=pd.read_csv(ROOT/score_source['score_export']['path'],float_precision='round_trip',parse_dates=['prediction_time'])
    if len(ledger)!=1281120:
        raise ValueError('Frozen score ledger size changed')
    phases,rows,denominators={},0,0
    months=frame.prediction_time.dt.strftime('%Y-%m')
    for key,plan in score_source['phase_metrics'].items():
        mask=months.eq(plan['month'])
        batch=frame.loc[mask].reset_index(drop=True)
        counts=audit.loc[mask].reset_index(drop=True)
        known,common20,common4,verified=preceding.phase_cohorts(batch,ledger,plan)
        actual=profiles.compare_phase(batch,counts,known,common20,common4,include_strata=(key==TARGET))
        for group,value in actual['groups'].items():
            for name in ('full_batch_rows','known_rows','unknown_rows','positive_rows','common20_rows',
                         'known_on_time_rows','other_delayed_rows','common4_by_seed'):
                if value['denominators'][name]!=source['phase_comparisons'][key]['groups'][group]['denominators'][name]:
                    raise ValueError('Original known/group/common-miss identity changed')
                denominators+=5 if name=='common4_by_seed' else 1
        phases[key],rows=actual,rows+verified
        print(f'{key}: fixed representation comparisons and all five seeds verified',flush=True)
    if rows!=1281120 or len(phases)!=12:
        raise ValueError('Frozen phase/score coverage changed')
    screen=profiles.representation_screen(phases,specification['phase_metadata'])
    for item in specification['protected_sources']+specification['analysis_code']:
        if preceding.sha256(ROOT/item['path'])!=item['sha256']:
            raise ValueError('Source changed during representation audit')
    return {'format_version':1,'status':'ok','analysis':ANALYSIS,'contract':contract(),
        'specification':{'path':Path(specification_path).relative_to(ROOT).as_posix(),
                         'sha256':preceding.sha256(specification_path)},
        'pre_publication_format_correction':specification['pre_publication_format_correction'],
        'source_report':{'path':SOURCE.relative_to(ROOT).as_posix(),'sha256':SOURCE_SHA},
        'private_audit_cache':private,'raw_approval_population':population,'representation_quality':quality,
        'existing_counter_reconstruction':reconstruction,'label_free_redundancy':redundancy,
        'phase_metadata':specification['phase_metadata'],'phase_comparisons':phases,
        'representation_consistency_screen':screen,
        'verification':{'query_rows':70844,'original_query_columns_preserved_exactly':175,
            'original_value_cells_preserved':70844*175,'score_rows_verified':rows,'phases_verified':12,
            'original_denominator_fields_verified':denominators,'seed_count':5,
            'protected_source_hashes_verified':len(specification['protected_sources']),
            'analysis_code_hashes_verified':len(specification['analysis_code']),
            'new_fits':0,'models_deserialized':0,'models_replayed':0,'new_model_features':0,
            'new_alert_policy':False,'new_selection':False,'original_holdout_not_rescored':True},
        'limitations':['Status-free unfinished history is an unobserved-delivery proxy, not verified physical backlog: cancellation/ingestion/revision clocks are unavailable.',
            'Legacy final-delivered eligibility is retrospective metadata only. Current query matching does not make every historical promise or approval age comparable.',
            'Same-approval-cohort completion/pending contrasts are descriptive and structurally selected; pending elapsed age is a lower bound on duration, not an observed final duration.',
            'Query-history occurrences, reused controls, five seeds and repeated historical months are dependent; no significance, causal or incremental prediction claims.',
            'The three prespecified matching schemes retain different query subsets/weights. Sparse weekday coverage cannot be repaired by changing conditions after inspection.',
            'A representation discrepancy or passing descriptive consistency screen is not a new-feature training result. Existing101 already contains pending/overdue history and deterministic ratios.']}


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--specification',type=Path,default=SPECIFICATION)
    parser.add_argument('--specification-only',action='store_true')
    parser.add_argument('--output',type=Path,default=OUTPUT)
    args=parser.parse_args(argv)
    if args.specification_only:
        preceding.fixed_json(args.specification,make_specification())
        print(json.dumps({'specification':str(args.specification),'new_fits':0}),flush=True)
        return
    if not args.specification.is_file() or args.specification.resolve()==args.output.resolve():
        parser.error('First freeze a separate --specification-only; report requires its own JSON')
    report=build_report(args.specification)
    preceding.fixed_json(args.output,report)
    print(json.dumps({'report':str(args.output),'bytes':args.output.stat().st_size,
                     'verification':report['verification']}),flush=True)
    return report


if __name__=='__main__':
    main()
