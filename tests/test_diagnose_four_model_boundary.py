"""Source-regression and identity-set checks for frozen boundary diagnosis."""
from copy import deepcopy
import json
import unittest
from uuid import uuid4

import numpy as np

from scripts import diagnose_four_model_boundary as diagnosis
from tests.test_diagnose_age_colsample import four_fixture


class FourModelBoundaryRunnerTests(unittest.TestCase):
    def test_all_original_group_metrics_and_daily_allocations_reproduce(self):
        frame, scores, known = four_fixture()
        public, _ = diagnosis.boundary.diagnose_phase(frame, scores, known)
        frozen, _ = diagnosis.prior.diagnose_phase(frame, scores, known)
        self.assertGreater(diagnosis.verify_previous(public, frozen), 100)
        changed = deepcopy(public)
        changed['groups'][0]['models']['base08']['FN'] += 1
        with self.assertRaises(ValueError):
            diagnosis.verify_previous(changed, frozen)
        changed = deepcopy(public)
        changed['groups'][0]['contrasts']['age_10_minus_08']['allocations']['cross_group_incoming_slots'] += 1
        with self.assertRaises(ValueError):
            diagnosis.verify_previous(changed, frozen)

    def test_same_miss_counts_do_not_mean_same_missed_identities(self):
        universe = {'a', 'b', 'c'}
        sets = {seed: ({'a'} if seed != 101 else {'b'}) for seed in diagnosis.prior.SEEDS}
        result = diagnosis.set_statistics(sets, universe)
        self.assertEqual(result['all_seed_intersection'], 0)
        self.assertEqual(result['union'], 2)
        self.assertEqual(result['multiplicity'], {'0': 1, '1': 1, '2': 0, '3': 0, '4': 1, '5': 0})
        for invalid in ({11: {'a'}}, {seed: {'outside'} for seed in diagnosis.prior.SEEDS}):
            with self.assertRaises(ValueError):
                diagnosis.set_statistics(invalid, universe)

    def test_all20_uses_identity_intersection_and_keeps_empty_denominators(self):
        private = {}
        for seed in diagnosis.prior.SEEDS:
            missed = {'a'} if seed != 101 else {'b'}
            groups = {'overall:ALL': {'a', 'b', 'c'}, 'route:SP->SC': set()}
            sets = {'overall:ALL': missed, 'route:SP->SC': set()}
            private[seed] = {'delayed': groups, 'common_missed': sets,
                'missed': {version: deepcopy(sets) for version in diagnosis.prior.VERSIONS},
                'row_ids': np.array(['a', 'b', 'c']), 'capacity': np.ones(3, int),
                'positions': {version: np.array([2, 3, 1]) for version in diagnosis.prior.VERSIONS}}
        result = diagnosis.summarize_persistent(private)['groups']
        self.assertEqual(result[0]['all20_missed'], 0)
        self.assertEqual(result[0]['miss_vote_counts']['16'], 1)
        self.assertEqual(result[0]['miss_vote_counts']['4'], 1)
        self.assertEqual(result[0]['miss_vote_counts']['0'], 1)
        self.assertIsNone(result[1]['all20_missed_rate'])
        self.assertNotIn('row_ids', json.dumps(result))
        changed = deepcopy(private)
        changed[29]['delayed']['overall:ALL'] = {'a'}
        with self.assertRaises(ValueError):
            diagnosis.summarize_persistent(changed)

    def test_specification_and_report_cannot_be_silently_replaced(self):
        runtime = diagnosis.ROOT / '.runtime'
        runtime.mkdir(exist_ok=True)
        path = runtime / f'boundary-test-{uuid4().hex}.json'
        try:
            diagnosis.fixed_json(path, {'measured': 3})
            diagnosis.fixed_json(path, {'measured': 3})
            with self.assertRaises(ValueError):
                diagnosis.fixed_json(path, {'measured': 4})
            self.assertEqual(json.loads(path.read_text(encoding='utf-8')), {'measured': 3})
        finally:
            path.unlink(missing_ok=True)

    def test_focus_loss_days_uses_complete_partition_and_preserves_day_counts(self):
        frame, scores, known = four_fixture()
        public, _ = diagnosis.boundary.diagnose_phase(frame, scores, known)
        focus = diagnosis.focus_loss_days(public)
        for contrast, groups in focus.items():
            for name, row in groups.items():
                self.assertEqual(row['newly_lost_day_count'], len(row['newly_lost_days']))
                self.assertTrue(set(row['net_outflow_and_new_loss_days']) <= set(row['newly_lost_days']))
                self.assertEqual(sum(item['added_alerts'] for item in row['whole_selected_days_partition_changes']),
                    sum(item['dropped_alerts'] for item in row['whole_selected_days_partition_changes']))
                expected = diagnosis.boundary.decode_group(public, 'marginal' if name == 'A' else 'route', name)
                self.assertEqual(sum(item['lost_delays'] for item in row['focus_daily_changes']),
                    expected['contrasts'][contrast]['exchanges']['lost_delays'])


if __name__ == '__main__':
    unittest.main()
