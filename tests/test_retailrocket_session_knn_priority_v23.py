"""Hand-calculated overlapping timers and historical decision integrity."""
from copy import deepcopy
import unittest

from scripts import retailrocket_session_knn_priority_v23 as priority
from scripts.run_retailrocket_session_knn_vote_v7 import paired_decision, schedule
from tests.test_retailrocket_session_knn_vote_v17 import measurements


def fixture():
    probes = [dict(original_ordinal=i, key_sha256=str(i)) for i in range(4)]
    measured, obs = measurements(probes, 1., [64]*4)
    obs['budget'] = [dict(context='query_append', subset_ordinal=0, stage=None, completed=True, seconds=.03),
                     dict(context='chunk_commit', subset_ordinal=None, stage=None, completed=True, seconds=.05)]
    return probes, measured, obs, dict(mode='baseline', seconds=7.45)


class AccountingTests(unittest.TestCase):
    def test_tail_commit_counted_once_and_budget_remains_nested(self):
        probes, measured, obs, entry = fixture()
        result = priority.summarize_run(measured, obs, entry, probes)
        self.assertEqual(result['costs']['primary_seconds'], 6.25)
        self.assertEqual(result['tail_commit_seconds'], .25)
        self.assertEqual(result['entry_exclusive_seconds']['tail_without_commit_seconds'], 0.)
        self.assertAlmostEqual(result['entry_exclusive_seconds']['entry_other_seconds'], 1.)
        self.assertAlmostEqual(sum(result['entry_exclusive_seconds'].values()), 7.45)
        self.assertAlmostEqual(sum(result['append_parts_seconds'].values()), 2.)
        self.assertAlmostEqual(result['all_observed_budget_seconds'], .08)

    def test_query_commit_and_tail_commit_keep_distinct_boundaries(self):
        probes, measured, obs, entry = fixture()
        measured['queries'][0].update(chunk_commit_seconds=.1, append_without_commit_seconds=.4)
        obs['append'][0]['parts_seconds'].update(nested_flush=.1, frame_encode=.15)
        result = priority.summarize_run(measured, obs, entry, probes)
        self.assertAlmostEqual(result['costs']['primary_seconds'], 6.15)
        self.assertAlmostEqual(result['tail_commit_seconds'], .15)
        self.assertAlmostEqual(result['entry_exclusive_seconds']['tail_without_commit_seconds'], .1)
        self.assertAlmostEqual(sum(result['entry_exclusive_seconds'].values()), 7.45)

    def test_invalid_timers_unaccounted_budget_order_or_failed_events_are_rejected(self):
        for change in ('tail', 'entry', 'budget', 'ordinal', 'failed', 'nan'):
            probes, m, o, e = fixture()
            if change == 'tail': m['tail_flush_and_eof_seal_seconds'] = .1
            elif change == 'entry': e['seconds'] = 1.
            elif change == 'budget': o['budget'][0]['seconds'] = 1.
            elif change == 'ordinal': m['queries'][1]['original_ordinal'] = 99
            elif change == 'failed': o['append'][0]['completed'] = False
            else: m['queries'][0]['verification_seconds'] = float('nan')
            with self.subTest(change=change), self.assertRaises(ValueError):
                priority.summarize_run(m, o, e, probes)

    def test_window_conserves_and_warmups_cannot_change_rejected_decision(self):
        probes, measured, obs, e = fixture()
        runs = {}
        for label, mode in schedule('compare48', 'candidate'):
            m = deepcopy(measured)
            if mode == 'candidate':
                for q in m['queries']: q['verification_seconds'] = 1.1
            # A fast B warmup must not rescue six failing B pairs.
            if label == 'warm_B':
                for q in m['queries']:
                    q['verification_seconds'] = .9
            for q in m['queries']:
                q['seconds'] = q['verification_seconds']+.5
            entry = dict(mode=mode, seconds=8.)
            runs[label] = priority.summarize_run(m, obs, entry, probes)
        report = dict(candidate='candidate', runs={k:v['costs'] for k,v in runs.items()},
            decision=paired_decision({k:v['costs'] for k,v in runs.items()}),
            hash_checks={'initial':{'seconds':10.}, 'final':{'seconds':10.}}, supervisor={'seconds':140.})
        result = priority.summarize_window(report, runs)
        self.assertFalse(result['decision']['supports_candidate'])
        self.assertEqual(result['decision']['faster_pairs'], 0)
        self.assertEqual(result['window_exclusive_seconds']['all_14_entry_seconds'], 112.)
        self.assertEqual(result['window_exclusive_seconds']['window_other_seconds'], 8.)
        self.assertIsNone(result['post_exit_wall_seconds'])
        for change in ('missing', 'forged', 'wrong_mode', 'window'):
            r, s = deepcopy(report), deepcopy(runs)
            if change == 'missing': del s['warm_B']
            elif change == 'forged': r['decision']['supports_candidate'] = True
            elif change == 'wrong_mode': s['pair_2_A']['costs']['mode'] = 'candidate'
            else: r['supervisor']['seconds'] = 120.
            with self.subTest(change=change), self.assertRaises(ValueError):
                priority.summarize_window(r, s)


if __name__ == '__main__':
    unittest.main()
