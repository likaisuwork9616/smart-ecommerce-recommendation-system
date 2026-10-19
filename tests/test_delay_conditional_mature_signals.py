"""Synthetic invariants for fixed conditional mature-history diagnostics."""
from copy import deepcopy
import json
import unittest

import numpy as np
import pandas as pd

from scripts import delay_conditional_mature_signals as conditional


CDF, JOINT, RECENT = conditional.CANDIDATE_FEATURES


def fixture(records):
    rows, known, missed = [], [], []
    for supplied in records:
        record = dict(supplied)
        known.append(record.pop("known", True))
        missed.append(record.pop("miss", False))
        row = {"order_id": "PRIVATE_IDENTIFIER_NEVER_EXPORTED", "state_route": "SP->RJ",
               "estimated_delivery_days": 25., "prediction_time": "2018-02-05 13:00:00",
               conditional.profiles.intersections.FEATURE: 48., "delayed": 0,
               CDF: .1, JOINT: .1, RECENT: .1}
        for count, key in conditional.SUPPORT_MAPPING.values():
            row[count], row[key] = 20., 1.
        row.update(record)
        rows.append(row)
    if not rows:
        frame, _, _, _ = fixture([{}])
        frame = frame.iloc[:0].copy()
    else:
        frame = pd.DataFrame(rows)
    known, missed = np.asarray(known, dtype=bool), np.asarray(missed, dtype=bool)
    return frame, known, missed, {seed: missed.copy() for seed in conditional.SEEDS}


def block(misses, controls, **fields):
    rows = []
    for values, missed in ((misses, True), (controls, False)):
        for value in values:
            rows.append({"delayed": int(missed), "miss": missed, CDF: value, JOINT: value, RECENT: value, **fields})
    return rows


def comparison(result, candidate=JOINT, scheme="promise_bin", group="ALL", control="known_on_time"):
    return result["groups"][group]["comparisons"][scheme][candidate][control]


def cells(result, candidate=JOINT, scheme="promise_bin", group="ALL"):
    table = result["groups"][group]["comparisons"][scheme][candidate]["strata"]
    return [dict(zip(table["columns"], values, strict=True)) for values in table["rows"]]


