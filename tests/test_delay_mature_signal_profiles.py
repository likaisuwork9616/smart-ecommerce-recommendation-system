"""Synthetic checks for fixed mature-signal profiles; no real data or models."""
from copy import deepcopy
import json
import unittest

import numpy as np
import pandas as pd

from scripts import delay_mature_signal_profiles as profiles


def fixture(rows=8):
    frame = pd.DataFrame({
        "state_route": ["SP->RJ" if i & 4 else "SP->SC" for i in range(rows)],
        "estimated_delivery_days": [25. if i & 2 else 15. for i in range(rows)],
        profiles.intersections.FEATURE: [48. if i & 1 else 24. for i in range(rows)],
        "delayed": [i % 2 for i in range(rows)],
    })
    for name in profiles.SIGNAL_FEATURES:
        frame[name] = np.arange(rows, dtype=float)
    for count, key in profiles.SUPPORT_MAPPING.values():
        frame[count], frame[key] = 5., 1.
    known = np.ones(rows, dtype=bool)
    common = frame.delayed.to_numpy() == 1
    seeds = {seed: common.copy() for seed in profiles.SEEDS}
    return frame, known, common, seeds


class MatureSignalProfileTests(unittest.TestCase):
    def test_finite_linear_quantiles_and_empty_are_strict_json(self):
        result = profiles.distribution(np.array([1., 3., 5., np.nan, np.inf, -np.inf]))
        self.assertEqual((result["rows"], result["finite"], result["missing"]), (6, 3, 3))
        self.assertEqual((result["mean"], result["p10"], result["p50"], result["p90"]), (3., 1.4, 3., 4.6))
        empty = profiles.distribution(np.array([np.nan]))
        self.assertTrue(all(empty[name] is None for name in ("mean", "p10", "p50", "p90", "min", "max")))
        json.dumps([result, empty], allow_nan=False)

    def test_all_fixed_groups_and_eight_cells_partition_without_marginal_sum(self):
        frame, known, common, seeds = fixture()
        result = profiles.profile_phase(frame, known, common, seeds)
        groups = result["groups"]
        self.assertEqual(set(groups), {"ALL", "R", "A", "RA", "R_not_A", "A_not_R", "NOT_A", "SP->SC",
                                       *(f"cell:{cell}" for cell in profiles.intersections.CELLS)})
        self.assertTrue(all(groups[f"cell:{cell}"]["denominators"]["full_batch_rows"] == 1 for cell in profiles.intersections.CELLS))
        self.assertEqual(groups["R"]["denominators"]["full_batch_rows"], 4)
        self.assertEqual(groups["RA"]["denominators"]["full_batch_rows"], 2)
        self.assertEqual(groups["A_not_R"]["denominators"]["full_batch_rows"], 2)
        self.assertEqual(groups["ALL"]["cohorts"]["other_delayed"]["rows"], 0)
        json.dumps(result, allow_nan=False)

    def test_unknown_query_label_not_read_and_feature_profiles_use_only_known(self):
        frame, known, common, seeds = fixture()
        frame["delayed"] = frame.delayed.astype(object)
        frame.loc[1, "delayed"] = "future target forbidden"
        known[1], common[1] = False, False
        for mask in seeds.values():
            mask[1] = False
        result = profiles.profile_phase(frame, known, common, seeds)
        row = result["groups"]["ALL"]
        self.assertEqual((row["denominators"]["known_rows"], row["denominators"]["unknown_rows"]), (7, 1))
        self.assertEqual(row["cohorts"]["all_known"]["distributions"][profiles.CANDIDATE_FEATURES[0]]["mean"], 27 / 7)
        changed = frame.copy()
        changed.at[1, "delayed"] = {"unread": "value"}
        self.assertEqual(result, profiles.profile_phase(changed, known, common, seeds))

    def test_all_five_seed_identity_profiles_are_preserved(self):
        frame, known, common, seeds = fixture()
        seeds[11][1], seeds[29][3] = False, False
        common = np.logical_and.reduce(list(seeds.values()))
        result = profiles.profile_phase(frame, known, common, seeds)
        focus = result["groups"]["ALL"]
        self.assertEqual(focus["denominators"]["common20_rows"], 2)
        self.assertEqual(set(focus["common4_by_seed"]), set(map(str, profiles.SEEDS)))
        feature = profiles.CANDIDATE_FEATURES[0]
        self.assertEqual(focus["common4_by_seed"]["11"]["distributions"][feature]["mean"], 5.)
        self.assertAlmostEqual(focus["common4_by_seed"]["29"]["distributions"][feature]["mean"], 13 / 3)
        self.assertNotIn("common4_by_seed", result["groups"]["cell:000"])

    def test_support_bins_include_unknown_zero_and_every_prespecified_boundary(self):
        frame, known, common, seeds = fixture(10)
        counts = np.array([0., 0., 1., 4., 5., 19., 20., 99., 100., 200.])
        frame["seller_completed_90d"] = counts
        frame["audit_seller_key_known"] = [0.] + [1.] * 9
        result = profiles.profile_phase(frame, known, common, seeds)
        seller = result["groups"]["ALL"]["cohorts"]["all_known"]["support"]["seller90"]
        self.assertEqual(seller["bins"], dict(zip(profiles.SUPPORT_BINS, [1, 1, 2, 2, 2, 2], strict=True)))
        self.assertEqual(seller["known_key_count_distribution"]["rows"], 9)

    def test_support_mapping_can_use_explicit_alternate_column_contract(self):
        frame, known, common, seeds = fixture()
        frame["count_extra"], frame["known_extra"] = 0., 1.
        result = profiles.profile_phase(frame, known, common, seeds,
                                       support_mapping={"custom": ("count_extra", "known_extra")})
        support = result["groups"]["ALL"]["cohorts"]["all_known"]["support"]
        self.assertEqual(list(support), ["custom"])
        self.assertEqual(support["custom"]["bins"]["0"], len(frame))

    def test_empty_focus_group_has_null_rates_and_distributions(self):
        frame, known, common, seeds = fixture()
        frame["state_route"] = "SP->SP"
        result = profiles.profile_phase(frame, known, common, seeds)
        empty = result["groups"]["SP->SC"]
        self.assertIsNone(empty["denominators"]["known_delay_rate"])
        self.assertIsNone(empty["denominators"]["common20_fraction_of_delays"])
        self.assertIsNone(empty["cohorts"]["common20"]["distributions"][profiles.CANDIDATE_FEATURES[0]]["p50"])
        self.assertEqual(empty["common4_by_seed"]["101"]["rows"], 0)

    def test_empty_phase_has_complete_schema_and_null_statistics(self):
        frame, known, common, seeds = fixture(0)
        result = profiles.profile_phase(frame, known, common, seeds)
        self.assertEqual(result["rows"], 0)
        self.assertEqual(len(result["groups"]), 16)
        self.assertIsNone(result["groups"]["ALL"]["denominators"]["known_delay_rate"])
        json.dumps(result, allow_nan=False)

    def test_reject_truthy_masks_missing_masks_and_series_identity_mismatch(self):
        frame, known, common, seeds = fixture()
        for invalid in (known.astype(int), known[:-1], np.array([True] * 7 + [None], dtype=object)):
            with self.subTest(invalid=repr(invalid)), self.assertRaisesRegex(ValueError, "boolean"):
                profiles.profile_phase(frame, invalid, common, seeds)
        wrong_index = pd.Series(known, index=np.arange(8) + 1)
        with self.assertRaisesRegex(ValueError, "index"):
            profiles.profile_phase(frame, wrong_index, common, seeds)

    def test_reject_seed_identity_mismatch_even_when_total_count_is_equal(self):
        frame, known, common, seeds = fixture()
        changed = common.copy()
        changed[0], changed[1] = True, False
        with self.assertRaisesRegex(ValueError, "identity"):
            profiles.profile_phase(frame, known, changed, seeds)
        wrong_keys = deepcopy(seeds)
        wrong_keys[999] = wrong_keys.pop(11)
        with self.assertRaisesRegex(ValueError, "seed"):
            profiles.profile_phase(frame, known, common, wrong_keys)
        seeds[11][0] = True
        with self.assertRaisesRegex(ValueError, "known delayed"):
            profiles.profile_phase(frame, known, common, seeds)

    def test_reject_invalid_known_labels_and_pooled_unknown_history(self):
        frame, known, common, seeds = fixture()
        invalid = frame.copy()
        invalid.loc[0, "delayed"] = 2
        with self.assertRaisesRegex(ValueError, "binary labels"):
            profiles.profile_phase(invalid, known, common, seeds)
        frame.loc[0, "audit_route_key_known"] = 0
        with self.assertRaisesRegex(ValueError, "pooled"):
            profiles.profile_phase(frame, known, common, seeds)
        frame.loc[0, "audit_route_key_known"] = np.nan
        with self.assertRaisesRegex(ValueError, "key-known"):
            profiles.profile_phase(frame, known, common, seeds)

    def test_correlation_pairs_duplicates_ties_constants_and_missingness(self):
        first, second, third = profiles.CANDIDATE_FEATURES
        frame = pd.DataFrame({first: [1., 2., 2., 4., np.nan], second: [np.nan] * 5,
                              third: [3., 3., 3., 3., 3.],
                              "same": [1., 2., 2., 4., np.inf],
                              "reverse": [4., 2., 2., 1., np.nan],
                              "partial": [1., np.nan, 2., 4., 8.],
                              "constant": [1.] * 5, "empty": [np.nan] * 5})
        result = profiles.compare_correlations(frame, ["same", "reverse", "partial", "constant", "empty"])
        first_row = result["by_candidate"][first]
        self.assertEqual(first_row["exact_duplicates"], [{"feature": "same", "paired_count": 4}])
        self.assertEqual(len(first_row["top_abs_spearman"]), 3)
        self.assertEqual(first_row["top_abs_spearman"][0]["feature"], "same")
        self.assertAlmostEqual(first_row["top_abs_spearman"][1]["spearman"], -1.)
        self.assertEqual(first_row["top_abs_spearman"][2]["paired_count"], 3)
        self.assertEqual(result["by_candidate"][second]["exact_duplicates"], [])
        self.assertEqual(result["by_candidate"][second]["top_abs_spearman"], [])
        self.assertEqual(result["by_candidate"][third]["top_abs_spearman"], [])
        json.dumps(result, allow_nan=False)

    def test_profile_and_correlation_preserve_input_values_and_order(self):
        frame, known, common, seeds = fixture()
        frame.index = [9, 3, 7, 1, 1, 22, 4, 2]
        before = frame.copy(deep=True)
        profiles.profile_phase(frame, known, common, seeds)
        profiles.compare_correlations(frame, list(profiles.RECOMPUTED_FEATURES))
        pd.testing.assert_frame_equal(before, frame, check_exact=True)


if __name__ == "__main__":
    unittest.main()
