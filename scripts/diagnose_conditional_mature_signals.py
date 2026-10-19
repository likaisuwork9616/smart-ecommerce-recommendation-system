"""Compare frozen mature signals within route/promise/week/support strata."""
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
from scripts import delay_conditional_mature_signals as conditional

SOURCE = ROOT/'reports/stage4/mature_history_signal_audit.json'
SOURCE_SHA = '765db1ba25c5ce2e2b87511292fbb46519237a685e3dc1ee22a534dd2a3dd914'
SOURCE_SPEC = ROOT/'reports/stage4/mature_history_signal_specification.json'
SOURCE_SPEC_SHA = '4a94a2442aaf147ebb314123e6c28fec2b692d7a1b596a33f2b9196d600ec760'
SPECIFICATION = ROOT/'reports/stage4/conditional_mature_signal_specification.json'
OUTPUT = ROOT/'reports/stage4/conditional_mature_signal_diagnostics.json'
TARGET = '2018-02/2018-02/evaluation'
ANALYSIS = 'fixed_route_promise_week_support_conditional_mature_signal_diagnosis'
CODE = ('scripts/diagnose_conditional_mature_signals.py',
        'scripts/delay_conditional_mature_signals.py',
        'scripts/audit_mature_history_signals.py', 'scripts/delay_mature_signal_profiles.py',
        'scripts/delay_mature_history_audit.py', 'scripts/diagnose_objective_misses.py')


def contract():
    return {
        'seeds': list(conditional.SEEDS),
        'candidates': list(conditional.CANDIDATE_FEATURES),
        'phase_scope': 'All12 original phases, separate outcome cutoffs; five seeds preserved. Only three disjoint development months enter the descriptive hypothesis screen, never pooled with repeated validation months.',
        'ranking': 'Original complete closed approval day score DESC/ID ASC, floor(N/10), unknown outcomes compete before known/cohort/group masks. No new alert ranking or quota.',
        'common_misses': 'Primary same-identity all20-model FN; focus groups also retain every seed own four-model FN. Same on-time controls are reused, not five independent datasets.',
        'groups': ['ALL','R','A','RA','R_not_A','A_not_R','NOT_A','SP->SC'] + [f'cell:{cell}' for cell in preceding.frozen.CELLS],
        'strata': 'Full state_route x promise condition x Monday00:00 approval week x each candidate own history-support bin(s). Week boundaries may cross calendar months but phases never mix.',
        'promise_conditions': {'promise_bin': 'Original <=7,(7,14],(14,21],(21,30],>30 calendar days, primary; this is not exact matching within bins.',
            'promise_days': 'Exact nonnegative integer calendar promise days sensitivity; same week, support, thresholds and weights.'},
        'support': {name:list(values) for name,values in conditional.CANDIDATE_SUPPORTS.items()},
        'support_bins': list(conditional.SUPPORT_BINS),
        'controls': {'primary':'all known on-time queries in the same stratum, no model-score selection',
                     'secondary':'other known delayed, excluding the own all20 common-miss cohort'},
        'coverage_tiers': {'finite_overlap': '>=1 finite common miss and >=1 finite control per stratum',
            'cohort_adequate': '>=3 finite common misses and >=5 finite controls, irrespective of local-history support',
            'supported': 'cohort_adequate AND every candidate-specific local history count>=20; unknown keys cannot qualify'},
        'coverage_denominator': 'Always retain all common misses; missing signal/no finite control/low cohort/low local history are disjoint uncovered reasons. All empty/zero-miss strata are retained in target-phase detail.',
        'weighting': 'Use finite common-miss count per stratum. Standardize control mean to the same composition. Equal-stratum effects are sensitivity summaries, never replacement weights chosen after results.',
        'ordering': 'Risk-oriented common/control probability: greater risk wins, abs difference<=1e-12 ties contribute0.5. Keep all ties. Average per-stratum ordering by common-miss count, never by number of pairs. Pair totals are not independent samples or a new model AUC.',
        'risk_signs': conditional.RISK_SIGNS.copy(), 'epsilon': conditional.EPSILON,
        'full_cell_detail': f'{TARGET} only, ALL/R/A/RA/SP->SC at both promise conditions. All12 phases retain complete summaries, weekly effects and all five seed summaries.',
        'hypothesis_screen': {'supported_common_min':20, 'supported_week_min':3, 'different_development_month_min':2,
            'direction': 'Within a phase/group, bin and exact-day supported mean risk differences and ordering-minus0.5 must all be nonzero with the same sign. All five own-seed summaries at both schemes must have the same direction. Positive and inverse hypotheses both reported; never change sign to pick a winner.',
            'scope': 'ALL/R/A/RA/SP->SC, separately; same direction in at least2 different development months is a work-screen flag, not significance, gain, automatic feature selection, or deployment approval.'},
        'prohibitions': ['No model loading/replay/fit, new feature engineering, scoring, seed/model choice or original holdout evaluation.',
            'No coarsening routes, widening weeks, changing support/promise bins or reducing thresholds after inspecting sparse coverage.',
            'No p values/confidence intervals from reused pairs/seeds/months; no causal or incremental prediction claim from outcome-conditional profiles.'],
        'privacy': 'Public aggregates and stratum context only; no order/seller identities or row-level score/rank vectors.'}


