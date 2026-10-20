"""Accept one inspected complete day from immutable scores; never run a model.

The specification is a delivery contract and source snapshot, not a new model
preregistration. Public outputs contain aggregates and source artifact hashes;
private output hashes and individual scores remain in the ignored local bundle.
"""
from __future__ import annotations

import argparse
import hashlib
import io
import json
from pathlib import Path
import subprocess
import sys

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts import delay_daily_delivery_acceptance as core

ANALYSIS = 'frozen_complete_day_offline_delivery_acceptance'
MONTH = '2018-02'
TARGET_PHASE = '2018-02/2018-02/evaluation'
CUTOFF = pd.Timestamp('2018-05-01')
SPECIFICATION = ROOT / 'reports/stage4/daily_delivery_acceptance_specification.json'
OUTPUT = ROOT / 'reports/stage4/daily_delivery_acceptance.json'
PRIVATE_DIRECTORY = '.runtime/offline_daily_delivery_2018-02-01'
COLSAMPLE = 'reports/stage4/age_colsample.json'
SEED_SOURCE = 'reports/stage4/age_seed_stability.json'
BOUNDARY = 'reports/stage4/four_model_boundary_diagnostics.json'
EVENT_SOURCE = 'reports/stage4/event_source_availability.json'
RAW_ORDERS = 'data/raw/olist/olist_orders_dataset.csv'
CODE_FILES = ('scripts/accept_frozen_daily_delivery.py', 'scripts/delay_daily_delivery_acceptance.py')
PINNED = {
    COLSAMPLE: 'feb46ee19e5c33596980dec2947b08e8e1d94b106f6af1f985f19e5989609b2c',
    SEED_SOURCE: '7b0a1e369307a718c3161d3a10045b8a9ecde385b9ab94bfe7c9c859262f11b8',
    'reports/stage4/age_colsample_specification.json': '6a3fdd1fe053b477dd3d4d0e9e9d9d1ae98a5d1879401876f866f63ed2c895a3',
    'reports/stage4/age_seed_stability_specification.json': 'd6317e3958fd0ccbca2692bbf2b185e98508149dc5e39f73cc2f36ac2b2f21cc',
    BOUNDARY: '3992f6ea97caeb7ee5a0b3c2022fada0813b0a8f29b1d1e8894398d4abb84102',
    'reports/stage4/four_model_boundary_specification.json': '3e22e3a4f23156e825051258d14d6233c700c01a79f91a0d1cdea06566387b4d',
    EVENT_SOURCE: 'fc5fdf4018a8b3d3202d8b7efb325904f215de78e4fe4871e48fe3e79ca29ee8',
    RAW_ORDERS: '8df58ef3d2d7e9944010f7beecd9b75367f5588ec6e3c91cec19ae3345ef9ecf',
    'scripts/delay_features.py': 'a21c70789b6e9831db8af196f29ac5084543f11495ab09edc150ac32e4b02cde',
    'scripts/delay_calibration_policy.py': '22bc706573a0bf6f2d8b20057247328e67a5776fa71d377bea80949db84a3e7d',
}
RAW_COLUMNS = ('order_id', 'order_status', 'order_purchase_timestamp', 'order_approved_at',
               'order_delivered_customer_date', 'order_estimated_delivery_date')
EXCLUSION_REASONS = ('not_final_delivered', 'missing_timeline', 'approval_before_purchase',
                     'delivery_before_approval', 'promise_before_approval_day')


def sha256(path):
    digest = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b''):
            digest.update(chunk)
    return digest.hexdigest()


def _unique_pairs(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f'Duplicate JSON key: {key}')
        result[key] = value
    return result


def read_json(path):
    def invalid(value):
        raise ValueError(f'Non-finite JSON constant: {value}')
    return json.loads(Path(path).read_text(encoding='utf-8'), object_pairs_hook=_unique_pairs,
                      parse_constant=invalid)


def json_bytes(payload):
    return (json.dumps(payload, ensure_ascii=False, sort_keys=True, indent=2, allow_nan=False) + '\n').encode('utf-8')


