"""Recompute saved costs with explicit, non-overlapping accounting boundaries."""
import math
from statistics import median

from scripts.retailrocket_session_knn_detailed_cost_v6 import DetailedTimedStore
from scripts.run_retailrocket_session_knn_vote_v7 import _costs, paired_decision, schedule
from scripts.run_retailrocket_session_knn_vote_v17 import _check_timers


def close(left, right):
    if not math.isclose(left, right, rel_tol=1e-9, abs_tol=1e-9):
        raise ValueError('Saved cost does not reproduce raw observations')


def remainder(total, parts):
    result = total-math.fsum(parts)
    if not math.isfinite(result) or result < 0:
        raise ValueError('Nested costs exceed their enclosing timer')
    return result


def summarize_run(measured, observations, entry, probes):
    _check_timers(measured)
    store = object.__new__(DetailedTimedStore)
    store.commit_events = measured['chunk_commits']
    store.append_events, store.budget_events = observations['append'], observations['budget']
    detail = store.detailed_cost_summary(measured)
    cost = dict(_costs(measured, probes), entry_seconds=entry['seconds'], mode=entry['mode'])
    if not math.isfinite(entry['seconds']) or entry['seconds'] <= 0:
        raise ValueError('Invalid full-entry timer')
    rows = measured['queries']
    query_commit = math.fsum(row['chunk_commit_seconds'] for row in rows)
    tail_commit = remainder(cost['all_commit_seconds'], [query_commit])
    tail_other = remainder(cost['tail_seconds'], [tail_commit])
    direct = detail['budget']['query_append_budget_seconds']
    append_other = remainder(cost['append_excluding_commit_seconds'], [direct])
    primary_parts = {name: cost[name] for name in (
        'verification_seconds', 'append_excluding_commit_seconds', 'all_commit_seconds')}
    close(math.fsum(primary_parts.values()), cost['primary_seconds'])
    exclusive = {'setup_seconds': cost['setup_seconds'], 'primary_seconds': cost['primary_seconds'],
                 'tail_without_commit_seconds': tail_other}
    exclusive['entry_other_seconds'] = remainder(entry['seconds'], list(exclusive.values()))
    close(math.fsum(exclusive.values()), entry['seconds'])
    rank = {key: math.fsum(q['rank_stages_seconds'][key] for q in rows)
            for key in rows[0]['rank_stages_seconds']}
    return {'costs': cost, 'entry_exclusive_seconds': exclusive,
            'entry_exclusive_percent': {key: value/entry['seconds']*100 for key, value in exclusive.items()},
            'primary_parts_seconds': primary_parts,
            'append_parts_seconds': {'direct_budget_seconds': direct,
                                     'append_without_commit_or_budget_seconds': append_other},
            'all_budget_by_context': detail['budget']['by_context'],
            'all_observed_budget_seconds': detail['budget']['budget_seconds'],
            'query_nested_commit_seconds': query_commit, 'tail_commit_seconds': tail_commit,
            'rank_stages_seconds': rank,
            'verification_outside_rank_seconds': remainder(cost['verification_seconds'], [cost['rank_seconds']]),
            'rank_unpartitioned_seconds': remainder(cost['rank_seconds'], list(rank.values()))}


def summarize_window(report, runs):
    if set(runs) != {name for name, _ in schedule('compare48', report['candidate'])}:
        raise ValueError('All fourteen fixed runs, including warmups, must be retained')
    for label, mode in schedule('compare48', report['candidate']):
        if runs[label]['costs']['mode'] != mode:
            raise ValueError('Changed pair order or implementation identity')
        for key, value in report['runs'][label].items():
            if key in runs[label]['costs']:
                if isinstance(value, str):
                    if runs[label]['costs'][key] != value:
                        raise ValueError('Changed run label')
                else:
                    close(runs[label]['costs'][key], value)
    decision = paired_decision({key: value['costs'] for key, value in runs.items()})
    if decision != report['decision']:
        raise ValueError('Published candidate decision differs from saved raw runs')
    parts = {'initial_source_hash_seconds': report['hash_checks']['initial']['seconds'],
             'final_source_hash_seconds': report['hash_checks']['final']['seconds'],
             'all_14_entry_seconds': math.fsum(row['costs']['entry_seconds'] for row in runs.values())}
    for value in parts.values():
        if not math.isfinite(value) or value < 0:
            raise ValueError('Invalid measured source hash or entry timer')
    total = report['supervisor']['seconds']
    parts['window_other_seconds'] = remainder(total, list(parts.values()))
    modes = {}
    for mode in ('baseline', report['candidate']):
        selected = [row for label, row in runs.items() if label.startswith('pair_') and row['costs']['mode'] == mode]
        if len(selected) != 6:
            raise ValueError('Exactly six retained paired runs per mode are required')
        modes[mode] = {group: {key: median(row[group][key] for row in selected)
                              for key in selected[0][group]}
                       for group in ('entry_exclusive_seconds', 'entry_exclusive_percent',
                                     'primary_parts_seconds', 'append_parts_seconds', 'rank_stages_seconds')}
        modes[mode]['all_budget_seconds_median'] = median(row['all_observed_budget_seconds'] for row in selected)
    return {'decision': decision, 'window_seconds': total, 'window_exclusive_seconds': parts,
            'window_exclusive_percent': {key: value/total*100 for key, value in parts.items()},
            'paired_mode_medians': modes,
            'post_exit_wall_seconds': None,
            'interpretation': 'Every raw entry conserves setup + primary + tail excluding final commit + entry other. '
                'Primary includes all commits once and direct append budget publication. Rank and budget subparts are nested. '
                'Group medians need not conserve each other. Window includes warmups; post-exit wall is not recorded.'}
