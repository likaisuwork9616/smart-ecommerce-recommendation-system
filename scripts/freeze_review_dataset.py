"""Freeze and audit order-level approval-time review labels; never fit a model."""
from __future__ import annotations

import argparse
import csv
import hashlib
import io
import json
from pathlib import Path
import subprocess

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
CODE = 'scripts/freeze_review_dataset.py'
PRIOR = 'reports/stage5/review_prediction_feasibility.json'
PRIOR_SHA = 'aa47a3218bcefbe6d6f2f10f1200f8d7b3c7a342c7f094e6a5520cee7e600c3f'
SPEC = 'reports/stage5/review_dataset_specification.json'
REPORT = 'reports/stage5/review_dataset_audit.json'
PRIVATE = '.runtime/stage5_review_dataset_v1'
ORDERS = 'data/raw/olist/olist_orders_dataset.csv'
REVIEWS = 'data/raw/olist/olist_order_reviews_dataset.csv'
CUSTOMERS = 'data/raw/olist/olist_customers_dataset.csv'
ORDER_COLUMNS = ['order_id', 'customer_id', 'order_purchase_timestamp', 'order_approved_at']
REVIEW_COLUMNS = ['review_id', 'order_id', 'review_score', 'review_creation_date',
                  'review_answer_timestamp']
COHORT_CUTOFF = pd.Timestamp('2018-05-01')
OBSERVATION_CUTOFF = pd.Timestamp('2018-07-01')
HORIZON_DAYS = 60
OUTER_MONTHS = ('2017-12', '2018-02', '2018-04')
LABEL_COLUMNS = ['order_id', 'prediction_time', 'window_deadline', 'observation_cutoff',
                 'horizon_complete', 'label_state', 'role_label_usable', 'y',
                 'first_visible_answer_at']
MEMBERSHIP_COLUMNS = ['outer_fold', 'role', 'fit_at'] + LABEL_COLUMNS
STATES = ('known_low_1_2', 'known_other_3_5', 'immature_observation_window',
          'unpositionable_answer_source_quality', 'invalid_visible_review_quality',
          'ambiguous_first_answer_tie', 'first_answer_not_after_approval',
          'late_answer_unknown', 'no_visible_answer_at_cutoff')


def protocol():
    return {
        'unit': 'one_order', 'prediction_time': 'order_approved_at',
        'cohort': {'purchase_and_approval_parseable': True,
                   'approval_not_before_purchase': True,
                   'approval_cutoff_exclusive': '2018-05-01',
                   'final_status_filter': False, 'missing_features_filter': False},
        'target': 'first_recorded_answer_in_(approval,approval+60_elapsed_days]_is_1_or_2',
        'horizon_elapsed_days': HORIZON_DAYS,
        'observation_cutoff_exclusive': '2018-07-01',
        'window_maturity': 'approval+60_days_strictly_before_each_role_cutoff',
        'answer_visibility': 'recorded_answer_strictly_before_each_role_cutoff',
        'unknown_target': 'nullable_y_never_imputed_to_negative',
        'review_policy': {
            'visible_rows_before_quality_checks': True,
            'quality_relevant_rows': 'visible_answer_at_or_before_order_window_deadline',
            'first_answer': 'earliest_visible_answer_including_answers_not_after_approval',
            'early_answer': 'quarantine_never_repick_later_answer',
            'ties': 'quarantine_even_equal_scores',
            'invalid_visible_in_window_row': 'quarantine_order_without_repick',
            'missing_or_unparseable_answer': 'static_source_quality_quarantine_order',
            'duplicate_key': '(review_id,order_id)_within_visible_in_window_rows',
            'review_id_reused_across_orders': 'allowed',
            'score': 'integer_1_through_5',
            'creation': 'parseable_and_not_after_answer',
            'late_answer_after_window': 'unknown_not_negative',
            'change_from_feasibility': 'no_future_parseable_row_can_quarantine_earlier_role'},
        'outer_query_months': list(OUTER_MONTHS),
        'inner_query_calendar_rule': 'latest_full_month_whose_end_plus_60_days_is_at_or_before_outer_fit',
        'inner_train_label_cutoff': 'inner_month_start',
        'inner_validation_label_cutoff': 'outer_month_start',
        'outer_train_label_cutoff': 'outer_month_start',
        'outer_evaluation_label_cutoff': '2018-07-01',
        'pool_policy': 'keep_all_time_eligible_orders_and_mask_unusable_y',
        'fit_policy': 'strict_maturity_and_valid_answer_before_fit_no_training_executed',
        'time_zone': 'original_naive_snapshot_clock_no_verified_business_zone_or_ingestion',
        'observation_claim': 'event_proxy_only_not_source_completeness_or_live_availability',
        'selection_claim': 'fixed_development_calendar_not_unseen_holdout',
        'candidate_features': 'prior_21_conditional_definitions_only_no_values_built',
        'stage4': {'status': 'pending_data', 'daily_budget': 0.10,
                   'seeds': [11, 29, 42, 73, 101], 'modified': False},
        'prohibited_this_run': ['training', 'feature_build', 'model_load', 'prediction',
                                'performance_metrics', 'model_selection', 'dashboard']}


