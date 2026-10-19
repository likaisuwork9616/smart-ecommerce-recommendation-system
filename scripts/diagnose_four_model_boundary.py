"""Diagnose frozen four-model misses and daily 10% boundaries without training."""
from __future__ import annotations

import argparse
from collections import Counter
import json
from pathlib import Path
import sys

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts import diagnose_age_colsample as prior
from scripts import delay_four_model_boundary as boundary

SOURCE = ROOT / 'reports/stage4/age_colsample.json'
DIAGNOSTIC = ROOT / 'reports/stage4/age_colsample_diagnostics.json'
SOURCE_SHA = 'feb46ee19e5c33596980dec2947b08e8e1d94b106f6af1f985f19e5989609b2c'
DIAGNOSTIC_SHA = '1212ab5910caaae27ccce90fdcbd5cce12176448e1f9a089bfc00c0550eafe8d'
ANALYSIS = 'frozen_four_model_common_misses_daily_boundary_and_exchanges'
SPECIFICATION = ROOT / 'reports/stage4/four_model_boundary_specification.json'
OUTPUT = ROOT / 'reports/stage4/four_model_boundary_diagnostics.json'
CODE_FILES = (
    'scripts/diagnose_four_model_boundary.py', 'scripts/delay_four_model_boundary.py',
    'scripts/diagnose_age_colsample.py', 'scripts/diagnose_age_seed_stability.py',
    'scripts/diagnose_age_intersections.py', 'scripts/diagnose_unobserved_handover_age.py',
    'scripts/diagnose_rank_batch_size.py', 'scripts/delay_route_exchanges.py',
    'scripts/delay_calibration_policy.py', 'scripts/diagnose_budget_misses.py',
    'scripts/diagnose_objective_misses.py',
)


def load_bound(path, digest):
    if prior.previous.sha256(path) != digest:
        raise ValueError(f'Frozen source changed: {path}')
    return json.loads(Path(path).read_text(encoding='utf-8'))


def contract():
    return {
        'seeds': list(prior.SEEDS), 'versions': list(prior.VERSIONS),
        'contrasts': {key: list(pair) for key, pair in prior.CONTRASTS.items()},
        'target_phase': prior.TARGET_PHASE,
        'phase_scope': 'All original 12 phases at all five seeds; historical cutoffs stay separate. February alone retains daily detail; no phase pooling.',
        'ranking': 'Full closed day, score DESC then order_id ASC, floor(N/10); unknown outcomes compete before known/group masks.',
        'common_miss': 'Known delayed and unalerted by all four versions within one seed.',
        'persistent_miss': 'Known delayed and unalerted by all four versions at all five seeds (20 model evaluations of the same identity).',
        'other_misses': 'Each version keeps its five-seed common/union/multiplicity. Newly lost always means that contrast own old alert and own new non-alert.',
        'groups': 'ALL, all observed routes plus fixed SP->RJ/SP->SC/SP->SP, original RPA marginals/eight cells, original five age bins inside110. R=SP->RJ; P=21<promise<=30; A=24<age_p90<=72 hours.',
        'boundary': 'One-based full-day rank minus daily capacity. Fixed bins inside_budget, one_to_three, four_to_ten, eleven_plus; capacity-zero rows separate. No raw-score comparison across models.',
        'tie': 'Cutoff ties and ties spanning the selected/unselected boundary are descriptive. ID breaks all ties; no new threshold.',
        'exchanges': 'Within day/group min(added,dropped), outgoing=max(dropped-added,0), incoming=max(added-dropped,0); sum daily gross. Route and RPA-cell partitions reconcile independently.',
        'statistics': 'All five seeds retained. Counts/rank-bin counts report mean/min/max, never confidence intervals. Known-delay denominator fixed within each phase/group. Zero denominators yield null.',
        'privacy': 'Public aggregates only; no order IDs, ID hashes, individual ranks or individual scores.',
        'prohibitions': ['No model loading, replay, fit, seed/model selection, new features, quotas, thresholds or default-model replacement.',
            'No original retained-holdout scoring; inspected historical/development data are not new unknown tests.',
            'No causal sampling claim or individual donor/recipient pairing. Dashboard remains deferred.'],
    }


