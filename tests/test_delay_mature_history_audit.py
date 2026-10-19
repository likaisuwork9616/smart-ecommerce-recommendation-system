"""Synthetic time, maturity, support and shrinkage checks for the signal audit."""

import unittest

import numpy as np
import pandas as pd
from pandas.testing import assert_frame_equal, assert_index_equal

from scripts.delay_budget_features import FEATURES as BUDGET_FEATURES
from scripts.delay_history_features import add_delivery_history
from scripts.delay_mature_history_audit import (
    AUDIT_ONLY_FEATURES,
    CANDIDATE_FEATURES,
    RECOMPUTED_FEATURES,
    SIGNAL_FEATURES,
    build_signals,
)
from scripts.delay_route_features import add_route_promise_features


def queries(rows):
    return pd.DataFrame(rows, columns=["order_id", "prediction_time", "estimated_delivery_days",
                                       "customer_state", "primary_seller_state"])


def events(rows):
    return pd.DataFrame(rows, columns=["order_id", "prediction_time", "label_available_time",
                                       "delayed", "customer_state", "primary_seller_state"])


def sellers(query, event, overrides=None):
    assignments = {key: "a" for key in list(query.order_id) + list(event.order_id)}
    assignments.update(overrides or {})
    return pd.DataFrame(assignments.items(), columns=["order_id", "primary_seller_id"])