def make_specification():
    source = preceding.bound_json(SOURCE,SOURCE_SHA)
    old_spec = preceding.bound_json(SOURCE_SPEC,SOURCE_SPEC_SHA)
    if (source['status'] != 'ok' or source['analysis'] != preceding.ANALYSIS
            or source['specification']['sha256'] != SOURCE_SPEC_SHA
            or source['contract'] != old_spec['contract']):
        raise ValueError('Require completed fixed mature-history audit')
    files = {}
    for item in old_spec['protected_sources'] + old_spec['analysis_code'] + [source['private_feature_cache']]:
        name = Path(item['path']).as_posix()
        if name in files and files[name] != item['sha256']:
            raise ValueError('Conflicting source hashes')
        files[name] = item['sha256']
    for path,digest in ((SOURCE,SOURCE_SHA),(SOURCE_SPEC,SOURCE_SPEC_SHA)):
        files[path.relative_to(ROOT).as_posix()] = digest
    for name,digest in files.items():
        if preceding.sha256(ROOT/name) != digest:
            raise ValueError(f'Changed protected source: {name}')
    return {'format_version':1,'analysis':ANALYSIS,'contract':contract(),
        'source_report':{'path':SOURCE.relative_to(ROOT).as_posix(),'sha256':SOURCE_SHA},
        'phase_metadata':source['phase_metadata'],
        'protected_sources':[{'path':name,'sha256':digest} for name,digest in sorted(files.items())],
        'analysis_code':[{'path':name,'sha256':preceding.sha256(ROOT/name)} for name in CODE]}


def verify_previous_counts(actual, old):
    checked = 0
    fields = ('full_batch_rows','known_rows','unknown_rows','positive_rows','known_on_time_rows',
              'common20_rows','other_delayed_rows','common4_by_seed')
    if set(actual['groups']) != set(old['groups']):
        raise ValueError('Fixed group support changed')
    for group,row in actual['groups'].items():
        before = old['groups'][group]
        for field in fields:
            if row['denominators'][field] != before['denominators'][field]:
                raise ValueError('Preceding known/miss group changed')
            checked += 5 if field == 'common4_by_seed' else 1
        for scheme in conditional.PROMISE_SCHEMES:
            for candidate in conditional.CANDIDATE_FEATURES:
                comparison = row['comparisons'][scheme][candidate]['known_on_time']
                for cohort,name in (('common20','common_mean'),('known_on_time','control_mean')):
                    expected = before['cohorts'][cohort]['distributions'][candidate]['mean']
                    actual_mean = comparison['unadjusted'][name]
                    if expected is None:
                        if actual_mean is not None:
                            raise ValueError('Undefined original mean changed')
                    elif actual_mean is None or not np.isclose(actual_mean,expected,atol=1e-12,rtol=1e-12):
                        raise ValueError('Original unadjusted profile changed')
                    checked += 1
    return checked


def direction(value):
    return None if value is None else 1 if value > conditional.EPSILON else -1 if value < -conditional.EPSILON else 0