def read_json(path):
    def unique(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise ValueError('Duplicate JSON key')
            result[key] = value
        return result
    def invalid(value):
        raise ValueError('Non-finite JSON value')
    return json.loads(Path(path).read_text(encoding='utf-8'), object_pairs_hook=unique,
                      parse_constant=invalid)


def json_bytes(value):
    return (json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2,
                       allow_nan=False) + '\n').encode('utf-8')


def descriptor(path, root=ROOT):
    path, root = Path(path).resolve(), Path(root).resolve()
    if not path.is_relative_to(root) or not path.is_file():
        raise ValueError('Source must be an existing project file')
    digest = hashlib.sha256()
    with path.open('rb') as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b''):
            digest.update(chunk)
    return {'path': path.relative_to(root).as_posix(), 'bytes': path.stat().st_size,
            'sha256': digest.hexdigest()}


def verify_sources(items, root=ROOT):
    if len({item['path'] for item in items}) != len(items):
        raise ValueError('Duplicate source binding')
    for item in items:
        if descriptor(Path(root) / item['path'], root) != {
                name: item[name] for name in ('path', 'bytes', 'sha256')}:
            raise ValueError('Bound source changed: ' + item['path'])
    return len(items)


def immutable_preflight(path, data):
    path = Path(path)
    if path.exists() and (not path.is_file() or path.read_bytes() != data):
        raise ValueError('Refusing to overwrite different output bytes')


def immutable_write(path, data):
    immutable_preflight(path, data)
    path = Path(path)
    if not path.exists():
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open('xb') as stream:
            stream.write(data)


def safe_output(path, allowed_public, root=ROOT, private=False):
    root, path = Path(root).resolve(), Path(path).resolve()
    if not path.is_relative_to(root):
        raise ValueError('Resolved output must stay inside the project root')
    runtime = (root / '.runtime').resolve()
    in_private = runtime.is_relative_to(root) and path.is_relative_to(runtime)
    if private and not in_private:
        raise ValueError('Private output must stay inside project .runtime')
    if not private and path != (root / allowed_public).resolve() and not in_private:
        raise ValueError('Output must be the designated public report or project .runtime')
    if in_private:
        checked = subprocess.run(['git', 'check-ignore', '--quiet', '--',
                                  path.relative_to(root).as_posix()], cwd=root,
                                 check=False, capture_output=True)
        if checked.returncode != 0:
            raise ValueError('Private output is not Git ignored')
    return path


def parse_clock(values):
    return pd.to_datetime(values, format='%Y-%m-%d %H:%M:%S', errors='coerce')