def make_specification():
    source = load_bound(SOURCE, SOURCE_SHA)
    old = load_bound(DIAGNOSTIC, DIAGNOSTIC_SHA)
    if (source['status'] != 'ok' or old['status'] != 'ok'
            or source['seeds'] != list(prior.SEEDS)
            or old['source_report']['sha256'] != SOURCE_SHA
            or set(source['phase_metrics']) != set(old['phases'])
            or len(source['phase_metrics']) != 12):
        raise ValueError('Require the complete frozen four-version experiment and diagnostic')
    protected = {item['path']: item['sha256'] for item in old['source_hashes']}
    for path, digest in [(SOURCE, SOURCE_SHA), (DIAGNOSTIC, DIAGNOSTIC_SHA)]:
        name = path.relative_to(ROOT).as_posix()
        if name in protected and protected[name] != digest:
            raise ValueError('Conflicting frozen source hash')
        protected[name] = digest
    for name, digest in protected.items():
        if prior.previous.sha256(ROOT / name) != digest:
            raise ValueError(f'Protected artifact changed: {name}')
    return {'format_version': 1, 'analysis': ANALYSIS, 'contract': contract(),
        'source_report': {'path': SOURCE.relative_to(ROOT).as_posix(), 'sha256': SOURCE_SHA},
        'preceding_diagnostic': {'path': DIAGNOSTIC.relative_to(ROOT).as_posix(), 'sha256': DIAGNOSTIC_SHA},
        'phase_metadata': old['phases'],
        'protected_sources': [{'path': name, 'sha256': digest} for name, digest in sorted(protected.items())],
        'analysis_code': [{'path': name, 'sha256': prior.previous.sha256(ROOT / name)} for name in CODE_FILES]}


def fixed_json(path, payload):
    path = Path(path).resolve()
    if path.suffix.lower() != '.json' or path.is_relative_to(ROOT / 'data') or path.is_relative_to(ROOT / 'models'):
        raise ValueError('Require a separate aggregate JSON path outside data/models')
    serialized = json.dumps(payload, ensure_ascii=False, separators=(',', ':'), allow_nan=False)
    if path.exists():
        if json.loads(path.read_text(encoding='utf-8')) != payload:
            raise ValueError(f'Refusing to overwrite a different frozen output: {path}')
    else:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(serialized, encoding='utf-8')


def verify_previous(public, frozen):
    """Compare every original group metric and exchange, not only total TP."""
    lookup = {(row['kind'], row['key']): row for row in public['groups']}
    checked = 0
    for kind, key, denominators, models, exchanges, allocations in frozen['groups']:
        row = lookup[kind, key]
        if row['denominators'] != dict(zip(prior.DENOMINATORS, denominators, strict=True)):
            raise ValueError('Frozen group denominator changed')
        checked += len(denominators)
        for version, expected in zip(prior.VERSIONS, models, strict=True):
            if row['models'][version] != dict(zip(prior.METRICS, expected, strict=True)):
                raise ValueError('Frozen model/group metrics changed')
            checked += len(expected)
        for contrast, expected, allocation in zip(prior.CONTRASTS, exchanges, allocations, strict=True):
            actual = row['contrasts'][contrast]
            if (actual['exchanges'] != dict(zip(prior.EXCHANGES, expected, strict=True))
                    or actual['allocations'] != dict(zip(prior.ALLOCATIONS, allocation, strict=True))):
                raise ValueError('Frozen group exchange or daily gross allocation changed')
            checked += len(expected) + len(allocation)
    return checked


def set_statistics(sets, universe):
    if set(sets) != set(prior.SEEDS) or any(not value <= universe for value in sets.values()):
        raise ValueError('Require five matched known-delay identity sets')
    union = set().union(*sets.values())
    common = set.intersection(*sets.values())
    votes = Counter(sum(order in sets[seed] for seed in prior.SEEDS) for order in universe)
    result = {'by_seed': {str(seed): len(sets[seed]) for seed in prior.SEEDS},
        'all_seed_intersection': len(common), 'union': len(union),
        'multiplicity': {str(number): votes[number] for number in range(6)}}
    if sum(result['multiplicity'].values()) != len(universe):
        raise AssertionError('Miss-vote partition changed')
    return result


def summarize_persistent(private):
    reference = private[prior.SEEDS[0]]['delayed']
    if any(private[seed]['delayed'] != reference for seed in prior.SEEDS):
        raise ValueError('Known-delay identity groups changed between seeds')
    groups = []
    for name, universe in reference.items():
        kind, key = name.split(':', 1)
        common_sets = {seed: private[seed]['common_missed'][name] for seed in prior.SEEDS}
        persistent = set.intersection(*common_sets.values())
        by_version = {version: set_statistics({seed: private[seed]['missed'][version][name]
            for seed in prior.SEEDS}, universe) for version in prior.VERSIONS}
        votes = Counter(sum(order in private[seed]['missed'][version][name]
            for seed in prior.SEEDS for version in prior.VERSIONS) for order in universe)
        gaps = {}
        for seed in prior.SEEDS:
            cache = private[seed]
            mask = np.isin(cache['row_ids'], list(persistent))
            gaps[str(seed)] = {version: boundary.gap_summary(mask, cache['positions'][version], cache['capacity'])
                for version in prior.VERSIONS}
        # Every count remains a number of identities, never 20 independent orders.
        groups.append({'kind': kind, 'key': key, 'known_delayed_rows': len(universe),
            'version_misses': by_version, 'four_version_common': set_statistics(common_sets, universe),
            'all20_missed': len(persistent), 'all20_missed_rate': len(persistent)/len(universe) if universe else None,
            'miss_vote_counts': {str(number): votes[number] for number in range(21)},
            'all20_gap_by_seed': gaps})
        if votes[20] != len(persistent) or sum(votes.values()) != len(universe):
            raise AssertionError('All20 miss votes do not reconcile')
    return {'groups': groups}