def descriptor(path, root=ROOT):
    root, path = Path(root).resolve(), Path(path).resolve()
    if not path.is_relative_to(root) or not path.is_file():
        raise ValueError('Source must be an existing file inside the project')
    return {'path': path.relative_to(root).as_posix(), 'bytes': path.stat().st_size, 'sha256': sha256(path)}


def verify_sources(items, root=ROOT):
    """Verify path, byte count and hash without deserializing any model."""
    if len({item['path'] for item in items}) != len(items):
        raise ValueError('Source paths must be unique')
    for item in items:
        if descriptor(Path(root) / item['path'], root) != {
                key: item[key] for key in ('path', 'bytes', 'sha256')}:
            raise ValueError(f'Source bytes changed: {item["path"]}')
    return len(items)


def _parsed(values, name, *, coerce=False):
    if any(isinstance(value, (int, float, bool, np.number)) and not pd.isna(value) for value in values):
        raise ValueError(f'Numeric values cannot be timestamps: {name}')
    parsed = pd.to_datetime(values, errors='coerce' if coerce else 'raise')
    if isinstance(parsed.dtype, pd.DatetimeTZDtype) or not pd.api.types.is_datetime64_any_dtype(parsed):
        raise ValueError(f'Require timezone-naive timestamps: {name}')
    return parsed


def reconstruct_cohort(raw):
    """Recreate only the original delivered/timeline predicate, without labels.

    All non-approval fields are interpreted only after restricting approvals to
    the pre-May scope. Reasons are mutually exclusive in the published order.
    Final status defines the retrospective research cohort, not as-of knowledge.
    """
    if (not set(RAW_COLUMNS).issubset(raw) or raw.order_id.isna().any()
            or raw.order_id.duplicated().any()):
        raise ValueError('Require unique complete raw order identities and predicate columns')
    approvals = _parsed(raw.order_approved_at, 'order_approved_at', coerce=True)
    scoped = raw.loc[approvals.notna() & approvals.lt(CUTOFF), list(RAW_COLUMNS)].copy()
    scoped['prediction_time'] = approvals.loc[scoped.index]
    for column in ('order_purchase_timestamp', 'order_delivered_customer_date', 'order_estimated_delivery_date'):
        scoped[column] = _parsed(scoped[column], column, coerce=True)
    reasons = pd.Series('eligible', index=scoped.index, dtype=object)
    checks = (
        ('not_final_delivered', ~scoped.order_status.eq('delivered')),
        ('missing_timeline', scoped[['order_purchase_timestamp', 'prediction_time',
                                    'order_delivered_customer_date', 'order_estimated_delivery_date']].isna().any(axis=1)),
        ('approval_before_purchase', scoped.prediction_time.lt(scoped.order_purchase_timestamp)),
        ('delivery_before_approval', scoped.order_delivered_customer_date.lt(scoped.prediction_time)),
        ('promise_before_approval_day', scoped.order_estimated_delivery_date.dt.normalize().lt(
            scoped.prediction_time.dt.normalize())),
    )
    for name, invalid in checks:
        reasons.loc[reasons.eq('eligible') & invalid] = name
    scoped['cohort_reason'] = reasons
    eligible = scoped.loc[reasons.eq('eligible'), ['order_id', 'prediction_time']].reset_index(drop=True)
    return eligible, scoped