class ConditionalMatureSignalsTests(unittest.TestCase):
    def test_simpson_reversal_is_removed_by_common_miss_standardization(self):
        records = block([.2] * 9, [.1] * 5, prediction_time="2018-02-05")
        records += block([.9] * 3, [.8] * 45, prediction_time="2018-02-12")
        result = conditional.compare_phase(*fixture(records))
        row = comparison(result)
        self.assertLess(row["unadjusted"]["native_difference"], 0)
        effect = row["effects"]["supported"]
        self.assertAlmostEqual(effect["native_difference"], .1)
        self.assertAlmostEqual(effect["standardized_control_mean"], .275)
        self.assertEqual((effect["strata_count"], effect["week_count"], effect["common_n"]), (2, 2, 12))

    def test_common_weights_differ_from_equal_strata_and_pair_weights(self):
        records = block([.8] * 9, [.5] * 5, prediction_time="2018-02-05")
        records += block([.3] * 3, [.5] * 50, prediction_time="2018-02-12")
        result = conditional.compare_phase(*fixture(records))
        effect = comparison(result)["effects"]["supported"]
        self.assertAlmostEqual(effect["native_difference"], .175)
        self.assertAlmostEqual(effect["equal_stratum_native_difference"], .05)
        self.assertAlmostEqual(effect["order_probability"], .75)
        self.assertEqual(effect["total_comparisons"], 195)
        self.assertEqual((effect["positive_strata"], effect["zero_strata"], effect["negative_strata"]), (1, 0, 1))
        self.assertEqual(sum(week["common_n"] for week in effect["by_week"]), effect["common_n"])

    def test_missing_signals_control_missingness_and_coverage_are_conserved(self):
        records = block([np.nan, np.inf, .5], [.1, np.nan])
        records += block([.7], [np.nan], prediction_time="2018-02-12")
        result = conditional.compare_phase(*fixture(records))
        coverage = comparison(result)["coverage"]
        self.assertEqual((coverage["all_common"], coverage["finite_common"], coverage["finite_overlap"]), (4, 2, 1))
        self.assertEqual(coverage["uncovered"], {"missing_signal": 2, "no_control": 1, "low_cohort": 1, "low_local_support": 0})
        self.assertEqual(sum(coverage["uncovered"].values()) + coverage["supported"], 4)
        first = cells(result)[0]
        self.assertEqual((first["common20_n"], first["common20_finite_n"], first["common20_missing_n"]), (3, 1, 2))
        self.assertEqual(first["known_on_time_missing_n"], 1)
        json.dumps(result, allow_nan=False)

    def test_exact_promise_days_are_preserved_as_a_separate_fixed_analysis(self):
        records = block([.8] * 3, [], estimated_delivery_days=22)
        records += block([], [.1] * 5, estimated_delivery_days=30)
        result = conditional.compare_phase(*fixture(records))
        self.assertEqual(comparison(result)["coverage"]["supported"], 3)
        exact = comparison(result, scheme="promise_days")
        self.assertEqual(exact["coverage"]["finite_overlap"], 0)
        self.assertEqual(exact["coverage"]["uncovered"]["no_control"], 3)
        self.assertIsNone(exact["effects"]["supported"]["risk_difference"])
        self.assertEqual({row["promise_days"] for row in cells(result, scheme="promise_days")}, {22., 30.})

    def test_monday_week_can_cross_months_and_sunday_does_not_move_to_next_week(self):
        records = block([.8] * 3, [], prediction_time="2018-01-31 23:59:59")
        records += block([], [.2] * 4, prediction_time="2018-02-01 00:00:00")
        records += block([], [.2], prediction_time="2018-02-04 23:59:59")
        result = conditional.compare_phase(*fixture(records))
        self.assertEqual(comparison(result)["coverage"]["supported"], 3)
        self.assertEqual([row["approval_week"] for row in cells(result)], ["2018-01-29"])
        self.assertEqual(comparison(result)["effects"]["supported"]["week_count"], 1)

    def test_full_state_route_is_fixed_and_never_pooled_by_R_A_membership(self):
        records = block([.8] * 3, [], state_route="SP->RJ")
        records += block([], [.2] * 5, state_route="SP->SC")
        result = conditional.compare_phase(*fixture(records))
        self.assertEqual(comparison(result)["coverage"]["finite_overlap"], 0)
        self.assertEqual({row["state_route"] for row in cells(result)}, {"SP->RJ", "SP->SC"})

    def test_each_candidate_uses_its_own_support_and_recent_requires_both_windows(self):
        records = block([.8] * 3, [.2] * 5, seller_completed_90d=100,
                        audit_seller_route_completed_90d=5, route_completed_90d=100,
                        audit_route_completed_30d=19)
        result = conditional.compare_phase(*fixture(records))
        self.assertEqual(comparison(result, candidate=CDF)["coverage"]["supported"], 3)
        for candidate in (JOINT, RECENT):
            row = comparison(result, candidate=candidate)
            self.assertEqual(row["coverage"]["cohort_adequate"], 3)
            self.assertEqual(row["coverage"]["supported"], 0)
            self.assertEqual(row["coverage"]["uncovered"]["low_local_support"], 3)
        recent = cells(result, candidate=RECENT)[0]
        self.assertEqual((recent["route30"], recent["route90"]), ("5-19", "100+"))

    def test_support_bins_are_matching_keys_not_just_an_afterward_gate(self):
        records = block([.8] * 3, [], seller_completed_90d=20)
        records += block([], [.2] * 5, seller_completed_90d=100)
        result = conditional.compare_phase(*fixture(records))
        self.assertEqual(comparison(result, candidate=CDF)["coverage"]["finite_overlap"], 0)
        self.assertEqual(comparison(result, candidate=JOINT)["coverage"]["supported"], 3)

    def test_unknown_key_and_known_zero_are_separate_and_never_coarsened(self):
        records = block([.8] * 3, [.2] * 5, seller_completed_90d=0, audit_seller_key_known=0)
        records += block([.7] * 3, [.1] * 5, seller_completed_90d=0, audit_seller_key_known=1)
        result = conditional.compare_phase(*fixture(records))
        rows = cells(result, candidate=CDF)
        self.assertEqual({row["seller90"] for row in rows}, {"unknown_key", "0"})
        coverage = comparison(result, candidate=CDF)["coverage"]
        self.assertEqual((coverage["cohort_adequate"], coverage["supported"]), (6, 0))
        self.assertEqual(coverage["uncovered"]["low_local_support"], 6)

    def test_cohort_gate_requires_three_common_and_five_controls_without_discarding_overlap(self):
        records = block([.8] * 2, [.2] * 5, prediction_time="2018-02-05")
        records += block([.8] * 3, [.2] * 4, prediction_time="2018-02-12")
        records += block([.8] * 3, [.2] * 5, prediction_time="2018-02-19")
        result = conditional.compare_phase(*fixture(records))
        coverage = comparison(result)["coverage"]
        self.assertEqual((coverage["finite_overlap"], coverage["cohort_adequate"], coverage["supported"]), (8, 3, 3))
        self.assertEqual((coverage["common_below_three"], coverage["control_below_five"]), (2, 3))
        self.assertEqual(coverage["uncovered"]["low_cohort"], 5)

    def test_risk_orientation_ties_and_epsilon_direction(self):
        result = conditional.compare_phase(*fixture(block([.2] * 3, [.8] * 5)))
        self.assertGreater(comparison(result, candidate=CDF)["effects"]["supported"]["risk_difference"], 0)
        self.assertEqual(comparison(result, candidate=CDF)["effects"]["supported"]["order_probability"], 1.)
        self.assertEqual(comparison(result, candidate=JOINT)["effects"]["supported"]["order_probability"], 0.)
        result = conditional.compare_phase(*fixture(block([.5 + 1e-13] * 3, [.5] * 5)))
        effect = comparison(result)["effects"]["supported"]
        self.assertEqual((effect["positive_strata"], effect["zero_strata"], effect["negative_strata"]), (0, 1, 0))
        self.assertEqual((effect["order_probability"], effect["tie_pair_count"], effect["total_comparisons"]), (.5, 15, 15))

    def test_pair_ordering_counts_ties_and_does_not_remove_them(self):
        result = conditional.compare_phase(*fixture(block([.2, .5, .8], [.2, .2, .5, .8, .8])))
        effect = comparison(result)["effects"]["supported"]
        self.assertEqual((effect["tie_pair_count"], effect["total_comparisons"], effect["risk_win_pair_count"]), (5, 15, 5))
        self.assertEqual(effect["order_probability"], .5)
        self.assertEqual(cells(result)[0]["known_on_time_tie_pair_count"], 5)

    def test_seed_identities_are_retained_even_when_seed_totals_equal(self):
        frame, known, common, seeds = fixture(block([.2, .8, .6], [.5] * 5))
        seeds[11][0] = False
        seeds[29][1] = False
        common = np.logical_and.reduce(list(seeds.values()))
        result = conditional.compare_phase(frame, known, common, seeds)
        row = result["groups"]["ALL"]
        eleven = row["common4_by_seed"]["11"]["promise_bin"][JOINT]
        twentynine = row["common4_by_seed"]["29"]["promise_bin"][JOINT]
        self.assertEqual(eleven["coverage"]["all_common"], twentynine["coverage"]["all_common"])
        self.assertNotEqual(eleven["effects"]["finite_overlap"]["native_difference"], twentynine["effects"]["finite_overlap"]["native_difference"])
        self.assertEqual(eleven["effects"]["finite_overlap"]["order_probability"], 1.)
        self.assertEqual(twentynine["effects"]["finite_overlap"]["order_probability"], .5)
        self.assertEqual(set(row["common4_by_seed"]), set(map(str, conditional.SEEDS)))
        self.assertNotIn("common4_by_seed", result["groups"]["cell:000"])

    def test_unknown_label_is_unread_but_full_batch_unknown_count_remains(self):
        frame, known, common, seeds = fixture(block([.8] * 3, [.2] * 5) + [{"known": False, "delayed": {"future": "forbidden"}}])
        result = conditional.compare_phase(frame, known, common, seeds)
        frame.at[len(frame) - 1, "delayed"] = ["unread future label"]
        self.assertEqual(result, conditional.compare_phase(frame, known, common, seeds))
        row = cells(result)[0]
        self.assertEqual((row["full_batch_n"], row["known_n"], row["unknown_n"]), (9, 8, 1))

    def test_other_delayed_is_secondary_and_excludes_common20_by_identity(self):
        records = block([.8] * 3, [.2] * 5) + [{"delayed": 1, JOINT: .7} for _ in range(5)]
        result = conditional.compare_phase(*fixture(records))
        row = comparison(result, control="other_delayed")
        self.assertEqual(row["coverage"]["supported"], 3)
        self.assertAlmostEqual(row["effects"]["supported"]["native_difference"], .1)
        self.assertEqual(cells(result)[0]["other_delayed_n"], 5)

    def test_zero_common_strata_missing_routes_and_empty_groups_remain_public(self):
        records = block([.8] * 3, [.2] * 5)
        records += [{"state_route": None, "known": False, "delayed": "unread", JOINT: np.nan}]
        result = conditional.compare_phase(*fixture(records))
        unknown = [row for row in cells(result) if row["state_route"] is None][0]
        self.assertEqual((unknown["full_batch_n"], unknown["common20_n"], unknown["full_batch_missing_n"]), (1, 0, 1))
        empty = comparison(result, group="SP->SC")
        self.assertEqual(empty["coverage"]["all_common"], 0)
        self.assertIsNone(empty["coverage"]["supported_fraction_all_common"])
        self.assertIsNone(empty["effects"]["supported"]["risk_difference"])
        self.assertEqual(cells(result, group="SP->SC"), [])
        json.dumps(result, allow_nan=False)

    def test_eight_RPA_cells_partition_all_denominators_and_required_marginals_exist(self):
        records = []
        for index in range(8):
            records += block([.8], [.2], state_route="SP->RJ" if index & 4 else "SP->SC",
                             estimated_delivery_days=25 if index & 2 else 15,
                             **{conditional.profiles.intersections.FEATURE: 48 if index & 1 else 24})
        result = conditional.compare_phase(*fixture(records))
        self.assertEqual(len(result["groups"]), 16)
        self.assertEqual(set(result["groups"]), {"ALL", "R", "A", "RA", "R_not_A", "A_not_R", "NOT_A", "SP->SC",
                                               *(f"cell:{cell}" for cell in conditional.profiles.intersections.CELLS)})
        for field in ("full_batch_rows", "known_rows", "unknown_rows", "positive_rows", "common20_rows", "known_on_time_rows", "other_delayed_rows"):
            self.assertEqual(sum(result["groups"][f"cell:{cell}"]["denominators"][field] for cell in conditional.profiles.intersections.CELLS), result["groups"]["ALL"]["denominators"][field])

    def test_empty_phase_has_complete_null_schema_and_no_nonstandard_json(self):
        result = conditional.compare_phase(*fixture([]))
        self.assertEqual(result["rows"], 0)
        self.assertEqual(len(result["groups"]), 16)
        self.assertIsNone(comparison(result)["unadjusted"]["native_difference"])
        self.assertEqual(cells(result), [])
        json.dumps(result, allow_nan=False)

    def test_include_strata_only_controls_serialization_not_summary_values(self):
        args = fixture(block([.8] * 3, [.2] * 5))
        full, compact = conditional.compare_phase(*args), conditional.compare_phase(*args, include_strata=False)
        full["contract"]["full_strata_included"] = False
        for row in full["groups"].values():
            for candidates in row["comparisons"].values():
                for candidate in candidates.values():
                    candidate.pop("strata", None)
        self.assertEqual(full, compact)
        with self.assertRaisesRegex(ValueError, "include_strata"):
            conditional.compare_phase(*args, include_strata=1)

    def test_public_result_contains_no_order_identifier_or_individual_values(self):
        args = fixture(block([.8] * 3, [.2] * 5))
        encoded = json.dumps(conditional.compare_phase(*args), allow_nan=False)
        self.assertNotIn("PRIVATE_IDENTIFIER_NEVER_EXPORTED", encoded)
        self.assertNotIn("order_id", encoded)
        self.assertNotIn("seller_id", encoded)

    def test_reject_nonboolean_misaligned_masks_invalid_seeds_and_identity(self):
        frame, known, common, seeds = fixture(block([.8] * 3, [.2] * 5))
        for invalid in (known.astype(int), known[:-1], np.array([True] * 7 + [None], dtype=object)):
            with self.subTest(invalid=repr(invalid)), self.assertRaisesRegex(ValueError, "boolean"):
                conditional.compare_phase(frame, invalid, common, seeds)
        with self.assertRaisesRegex(ValueError, "index"):
            conditional.compare_phase(frame, pd.Series(known, index=np.arange(8) + 1), common, seeds)
        changed = deepcopy(seeds)
        changed[999] = changed.pop(11)
        with self.assertRaisesRegex(ValueError, "seed"):
            conditional.compare_phase(frame, known, common, changed)
        wrong = common.copy()
        wrong[0], wrong[-1] = False, True
        with self.assertRaisesRegex(ValueError, "identity"):
            conditional.compare_phase(frame, known, wrong, seeds)
        for value in seeds.values():
            value[-1] = True
        common[-1] = True
        with self.assertRaisesRegex(ValueError, "known delayed"):
            conditional.compare_phase(frame, known, common, seeds)

    def test_invalid_labels_timestamps_promises_and_support_contracts_fail(self):
        args = fixture(block([.8] * 3, [.2] * 5))
        invalids = [("delayed", 9, "binary labels"), ("prediction_time", None, "timezone-naive"),
                    ("prediction_time", "2018-02-05T00:00:00Z", "timezone-naive"),
                    ("estimated_delivery_days", 25.5, "integers"),
                    ("seller_completed_90d", -1, "nonnegative integers"),
                    ("audit_seller_key_known", 0, "pooled")]
        for column, value, message in invalids:
            changed = args[0].copy()
            changed.at[0, column] = value
            with self.subTest(column=column, value=value), self.assertRaisesRegex(ValueError, message):
                conditional.compare_phase(changed, *args[1:])

    def test_inputs_and_duplicate_nonmonotonic_indices_are_preserved(self):
        frame, known, common, seeds = fixture(block([.8] * 3, [.2] * 5))
        frame.index = [8, 3, 3, 1, 99, 6, 4, 2]
        before = frame.copy(deep=True)
        seed_before = deepcopy(seeds)
        conditional.compare_phase(frame, known, common, seeds)
        pd.testing.assert_frame_equal(frame, before, check_exact=True)
        for seed in conditional.SEEDS:
            np.testing.assert_array_equal(seed_before[seed], seeds[seed])


if __name__ == "__main__":
    unittest.main()