def approval_cohort(orders):
    missing = set(ORDER_COLUMNS) - set(orders.columns)
    if missing:
        raise ValueError('Missing order columns')
    if orders.order_id.isna().any() or orders.order_id.eq('').any() or orders.order_id.duplicated().any():
        raise ValueError('Order IDs must be present and unique')
    purchase = parse_clock(orders.order_purchase_timestamp)
    approval = parse_clock(orders.order_approved_at)
    valid = purchase.notna() & approval.notna() & approval.ge(purchase)
    result = orders.loc[valid & approval.lt(COHORT_CUTOFF), ['order_id', 'customer_id']].copy()
    result['prediction_time'] = approval.loc[result.index]
    result['window_deadline'] = result.prediction_time + pd.Timedelta(days=HORIZON_DAYS)
    result = result.sort_values(['prediction_time', 'order_id']).reset_index(drop=True)
    quality = {'source_orders': len(orders), 'missing_or_invalid_purchase': int(purchase.isna().sum()),
               'missing_or_invalid_approval': int(approval.isna().sum()),
               'approval_before_purchase': int(approval.lt(purchase).sum()),
               'valid_purchase_approval': int(valid.sum()), 'cohort_orders': len(result),
               'final_status_filter_applied': False, 'missing_feature_filter_applied': False}
    return result, quality


def prepare_reviews(reviews):
    if set(REVIEW_COLUMNS) - set(reviews.columns):
        raise ValueError('Missing review columns')
    result = reviews[REVIEW_COLUMNS].copy()
    result['answer_at'] = parse_clock(result.review_answer_timestamp)
    result['creation_at'] = parse_clock(result.review_creation_date)
    result['score'] = pd.to_numeric(result.review_score, errors='coerce')
    result['score_valid'] = result.score.isin([1, 2, 3, 4, 5])
    result['key_valid'] = result.review_id.notna() & result.review_id.ne('')
    # This inventory is source quality, not a historical availability claim.
    quality = {'source_review_rows': len(result),
               'missing_order_key_rows': int((result.order_id.isna() | result.order_id.eq('')).sum()),
               'unpositionable_answer_rows': int(result.answer_at.isna().sum()),
               'unpositionable_answer_orders': int(result.loc[result.answer_at.isna(), 'order_id'].nunique()),
               'missing_review_key_rows': int((~result.key_valid).sum()),
               'invalid_score_rows': int((~result.score_valid).sum()),
               'missing_or_invalid_creation_rows': int(result.creation_at.isna().sum()),
               'creation_after_answer_rows': int(result.creation_at.gt(result.answer_at).sum()),
               'duplicate_pair_rows': int(result.duplicated(['review_id', 'order_id'], keep=False).sum()),
               'multi_review_orders': int(result.groupby('order_id').size().gt(1).sum()),
               'review_id_reused_across_orders_groups': int(result.groupby('review_id').order_id.nunique().gt(1).sum())}
    return result, quality