def choose_day(cache, reconstructed, scoped_raw):
    """Choose the first nonempty February roster before looking at scores."""
    required = ['order_id', 'prediction_time']
    for frame in (cache, reconstructed):
        if (list(frame.columns) != required or frame.empty or frame.order_id.isna().any()
                or frame.order_id.duplicated().any() or frame.prediction_time.isna().any()
                or frame.prediction_time.ge(CUTOFF).any()):
            raise ValueError('Require a unique pre-May identity/time cohort')
    try:
        pd.testing.assert_frame_equal(cache.sort_values('order_id').reset_index(drop=True),
                                      reconstructed.sort_values('order_id').reset_index(drop=True),
                                      check_dtype=False, check_exact=True)
    except AssertionError as exc:
        raise ValueError('Frozen feature population does not equal the raw predicate cohort') from exc
    month = cache.loc[cache.prediction_time.dt.strftime('%Y-%m').eq(MONTH)]
    if month.empty:
        raise ValueError('No inspected February day is available')
    day = month.prediction_time.min().normalize()
    roster = month.loc[month.prediction_time.dt.normalize().eq(day)].reset_index(drop=True)
    raw_day = scoped_raw.loc[scoped_raw.prediction_time.dt.normalize().eq(day)]
    excluded = {name: int(raw_day.cohort_reason.eq(name).sum()) for name in EXCLUSION_REASONS}
    if len(raw_day) != len(roster) + sum(excluded.values()):
        raise ValueError('Raw day exclusions do not reconcile')
    return roster, {
        'selection_rule': 'First nonempty approval day in the frozen February evaluation cohort, without a score or delay-label performance criterion; eligibility itself is the fixed retrospective delivered cohort.',
        'day': day.date().isoformat(), 'month': MONTH, 'target_phase': TARGET_PHASE,
        'feature_cohort_rows_verified': len(cache), 'raw_pre_may_approval_rows': len(scoped_raw),
        'raw_day_approval_rows': len(raw_day), 'full_day_rows': len(roster),
        'daily_capacity': len(roster) // 10, 'mutually_exclusive_excluded_day_rows': excluded,
        'prediction_time_min': roster.prediction_time.min().isoformat(),
        'prediction_time_max': roster.prediction_time.max().isoformat(),
        'scope': 'Complete day only within the retrospectively valid final-delivered research cohort, not all real approvals.',
    }


def model_manifest(colsample, seed_source):
    """Extract twenty reported month versions and cross-check the frozen 0.8 side."""
    frozen = {(item['seed'], item['candidate']): item for item in
              colsample['frozen_reference']['monthly_models'] if item['month'] == MONTH}
    if len(frozen) != 10:
        raise ValueError('Require ten distinct frozen 0.8 month models')
    result = []
    for version in core.VERSIONS:
        setting, candidate = core.VERSION_SOURCE[version]
        report = seed_source if setting == .8 else colsample
        entries = [item for item in report['monthly_training'] if item['month'] == MONTH]
        if len(entries) != len(core.SEEDS) or {item['seed'] for item in entries} != set(core.SEEDS):
            raise ValueError('Require exactly one month record per frozen seed')
        for seed in core.SEEDS:
            entry = next(item for item in entries if item['seed'] == seed)
            training, models = entry['training_split'], entry['models']
            if set(models) != {core.BASELINE, core.AGE}:
                raise ValueError('Monthly model candidates changed')
            info = models[candidate]
            artifact = info['version_artifact']
            count = 101 if candidate == core.BASELINE else 102
            if (info['seed'] != seed or info['candidate'] != candidate
                    or info['classifier_parameters']['random_state'] != seed
                    or info['classifier_parameters']['colsample_bytree'] != setting
                    or info['feature_count'] != count or info['training_design'] != 'deadline_wait0'
                    or training['wait_days'] != 0 or training['training_clock'] != 'deadline'
                    or training['model_fit_time'] != '2018-02-01T00:00:00'
                    or training['scoring_start'] != '2018-02-01T00:00:00'
                    or training['scoring_end'] != '2018-03-01T00:00:00'
                    or info['score_semantics'] != 'sigmoid(raw margin), strictly monotone uncalibrated ranking score'):
                raise ValueError('Reported seed/model/training contract changed')
            if setting == .8 and any(artifact[key] != frozen[seed, candidate][key] for key in ('path', 'sha256')):
                raise ValueError('The 0.8 monthly model disagrees with the frozen reference')
            result.append({
                'version': version, 'seed': seed, 'candidate': candidate, 'colsample_bytree': setting,
                'reported_feature_count': count, 'training_design': 'deadline_wait0',
                'reported_logical_model_fit_time': training['model_fit_time'],
                'reported_logical_scoring_start': training['scoring_start'],
                'reported_logical_scoring_end': training['scoring_end'],
                'score_semantics': info['score_semantics'], 'path': artifact['path'], 'sha256': artifact['sha256'],
            })
    if len({item['path'] for item in result}) != 20:
        raise ValueError('Model artifact paths must identify twenty distinct frozen files')
    return result