class MatureHistoryAuditTests(unittest.TestCase):
    def test_exact_90_and_30_day_boundaries_are_inclusive_and_approval_is_exclusive(self):
        time = pd.Timestamp("2020-04-01 12:00")
        query = queries([("q", time, 10, "RJ", "SP")])
        delivery_times = [time - pd.Timedelta(days=90, nanoseconds=1),
                          time - pd.Timedelta(days=90),
                          time - pd.Timedelta(days=30, nanoseconds=1),
                          time - pd.Timedelta(days=30),
                          time - pd.Timedelta(nanoseconds=1), time,
                          time + pd.Timedelta(nanoseconds=1)]
        event = events([(str(i), value - pd.Timedelta(days=10), value, 1, "RJ", "SP")
                        for i, value in enumerate(delivery_times)])
        row = build_signals(query, event, sellers(query, event)).iloc[0]
        for name in ("global_completed_90d", "seller_completed_90d", "route_completed_90d",
                     "audit_seller_route_completed_90d"):
            self.assertEqual(row[name], 4)
        self.assertEqual(row.audit_global_completed_30d, 2)
        self.assertEqual(row.audit_route_completed_30d, 2)
        self.assertEqual(row.audit_global_delay_count_90d, 4)
        self.assertEqual(row.audit_route_delay_count_30d, 2)

    def test_current_query_labels_and_same_id_outcome_are_never_consumed(self):
        query = queries([("q", "2020-04-01", 10, "RJ", "SP")])
        query["delayed"] = 0
        query["label_available_time"] = pd.Timestamp("2020-04-03")
        event = events([("old", "2020-03-01", "2020-03-05", 1, "RJ", "SP"),
                        ("q", "2020-04-01", "2020-04-01", 1, "RJ", "SP")])
        lookup = sellers(query, event)
        before = build_signals(query, event, lookup)
        query["delayed"] = 1
        query["label_available_time"] = pd.Timestamp("2020-08-03")
        event.loc[event.order_id == "q", "delayed"] = 0
        event.loc[event.order_id == "q", "label_available_time"] = "2020-08-03"
        after = build_signals(query, event, lookup)
        assert_frame_equal(before[SIGNAL_FEATURES], after[SIGNAL_FEATURES])
        self.assertEqual(after.iloc[0].global_completed_90d, 1)

    def test_future_event_duration_coordinates_and_labels_do_not_change_past_values(self):
        query = queries([("q", "2020-04-01", 10, "RJ", "SP")])
        event = events([("old", "2020-03-01", "2020-03-05", 1, "RJ", "SP"),
                        ("future", "2020-03-01", "2020-04-02", 1, "RJ", "SP")])
        lookup = sellers(query, event)
        before = build_signals(query, event, lookup)
        event.loc[event.order_id == "future", "prediction_time"] = "2019-01-01"
        event.loc[event.order_id == "future", "label_available_time"] = "2020-12-31"
        event.loc[event.order_id == "future", "delayed"] = 0
        after = build_signals(query, event, lookup)
        assert_frame_equal(before[SIGNAL_FEATURES], after[SIGNAL_FEATURES])

    def test_unknown_seller_and_route_keys_do_not_pool(self):
        query = queries([("q", "2020-04-01", 10, "RJ", np.nan),
                         ("blank", "2020-04-01", 10, "RJ", "")])
        event = events([("old", "2020-03-01", "2020-03-05", 1, "RJ", np.nan),
                        ("blank-old", "2020-03-01", "2020-03-05", 1, "RJ", "")])
        lookup = sellers(query, event, {"q": None, "old": None, "blank": "", "blank-old": ""})
        result = build_signals(query, event, lookup)
        self.assertTrue(result[CANDIDATE_FEATURES].isna().all(axis=None))
        for name in ("audit_seller_key_known", "audit_route_key_known",
                     "audit_seller_route_key_known", "audit_seller_route_completed_90d",
                     "audit_route_completed_30d", "audit_seller_delay_count_90d"):
            self.assertTrue(result[name].eq(0).all(), name)

    def test_seller_route_and_joint_histories_have_distinct_membership(self):
        query = queries([("q", "2020-04-01", 5, "RJ", "SP")])
        event = events([("joint", "2020-03-01", "2020-03-04", 1, "RJ", "SP"),
                        ("seller-only", "2020-03-01", "2020-03-11", 0, "SC", "SP"),
                        ("route-only", "2020-03-01", "2020-03-13", 1, "RJ", "SP"),
                        ("neither", "2020-03-01", "2020-03-02", 0, "SC", "SP")])
        row = build_signals(query, event, sellers(query, event, {"route-only": "b", "neither": "b"})).iloc[0]
        self.assertEqual(row.seller_completed_90d, 2)
        self.assertEqual(row.route_completed_90d, 2)
        self.assertEqual(row.audit_seller_route_completed_90d, 1)
        self.assertEqual(row.audit_seller_promise_count_le_90d, 1)
        self.assertEqual(row.audit_seller_promise_cdf_raw_90d, .5)
        self.assertEqual(row.audit_route_promise_cdf_raw_90d, .5)
        self.assertEqual(row.audit_seller_route_delay_rate_raw_90d, 1)
        self.assertAlmostEqual(row.seller_promise_cdf_90d, (1 + 20 * .5) / 22)
        self.assertAlmostEqual(row.seller_route_delay_rate_90d, (1 + 20 * row.route_delay_rate_90d) / 21)

    def test_hierarchical_prior_formulas_and_effective_prior_fractions(self):
        query = queries([("q", "2020-04-01", 5, "RJ", "SP")])
        event = events([("older", "2020-02-01", "2020-02-05", 0, "RJ", "SP"),
                        ("recent", "2020-03-05", "2020-03-15", 1, "RJ", "SP"),
                        ("other", "2020-03-05", "2020-03-08", 0, "SC", "SP")])
        row = build_signals(query, event, sellers(query, event, {"other": "b"})).iloc[0]
        global90 = (1 + 20 * .05) / 23
        route90 = (1 + 20 * global90) / 22
        global30 = (1 + 20 * .05) / 22
        route30 = (1 + 20 * global30) / 21
        self.assertAlmostEqual(row.route_delay_rate_90d, route90)
        self.assertAlmostEqual(row.audit_global_delay_rate_30d, global30)
        self.assertAlmostEqual(row.audit_route_recent30_delay_rate_30d, route30)
        self.assertAlmostEqual(row.route_recent30_delay_rate_excess90d, route30 - route90)
        self.assertAlmostEqual(row.seller_promise_cdf_90d, (1 + 20 * (2 / 3)) / 22)
        self.assertAlmostEqual(row.seller_route_delay_rate_90d, (1 + 20 * route90) / 22)
        self.assertAlmostEqual(row.audit_seller_promise_prior_fraction_90d, 20 / 22)
        self.assertAlmostEqual(row.audit_seller_route_delay_prior_fraction_90d, 20 / 22)
        self.assertAlmostEqual(row.audit_route_recent30_prior_fraction, 20 / 21)

    def test_calendar_day_duration_matches_current_calendar_promise(self):
        query = queries([("one-day", "2020-04-01", 1, "RJ", "SP"),
                         ("fraction", "2020-04-01", .5, "RJ", "SP")])
        event = events([("old", "2020-03-01 23:59", "2020-03-02 00:01", 0, "RJ", "SP")])
        result = build_signals(query, event, sellers(query, event))
        self.assertEqual(result.iloc[0].seller_promise_cdf_90d, 1)
        self.assertEqual(result.iloc[1].seller_promise_cdf_90d, 0)
        self.assertAlmostEqual(result.iloc[0].seller_delivery_days_90d, 2 / 1440)

    def test_known_empty_histories_have_zero_support_and_explicit_prior(self):
        query = queries([("q", "2020-04-01", 5, "RJ", "SP")])
        event = events([("other", "2020-03-01", "2020-03-05", 1, "SC", "SP")])
        row = build_signals(query, event, sellers(query, event, {"other": "b"})).iloc[0]
        self.assertEqual(row.seller_completed_90d, 0)
        self.assertEqual(row.seller_promise_cdf_90d, 1)
        self.assertEqual(row.audit_seller_promise_prior_fraction_90d, 1)
        self.assertEqual(row.audit_seller_route_completed_90d, 0)
        self.assertEqual(row.seller_route_delay_rate_90d, row.route_delay_rate_90d)
        self.assertEqual(row.audit_route_completed_30d, 0)
        self.assertTrue(np.isnan(row.audit_seller_promise_cdf_raw_90d))
        self.assertEqual(row.audit_seller_key_known, 1)

    def test_completely_empty_history_preserves_rate_prior_but_not_cdf(self):
        query = queries([("q", "2020-04-01", 5, "RJ", "SP")])
        event = events([])
        row = build_signals(query, event, sellers(query, event)).iloc[0]
        self.assertTrue(np.isnan(row.seller_promise_cdf_90d))
        self.assertEqual(row.seller_route_delay_rate_90d, .05)
        self.assertEqual(row.route_recent30_delay_rate_excess90d, 0)
        self.assertEqual(row.audit_global_completed_30d, 0)
        self.assertEqual(row.audit_global_delay_prior_fraction_30d, 1)

    def test_row_index_order_and_inputs_are_preserved_and_stale_cache_is_overwritten(self):
        query = queries([("later", "2020-04-01", 5, "RJ", "SP"),
                         ("earlier", "2020-02-01", 5, "RJ", "SP"),
                         ("middle", "2020-03-01", 5, "SC", "SP")])
        query.index = [9, 9, 2]
        query["arbitrary_existing_feature"] = [3, 2, 1]
        query["route_delay_rate_90d"] = -999
        event = events([("old", "2020-02-01", "2020-02-15", 1, "RJ", "SP")])
        lookup = sellers(query, event)
        originals = [frame.copy(deep=True) for frame in (query, event, lookup)]
        result = build_signals(query, event, lookup)
        assert_index_equal(result.index, query.index)
        self.assertEqual(result.order_id.tolist(), query.order_id.tolist())
        self.assertEqual(result.arbitrary_existing_feature.tolist(), [3, 2, 1])
        self.assertFalse(result.route_delay_rate_90d.eq(-999).any())
        for actual, expected in zip((query, event, lookup), originals):
            assert_frame_equal(actual, expected)
        shuffled = build_signals(query.iloc[::-1], event.iloc[::-1], lookup)
        assert_frame_equal(result.set_index("order_id")[SIGNAL_FEATURES].sort_index(),
                           shuffled.set_index("order_id")[SIGNAL_FEATURES].sort_index())

    def test_recomputed_contract_matches_legacy_builders_and_budget_interactions(self):
        query = queries([("q", "2020-04-01", 5, "RJ", "SP")])
        event = events([("old", "2020-03-01", "2020-03-05", 1, "RJ", "SP")])
        lookup = sellers(query, event)
        expected = add_delivery_history(add_route_promise_features(query, event), event, lookup)
        expected["seller_promise_margin_days"] = expected.estimated_delivery_days - expected.seller_delivery_days_90d
        expected["seller_promise_ratio"] = expected.estimated_delivery_days / expected.seller_delivery_days_90d
        for prefix in ("seller", "route"):
            expected[f"{prefix}_delay_rate_excess_global"] = expected[f"{prefix}_delay_rate_90d"] - expected.global_delay_rate_90d
        result = build_signals(query, event, lookup)
        assert_frame_equal(result[RECOMPUTED_FEATURES], expected[RECOMPUTED_FEATURES])
        self.assertEqual(len(RECOMPUTED_FEATURES), 20)
        self.assertEqual(len(CANDIDATE_FEATURES), 3)
        self.assertFalse(set(CANDIDATE_FEATURES + AUDIT_ONLY_FEATURES) & set(BUDGET_FEATURES))
        self.assertTrue(all(np.issubdtype(result[name].dtype, np.number) for name in AUDIT_ONLY_FEATURES))

    def test_duplicate_and_null_ids_in_each_input_are_rejected(self):
        query = queries([("q", "2020-04-01", 5, "RJ", "SP")])
        event = events([("old", "2020-03-01", "2020-03-05", 1, "RJ", "SP")])
        lookup = sellers(query, event)
        for index in range(3):
            with self.subTest(input=index):
                frames = [query.copy(), event.copy(), lookup.copy()]
                frames[index] = pd.concat([frames[index], frames[index].iloc[[0]]], ignore_index=True)
                with self.assertRaisesRegex(ValueError, "one row per non-null order_id"):
                    build_signals(*frames)
                frames = [query.copy(), event.copy(), lookup.copy()]
                frames[index].loc[0, "order_id"] = None
                with self.assertRaisesRegex(ValueError, "one row per non-null order_id"):
                    build_signals(*frames)

    def test_invalid_missing_aware_or_impossible_timestamps_are_rejected(self):
        query = queries([("q", "2020-04-01", 5, "RJ", "SP")])
        event = events([("old", "2020-03-01", "2020-03-05", 1, "RJ", "SP")])
        lookup = sellers(query, event)
        for index, column in ((0, "prediction_time"), (1, "prediction_time"), (1, "label_available_time")):
            for value in ("invalid", None, "2020-03-01T00:00:00Z"):
                with self.subTest(input=index, column=column, value=value):
                    frames = [query.copy(), event.copy(), lookup.copy()]
                    frames[index].loc[0, column] = value
                    with self.assertRaises(ValueError):
                        build_signals(*frames)
        event.loc[0, "label_available_time"] = "2020-02-01"
        with self.assertRaisesRegex(ValueError, "must not precede"):
            build_signals(query, event, lookup)

    def test_moved_same_id_query_timestamp_is_rejected(self):
        query = queries([("q", "2020-04-01", 5, "RJ", "SP")])
        event = events([("q", "2020-03-01", "2020-03-05", 1, "RJ", "SP")])
        with self.assertRaisesRegex(ValueError, "identical prediction_time"):
            build_signals(query, event, sellers(query, event))

    def test_nonbinary_historical_labels_and_missing_required_columns_are_rejected(self):
        query = queries([("q", "2020-04-01", 5, "RJ", "SP")])
        event = events([("old", "2020-03-01", "2020-03-05", 2, "RJ", "SP")])
        lookup = sellers(query, event)
        with self.assertRaisesRegex(ValueError, "binary"):
            build_signals(query, event, lookup)
        with self.assertRaisesRegex(ValueError, "Missing queries"):
            build_signals(query.drop(columns="estimated_delivery_days"), event, lookup)

    def test_candidates_and_support_match_independent_bruteforce_on_shuffled_history(self):
        rng = np.random.default_rng(81)
        origin = pd.Timestamp("2020-01-01")
        event = events([
            (f"e{i}", origin + pd.Timedelta(days=int(day - duration), hours=23),
             origin + pd.Timedelta(days=int(day), hours=23), int(i % 3 == 0),
             "RJ" if i % 3 else "SC", "SP")
            for i, (day, duration) in enumerate(zip(rng.integers(0, 130, 70), rng.integers(1, 20, 70)))
        ])
        query = queries([(f"q{i}", origin + pd.Timedelta(days=int(day), hours=23),
                          int(i % 15 + 1), "RJ" if i % 3 else "SC", "SP")
                         for i, day in enumerate(rng.integers(20, 150, 14))])
        overrides = {key: ("b" if i % 2 else "a") for i, key in enumerate(event.order_id)}
        overrides.update({key: ("b" if i % 2 else "a") for i, key in enumerate(query.order_id)})
        lookup = sellers(query, event, overrides)
        result = build_signals(query.iloc[::-1], event.sample(frac=1, random_state=2), lookup)
        assignment = lookup.set_index("order_id").primary_seller_id
        delivery = pd.to_datetime(event.label_available_time)
        approval = pd.to_datetime(event.prediction_time)
        calendar_days = (delivery.dt.normalize() - approval.dt.normalize()).dt.days
        seller_ids = event.order_id.map(assignment)
        for row in result.itertuples():
            historical = (delivery >= row.prediction_time - pd.Timedelta(days=90)) & (delivery < row.prediction_time)
            historical30 = (delivery >= row.prediction_time - pd.Timedelta(days=30)) & (delivery < row.prediction_time)
            seller = historical & seller_ids.eq(assignment.loc[row.order_id])
            route_key = event.customer_state.eq(row.customer_state) & event.primary_seller_state.eq(row.primary_seller_state)
            route = historical & route_key
            joint = seller & route_key
            recent_route = historical30 & route_key
            global90rate = (event.loc[historical, "delayed"].sum() + 1) / (historical.sum() + 20)
            route90rate = (event.loc[route, "delayed"].sum() + 20 * global90rate) / (route.sum() + 20)
            global30rate = (event.loc[historical30, "delayed"].sum() + 1) / (historical30.sum() + 20)
            route30rate = (event.loc[recent_route, "delayed"].sum() + 20 * global30rate) / (recent_route.sum() + 20)
            global_cdf = calendar_days.loc[historical].le(row.estimated_delivery_days).mean()
            seller_cdf = (calendar_days.loc[seller].le(row.estimated_delivery_days).sum() + 20 * global_cdf) / (seller.sum() + 20)
            joint_rate = (event.loc[joint, "delayed"].sum() + 20 * route90rate) / (joint.sum() + 20)
            self.assertAlmostEqual(row.seller_promise_cdf_90d, seller_cdf)
            self.assertAlmostEqual(row.seller_route_delay_rate_90d, joint_rate)
            self.assertAlmostEqual(row.route_recent30_delay_rate_excess90d, route30rate - route90rate)
            self.assertEqual(row.seller_completed_90d, seller.sum())
            self.assertEqual(row.route_completed_90d, route.sum())
            self.assertEqual(row.audit_seller_route_completed_90d, joint.sum())
            self.assertEqual(row.audit_route_completed_30d, recent_route.sum())
            self.assertEqual(row.audit_global_promise_count_le_90d, calendar_days.loc[historical].le(row.estimated_delivery_days).sum())


if __name__ == "__main__":
    unittest.main()
