"""Decision gates and paired timing definitions for the V7 supervised runner."""
import unittest

from scripts.run_retailrocket_session_knn_vote_v7 import (
    _costs, _profile_rollup, paired_decision, schedule)


def pairs(savings, whole_b=1.):
    runs = {}
    for i, saving in enumerate(savings,1):
        runs[f'pair_{i}_A'] = {'primary_seconds':100., 'entry_seconds':2.}
        runs[f'pair_{i}_B'] = {'primary_seconds':100.-saving, 'entry_seconds':whole_b}
    return paired_decision(runs)


class VoteComparisonTests(unittest.TestCase):
    def test_warmups_are_excluded_and_order_is_balanced(self):
        order = schedule('compare48','rank_counts')
        self.assertEqual([mode for _,mode in order[:2]], ['baseline','rank_counts'])
        self.assertEqual([label for label,_ in order[2:]],
                         ['pair_1_A','pair_1_B','pair_2_B','pair_2_A','pair_3_A','pair_3_B',
                          'pair_4_B','pair_4_A','pair_5_A','pair_5_B','pair_6_B','pair_6_A'])

    def test_five_wins_both_orders_and_five_percent_pass(self):
        self.assertTrue(pairs([5,5,5,5,5,-2])['supports_candidate'])
        self.assertFalse(pairs([20,-1,10,-1,30,25])['supports_candidate'])
        self.assertFalse(pairs([4,4,4,4,12,12])['supports_candidate'])

    def test_full_entry_regression_blocks_followup(self):
        decision=pairs([8]*6,whole_b=2.5)
        self.assertTrue(decision['primary_gate_passed'])
        self.assertTrue(decision['entry_regressed'])
        self.assertFalse(decision['supports_candidate'])

    def test_primary_excludes_nested_commit_but_keeps_final_flush_and_budget(self):
        q={'subset_ordinal':0,'original_ordinal':9,'key_sha256':'synthetic','verification_seconds':1.,
           'rank_seconds':.8,'rank_stages_seconds':{'sql_selected_votes_and_accumulation':.4},
           'append_without_commit_seconds':.5,'checkpoint_append_seconds':1.,'chunk_commit_seconds':.5}
        m={'queries':[q],'committed_prefix_rows':0,'chunk_commits':[{'seconds':.5},{'seconds':.3}],
           'setup_seconds':4.,'tail_flush_and_eof_seal_seconds':2.}
        self.assertAlmostEqual(_costs(m,[q])['primary_seconds'],2.3)
        with self.assertRaisesRegex(ValueError,'roster'):
            _costs(m,[dict(q,original_ordinal=10)])

    def test_profiler_must_conserve_outer_and_match_actual_operations(self):
        row={'rank_stages_seconds':{'sql_selected_votes_and_accumulation':1.},'sql_workload':{
             'sql_selected_rows_inserted':2,'sql_vote_membership_rows_returned':10,'exact_vote_additions':9}}
        event={'outer_seconds':1.,'selected_rows':2,'membership_rows':10,'additions':9,
               'parts_seconds':{'accumulate':.75,'other':.25}}
        self.assertEqual(_profile_rollup([event],{'queries':[row]}),event['parts_seconds'])
        with self.assertRaises(ValueError):
            _profile_rollup([dict(event,membership_rows=11)],{'queries':[row]})
        with self.assertRaises(ValueError):
            _profile_rollup([dict(event,outer_seconds=1.1)],{'queries':[row]})