def focus_loss_days(public):
    """Describe complete days with focus losses, without pairing changed orders."""
    decoded = [boundary.decode_daily_exchange(row) for row in public['daily_exchanges']]
    results = {}
    for contrast in prior.CONTRASTS:
        rows = [row for row in decoded if row['contrast'] == contrast]
        results[contrast] = {}
        for focus in ('SP->RJ', 'A', 'SP->SC'):
            kind = 'cell' if focus == 'A' else 'route'
            partition = [row for row in rows if row['kind'] == kind]
            focus_rows = [row for row in partition if (row['key'].endswith('1') if focus == 'A' else row['key'] == focus)]
            focus_days = {}
            for row in focus_rows:
                day = focus_days.setdefault(row['day'], {field: 0 for field in boundary.DAILY_EXCHANGE_FIELDS[:11]})
                for field in day:
                    day[field] += row[field]
            selected = sorted(day for day, values in focus_days.items() if values['lost_delays'] > 0)
            outgoing_days = sorted(day for day in selected
                if focus_days[day]['dropped_alerts'] > focus_days[day]['added_alerts'])
            changes = []
            for key in sorted({row['key'] for row in partition}):
                chosen = [row for row in partition if row['key'] == key and row['day'] in selected]
                values = {field: sum(row[field] for row in chosen) for field in boundary.DAILY_EXCHANGE_FIELDS}
                changes.append({'key': key, **values})
            results[contrast][focus] = {'partition': kind, 'newly_lost_days': selected,
                'newly_lost_day_count': len(selected),
                'net_outflow_and_new_loss_days': outgoing_days,
                'focus_daily_changes': [{'day': day, **values} for day, values in sorted(focus_days.items())],
                'whole_selected_days_partition_changes': changes,
                'interpretation': 'All changed reminders on these complete days, including on-time/unknown outcomes; group marginals are not causal donor-recipient pairs.'}
    return results


