"""Synthetic guards for the second gap window, including the previous 34 probes."""
from copy import deepcopy
from pathlib import Path
import hashlib
import json
import tempfile
import unittest

from scripts import retailrocket_session_knn_checkpoint_v2 as cp
from scripts import retailrocket_session_knn_gap_v8 as gap
from scripts.retailrocket_session_knn_joint_cost_v5 import DIMENSIONS, POLICY
from tests import test_retailrocket_session_knn_sql_v4 as sql_fixture


CELLS = ('0000/n3/v2', '0000/n3/v3')


def digest(value):
    data = json.dumps(value, ensure_ascii=False, separators=(',', ':')).encode('utf-8')
    return hashlib.sha256(data).hexdigest()


class TargetSelectionTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.path = Path(tmp.name)/'structural.jsonl'
        # Include both edges of n3, v2, v3 and distractors on their far sides.
        shapes = ([(100, 100), (299, 400), (499, 499)]*3 +
                  [(100, 500), (350, 999), (499, 1999)]*3 + [(100, 500), (499, 1999)] +
                  [(99, 200), (500, 2000), (300, 2000)])
        self.rows = []
        for i, (n,v) in enumerate(shapes):
            key = [str(1000+i), 0, i]
            self.rows.append({'original_ordinal': i, 'key': key, 'key_sha256': digest(key),
                              'eligible_neighbors': n, 'vote_memberships_upper': v,
                              'posting_work': n, 'causal_candidates': 99,
                              'variable_scalar_slots': 1+6*n, 'history_size': 1,
                              'history_sha256': digest([str(2000+i)]), 'current_session_excluded': 0})
        self.prior = {'probes': [deepcopy(self.rows[i]) for i in (0, 13, 21)]}
        for p in self.prior['probes']:
            del p['original_ordinal']
        self.frozen = {'population': {'complete': True, 'selection_policy': POLICY,
                                      'total_queries': len(shapes), 'expected_queries': len(shapes),
                                      'p90_nearest_rank': dict.fromkeys(DIMENSIONS, 99999)},
                       'probes': [dict(deepcopy(self.rows[i]), cell='0000') for i in (21,22)]}
        self.previous_gap = {'probes': [dict(deepcopy(self.rows[20]), cell='0000/n2/v2')]}
        self.spec = {'selection': {'quota': 4, 'planned_unique_queries': 8,
                                   'prefix_with_terminator': 'k1-gap-v8-20261105\x00'},
                     'quotas': [{'cell': cell, 'population': n, 'eligible': n-1,
                                 'historical_exclusions': 1, 'planned_new_queries': 4}
                                for cell,n in zip(CELLS,(9,11))]}
        self.store_rows()

    def store_rows(self):
        raw = b''.join(cp.encoded(r) for r in self.rows)
        self.path.write_bytes(raw)
        self.frozen['population'].update(roster_sha256=hashlib.sha256(raw).hexdigest(), roster_bytes=len(raw))
        self.previous_gap['roster_sha256'] = self.frozen['population']['roster_sha256']

    def choose(self):
        return gap.select_gap_roster(self.path, self.prior, self.frozen, self.previous_gap, self.spec)

    def audit(self, selection):
        gap.audit_gap_order(self.path, selection, self.prior, self.frozen, self.previous_gap, self.spec)

    def test_salted_known_answer_and_original_order(self):
        chosen = self.choose()
        self.assertEqual([r['original_ordinal'] for r in chosen['probes']], [4,5,6,8,9,10,11,16])
        self.assertEqual([r['cell'] for r in chosen['probes']], [CELLS[0]]*4+[CELLS[1]]*4)
        self.audit(chosen)
        self.prior['probes'].reverse()
        self.spec['quotas'].reverse()
        self.assertEqual(chosen, self.choose())

    def test_full_sort_refuses_wrong_winner_and_changed_structure(self):
        chosen = self.choose()
        for field in ('winner', 'work'):
            with self.subTest(field=field):
                changed = deepcopy(chosen)
                if field == 'winner':
                    changed['probes'][0] = dict(self.rows[3], cell=CELLS[0])
                else:
                    changed['probes'][0]['vote_memberships_upper'] -= 1
                with self.assertRaises(ValueError):
                    self.audit(changed)

    def test_prior34_must_be_distinct_and_match_original_structure(self):
        for corruption in ('shared_with_v3', 'wrong_ordinal', 'history_changed', 'wrong_grid_cell'):
            with self.subTest(corruption=corruption):
                source = deepcopy(self.previous_gap['probes'])
                if corruption == 'shared_with_v3':
                    self.previous_gap['probes'][0] = dict(self.rows[0],cell=CELLS[0])
                elif corruption == 'wrong_ordinal':
                    self.previous_gap['probes'][0]['original_ordinal'] += 1
                elif corruption == 'history_changed':
                    self.previous_gap['probes'][0]['history_sha256'] = '0'*64
                else:
                    self.previous_gap['probes'][0]['cell'] = '0000/n1/v2'
                with self.assertRaises(ValueError):
                    self.choose()
                self.previous_gap['probes'] = source

    def test_target_already_represented_by_a_prior_sample_fails(self):
        for cohort in (self.frozen, self.previous_gap):
            with self.subTest(cohort='48' if cohort is self.frozen else '34'):
                cohort['probes'].append(dict(self.rows[1],cell='0000' if cohort is self.frozen else CELLS[0]))
                self.spec['quotas'][0].update(eligible=7,historical_exclusions=2)
                with self.assertRaises(ValueError):
                    self.choose()
                cohort['probes'].pop()

    def test_fixed_quota_shortfall_is_not_redistributed(self):
        self.prior['probes'].extend(deepcopy(self.rows[i]) for i in range(1,6))
        self.spec['quotas'][0].update(eligible=3,historical_exclusions=6)
        with self.assertRaises(ValueError):
            self.choose()

    def test_fixed_rule_rejects_substituted_cell_wrong_salt_and_quota(self):
        original = deepcopy(self.spec)
        for mutation in ('salt','duplicate','different_cell','quota','changed_capacity'):
            with self.subTest(mutation=mutation):
                self.spec = deepcopy(original)
                if mutation=='salt':
                    self.spec['selection']['prefix_with_terminator'] = 'k1-gap-v8-20261105'
                elif mutation=='duplicate':
                    self.spec['quotas'][1]=deepcopy(self.spec['quotas'][0])
                elif mutation=='different_cell':
                    self.spec['quotas'][1]['cell']='0000/n3/v4'
                elif mutation=='quota':
                    self.spec['selection']['quota']=3
                else:
                    self.spec['quotas'][0]['population']+=1
                with self.assertRaises(ValueError):
                    self.choose()

    def test_roster_integrity_includes_unselected_rows(self):
        raw = self.path.read_bytes()
        self.path.write_bytes(raw.replace(b'\n', b' \n'))
        with self.assertRaises(ValueError):
            self.choose()
        self.rows[22]['original_ordinal']+=1
        self.store_rows()
        with self.assertRaises(ValueError):
            self.choose()