def label_asof(cohort, prepared, cutoff):
    """Build labels at one cutoff, with no future parseable quality taint."""
    cutoff = pd.Timestamp(cutoff)
    if cutoff.tzinfo is not None:
        raise ValueError('Cutoff must use the original naive clock')
    if cohort.order_id.duplicated().any() or cohort.order_id.isna().any():
        raise ValueError('Cohort must have one row per order')
    frame = cohort[['order_id', 'prediction_time', 'window_deadline']].copy()
    frame['observation_cutoff'] = cutoff
    frame['horizon_complete'] = frame.window_deadline.lt(cutoff)
    static_bad = set(prepared.loc[prepared.answer_at.isna(), 'order_id'].dropna())
    # Filter visibility BEFORE score/key/creation and duplicate quality checks.
    visible = prepared.loc[prepared.answer_at.lt(cutoff)].merge(
        frame[['order_id', 'window_deadline']], on='order_id', how='inner', validate='many_to_one')
    visible = visible.sort_values(['order_id', 'answer_at', 'review_id'], na_position='last')
    first = visible.drop_duplicates('order_id').set_index('order_id')
    frame['first_visible_answer_at'] = first.answer_at.reindex(frame.order_id).to_numpy()
    first_score = pd.Series(first.score.reindex(frame.order_id).to_numpy(), index=frame.index)
    relevant = visible.loc[visible.answer_at.le(visible.window_deadline)].copy()
    duplicate = relevant.duplicated(['review_id', 'order_id'], keep=False)
    invalid = (~relevant.key_valid | ~relevant.score_valid | relevant.creation_at.isna()
               | relevant.creation_at.gt(relevant.answer_at) | duplicate)
    bad_ids = set(relevant.loc[invalid, 'order_id'])
    earliest = relevant.groupby('order_id').answer_at.transform('min')
    tied_ids = set(relevant.loc[relevant.answer_at.eq(earliest)].groupby('order_id').size().loc[lambda x: x.gt(1)].index)
    has_answer = frame.first_visible_answer_at.notna()
    within = has_answer & frame.first_visible_answer_at.le(frame.window_deadline)
    after = within & frame.first_visible_answer_at.gt(frame.prediction_time)
    early = within & ~after
    usable = (frame.horizon_complete & after & ~frame.order_id.isin(static_bad)
              & ~frame.order_id.isin(bad_ids) & ~frame.order_id.isin(tied_ids))
    frame['y'] = pd.Series(pd.NA, index=frame.index, dtype='Int64')
    frame.loc[usable, 'y'] = first_score.loc[usable].le(2).astype('int64')
    frame['role_label_usable'] = usable
    frame['label_state'] = 'no_visible_answer_at_cutoff'
    frame.loc[has_answer & ~within, 'label_state'] = 'late_answer_unknown'
    frame.loc[~frame.horizon_complete, 'label_state'] = 'immature_observation_window'
    frame.loc[usable & frame.y.eq(0).fillna(False), 'label_state'] = 'known_other_3_5'
    frame.loc[usable & frame.y.eq(1).fillna(False), 'label_state'] = 'known_low_1_2'
    frame.loc[early, 'label_state'] = 'first_answer_not_after_approval'
    frame.loc[frame.order_id.isin(tied_ids), 'label_state'] = 'ambiguous_first_answer_tie'
    frame.loc[frame.order_id.isin(bad_ids), 'label_state'] = 'invalid_visible_review_quality'
    frame.loc[frame.order_id.isin(static_bad), 'label_state'] = 'unpositionable_answer_source_quality'
    result = frame[LABEL_COLUMNS].reset_index(drop=True)
    violations = {'usable_answer_not_before_cutoff': int((usable & ~frame.first_visible_answer_at.lt(cutoff)).sum()),
                  'usable_deadline_not_before_cutoff': int((usable & ~frame.window_deadline.lt(cutoff)).sum()),
                  'usable_answer_not_after_approval': int((usable & ~frame.first_visible_answer_at.gt(frame.prediction_time)).sum()),
                  'usable_answer_after_deadline': int((usable & frame.first_visible_answer_at.gt(frame.window_deadline)).sum()),
                  'unusable_nonnull_y': int((~usable & frame.y.notna()).sum()),
                  'usable_null_y': int((usable & frame.y.isna()).sum()),
                  'visible_metadata_at_or_after_cutoff': int(frame.first_visible_answer_at.ge(cutoff).sum())}
    if any(violations.values()):
        raise ValueError('Label availability invariant failed')
    states = {state: int(result.label_state.eq(state).sum()) for state in STATES}
    if sum(states.values()) != len(result):
        raise ValueError('Label state accounting failed')
    summary = {'orders': len(result), 'cutoff_exclusive': str(cutoff),
               'mature_windows': int(frame.horizon_complete.sum()),
               'immature_windows': int((~frame.horizon_complete).sum()),
               'usable_labels': int(usable.sum()), 'unknown_or_ineligible_labels': int((~usable).sum()),
               'low_1_2': int(frame.y.eq(1).sum()), 'other_3_5': int(frame.y.eq(0).sum()),
               'exclusive_label_states': states,
               'early_answered_but_immature_excluded': int((after & ~frame.horizon_complete & ~frame.order_id.isin(static_bad | bad_ids | tied_ids)).sum()),
               'source_quality_quarantine_is_historical_availability_proof': False,
               'leakage_violations': violations}
    return result, summary