def build_report(specification_path):
    expected = make_specification()
    specification = json.loads(Path(specification_path).read_text(encoding='utf-8'))
    if specification != expected:
        raise ValueError('Pre-analysis specification, code or protected sources changed')
    source = load_bound(SOURCE, SOURCE_SHA)
    frozen = load_bound(DIAGNOSTIC, DIAGNOSTIC_SHA)
    frame = pd.read_csv(ROOT / source['feature_dataset']['path'], float_precision='round_trip',
        dtype={name: object for name in ('order_id', 'state_route', 'primary_seller_id',
            'customer_zip_prefix3', 'primary_seller_zip_prefix3')})
    for name in ('prediction_time', 'label_available_time'):
        frame[name] = pd.to_datetime(frame[name], errors='raise')
    if (frame.shape != (70844, 138) or list(frame.columns) != source['feature_dataset']['columns']
            or frame.prediction_time.ge('2018-05-01').any()
            or frame.order_id.isna().any() or frame.order_id.duplicated().any()):
        raise ValueError('Frozen feature population changed')
    ledger = pd.read_csv(ROOT / source['score_export']['path'], float_precision='round_trip', parse_dates=['prediction_time'])
    if (len(ledger) != 1281120 or set(ledger.seed) != set(prior.SEEDS)
            or set(ledger.colsample_bytree) != {.8, 1.}
            or ledger.duplicated(['colsample_bytree', 'seed', 'fold', 'role', 'candidate', 'model_version', 'order_id']).any()):
        raise ValueError('Combined complete scoring ledger changed')
    previous_source = json.loads((ROOT / source['source_report']['path']).read_text(encoding='utf-8'))
    old_ledger = pd.read_csv(ROOT / previous_source['score_export']['path'], float_precision='round_trip', parse_dates=['prediction_time'])
    identity = ['seed', 'fold', 'role', 'candidate', 'model_version', 'order_id']
    pd.testing.assert_frame_equal(ledger.loc[ledger.colsample_bytree.eq(.8), old_ledger.columns]
        .sort_values(identity).reset_index(drop=True), old_ledger.sort_values(identity).reset_index(drop=True), check_exact=True)
    if len(old_ledger) != 640560:
        raise ValueError('Original0.8 scoring size changed')
    del old_ledger
    phases = {str(seed): {} for seed in prior.SEEDS}
    persistent, checked, rows_verified = {}, 0, 0
    month_labels = frame.prediction_time.dt.strftime('%Y-%m')
    for key, plan in source['phase_metrics'].items():
        batch = frame.loc[month_labels.eq(plan['month'])].reset_index(drop=True)
        private = {}
        for seed in prior.SEEDS:
            scores, known_reference = {}, None
            for col in ('0.8', '1.0'):
                part = ledger.loc[ledger.colsample_bytree.eq(float(col)) & ledger.seed.eq(seed)
                    & ledger.fold.eq(plan['fold']) & ledger.model_version.eq(plan['month']) & ledger.role.eq(plan['ledger_role'])]
                known, values, _ = prior.previous.verify_phase_ledger(batch, part, plan, seed, plan['by_colsample'][col][str(seed)])
                if known_reference is not None:
                    np.testing.assert_array_equal(known_reference, known)
                known_reference = known
                for version, (version_col, candidate) in prior.VERSION_SOURCE.items():
                    if version_col == col:
                        scores[version] = values[candidate]
                rows_verified += len(part)
            public, cache = boundary.diagnose_phase(batch, scores, known_reference, include_daily=(key == prior.TARGET_PHASE))
            checked += verify_previous(public, frozen['seed_phases'][str(seed)][key])
            phases[str(seed)][key], private[seed] = public, cache
        persistent[key] = summarize_persistent(private)
        print(f'{key}: all five seeds, four-model misses, rank gaps and daily allocation verified', flush=True)
    if rows_verified != len(ledger):
        raise ValueError('Unrecognized scoring rows')
    for item in specification['protected_sources'] + specification['analysis_code']:
        if prior.previous.sha256(ROOT / item['path']) != item['sha256']:
            raise ValueError('Source changed during diagnosis')
    return {'format_version': 1, 'status': 'ok', 'analysis': ANALYSIS,
        'specification': {'path': Path(specification_path).relative_to(ROOT).as_posix(),
            'sha256': prior.previous.sha256(specification_path)},
        'contract': contract(), 'schema': boundary.schema(), 'phases': specification['phase_metadata'],
        'seeds': list(prior.SEEDS), 'seed_phases': phases, 'persistent_misses': persistent,
        'february_focus_loss_days': {str(seed): focus_loss_days(phases[str(seed)][prior.TARGET_PHASE]) for seed in prior.SEEDS},
        'verification': {'phases_per_seed': 12, 'seed_phase_groups_verified': 60,
            'model_phase_groups_verified': 240, 'contrast_phase_groups_verified': 240,
            'score_rows_verified': rows_verified, 'original08_score_rows_verified': 640560,
            'preceding_metric_and_allocation_fields_verified': checked,
            'protected_source_hashes_verified': len(specification['protected_sources']),
            'analysis_code_hashes_verified': len(specification['analysis_code']),
            'models_deserialized': 0, 'new_fits': 0, 'saved_models_replayed': 0,
            'new_selection': False, 'original_holdout_not_rescored': True,
            'private_order_identities_exported': False},
        'limitations': ['The same inspected historical validation and development orders are reused; five seeds and20 model evaluations are not independent data.',
            'Rank-gap bins describe distance under the existing daily budget. They do not estimate the performance of a changed budget or policy.',
            'Daily co-occurrence of route/cell outflow and inflow is not identified order-level displacement or feature causality.',
            'All12 phase contexts remain separate, including repeated months with different historical outcome cutoffs.',
            'No new training intervention was selected or executed. Original default RF and research primary remain unchanged.']}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--specification', type=Path, default=SPECIFICATION)
    parser.add_argument('--specification-only', action='store_true')
    parser.add_argument('--output', type=Path, default=OUTPUT)
    args = parser.parse_args(argv)
    if args.specification_only:
        fixed_json(args.specification, make_specification())
        print(json.dumps({'specification': str(args.specification), 'new_fits': 0}), flush=True)
        return
    if args.output.resolve() == args.specification.resolve():
        parser.error('Report and specification must have separate paths')
    if not args.specification.is_file():
        parser.error('Save --specification-only before diagnosis')
    report = build_report(args.specification)
    fixed_json(args.output, report)
    print(json.dumps({'report': str(args.output), 'bytes': args.output.stat().st_size,
        'verification': report['verification']}), flush=True)
    return report


if __name__ == '__main__':
    main()