def contract():
    return {
        'purpose': 'Offline delivery contract and source snapshot for already-inspected frozen scores; not a new model preregistration.',
        'phase': TARGET_PHASE, 'daily_fraction': .1, 'seeds': list(core.SEEDS), 'versions': list(core.VERSIONS),
        'selection': 'First nonempty February approval day chosen from the bound roster before reading scores.',
        'ranking': 'Full research-cohort day; score DESC, order_id ASC; floor(N/10), no outcome/group filtering or quota.',
        'score_reading': 'Only identity/time/version/availability/score/alert columns are read; outcome_for_metrics is explicitly excluded.',
        'source_rank': 'The frozen source contains alert flags but no saved daily rank; reconstructed ranks are checked by private output readback.',
        'model_clock': 'Reported logical historical replay clocks only; this does not prove the artifact physically existed in 2018 or production as-of availability.',
        'completeness': 'Source-cohort completeness is retrospective final-delivered eligibility; no production day-close or raw all-approval scoring is established.',
        'privacy': 'Individual identities/times/scores/ranks and private output hashes stay in ignored local files; public output has aggregates and source artifact hashes only.',
        'event_signal_status': 'pending_data_no_training',
        'prohibitions': ['No model loading, fitting, prediction, replay, calibration, selection or changed default.',
                         'No TP/FP/FN, recall, precision, performance comparison or new generalization conclusion.',
                         'No original retained-test scoring, external notification, Dashboard or service deployment.'],
    }


def load_roster(source, root=ROOT):
    path = Path(root) / source['feature_dataset']['path']
    header = pd.read_csv(path, nrows=0).columns.tolist()
    if header != source['feature_dataset']['columns'] or len(header) != 138:
        raise ValueError('Frozen feature header changed')
    cache = pd.read_csv(path, usecols=['order_id', 'prediction_time'], dtype={'order_id': str})
    cache['prediction_time'] = _parsed(cache.prediction_time, 'feature prediction_time')
    if len(cache) != source['feature_dataset']['rows']:
        raise ValueError('Frozen feature row count changed')
    raw = pd.read_csv(Path(root) / RAW_ORDERS, usecols=list(RAW_COLUMNS), dtype={'order_id': str})
    reconstructed, scoped = reconstruct_cohort(raw)
    return choose_day(cache, reconstructed, scoped)


def make_specification(root=ROOT):
    root = Path(root)
    sources = []
    for name, expected in PINNED.items():
        item = descriptor(root / name, root)
        if item['sha256'] != expected:
            raise ValueError(f'Pinned source changed: {name}')
        sources.append(item)
    source, seed_source = read_json(root / COLSAMPLE), read_json(root / SEED_SOURCE)
    if (source['status'] != 'ok' or seed_source['status'] != 'ok'
            or source['seeds'] != list(core.SEEDS) or seed_source['seeds'] != list(core.SEEDS)
            or source['specification_sha256'] != PINNED['reports/stage4/age_colsample_specification.json']
            or seed_source['specification_sha256'] != PINNED['reports/stage4/age_seed_stability_specification.json']
            or read_json(root / EVENT_SOURCE)['decision'] != 'pending_data_no_training'):
        raise ValueError('Frozen source or pending-data decision changed')
    for info in (source['feature_dataset'], source['score_export']):
        item = descriptor(root / info['path'], root)
        if item['sha256'] != info['sha256']:
            raise ValueError('Feature/score source hash changed')
        sources.append(item)
    models = model_manifest(source, seed_source)
    for info in models:
        item = descriptor(root / info['path'], root)
        if item['sha256'] != info['sha256']:
            raise ValueError('Frozen monthly model bytes changed')
        info['bytes'] = item['bytes']
    _, selected = load_roster(source, root)
    code = [descriptor(root / name, root) for name in CODE_FILES]
    verify_sources(sources + models + code, root)
    return {
        'format_version': 1, 'analysis': ANALYSIS, 'contract': contract(), 'schema': core.schema(),
        'selected_day': selected, 'sources': sources, 'monthly_models': models, 'analysis_code': code,
        'private_directory': PRIVATE_DIRECTORY,
        'source_clock_limit': 'No raw ingested-at clock, event capture denominator, historical promise versions or production day-close proof.',
    }