def phase_screen(group,candidate):
    effects = {scheme:group['comparisons'][scheme][candidate]['known_on_time']['effects']['supported']
               for scheme in conditional.PROMISE_SCHEMES}
    sufficient = all(row['common_n'] >= 20 and row['week_count'] >= 3 for row in effects.values())
    signs = []
    for row in effects.values():
        signs.extend((direction(row['risk_difference']),
            direction(row['order_probability']-.5) if row['order_probability'] is not None else None))
    aligned = signs[0] in (-1,1) and all(sign == signs[0] for sign in signs)
    seed_aligned = False
    seed_directions = {}
    if aligned:
        for seed in conditional.SEEDS:
            per_seed = []
            for scheme in conditional.PROMISE_SCHEMES:
                row = group['common4_by_seed'][str(seed)][scheme][candidate]['effects']['supported']
                per_seed.extend((direction(row['risk_difference']),
                    direction(row['order_probability']-.5) if row['order_probability'] is not None else None))
            seed_directions[str(seed)] = per_seed
        seed_aligned = all(all(sign == signs[0] for sign in values) for values in seed_directions.values())
    return {'data_sufficient_both_schemes':sufficient,'bin_exact_direction_aligned':aligned,
        'all_five_seed_directions_aligned':seed_aligned,'direction':signs[0] if aligned else None,
        'work_screen_passed':bool(sufficient and aligned and seed_aligned),
        'supported_by_scheme':{scheme:{field:row[field] for field in
            ('common_n','control_n','strata_count','week_count','risk_difference','order_probability')}
            for scheme,row in effects.items()},'seed_directions':seed_directions}


def hypothesis_screen(phases,metadata):
    keys = [key for key,plan in metadata.items() if plan['ledger_role']=='evaluation']
    if len(keys) != 3 or len({metadata[key]['month'] for key in keys}) != 3:
        raise ValueError('Require three distinct inspected development months')
    results = {}
    for candidate in conditional.CANDIDATE_FEATURES:
        results[candidate] = {}
        for group in conditional.FOCUS_GROUPS:
            monthly = {key:phase_screen(phases[key]['groups'][group],candidate) for key in keys}
            by_sign = {str(sign):[key for key,row in monthly.items()
                if row['work_screen_passed'] and row['direction']==sign] for sign in (-1,1)}
            results[candidate][group] = {'development_phases':monthly,
                'passing_months_by_direction':by_sign,
                'work_screen_at_least_two_months':any(len(values)>=2 for values in by_sign.values())}
    return {'by_candidate':results,'automatic_training_selection':False,
        'interpretation':'Predeclared exploratory data/consistency screen only. Passing does not establish significance, causality, incremental model benefit or suitable deployment.'}