def calendar_split_plan():
    result = []
    for month in OUTER_MONTHS:
        outer = pd.Timestamp(month + '-01')
        candidate = outer - pd.offsets.MonthBegin(1)
        while candidate + pd.offsets.MonthBegin(1) + pd.Timedelta(days=HORIZON_DAYS) > outer:
            candidate -= pd.offsets.MonthBegin(1)
        inner_end = candidate + pd.offsets.MonthBegin(1)
        result.append({'outer_fold': month, 'outer_fit_at': str(outer),
                       'outer_query_start': str(outer),
                       'outer_query_end_exclusive': str(outer + pd.offsets.MonthBegin(1)),
                       'inner_fit_at': str(candidate), 'inner_query_start': str(candidate),
                       'inner_query_end_exclusive': str(inner_end),
                       'inner_month_end_plus_horizon': str(inner_end + pd.Timedelta(days=HORIZON_DAYS))})
    return result


def build_membership(cohort, prepared, customer_unique=None):
    pieces, folds = [], []
    cache = {}
    def at(cutoff):
        if cutoff not in cache:
            cache[cutoff] = label_asof(cohort, prepared, cutoff)[0].set_index('order_id', drop=False)
        return cache[cutoff]
    for plan in calendar_split_plan():
        outer, inner = pd.Timestamp(plan['outer_fit_at']), pd.Timestamp(plan['inner_fit_at'])
        inner_end = pd.Timestamp(plan['inner_query_end_exclusive'])
        outer_end = pd.Timestamp(plan['outer_query_end_exclusive'])
        roles = [('inner_train_pool', cohort.prediction_time.lt(inner), inner, inner),
                 ('inner_validation', cohort.prediction_time.ge(inner) & cohort.prediction_time.lt(inner_end), outer, inner),
                 ('outer_train_pool', cohort.prediction_time.lt(outer), outer, outer),
                 ('outer_evaluation', cohort.prediction_time.ge(outer) & cohort.prediction_time.lt(outer_end), OBSERVATION_CUTOFF, outer)]
        role_frames, summaries = {}, {}
        for role, mask, cutoff, fit in roles:
            subcohort = cohort.loc[mask]
            result = at(cutoff).loc[subcohort.order_id].reset_index(drop=True)
            # Generate accounting independently for the precise role pool.
            _, summary = label_asof(subcohort, prepared, cutoff)
            summary.update({'role': role, 'fit_at': str(fit), 'role_cutoff_exclusive': str(cutoff),
                            'pool_includes_unknown_or_ineligible': True, 'actual_fits': 0})
            role_frames[role] = result
            summaries[role] = summary
            result.insert(0, 'fit_at', fit)
            result.insert(0, 'role', role)
            result.insert(0, 'outer_fold', plan['outer_fold'])
            pieces.append(result[MEMBERSHIP_COLUMNS])
        overlap = {}
        for train, query in [('inner_train_pool', 'inner_validation'),
                             ('outer_train_pool', 'outer_evaluation'),
                             ('inner_train_pool', 'outer_evaluation'),
                             ('inner_validation', 'outer_evaluation')]:
            overlap[train + '_vs_' + query] = len(set(role_frames[train].order_id) & set(role_frames[query].order_id))
        if any(overlap.values()):
            raise ValueError('Train-query order overlap')
        customer_overlap = {}
        if customer_unique is not None:
            for train, query in [('inner_train_pool', 'inner_validation'),
                                 ('outer_train_pool', 'outer_evaluation')]:
                a = set(role_frames[train].order_id.map(customer_unique).dropna())
                b = set(role_frames[query].order_id.map(customer_unique).dropna())
                customer_overlap[train + '_vs_' + query] = len(a & b)
        folds.append({'calendar': plan, 'roles': summaries,
                      'train_query_order_overlap': overlap,
                      'customer_unique_id_overlap_groups': customer_overlap})
    return pd.concat(pieces, ignore_index=True), folds