def read_day_scores(path, selected_day, source, *, chunksize=100000):
    expected_header = source['score_export']['source_columns'] + [source['score_export']['appended_discriminator']]
    if pd.read_csv(path, nrows=0).columns.tolist() != expected_header:
        raise ValueError('Frozen score header changed')
    if 'outcome_for_metrics' in core.REQUIRED_LEDGER_COLUMNS:
        raise AssertionError('Outcome column must never be read for delivery acceptance')
    pieces, total = [], 0
    for part in pd.read_csv(path, usecols=list(core.REQUIRED_LEDGER_COLUMNS),
                            float_precision='round_trip', chunksize=chunksize, dtype={'order_id': str}):
        total += len(part)
        # Restrict phase using version metadata before interpreting selected clocks.
        scoped = part.loc[part.fold.eq(MONTH) & part.role.eq('evaluation') & part.model_version.eq(MONTH)].copy()
        if not scoped.empty:
            scoped['prediction_time'] = _parsed(scoped.prediction_time, 'ledger prediction_time')
            pieces.append(scoped.loc[scoped.prediction_time.dt.normalize().eq(pd.Timestamp(selected_day))])
    if total != source['score_export']['rows'] or not pieces:
        raise ValueError('Frozen ledger total rows or selected day missing')
    return pd.concat(pieces, ignore_index=True), total


def verify_boundaries(public, private, previous):
    """Compare original boundary scores internally, publishing only check counts."""
    checked = 0
    for run in public['runs']:
        seed, version = run['seed'], run['version']
        days = previous['seed_phases'][str(seed)][TARGET_PHASE]['daily_boundaries']
        selected = [item for item in days if item['day'] == public['day']]
        if len(selected) != 1:
            raise ValueError('Require exactly one original boundary for the accepted day')
        day = selected[0]
        if day['full_rows'] != public['full_day_rows'] or day['capacity'] != public['daily_capacity']:
            raise ValueError('Original day denominator or capacity changed')
        frozen = day['models'][version]
        if frozen['known_alerts'] != run['alerts'] or frozen['unknown_alerts'] != 0:
            raise ValueError('Original evaluation known/unknown alert counts changed')
        part = private.loc[private.version.eq(version) & private.seed.eq(seed)]
        size, capacity = len(part), public['daily_capacity']
        values = part.score.to_numpy()
        cutoff = float(values[capacity - 1]) if capacity else None
        following = float(values[capacity]) if capacity < size else None
        comparisons = {'cutoff_score': cutoff, 'next_score': following,
                       'score_margin': cutoff - following if cutoff is not None and following is not None else None}
        comparisons.update({name: run['ties'][name] for name in
                            ('cutoff_tie_rows', 'cutoff_tie_alerted_rows', 'cutoff_tie_unalerted_rows', 'cross_boundary_tie')})
        if any(frozen[name] != value for name, value in comparisons.items()):
            raise ValueError('Reconstructed boundary differs from the frozen boundary report')
        checked += len(comparisons) + 4
    return {'runs_verified': len(public['runs']), 'aggregate_and_internal_boundary_fields_verified': checked,
            'individual_boundary_scores_published': False}


def private_path(path, *, root=ROOT, sources=()):
    root, path = Path(root).resolve(), Path(path).resolve()
    runtime = (root / '.runtime').resolve()
    if (not runtime.is_relative_to(root) or not path.is_relative_to(runtime) or path == runtime
            or path in {(root / item['path']).resolve() for item in sources}):
        raise ValueError('Private output must stay in project .runtime and cannot overwrite a source')
    relative = path.relative_to(root).as_posix()
    check = subprocess.run(['git', '-C', str(root), 'check-ignore', '--quiet', '--', relative],
                           capture_output=True, check=False)
    if check.returncode != 0:
        raise ValueError('Private output must be covered by Git ignore rules')
    return path