class RepeatProofAndCoverageTests(unittest.TestCase):
    def make_frames(self, folder, repeat, lines, lengths):
        root = folder/f'repeat_{repeat}'/'verified_subset'
        (root/'chunks').mkdir(parents=True)
        (root/'payloads').mkdir()
        start = 0
        for i,n in enumerate(lengths):
            name = f'payloads/{i}.jsonl'
            (root/name).write_bytes(b''.join(lines[start:start+n]))
            (root/'chunks'/f'{i:08d}.json').write_bytes(cp.encoded({'payload':{'path':name}}))
            start += n

    def test_frame_comparison_checks_all_eight_actual_lines_across_chunks(self):
        with tempfile.TemporaryDirectory() as tmp:
            folder=Path(tmp)
            frames=[cp.encoded({'ordinal':i,'payload':{'fake':str(i)}}) for i in range(8)]
            self.make_frames(folder,0,frames,[5,3])
            self.make_frames(folder,1,frames,[3,5])
            gap.compare_frames(folder,8)
            with self.assertRaises(ValueError):
                gap.compare_frames(folder,7)
            tail=folder/'repeat_1/verified_subset/payloads/1.jsonl'
            original=tail.read_bytes()
            for changed in (original.replace(b'7',b'8'), original+frames[-1]):
                tail.write_bytes(changed)
                with self.assertRaises(ValueError):
                    gap.compare_frames(folder,8)

    def test_coverage_removes_only_two_fully_verified_cells(self):
        remaining={CELLS[0]:9, CELLS[1]:11, '0010/n3/v2':7}
        added={c:{'population':remaining[c],'measured':4} for c in CELLS}
        coverage, missing=gap.check_coverage(remaining,added,total_cells=5,historic_unique=7)
        self.assertEqual(coverage, {'v6_plus_new_cells_with_sample':4, 'v6_plus_new_unrepresented_population':7,
                                    'distinct_historically_verified_queries':15})
        self.assertEqual(missing,{'0010/n3/v2':7})
        for field in ('population','measured'):
            wrong=deepcopy(added)
            wrong[CELLS[1]][field]-=1
            with self.assertRaises(ValueError):
                gap.check_coverage(remaining,wrong)

    def test_all_eligible_memberships_are_read_even_when_some_items_are_future(self):
        # The smaller pool contains a future item in every selected session.
        # Here the 200 membership visits are exact, but only 100 votes are causal.
        oracle=sql_fixture.ExactRankingTests()
        sessions={(str(i),10):{'1','11'} for i in range(100)}
        sessions.update({(str(1000+i),10):{'2','12'} for i in range(499)})
        oracle.fixture(sessions,catalog={'1':0,'2':0,'11':200,'12':0})
        self.addCleanup(oracle.doCleanups)
        probes=[]; observations=[]
        for i in range(8):
            seed, n, cell=('1',100,CELLS[0]) if i<4 else ('2',499,CELLS[1])
            key=[str(9000+i),40,100]
            _,work=oracle.check([seed],current=(key[0],key[1]),at=key[2])
            probes.append({'original_ordinal':i,'key_sha256':digest(key),'cell':cell,
                           'eligible_neighbors':n,'vote_memberships_upper':2*n})
            observations.append({'original_ordinal':i,'key_sha256':digest(key),'sql_workload':work})
        measured={'queries':observations}
        result=gap.sample_workload(probes,measured)
        for cell,n,additions in ((CELLS[0],100,400),(CELLS[1],499,3992)):
            self.assertEqual(result[cell]['sql_selected_rows_inserted'],4*n)
            self.assertEqual(result[cell]['sql_vote_membership_rows_returned'],8*n)
            self.assertEqual(result[cell]['exact_vote_additions'],additions)
        # A truncated count is below the general structural bound, yet it must
        # be refused here because both pools fit entirely below k=500.
        observations[0]['sql_workload']['sql_vote_membership_rows_returned']-=1
        with self.assertRaises(ValueError):
            gap.sample_workload(probes,measured)


if __name__=='__main__':
    unittest.main()
