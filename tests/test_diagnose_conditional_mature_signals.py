"""Regression checks for the predeclared, descriptive hypothesis screen."""
import copy
import unittest

from scripts import diagnose_conditional_mature_signals as runner


def group_fixture(sign=1):
    candidate = runner.conditional.CANDIDATE_FEATURES[0]
    effect = {'common_n': 20, 'control_n': 40, 'strata_count': 4,
              'week_count': 3, 'risk_difference': sign * .01,
              'order_probability': .5 + sign * .05}
    comparison = {'effects': {'supported': effect}}
    group = {'comparisons': {scheme: {candidate: {'known_on_time': copy.deepcopy(comparison)}}
                             for scheme in runner.conditional.PROMISE_SCHEMES},
             'common4_by_seed': {str(seed): {scheme: {candidate: copy.deepcopy(comparison)}
                                  for scheme in runner.conditional.PROMISE_SCHEMES}
                                 for seed in runner.conditional.SEEDS}}
    return candidate, group


class ConditionalScreenTests(unittest.TestCase):
    def test_pass_requires_both_mean_and_order_in_both_schemes_and_all_seeds(self):
        candidate, group = group_fixture()
        result = runner.phase_screen(group, candidate)
        self.assertTrue(result['work_screen_passed'])
        self.assertEqual(result['direction'], 1)
        self.assertEqual(set(result['seed_directions']), {'11', '29', '42', '73', '101'})

    def test_exact_day_sparse_cannot_be_replaced_by_bin_result(self):
        candidate, group = group_fixture()
        group['comparisons']['promise_days'][candidate]['known_on_time']['effects']['supported']['common_n'] = 19
        result = runner.phase_screen(group, candidate)
        self.assertTrue(result['bin_exact_direction_aligned'])
        self.assertFalse(result['data_sufficient_both_schemes'])
        self.assertFalse(result['work_screen_passed'])

    def test_two_weeks_are_insufficient_even_with_many_queries(self):
        candidate, group = group_fixture()
        row = group['comparisons']['promise_bin'][candidate]['known_on_time']['effects']['supported']
        row.update(common_n=200, week_count=2)
        self.assertFalse(runner.phase_screen(group, candidate)['work_screen_passed'])

    def test_one_seed_reversal_fails(self):
        candidate, group = group_fixture()
        group['common4_by_seed']['73']['promise_days'][candidate]['effects']['supported']['risk_difference'] = -.01
        result = runner.phase_screen(group, candidate)
        self.assertTrue(result['bin_exact_direction_aligned'])
        self.assertFalse(result['all_five_seed_directions_aligned'])
        self.assertFalse(result['work_screen_passed'])

    def test_mean_order_disagreement_fails(self):
        candidate, group = group_fixture()
        group['comparisons']['promise_days'][candidate]['known_on_time']['effects']['supported']['order_probability'] = .49
        self.assertFalse(runner.phase_screen(group, candidate)['work_screen_passed'])

    def test_ties_and_undefined_order_do_not_supply_direction(self):
        for order in (.5, .5 + 1e-13, None):
            with self.subTest(order=order):
                candidate, group = group_fixture()
                group['comparisons']['promise_bin'][candidate]['known_on_time']['effects']['supported']['order_probability'] = order
                self.assertFalse(runner.phase_screen(group, candidate)['work_screen_passed'])

    def test_inverse_hypothesis_is_preserved_without_relabeling(self):
        candidate, group = group_fixture(-1)
        result = runner.phase_screen(group, candidate)
        self.assertTrue(result['work_screen_passed'])
        self.assertEqual(result['direction'], -1)

    def test_repeated_validation_months_cannot_count_as_development_replication(self):
        metadata = {f'p{i}': {'ledger_role': 'evaluation', 'month': '2018-02'} for i in range(3)}
        with self.assertRaisesRegex(ValueError, 'three distinct'):
            runner.hypothesis_screen({}, metadata)


if __name__ == '__main__':
    unittest.main()