def make_specification(root=ROOT):
    root = Path(root)
    prior = descriptor(root / PRIOR, root)
    if prior['sha256'] != PRIOR_SHA:
        raise ValueError('Prior feasibility report changed')
    previous = read_json(root / PRIOR)
    sources = [{name: item[name] for name in ('path', 'bytes', 'sha256')}
               for item in previous['sources']]
    verify_sources(sources, root)
    # Header checking uses only the prior pinned schema; no candidate feature values.
    schemas = []
    for item in previous['sources']:
        if 'columns' in item:
            with (root / item['path']).open(encoding='utf-8-sig', newline='') as stream:
                columns = next(csv.reader(stream))
            if columns != item['columns']:
                raise ValueError('Raw CSV schema changed')
            schemas.append({'path': item['path'], 'columns': columns,
                            'previous_snapshot_rows': item['rows']})
    sources += [prior, descriptor(root / CODE, root)]
    verify_sources(sources, root)
    return {'format_version': 1, 'role': 'frozen_dataset_contract_not_training_preregistration',
            'protocol': protocol(), 'calendar_split_plan': calendar_split_plan(),
            'sources': sources, 'raw_schemas': schemas,
            'expected_existing_cohort_orders': 73254,
            'private_output_root': PRIVATE,
            'public_output': REPORT,
            'privacy': {'public_individual_ids_labels_scores': False,
                        'public_roster_hash_or_private_output_digest': False,
                        'private_source_join_keys_only_not_model_inputs': True}}


def verify_specification(spec, root=ROOT):
    expected = make_specification(root)
    if spec != expected:
        raise ValueError('Frozen specification does not match current protocol and sources')
    return verify_sources(spec['sources'], root)


def csv_bytes(frame):
    return frame.to_csv(index=False, lineterminator='\n', date_format='%Y-%m-%d %H:%M:%S',
                        na_rep='').encode('utf-8')


def read_private_csv(data, columns):
    frame = pd.read_csv(io.BytesIO(data), dtype='string', keep_default_na=False)
    if list(frame.columns) != list(columns):
        raise ValueError('Unexpected private CSV schema')
    dates = ['prediction_time', 'window_deadline', 'observation_cutoff', 'first_visible_answer_at']
    if 'fit_at' in columns:
        dates += ['fit_at']
    for name in dates:
        raw = frame[name]
        frame[name] = parse_clock(raw.replace('', pd.NA))
        if (raw.ne('') & frame[name].isna()).any():
            raise ValueError('Private CSV clock failed parsing')
    for name in ('horizon_complete', 'role_label_usable'):
        if not frame[name].isin(['True', 'False']).all():
            raise ValueError('Private CSV boolean invalid')
        frame[name] = frame[name].eq('True').astype(bool)
    if not frame.y.isin(['', '0', '1']).all():
        raise ValueError('Private CSV target invalid')
    frame['y'] = pd.to_numeric(frame.y.replace('', pd.NA)).astype('Int64')
    for name in set(columns) - set(dates) - {'horizon_complete', 'role_label_usable', 'y'}:
        frame[name] = frame[name].astype(object)
    return frame[columns]


def assert_exact_private(frame, data):
    restored = read_private_csv(data, list(frame.columns))
    expected = frame.copy()
    for name in expected.select_dtypes(include=['string']).columns:
        expected[name] = expected[name].astype(object)
    pd.testing.assert_frame_equal(expected.reset_index(drop=True), restored, check_exact=True)
    if restored.loc[~restored.role_label_usable, 'y'].notna().any():
        raise ValueError('Unusable label leaked in private output')
    return {'rows': len(frame), 'columns': len(frame.columns),
            'exact_cells_compared': len(frame) * len(frame.columns),
            'nullable_y_mask_verified': True}


