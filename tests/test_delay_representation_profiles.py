"""Synthetic tests of representation denominators and fixed comparisons."""
from copy import deepcopy
import json
import unittest

import numpy as np
import pandas as pd

from scripts import delay_representation_profiles as audit


def fixture(records):
    frame_rows, audit_rows, known, missed = [], [], [], []
    for i, supplied in enumerate(records):
        record = dict(supplied)
        known.append(record.pop("known", True))
        missed.append(record.pop("miss", False))
        approved = record.pop("approved", 100)
        pending = record.pop("pending", 50)
        overdue = record.pop("pending_overdue", 10)
        basis_overrides = record.pop("audit_overrides", {})
        row = {"order_id": f"PRIVATE_QUERY_{i}", "prediction_time": "2018-02-05 12:00:00",
               "state_route": "SP->RJ", "estimated_delivery_days": 25,
               audit.profiles.intersections.FEATURE: 48., "delayed": 0}
        for count, key in audit.old.SUPPORT_MAPPING.values():
            row[count], row[key] = 20., 1.
        row.update(record)
        extra = {"order_id": row["order_id"], "prediction_time": row["prediction_time"]}
        for basis, (_, window) in audit.core.BASES.items():
            fields = dict(approved=approved, pending=pending, pending_overdue=overdue)
            fields.update(basis_overrides.get(basis, {}))
            key_known = fields.pop("key_known", 1)
            a, p, o = fields["approved"], fields["pending"], fields["pending_overdue"]
            c = a - p
            values = {name: 0. for name in audit.core.counter_names(window)}
            values.update(approved=a, pending=p, completed=c, pending_overdue=o,
                          pending_active=p-o, completed_legacy=c, pending_legacy=p,
                          legacy_delivery_window=c, completed_valid_promise=c,
                          pending_valid_promise=p, completed_promise_days_sum=25*c,
                          pending_promise_days_sum=25*p, completed_age_0_7=c, pending_age_0_7=p)
            values.update(fields)
            prefix = f"audit_{basis}_"
            extra[prefix + "key_known"] = float(key_known)
            extra.update({prefix + name: value if key_known else np.nan for name, value in values.items()})
        frame_rows.append(row)
        audit_rows.append(extra)
    if not records:
        frame, values, *_ = fixture([{}])
        frame, values = frame.iloc[:0].copy(), values.iloc[:0].copy()
    else:
        frame, values = pd.DataFrame(frame_rows), pd.DataFrame(audit_rows)
    known, missed = np.asarray(known, bool), np.asarray(missed, bool)
    return frame, values, known, missed, {seed: missed.copy() for seed in audit.SEEDS}


def block(misses, controls, **fields):
    return [{"pending": value, "miss": flag, "delayed": int(flag), **fields}
            for values, flag in ((misses, True), (controls, False)) for value in values]


def comparison(result, *, basis="seller90", metric="pending_share", scheme="promise_days", group="ALL", control="known_on_time"):
    return result["groups"][group]["comparisons"][scheme][basis][metric][control]


def detail(result, **kwargs):
    group = kwargs.pop("group", "ALL")
    scheme = kwargs.pop("scheme", "promise_days")
    basis = kwargs.pop("basis", "seller90")
    metric = kwargs.pop("metric", "pending_share")
    table = result["groups"][group]["comparisons"][scheme][basis][metric]["strata"]
    return [dict(zip(table["columns"], row, strict=True)) for row in table["rows"]]


def screen_group(direction=1, count=20, weeks=3):
    def effect():
        return {"effects": {"supported": {"common_n": count, "control_n": 50,
                "week_count": weeks, "strata_count": weeks,
                "risk_difference": direction*.1, "order_probability": .5+direction*.1}}}
    comparisons = {scheme: {basis: {metric: {"known_on_time": effect()} for metric in audit.METRICS}
                            for basis in audit.COMPARISON_BASES} for scheme in audit.SCHEMES}
    seeds = {str(seed): {"comparisons": {scheme: {basis: {metric: effect() for metric in audit.METRICS}
                      for basis in audit.COMPARISON_BASES} for scheme in audit.SCHEMES}} for seed in audit.SEEDS}
    return {"comparisons": comparisons, "common4_by_seed": seeds}