def immutable_bundle(bundle, *, root=ROOT, sources=()):
    """Preflight every member before writing any missing file; never overwrite."""
    checked = [(private_path(path, root=root, sources=sources), content) for path, content in bundle.items()]
    if len({path for path, _ in checked}) != len(checked):
        raise ValueError('Private bundle paths must be distinct')
    for path, content in checked:
        if not isinstance(content, bytes):
            raise ValueError('Private bundle members must be exact bytes')
        if path.exists() and (not path.is_file() or path.read_bytes() != content):
            raise ValueError(f'Refusing to overwrite a different private bundle member: {path.name}')
    for path, content in checked:
        if not path.exists():
            path.parent.mkdir(parents=True, exist_ok=True)
            with path.open('xb') as stream:
                stream.write(content)


def public_json_path(path, *, root=ROOT, sources=()):
    root, path = Path(root).resolve(), Path(path).resolve()
    protected = {(root / item['path']).resolve() for item in sources}
    if (not path.is_relative_to(root) or path.suffix.lower() != '.json'
            or path.is_relative_to(root / 'data') or path.is_relative_to(root / 'models') or path in protected):
        raise ValueError('Public JSON must be a separate project output outside data/models and protected sources')
    return path


def immutable_json(path, payload, *, root=ROOT, sources=()):
    path = public_json_path(path, root=root, sources=sources)
    encoded = json_bytes(payload)
    if path.exists():
        if read_json(path) != payload:
            raise ValueError('Refusing to overwrite different public JSON content')
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('xb') as stream:
        stream.write(encoded)


def csv_bytes(frame):
    return frame.to_csv(index=False, float_format='%.17g', lineterminator='\n').encode('utf-8')


def readback_csv(content):
    return pd.read_csv(io.BytesIO(content), float_precision='round_trip', dtype={'order_id': str},
                       parse_dates=['prediction_time'])


def verify_csv_bundle(roster, rankings, alerts, private, *, day):
    ranking_frame, alert_frame = readback_csv(rankings), readback_csv(alerts)
    output_checks = core.verify_private_output(roster, ranking_frame, day=day)
    try:
        pd.testing.assert_frame_equal(ranking_frame, private, check_dtype=False, check_exact=True)
        pd.testing.assert_frame_equal(alert_frame, private.loc[private.alert].reset_index(drop=True),
                                      check_dtype=False, check_exact=True)
    except AssertionError as exc:
        raise ValueError('CSV readback differs from accepted frozen scores or exact alert subset') from exc
    return {**output_checks, 'exact_frozen_score_rows_verified': len(private),
            'exact_selected_subset_rows_verified': len(alert_frame)}