def write_private_bundle(labels, membership, spec, root=ROOT, directory=None,
                         specification_sha256=None, public_preflight=None):
    root = Path(root)
    directory = safe_output(root / (directory or PRIVATE), '', root, private=True)
    frames = {'order_labels.csv': labels, 'split_membership.csv': membership}
    payloads = {name: csv_bytes(frame) for name, frame in frames.items()}
    checks = {name: assert_exact_private(frames[name], payloads[name]) for name in frames}
    manifest = {'format_version': 1, 'kind': 'private_order_label_metadata_not_features',
                'protocol': spec['protocol'],
                'specification_sha256': specification_sha256 or hashlib.sha256(json_bytes(spec)).hexdigest(),
                'files': {name: {'bytes': len(data), 'sha256': hashlib.sha256(data).hexdigest(),
                                 'rows': len(frames[name]), 'columns': list(frames[name].columns)}
                          for name, data in payloads.items()},
                'actual_model_fits': 0, 'unknown_y_is_nullable': True}
    payloads['manifest.json'] = json_bytes(manifest)
    public = {name: {'path': (directory / name).relative_to(root.resolve()).as_posix(),
                     'rows': len(frame), 'columns': list(frame.columns)}
              for name, frame in frames.items()}
    public['manifest'] = {'path': (directory / 'manifest.json').relative_to(root.resolve()).as_posix(),
                          'verified': True, 'digest_public': False}
    bound_paths = {(root / item['path']).resolve() for item in spec['sources']}
    for name, data in payloads.items():
        path = safe_output(directory / name, '', root, private=True)
        if path in bound_paths:
            raise ValueError('Output collides with bound source')
        immutable_preflight(path, data)
    # Preflight all three artifacts before any writes.
    verify_sources(spec['sources'], root)
    if public_preflight is not None:
        public_preflight(public, checks)
    for name, data in payloads.items():
        immutable_write(directory / name, data)
    for name, frame in frames.items():
        checks[name] = assert_exact_private(frame, (directory / name).read_bytes())
    if read_json(directory / 'manifest.json') != manifest:
        raise ValueError('Private manifest readback mismatch')
    verify_sources(spec['sources'], root)
    return public, checks