def build_report(specification_path):
    specification = json.loads(Path(specification_path).read_text(encoding='utf-8'))
    if specification != make_specification():
        raise ValueError('Frozen specification/code/source changed')
    source = preceding.bound_json(SOURCE,SOURCE_SHA)
    score_source = preceding.bound_json(preceding.SOURCE,preceding.SOURCE_SHA)
    dtype = {name:object for name in ('order_id','primary_seller_id','state_route',
                                    'customer_zip_prefix3','primary_seller_zip_prefix3')}
    frame = pd.read_csv(ROOT/source['private_feature_cache']['path'],float_precision='round_trip',dtype=dtype)
    original = pd.read_csv(ROOT/score_source['feature_dataset']['path'],float_precision='round_trip',dtype=dtype)
    for dataset in (frame,original):
        for name in ('prediction_time','label_available_time'):
            dataset[name] = pd.to_datetime(dataset[name],errors='raise')
    if (frame.shape != (70844,175) or list(frame.columns) != source['private_feature_cache']['columns']
            or frame.prediction_time.ge(preceding.CUTOFF).any()
            or frame.order_id.isna().any() or frame.order_id.duplicated().any()):
        raise ValueError('Fixed pre-May mature-signal query cohort changed')
    pd.testing.assert_frame_equal(frame[original.columns],original,check_exact=True)
    ledger = pd.read_csv(ROOT/score_source['score_export']['path'],float_precision='round_trip',parse_dates=['prediction_time'])
    if (len(ledger)!=1281120 or set(ledger.seed)!=set(conditional.SEEDS)
            or set(ledger.colsample_bytree)!={.8,1.}
            or ledger.duplicated(['colsample_bytree','seed','fold','role','candidate','model_version','order_id']).any()):
        raise ValueError('Fixed score ledger changed')
    phases,rows,fields = {},0,0
    months = frame.prediction_time.dt.strftime('%Y-%m')
    for key,plan in score_source['phase_metrics'].items():
        batch = frame.loc[months.eq(plan['month'])].reset_index(drop=True)
        known,common20,common4,verified = preceding.phase_cohorts(batch,ledger,plan)
        actual = conditional.compare_phase(batch,known,common20,common4,include_strata=(key==TARGET))
        fields += verify_previous_counts(actual,source['phase_profiles'][key])
        phases[key],rows = actual,rows+verified
        print(f'{key}: fixed conditional strata and all five seeds verified',flush=True)
    if rows != len(ledger) or len(phases)!=12:
        raise ValueError('Unrecognized scoring/phase rows')
    screen = hypothesis_screen(phases,specification['phase_metadata'])
    for item in specification['protected_sources']+specification['analysis_code']:
        if preceding.sha256(ROOT/item['path']) != item['sha256']:
            raise ValueError('Source changed during conditional diagnosis')
    return {'format_version':1,'status':'ok','analysis':ANALYSIS,'contract':contract(),
        'specification':{'path':Path(specification_path).relative_to(ROOT).as_posix(),
                         'sha256':preceding.sha256(specification_path)},
        'source_report':{'path':SOURCE.relative_to(ROOT).as_posix(),'sha256':SOURCE_SHA},
        'phase_metadata':specification['phase_metadata'],'phase_comparisons':phases,
        'hypothesis_screen':screen,
        'verification':{'query_rows_verified':70844,'frozen_cache_columns':175,
            'original_columns_preserved_exactly':138,'original_value_cells_verified':70844*138,
            'score_rows_verified':rows,'phases_verified':12,'seed_count':5,
            'preceding_denominator_and_mean_fields_verified':fields,
            'protected_source_hashes_verified':len(specification['protected_sources']),
            'analysis_code_hashes_verified':len(specification['analysis_code']),
            'models_deserialized':0,'new_fits':0,'saved_models_replayed':0,
            'new_features_created':0,'new_alert_policy':False,'new_selection':False,
            'original_holdout_not_rescored':True,'private_identities_published':False},
        'limitations':['The same inspected historical/development queries and fixed model misses are reused; matching does not remove model-outcome selection or establish causality.',
            'Within-bin promise/day and within-week approval-time variation can remain. Exact-day sensitivity can be sparse and must not be replaced after inspection.',
            'Supported strata require3 misses/5 controls and local20 history only as fixed work definitions, not power, significance, safety or incremental prediction guarantees.',
            'Five seeds reuse outcomes and controls; repeated validation months retain distinct cutoffs and are not independent replications.',
            'Pair-ordering retains ties and uses miss-count stratum weights; pair totals are not independent samples or new model AUC.',
            'Completed-history, final-status eligibility, exported-attribute and event-time-as-knowledge assumptions remain those of the frozen mature audit.']}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--specification',type=Path,default=SPECIFICATION)
    parser.add_argument('--specification-only',action='store_true')
    parser.add_argument('--output',type=Path,default=OUTPUT)
    args = parser.parse_args(argv)
    if args.specification_only:
        preceding.fixed_json(args.specification,make_specification())
        print(json.dumps({'specification':str(args.specification),'new_fits':0}),flush=True)
        return
    if not args.specification.is_file() or args.specification.resolve()==args.output.resolve():
        parser.error('First save separate --specification-only; report must have its own JSON path')
    report = build_report(args.specification)
    preceding.fixed_json(args.output,report)
    print(json.dumps({'report':str(args.output),'bytes':args.output.stat().st_size,
                      'verification':report['verification']}),flush=True)
    return report


if __name__=='__main__':
    main()