def build_report(specification_path, output_path=OUTPUT, *, root=ROOT):
    root = Path(root)
    expected = make_specification(root)
    specification = read_json(specification_path)
    if specification != expected:
        raise ValueError('Delivery specification, source manifest or analysis code changed')
    bound = specification['sources'] + specification['monthly_models'] + specification['analysis_code']
    verify_sources(bound, root)
    source = read_json(root / COLSAMPLE)
    roster, selected = load_roster(source, root)
    if selected != specification['selected_day']:
        raise ValueError('Selected complete day changed')
    ledger, total = read_day_scores(root / source['score_export']['path'], selected['day'], source)
    public, private = core.accept_day(roster, ledger, day=selected['day'])
    boundary_checks = verify_boundaries(public, private, read_json(root / BOUNDARY))
    rankings = csv_bytes(private)
    alerts = csv_bytes(private.loc[private.alert].reset_index(drop=True))
    csv_checks = verify_csv_bundle(roster, rankings, alerts, private, day=selected['day'])
    paths = {name: root / specification['private_directory'] / name for name in ('rankings.csv', 'alerts.csv', 'manifest.json')}
    specification_item = descriptor(specification_path, root)
    private_manifest = {
        'format_version': 1, 'analysis': ANALYSIS, 'specification': specification_item,
        'source_scores': descriptor(root / source['score_export']['path'], root),
        'day': selected['day'], 'outputs': [
            {'path': paths[name].relative_to(root).as_posix(), 'rows': rows,
             'bytes': len(content), 'sha256': hashlib.sha256(content).hexdigest()}
            for name, content, rows in (('rankings.csv', rankings, len(private)), ('alerts.csv', alerts, int(private.alert.sum())))],
        'privacy': 'Local ignored manifest; output hashes are not published in aggregate reports.',
    }
    bundle = {paths['rankings.csv']: rankings, paths['alerts.csv']: alerts,
              paths['manifest.json']: json_bytes(private_manifest)}
    outputs = [{'path': paths[name].relative_to(root).as_posix(), 'rows': rows,
                'columns': list(core.PRIVATE_COLUMNS), 'status': 'exact_readback_verified'}
               for name, rows in (('rankings.csv', len(private)), ('alerts.csv', int(private.alert.sum())))]
    report = {
        'format_version': 1, 'status': 'ok', 'analysis': ANALYSIS,
        'specification': specification_item, 'contract': specification['contract'], 'schema': specification['schema'],
        'selected_day': selected, 'acceptance': public, 'source_manifest': specification['sources'],
        'monthly_model_manifest': specification['monthly_models'], 'analysis_code': specification['analysis_code'],
        'private_outputs': outputs, 'verification': {
            'bound_source_and_model_and_code_files': len(bound), 'ledger_total_rows_verified': total,
            'frozen_source_alert_flags_verified': len(private), 'frozen_source_daily_ranks_available': 0,
            'original_boundary': boundary_checks, 'private_csv': csv_checks,
            'new_fit_count': 0, 'model_deserializations': 0, 'new_prediction_count': 0,
            'score_ledger_outcome_columns_parsed': 0, 'score_ledger_outcomes_used': False,
            'new_performance_metrics': 0, 'new_model_selection': 0,
            'original_retained_test_scored': False,
        },
        'decision': 'offline_frozen_score_delivery_verified_event_signals_pending_data_no_training',
        'limitations': [
            'The 242-row day is a complete research cohort, not complete raw approval coverage; final status is retrospective.',
            'Five seeds repeat the same identities; total selected rows across runs are not distinct orders or a combined notification list.',
            'Logical historical fit/scoring timestamps do not prove original ingestion or production as-of model availability.',
            'No score-ledger outcome values or performance conclusions are produced; raw status/timelines establish only the retrospective cohort. Live data, day-close, notification SLA and effect remain unaccepted.',
        ],
    }
    # Preflight public content before private writes; an incompatible report must
    # not leave a new private delivery bundle behind.
    output_path = public_json_path(output_path, root=root, sources=bound + [specification_item])
    if output_path in {path.resolve() for path in paths.values()}:
        raise ValueError('Public report must not collide with a private bundle member')
    if output_path.exists() and read_json(output_path) != report:
        raise ValueError('Refusing a different existing public acceptance report')
    verify_sources(bound + [specification_item], root)
    immutable_bundle(bundle, root=root, sources=bound + [specification_item])
    # Re-read the actual files, not only their in-memory serialization.
    verify_csv_bundle(roster, paths['rankings.csv'].read_bytes(), paths['alerts.csv'].read_bytes(), private, day=selected['day'])
    if read_json(paths['manifest.json']) != private_manifest:
        raise ValueError('Private manifest readback changed')
    verify_sources(bound + [specification_item], root)
    immutable_json(output_path, report, root=root, sources=bound + [specification_item])
    verify_sources(bound + [specification_item], root)
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--specification', type=Path, default=SPECIFICATION)
    parser.add_argument('--output', type=Path, default=OUTPUT)
    parser.add_argument('--specification-only', action='store_true', help='Freeze only the delivery contract and source snapshot')
    args = parser.parse_args()
    if args.specification_only:
        specification = make_specification()
        bound = specification['sources'] + specification['monthly_models'] + specification['analysis_code']
        immutable_json(args.specification, specification, sources=bound)
        verify_sources(bound)
        print('Delivery contract and source snapshot frozen; no model or score replay.', flush=True)
    else:
        report = build_report(args.specification, args.output)
        print(f'Accepted {report["selected_day"]["day"]}: {report["acceptance"]["run_count"]} frozen runs; no training or performance evaluation.', flush=True)


if __name__ == '__main__':
    main()
