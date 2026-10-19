"""Audit approval-time mature histories against frozen common misses; no fit."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import sys

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts import diagnose_age_colsample as frozen
from scripts import delay_mature_history_audit as signals
from scripts import delay_mature_signal_profiles as profiles
from scripts.delay_features import load_olist_tables, build_order_features, add_delay_target
from scripts.delay_history_features import build_primary_sellers
from scripts.delay_unobserved_handover_age_training import feature_names

CUTOFF = pd.Timestamp('2018-05-01')
ANALYSIS = 'approval_time_mature_history_signal_audit_without_training'
PRECEDING = ROOT / 'reports/stage4/four_model_boundary_diagnostics.json'
PRECEDING_SHA = '3992f6ea97caeb7ee5a0b3c2022fada0813b0a8f29b1d1e8894398d4abb84102'
PRECEDING_SPEC = ROOT / 'reports/stage4/four_model_boundary_specification.json'
PRECEDING_SPEC_SHA = '3e22e3a4f23156e825051258d14d6233c700c01a79f91a0d1cdea06566387b4d'
SOURCE = ROOT / 'reports/stage4/age_colsample.json'
SOURCE_SHA = 'feb46ee19e5c33596980dec2947b08e8e1d94b106f6af1f985f19e5989609b2c'
SPECIFICATION = ROOT / 'reports/stage4/mature_history_signal_specification.json'
OUTPUT = ROOT / 'reports/stage4/mature_history_signal_audit.json'
CACHE = ROOT / 'data/processed/olist_mature_history_signal_audit_approval_pre_may.csv'
CODE = ('scripts/audit_mature_history_signals.py', 'scripts/delay_mature_history_audit.py',
    'scripts/delay_mature_signal_profiles.py', 'scripts/delay_features.py',
    'scripts/delay_history_features.py', 'scripts/delay_route_features.py',
    'scripts/delay_budget_features.py', 'scripts/delay_unobserved_handover_age_training.py',
    'scripts/diagnose_age_colsample.py', 'scripts/diagnose_age_seed_stability.py',
    'scripts/diagnose_age_intersections.py', 'scripts/delay_calibration_policy.py')


def sha256(path):
    digest = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            digest.update(block)
    return digest.hexdigest()


def bound_json(path, digest):
    if sha256(path) != digest:
        raise ValueError(f'Frozen source changed: {path}')
    return json.loads(Path(path).read_text(encoding='utf-8'))


def contract():
    return {
        'seeds': list(frozen.SEEDS), 'versions': list(frozen.VERSIONS),
        'ranking': 'Original complete closed approval day, score DESC/ID ASC, floor(N/10), unknown outcomes compete before all outcome/group masks.',
        'phase_scope': 'All12 original phases at all5 seeds, original outcome cutoff per fold. No repeated historical month pooling and no original retained-holdout scoring.',
        'event_cohort': 'Exactly legacy add_delay_target eligibility: final delivered status, valid purchase<=approval<=delivery, valid promise day>=approval day. This audited legacy cohort is not status-free raw delivery history.',
        'feature_clock': 'Actual customer-delivery event in [approval-90d,approval), or [approval-30d,approval); lower inclusive, upper exclusive. No deadline training clock. Same-ID query/event approvals must match, so own delivery cannot enter own history.',
        'assumptions': 'Event time proxies knowledge time; no ingestion/revision clocks. Original promise and static primary seller/customer states use final exported attributes under prior approval-time availability assumptions.',
        'query_scope': 'Exactly frozen70844-row138-column pre-May feature cohort; original columns and values remain unchanged. New audit fields never enter model feature lists.',
        'primary_seller': 'Highest item price then smallest item sequence, same original lookup; state route is seller state -> customer state, not a carrier route.',
        'recomputed_features': list(signals.RECOMPUTED_FEATURES),
        'candidates': {
            'seller_promise_cdf_90d': 'Same seller completed calendar-day durations <= current query promise; (seller count_le +20*current global CDF)/(seller n+20). Unknown seller or empty global gives null; known empty seller history uses global prior.',
            'seller_route_delay_rate_90d': 'Joint primary seller x state-route completed delayed count, with20 pseudo outcomes at current existing route90 rate. Unknown key gives null; zero local n equals route prior.',
            'route_recent30_delay_rate_excess90d': 'Route30 completed delayed rate shrunk with20 current global30 pseudo outcomes (global30 shrunk with20 at0.05), minus existing route90 rate. 30d is nested in90d, not independent; zero route30 n can still yield nonzero excess from priors.'},
        'candidate_order': list(signals.CANDIDATE_FEATURES),
        'audit_only_features': list(signals.AUDIT_ONLY_FEATURES),
        'support_bins': ['unknown_key', '0', '1-4', '5-19', '20-99', '100+'],
        'groups': ['ALL', 'R', 'A', 'RA', 'R_not_A', 'A_not_R', 'NOT_A', 'SP->SC'] + [f'cell:{cell}' for cell in frozen.CELLS],
        'cohorts': 'Known/on-time/delayed; same-identity all20 common FN vs other delayed; each of all five seed own four-model common FN in fixed focus groups. Outcome labels only define retrospective diagnosis cohorts.',
        'statistics': 'Missing/finite counts and min/p10/p50/p90/max/mean; zero denominator rates null. Support and priors remain separate. Original-label-free Spearman/duplicate checks describe association, not new-feature benefit or causality.',
        'training_decision': 'Audit first; do not auto-select a candidate using these inspected outcomes. New single-factor training needs a separately frozen specification; baseline101x0.8, five seeds, original preprocessing/clocks and full-day10% remain the reference.',
        'privacy': 'Public only aggregates, source names and hashes; per-query cache stays Git ignored; no IDs, seller identities, individual scores or labels exported publicly.',
        'prohibitions': ['No model deserialization/replay/fit or new alerts, budgets, subgroup quotas, seed choice, ensemble, or default-model change.',
            'No query feature or scoring at/after2018-05-01. No current or future query outcome used to construct history.',
            'Do not claim completed history covers pending/slow unfinished/cancelled orders; do not identify a cause from common-miss conditional profiles.'],
    }


def make_specification():
    before = bound_json(PRECEDING_SPEC, PRECEDING_SPEC_SHA)
    source = bound_json(SOURCE, SOURCE_SHA)
    if (source['seeds'] != list(frozen.SEEDS) or len(source['phase_metrics']) != 12
            or set(source['phase_metrics']) != set(before['phase_metadata'])):
        raise ValueError('Fixed seeds or phase coverage changed')
    files = {}
    for item in before['protected_sources'] + before['analysis_code']:
        name = Path(item['path']).as_posix()
        if name in files and files[name] != item['sha256']:
            raise ValueError('Conflicting protected artifact hashes')
        files[name] = item['sha256']
    for path, digest in ((PRECEDING, PRECEDING_SHA), (PRECEDING_SPEC, PRECEDING_SPEC_SHA)):
        files[path.relative_to(ROOT).as_posix()] = digest
    for name, digest in files.items():
        if sha256(ROOT / name) != digest:
            raise ValueError(f'Protected source changed: {name}')
    numeric, categorical = feature_names(frozen.BASELINE)
    if len(numeric) != 93 or len(categorical) != 8 or set(signals.CANDIDATE_FEATURES) & set(numeric + categorical):
        raise ValueError('Changed101 feature package or duplicate candidate name')
    return {'format_version': 1, 'analysis': ANALYSIS, 'contract': contract(),
        'phase_metadata': before['phase_metadata'],
        'protected_sources': [{'path': name, 'sha256': digest} for name, digest in sorted(files.items())],
        'analysis_code': [{'path': name, 'sha256': sha256(ROOT/name)} for name in CODE],
        'baseline_numeric_features': numeric, 'baseline_categorical_features': categorical}


def fixed_json(path, report):
    path = Path(path).resolve()
    if path.suffix.lower() != '.json' or path.is_relative_to(ROOT/'data') or path.is_relative_to(ROOT/'models'):
        raise ValueError('Require separate aggregate JSON outside data/models')
    serialized = json.dumps(report, ensure_ascii=False, separators=(',', ':'), allow_nan=False)
    if path.exists():
        if json.loads(path.read_text(encoding='utf-8')) != report:
            raise ValueError(f'Refusing to overwrite different existing output: {path}')
    else:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(serialized, encoding='utf-8')


def mature_events(raw_dir):
    tables = load_olist_tables(raw_dir)
    # Filter approval population before building any static/target features.
    approvals = pd.to_datetime(tables['orders'].order_approved_at, errors='coerce', format='mixed')
    tables['orders'] = tables['orders'].loc[approvals.lt(CUTOFF)].copy()
    base = build_order_features(tables)
    eligible = add_delay_target(base, tables['orders'])
    events = eligible.loc[eligible.label_available_time.lt(CUTOFF)].copy()
    primary = build_primary_sellers(tables['order_items'])
    return events, primary, {'raw_pre_may_approval_rows': len(base),
        'legacy_pre_may_approval_eligible_rows': len(eligible),
        'mature_eligible_delivery_events_before_may': len(events),
        'legacy_eligible_but_delivered_at_or_after_may': len(eligible)-len(events)}


def validate_cache(before, after):
    if len(before) != len(after) or not before.index.equals(after.index):
        raise ValueError('Frozen query identities/order changed')
    comparisons = 0
    for name in signals.RECOMPUTED_FEATURES:
        left, right = before[name].to_numpy(float), after[name].to_numpy(float)
        np.testing.assert_array_equal(np.isnan(left), np.isnan(right))
        # Existing prefix summation is evaluated in its original stable order.
        np.testing.assert_allclose(left, right, atol=1e-10, rtol=1e-12, equal_nan=True)
        comparisons += len(before)
    pd.testing.assert_frame_equal(before.drop(columns=signals.RECOMPUTED_FEATURES),
        after[before.columns].drop(columns=signals.RECOMPUTED_FEATURES), check_exact=True)
    return comparisons


def phase_cohorts(frame, ledger, plan):
    """Check all original scores/alerts and return identity-aligned fixed misses."""
    common4, known_reference, verified = {}, None, 0
    for seed in frozen.SEEDS:
        seed_caught = np.zeros(len(frame), bool)
        for col in ('0.8', '1.0'):
            part = ledger.loc[ledger.colsample_bytree.eq(float(col)) & ledger.seed.eq(seed)
                & ledger.fold.eq(plan['fold']) & ledger.model_version.eq(plan['month']) & ledger.role.eq(plan['ledger_role'])]
            known, scores, _ = frozen.previous.verify_phase_ledger(frame, part, plan, seed, plan['by_colsample'][col][str(seed)])
            if known_reference is not None:
                np.testing.assert_array_equal(known_reference, known)
            known_reference = known
            for score in scores.values():
                seed_caught |= frozen.apply_alert_policy(frame, score, 0., .1, raw_scores=score)
            verified += len(part)
        labels = np.zeros(len(frame), int)
        labels[known_reference] = frame.delayed.to_numpy()[known_reference].astype(int)
        common4[seed] = known_reference & (labels == 1) & ~seed_caught
    return known_reference, np.logical_and.reduce(list(common4.values())), common4, verified


def verify_common_counts(batch, known, common20, common4, preceding, phase):
    cells, group_masks = frozen.intersections.group_masks(batch)
    masks = {('overall','ALL'): np.ones(len(batch),bool),
        **{('marginal',name): mask for name, mask in group_masks.items()},
        **{('cell',cell): cells == cell for cell in frozen.CELLS}}
    routes = batch.state_route.fillna('unknown').to_numpy()
    masks.update({('route',route): routes == route for route in set(routes) | {'SP->RJ','SP->SC','SP->SP'}})
    checked = 0
    for row in preceding['persistent_misses'][phase]['groups']:
        key = (row['kind'],row['key'])
        if key not in masks:
            continue
        mask = masks[key]
        positive = mask & known & batch.delayed.eq(1).to_numpy()
        if (int(positive.sum()) != row['known_delayed_rows'] or int((mask & common20).sum()) != row['all20_missed']):
            raise ValueError('Preceding all20 miss cohort changed')
        for seed in frozen.SEEDS:
            before = next(r for r in preceding['seed_phases'][str(seed)][phase]['groups']
                if (r['kind'],r['key']) == key)
            if int((mask & common4[seed]).sum()) != before['common_missed_delays']:
                raise ValueError('Preceding own-seed four-model miss cohort changed')
        checked += 7
    return checked


def write_private_cache(path, frame):
    path = Path(path).resolve()
    if not path.is_relative_to(ROOT/'data/processed') or path.suffix.lower() != '.csv':
        raise ValueError('Per-query audit cache must remain in ignored data/processed')
    if path.exists():
        # Byte comparison avoids silently replacing an earlier run/cache.
        if path.read_text(encoding='utf-8') != frame.to_csv(index=False, lineterminator='\n'):
            raise ValueError('Existing private cache differs')
    else:
        path.parent.mkdir(parents=True, exist_ok=True)
        frame.to_csv(path,index=False,lineterminator='\n')
    return {'path':path.relative_to(ROOT).as_posix(),'sha256':sha256(path),
        'rows':len(frame),'columns':list(frame.columns),'git_ignored':True}


def build_report(specification_path, raw_dir, cache_path):
    specification = json.loads(Path(specification_path).read_text(encoding='utf-8'))
    if specification != make_specification():
        raise ValueError('Pre-analysis specification/code/sources changed')
    source = bound_json(SOURCE,SOURCE_SHA)
    preceding = bound_json(PRECEDING,PRECEDING_SHA)
    frame = pd.read_csv(ROOT/source['feature_dataset']['path'],float_precision='round_trip',
        dtype={name:object for name in ('order_id','primary_seller_id','state_route','customer_zip_prefix3','primary_seller_zip_prefix3')})
    for name in ('prediction_time','label_available_time'):
        frame[name] = pd.to_datetime(frame[name],errors='raise')
    if frame.shape != (70844,138) or frame.prediction_time.ge(CUTOFF).any():
        raise ValueError('Frozen pre-May query population changed')
    events, primary, event_quality = mature_events(raw_dir)
    print(f'Rebuilding mature signals: {len(frame)} queries, {len(events)} eligible completed events',flush=True)
    enriched = signals.build_signals(frame,events,primary)
    fields_verified = validate_cache(frame,enriched)
    reconstruction = {}
    for name in signals.RECOMPUTED_FEATURES:
        left,right = frame[name].to_numpy(float),enriched[name].to_numpy(float)
        finite = np.isfinite(left)
        reconstruction[name] = {'finite_rows':int(finite.sum()),'missing_rows':int((~finite).sum()),
            'maximum_absolute_error':float(np.max(np.abs(left[finite]-right[finite]))) if finite.any() else None}
    # Preserve every original byte-level value in the exported source columns;
    # diagnostics use independently rebuilt values only after equivalence above.
    cache = frame.copy()
    for name in signals.CANDIDATE_FEATURES + signals.AUDIT_ONLY_FEATURES:
        cache[name] = enriched[name].to_numpy()
    cache_info = write_private_cache(cache_path,cache)
    ledger = pd.read_csv(ROOT/source['score_export']['path'],float_precision='round_trip',parse_dates=['prediction_time'])
    if (len(ledger) != 1281120 or set(ledger.seed) != set(frozen.SEEDS)
            or set(ledger.colsample_bytree) != {.8,1.}
            or ledger.duplicated(['colsample_bytree','seed','fold','role','candidate','model_version','order_id']).any()):
        raise ValueError('Frozen complete score ledger changed')
    phase_profiles, score_rows, preceding_fields = {}, 0, 0
    month_values = frame.prediction_time.dt.strftime('%Y-%m')
    for phase,plan in source['phase_metrics'].items():
        batch = enriched.loc[month_values.eq(plan['month'])].reset_index(drop=True)
        known,common20,common4,verified = phase_cohorts(batch,ledger,plan)
        score_rows += verified
        preceding_fields += verify_common_counts(batch,known,common20,common4,preceding,phase)
        phase_profiles[phase] = profiles.profile_phase(batch,known,common20,common4)
        print(f'{phase}: five seeds and original common-miss cohorts reconciled',flush=True)
    if score_rows != len(ledger):
        raise ValueError('Unrecognized score rows')
    correlations = profiles.compare_correlations(enriched,specification['baseline_numeric_features'])
    quality = {name: {'finite':int(np.isfinite(enriched[name].to_numpy(float)).sum()),
        'missing':int(enriched[name].isna().sum())} for name in signals.SIGNAL_FEATURES}
    for item in specification['protected_sources']+specification['analysis_code']:
        if sha256(ROOT/item['path']) != item['sha256']:
            raise ValueError('Protected source changed during mature signal audit')
    return {'format_version':1,'status':'ok','analysis':ANALYSIS,'contract':contract(),
        'specification':{'path':Path(specification_path).relative_to(ROOT).as_posix(),'sha256':sha256(specification_path)},
        'private_feature_cache':cache_info,'event_quality':event_quality,'feature_quality':quality,
        'existing_feature_reconstruction':reconstruction,
        'phase_metadata':specification['phase_metadata'],'phase_profiles':phase_profiles,
        'label_free_redundancy':correlations,
        'verification':{'queries_verified':len(frame),'recomputed_existing_feature_count':len(signals.RECOMPUTED_FEATURES),
            'existing_feature_values_verified':fields_verified,'unchanged_original_feature_columns':138,
            'seed_count':5,'phases_per_seed':12,'score_rows_verified':score_rows,
            'preceding_common_miss_count_fields_verified':preceding_fields,
            'protected_source_hashes_verified':len(specification['protected_sources']),
            'analysis_code_hashes_verified':len(specification['analysis_code']),
            'new_candidate_audit_fields':3,'models_deserialized':0,'new_fits':0,'saved_models_replayed':0,
            'new_alert_policy':False,'new_selection':False,'original_holdout_not_rescored':True,
            'query_feature_cutoff_exclusive':'2018-05-01','private_identities_published':False},
        'limitations':['These are outcome-conditional profiles on inspected historical/development orders, not trained or validated candidate model performance.',
            'Completed-history selection excludes unfinished/cancelled outcomes and inherits legacy final-status and exported-attribute assumptions.',
            'Sparse rates/CDFs may mostly repeat the declared global/route prior; zero support is not local evidence.',
            '30-day windows overlap90-day windows. Correlation and group differences do not establish new information gain, causal bottlenecks or generalization.',
            'No new candidate was fit or deployed. A future single-factor experiment needs its own frozen training specification.']}


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--specification',type=Path,default=SPECIFICATION)
    parser.add_argument('--specification-only',action='store_true')
    parser.add_argument('--raw-dir',type=Path,default=ROOT/'data/raw/olist')
    parser.add_argument('--cache',type=Path,default=CACHE)
    parser.add_argument('--output',type=Path,default=OUTPUT)
    args=parser.parse_args(argv)
    if args.specification_only:
        fixed_json(args.specification,make_specification())
        print(json.dumps({'specification':str(args.specification),'new_fits':0}),flush=True)
        return
    if not args.specification.is_file() or args.specification.resolve()==args.output.resolve():
        parser.error('Require separate saved --specification and output; first run --specification-only')
    report=build_report(args.specification,args.raw_dir,args.cache)
    fixed_json(args.output,report)
    print(json.dumps({'report':str(args.output),'bytes':args.output.stat().st_size,'verification':report['verification']}),flush=True)
    return report


if __name__=='__main__':
    main()