def screen_fixture(directions=(1, 1, -1)):
    phases, metadata = {}, {}
    for month, direction in zip(("2017-12", "2018-02", "2018-04"), directions, strict=True):
        key = f"{month}/{month}/evaluation"
        phases[key] = {"groups": {group: screen_group(direction) for group in audit.FOCUS_GROUPS}}
        metadata[key] = {"ledger_role": "evaluation", "month": month}
    return phases, metadata


class RepresentationProfileTests(unittest.TestCase):
    def test_query_ratios_keep_zero_approval_and_unknown_key_missing(self):
        frame, values, *_ = fixture([{}, {"approved": 0, "pending": 0, "pending_overdue": 0},
                                    {"audit_overrides": {basis: {"key_known": 0} for basis in audit.BASES}}])
        result = audit.derive_metrics(values)
        self.assertEqual(len(result), 6)
        for basis in audit.COMPARISON_BASES:
            self.assertAlmostEqual(result[f"{basis}_pending_share"][0], .5)
            self.assertTrue(np.isnan(result[f"{basis}_pending_share"][1:]).all())
        self.assertEqual(frame.order_id.tolist(), values.order_id.tolist())

    def test_query_means_and_pooled_occurrence_ratios_have_different_denominators(self):
        args = fixture([{"approved": 100, "pending": 0, "pending_overdue": 0},
                        {"approved": 10, "pending": 10, "pending_overdue": 2}])
        result = audit.compare_phase(*args)
        row = result["groups"]["ALL"]["cohorts"]["all_known"]["seller90"]
        self.assertEqual(row["query_ratios"]["pending_share"]["mean"], .5)
        self.assertAlmostEqual(row["pooled_occurrence_ratios"]["pending_share"], 10/110)
        self.assertEqual(row["counter_sums"]["approved"], 110)
        self.assertEqual(row["age_composition"]["pending"]["0_7"]["pooled_occurrence_share"], 1.)
        self.assertEqual(row["valid_promise_days"]["completed"]["pooled_occurrence_mean"], 25.)

    def test_public_phase_is_equal_after_strict_json_round_trip(self):
        result = audit.compare_phase(*fixture(block([80]*3, [20]*5)), include_strata=True)
        self.assertEqual(result, json.loads(json.dumps(result, allow_nan=False)))
        screen = audit.representation_screen(*screen_fixture())
        self.assertEqual(screen, json.loads(json.dumps(screen, allow_nan=False)))

    def test_weekday_sensitivity_preserves_week_and_reports_lost_overlap(self):
        records = block([80]*3, [], prediction_time="2018-02-05 12:00:00")
        records += block([], [20]*5, prediction_time="2018-02-06 12:00:00")
        result = audit.compare_phase(*fixture(records), include_strata=True)
        self.assertEqual(comparison(result)["coverage"]["supported"], 3)
        weekday = comparison(result, scheme="promise_days_weekday")
        self.assertEqual(weekday["coverage"]["uncovered"]["no_control"], 3)
        self.assertEqual(sum(weekday["coverage"]["uncovered"].values()) + weekday["coverage"]["supported"], 3)
        rows = detail(result, scheme="promise_days_weekday")
        self.assertEqual({row["approval_weekday"] for row in rows}, {0, 1})
        self.assertEqual({row["approval_week"] for row in rows}, {"2018-02-05"})
        self.assertEqual(list(rows[0])[2], "approval_week")

    def test_old_support_clocks_and_candidate_support_pair_are_retained(self):
        args = fixture(block([800]*3, [200]*5, approved=1000, seller_completed_90d=19,
                             audit_seller_route_completed_90d=20, route_completed_90d=100,
                             audit_route_completed_30d=19))
        original = args[0].copy(deep=True)
        result = audit.compare_phase(*args)
        self.assertEqual(comparison(result)["coverage"]["supported"], 0)
        self.assertEqual(comparison(result)["coverage"]["uncovered"]["low_local_support"], 3)
        self.assertEqual(comparison(result, basis="joint90")["coverage"]["supported"], 3)
        self.assertEqual(comparison(result, basis="route90")["coverage"]["supported"], 0)
        pd.testing.assert_frame_equal(args[0], original, check_exact=True)

    def test_common_weights_are_neither_pair_weights_nor_equal_stratum_weights(self):
        rows = block([80]*9, [50]*5)
        rows += block([30]*3, [50]*50, prediction_time="2018-02-12 12:00:00")
        result = audit.compare_phase(*fixture(rows))
        effect = comparison(result)["effects"]["supported"]
        self.assertAlmostEqual(effect["risk_difference"], .175)
        self.assertAlmostEqual(effect["equal_stratum_risk_difference"], .05)
        self.assertEqual(effect["order_probability"], .75)
        self.assertEqual(effect["total_comparisons"], 195)
        self.assertEqual(sum(row["common_n"] for row in effect["by_week"]), 12)

    def test_equal_risk_ties_remain_half_wins(self):
        result = audit.compare_phase(*fixture(block([50]*3, [50]*5)))
        effect = comparison(result)["effects"]["supported"]
        self.assertEqual((effect["tie_pair_count"], effect["total_comparisons"], effect["order_probability"]), (15, 15, .5))

    def test_seed_masks_preserve_identities_even_when_totals_match(self):
        frame, values, known, common, seeds = fixture(block([20, 80, 60], [50]*5))
        seeds[11][0], seeds[29][1] = False, False
        common = np.logical_and.reduce(list(seeds.values()))
        result = audit.compare_phase(frame, values, known, common, seeds)
        row = result["groups"]["ALL"]["common4_by_seed"]
        left = row["11"]["comparisons"]["promise_days"]["seller90"]["pending_share"]
        right = row["29"]["comparisons"]["promise_days"]["seller90"]["pending_share"]
        self.assertEqual(left["coverage"]["all_common"], right["coverage"]["all_common"])
        self.assertNotEqual(left["effects"]["finite_overlap"]["risk_difference"], right["effects"]["finite_overlap"]["risk_difference"])
        self.assertEqual(set(row), set(map(str, audit.SEEDS)))

    def test_common20_must_be_identity_intersection_and_known_positive(self):
        frame, values, known, common, seeds = fixture(block([80]*3, [20]*5))
        seeds[11][0] = False
        with self.assertRaisesRegex(ValueError, "intersection"):
            audit.compare_phase(frame, values, known, common, seeds)
        seeds[11] = common.copy()
        frame.loc[0, "delayed"] = 0
        with self.assertRaisesRegex(ValueError, "known delayed"):
            audit.compare_phase(frame, values, known, common, seeds)

    def test_unknown_query_label_is_not_read_and_public_output_has_no_ids(self):
        args = fixture(block([80]*3, [20]*5) + [{"known": False, "delayed": {"future": "PRIVATE"}}])
        result = audit.compare_phase(*args, include_strata=True)
        args[0].at[8, "delayed"] = ["another forbidden label"]
        self.assertEqual(result, audit.compare_phase(*args, include_strata=True))
        self.assertEqual(result["groups"]["ALL"]["cohorts"]["unknown"]["seller90"]["rows"], 1)
        text = json.dumps(result, allow_nan=False)
        self.assertNotIn("PRIVATE", text)
        self.assertNotIn("order_id", text)
        self.assertEqual(len(result["groups"]), 16)
        self.assertNotIn("common4_by_seed", result["groups"]["cell:000"])
        self.assertNotIn("strata", result["groups"]["cell:000"]["comparisons"]["promise_days"]["seller90"]["pending_share"])

    def test_audit_index_identity_and_clock_alignment_are_required(self):
        frame, values, known, common, seeds = fixture(block([80]*3, [20]*5))
        invalid = values.copy()
        invalid.index = invalid.index[::-1]
        with self.assertRaisesRegex(ValueError, "ordered query index"):
            audit.compare_phase(frame, invalid, known, common, seeds)
        invalid = values.copy()
        invalid.loc[0, "order_id"] = "DIFFERENT"
        with self.assertRaisesRegex(ValueError, "identities"):
            audit.compare_phase(frame, invalid, known, common, seeds)
        invalid = values.copy()
        invalid.loc[0, "prediction_time"] = "2018-02-05 13:00:00"
        with self.assertRaisesRegex(ValueError, "clocks"):
            audit.compare_phase(frame, invalid, known, common, seeds)

    def test_audit_counter_conservation_is_validated(self):
        frame, values, *_ = fixture([{}])
        values.loc[0, "audit_seller90_approved"] += 1
        with self.assertRaisesRegex(ValueError, "conservation"):
            audit._audit_arrays(frame, values)

    def test_unknown_keys_cannot_have_fabricated_zero_counters(self):
        frame, values, *_ = fixture([{}])
        values.loc[0, "audit_seller90_key_known"] = 0
        with self.assertRaisesRegex(ValueError, "NaN"):
            audit._audit_arrays(frame, values)

    def test_audit_group_keys_must_agree_with_original_support_keys(self):
        frame, values, known, common, seeds = fixture([{
            "audit_overrides": {basis: {"key_known": 0} for basis in audit.BASES}}])
        with self.assertRaisesRegex(ValueError, "original mature-support"):
            audit.compare_phase(frame, values, known, common, seeds)

    def test_empty_queries_and_zero_miss_cells_remain_valid_json(self):
        result = audit.compare_phase(*fixture([]), include_strata=True)
        self.assertEqual(result["rows"], 0)
        self.assertIsNone(comparison(result)["effects"]["supported"]["risk_difference"])
        self.assertEqual(detail(result), [])
        json.dumps(result, allow_nan=False)

    def test_secondary_other_delayed_uses_its_own_controls(self):
        records = block([80]*3, [20]*5) + [{"pending": 70, "delayed": 1}]*5
        result = audit.compare_phase(*fixture(records))
        other = comparison(result, control="other_delayed")
        self.assertAlmostEqual(other["effects"]["supported"]["risk_difference"], .1)
        self.assertEqual(result["groups"]["ALL"]["denominators"]["other_delayed_rows"], 5)

    def test_two_distinct_development_months_can_flag_positive_or_inverse(self):
        for directions in ((1, 1, -1), (-1, -1, 1)):
            phases, metadata = screen_fixture(directions)
            result = audit.representation_screen(phases, metadata)
            row = result["by_basis"]["seller90"]["pending_share"]["ALL"]
            self.assertTrue(row["work_screen_at_least_two_months"])
            self.assertEqual(len(row["passing_months_by_direction"][str(directions[0])]), 2)
            self.assertFalse(result["automatic_training_selection"])

    def test_screen_requires_weekday_scheme_support_and_all_five_seeds(self):
        row = screen_group()
        row["comparisons"]["promise_days_weekday"]["seller90"]["pending_share"]["known_on_time"]["effects"]["supported"]["common_n"] = 19
        self.assertFalse(audit._phase_screen(row, "seller90", "pending_share")["work_screen_passed"])
        row = screen_group()
        row["common4_by_seed"]["101"]["comparisons"]["promise_days_weekday"]["seller90"]["pending_share"]["effects"]["supported"]["risk_difference"] = -.1
        self.assertFalse(audit._phase_screen(row, "seller90", "pending_share")["work_screen_passed"])

    def test_screen_rejects_mean_order_disagreement_zero_and_short_week_coverage(self):
        for field, value in (("order_probability", .4), ("risk_difference", 0.), ("week_count", 2)):
            row = screen_group()
            row["comparisons"]["promise_days"]["seller90"]["pending_share"]["known_on_time"]["effects"]["supported"][field] = value
            self.assertFalse(audit._phase_screen(row, "seller90", "pending_share")["work_screen_passed"])

    def test_repeated_validation_months_are_ignored_and_duplicate_development_months_rejected(self):
        phases, metadata = screen_fixture()
        previous = deepcopy(audit.representation_screen(phases, metadata))
        metadata["repeat/2018-02/validation"] = {"ledger_role": "validation", "month": "2018-02"}
        phases["repeat/2018-02/validation"] = {"forbidden": "not a development phase"}
        self.assertEqual(previous, audit.representation_screen(phases, metadata))
        evaluations = [key for key in metadata if metadata[key]["ledger_role"] == "evaluation"]
        metadata[evaluations[2]]["month"] = metadata[evaluations[0]]["month"]
        with self.assertRaisesRegex(ValueError, "three distinct"):
            audit.representation_screen(phases, metadata)


if __name__ == "__main__":
    unittest.main()