def run_audit(spec, root=ROOT, directory=None, specification_path=None, output_path=None):
    root = Path(root)
    bound = verify_specification(spec, root)
    specification_path = safe_output(specification_path or root / SPEC, SPEC, root)
    output_path = safe_output(output_path or root / REPORT, REPORT, root)
    private_directory = safe_output(root / (directory or PRIVATE), '', root, private=True)
    if specification_path.is_relative_to(private_directory) or output_path.is_relative_to(private_directory):
        raise ValueError('Public output collides with private bundle directory')
    specification_source = descriptor(specification_path, root)
    if read_json(specification_path) != spec:
        raise ValueError('Specification bytes do not describe the loaded contract')
    bound_paths = {(root / item['path']).resolve() for item in spec['sources']}
    if (output_path in bound_paths or specification_path in bound_paths
            or output_path == specification_path):
        raise ValueError('Public output collides with a source or specification')
    orders = pd.read_csv(root / ORDERS, usecols=ORDER_COLUMNS, dtype='string')
    raw_reviews = pd.read_csv(root / REVIEWS, usecols=REVIEW_COLUMNS, dtype='string')
    customers = pd.read_csv(root / CUSTOMERS, usecols=['customer_id', 'customer_unique_id'], dtype='string')
    if customers.customer_id.isna().any() or customers.customer_id.duplicated().any():
        raise ValueError('Customer join key must be unique')
    cohort, order_quality = approval_cohort(orders)
    if len(cohort) != spec['expected_existing_cohort_orders']:
        raise ValueError('Cohort count differs from existing frozen feasibility source')
    prepared, review_quality = prepare_reviews(raw_reviews)
    if review_quality['missing_order_key_rows']:
        raise ValueError('Unmapped review rows cannot establish order-level completeness')
    review_quality['source_review_rows_orphan_to_all_orders'] = int(
        (~prepared.order_id.isin(orders.order_id)).sum())
    if review_quality['source_review_rows_orphan_to_all_orders']:
        raise ValueError('Review rows orphaned from all raw orders')
    labels, final_summary = label_asof(cohort, prepared, OBSERVATION_CUTOFF)
    unique = customers.set_index('customer_id').customer_unique_id
    customer_map = cohort.set_index('order_id').customer_id.map(unique)
    membership, folds = build_membership(cohort, prepared, customer_map)
    verify_sources(spec['sources'], root)
    def result_for(outputs, private_checks):
        return {'format_version': 1, 'status': 'passed_bounded_offline_dataset_contract',
            'decision': 'dataset_contract_frozen_no_training_stage4_pending_data',
            'specification': specification_source,
            'protocol': protocol(), 'source_snapshot_role': 'existing_export_event_proxy_not_historical_ingestion_proof',
            'sources': spec['sources'], 'order_quality': order_quality,
            'global_review_source_quality_not_historical_fit_availability': review_quality,
            'final_observation_labels': final_summary, 'nested_calendar_development_support': folds,
            'private_outputs': outputs,
            'candidate_feature_values_built': 0,
            'candidate_feature_contract': 'prior_21_conditional_definitions_unchanged_no_feature_cache',
            'verification': {'bound_sources_before_after': bound, 'raw_schema_headers_verified': 9,
                             'order_labels_unique_rows': len(labels),
                             'split_membership_rows': len(membership),
                             'role_blocks': len(folds) * 4, 'private_csv_exact_readback': private_checks,
                             'specification_file_bytes_bound_before_after': True,
                             'model_fits': 0, 'model_loads': 0, 'new_predictions': 0,
                             'performance_metrics': 0, 'model_selection': 0, 'dashboard': 0,
                             'original_retained_test_scored': False},
            'limitations': ['No real ingestion, revision history, time zone or source day-close completeness proof.',
                            'Unknown and nonresponse labels are not negative; labeled subsets may be selective.',
                            'H60 and C2018-07-01 are fixed research observation rules, not business-optimal or freshness claims.',
                            'Existing inspected months are development windows, not new unseen held-out tests.',
                            'Rolling folds share historical orders and customers; not independent replications.',
                            'Static unpositionable-answer quarantine is a source-quality assumption, not an as-of proof.']}
    def preflight_public(outputs, private_checks):
        verify_sources([specification_source], root)
        immutable_preflight(output_path, json_bytes(result_for(outputs, private_checks)))
    outputs, private_checks = write_private_bundle(
        labels, membership, spec, root, private_directory,
        specification_sha256=specification_source['sha256'], public_preflight=preflight_public)
    verify_sources(spec['sources'] + [specification_source], root)
    return result_for(outputs, private_checks)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--specification-only', action='store_true')
    parser.add_argument('--specification', default=SPEC)
    parser.add_argument('--output', default=REPORT)
    parser.add_argument('--private-directory', default=PRIVATE)
    args = parser.parse_args(argv)
    specification_path = safe_output(ROOT / args.specification, SPEC)
    report_path = safe_output(ROOT / args.output, REPORT)
    private_directory = safe_output(ROOT / args.private_directory, '', private=True)
    if specification_path == report_path:
        raise ValueError('Specification and report paths collide')
    if specification_path.is_relative_to(private_directory) or report_path.is_relative_to(private_directory):
        raise ValueError('Public report collides with private bundle')
    if args.specification_only:
        spec = make_specification()
        if specification_path in {(ROOT / item['path']).resolve() for item in spec['sources']}:
            raise ValueError('Specification path collides with a bound source')
        immutable_write(specification_path, json_bytes(spec))
        verify_sources(spec['sources'])
        print(json.dumps({'status': 'specification_frozen', 'bound_sources': len(spec['sources']),
                          'model_fits': 0}))
        return
    spec = read_json(specification_path)
    result = run_audit(spec, directory=private_directory,
                       specification_path=specification_path, output_path=report_path)
    verify_sources(spec['sources'] + [result['specification']])
    immutable_write(report_path, json_bytes(result))
    if read_json(report_path) != result:
        raise ValueError('Public audit report readback mismatch')
    verify_sources(spec['sources'] + [result['specification']])
    print(json.dumps({'status': result['status'], 'orders': result['verification']['order_labels_unique_rows'],
                      'role_blocks': result['verification']['role_blocks'],
                      'split_membership_rows': result['verification']['split_membership_rows'],
                      'model_fits': 0}))


if __name__ == '__main__':
    main()
