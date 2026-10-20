"""Synthetic independent oracles for status-free history representation."""
from __future__ import annotations

import unittest

import numpy as np
import pandas as pd
from pandas.testing import assert_frame_equal

from scripts.delay_history_representativeness import (
    AGE_BINS, BASES, COUNTERS, build_representation, counter_names,
)


def history(rows):
    """ID, approval, delivery, promise, carrier, seller, route, legacy."""
    return pd.DataFrame([{
        "order_id": row[0], "prediction_time": pd.Timestamp(row[1]),
        "purchase_time": pd.Timestamp(row[1]) - pd.Timedelta(hours=1),
        "delivery_time": pd.Timestamp(row[2]) if row[2] is not None else pd.NaT,
        "promise_time": pd.Timestamp(row[3]) if row[3] is not None else pd.NaT,
        "carrier_time": pd.Timestamp(row[4]) if row[4] is not None else pd.NaT,
        "primary_seller_id": row[5], "state_route": row[6], "legacy_eligible": row[7],
    } for row in rows], columns=["order_id", "prediction_time", "purchase_time", "delivery_time",
                                "promise_time", "carrier_time", "primary_seller_id", "state_route", "legacy_eligible"])


def queries(times, seller="s1", route="SP->RJ"):
    return pd.DataFrame({"order_id": [f"query-{i}" for i in range(len(times))],
                         "prediction_time": pd.to_datetime(times, format="mixed"), "primary_seller_id": seller,
                         "state_route": route})


def known(value):
    return value is not None and not pd.isna(value) and bool(str(value).strip())


def independent_oracle(query, raw):
    extra, quality = {}, {}
    for basis, (kind, window) in BASES.items():
        columns = {name: [] for name in counter_names(window)}
        known_values, used = [], set()
        occurrences = 0
        for row in query.itertuples(index=False):
            qknown = (known(row.primary_seller_id) if kind == "seller" else known(row.state_route)
                      if kind == "route" else known(row.primary_seller_id) and known(row.state_route))
            known_values.append(float(qknown))
            if not qknown:
                for name in columns:
                    columns[name].append(np.nan)
                continue
            selected = pd.Series(True, index=raw.index)
            if kind in ("seller", "joint"):
                selected &= raw.primary_seller_id.eq(row.primary_seller_id)
            if kind in ("route", "joint"):
                selected &= raw.state_route.eq(row.state_route)
            group = raw.loc[selected]
            h = group.loc[(group.prediction_time < row.prediction_time)
                          & (group.prediction_time >= row.prediction_time - pd.Timedelta(days=window))]
            used.update(h.order_id)
            occurrences += len(h)
            observed = h.delivery_time.notna() & h.delivery_time.lt(row.prediction_time)
            complete = observed & h.delivery_time.ge(h.prediction_time)
            invalid_delivery = observed & h.delivery_time.lt(h.prediction_time)
            pending = ~observed
            promise_days = (h.promise_time.dt.normalize() - h.prediction_time.dt.normalize()).dt.days
            valid_promise = promise_days.notna() & promise_days.ge(0)
            expired = valid_promise & (h.promise_time.dt.normalize() + pd.Timedelta(days=1)).le(row.prediction_time)
            legacy_delivered = group.loc[group.legacy_eligible & group.delivery_time.lt(row.prediction_time)
                & group.delivery_time.ge(row.prediction_time - pd.Timedelta(days=window))]
            values = {
                "approved": len(h), "completed": int(complete.sum()), "pending": int(pending.sum()),
                "invalid_delivery": int(invalid_delivery.sum()),
                "pending_active": int((pending & valid_promise & ~expired).sum()),
                "pending_overdue": int((pending & expired).sum()),
                "pending_invalid_promise": int((pending & ~valid_promise).sum()),
                "pending_missing_promise": int((pending & promise_days.isna()).sum()),
                "pending_negative_promise": int((pending & promise_days.lt(0)).sum()),
                "pending_no_carrier_event": int((pending & ~(h.carrier_time.notna() & h.carrier_time.lt(row.prediction_time))).sum()),
                "delivery_equal_query": int(h.delivery_time.eq(row.prediction_time).sum()),
                "completed_legacy": int((complete & h.legacy_eligible).sum()),
                "pending_legacy": int((pending & h.legacy_eligible).sum()),
                "completed_legacy_excluded": int((complete & ~h.legacy_eligible).sum()),
                "pending_legacy_excluded": int((pending & ~h.legacy_eligible).sum()),
                "legacy_delivery_window": len(legacy_delivered),
                "legacy_delivery_old_approval": int(legacy_delivered.prediction_time.lt(row.prediction_time - pd.Timedelta(days=window)).sum()),
                "completed_valid_promise": int((complete & valid_promise).sum()),
                "pending_valid_promise": int((pending & valid_promise).sum()),
                "completed_promise_days_sum": float(promise_days[complete & valid_promise].sum()),
                "pending_promise_days_sum": float(promise_days[pending & valid_promise].sum()),
            }
            age = (row.prediction_time - h.prediction_time).dt.total_seconds() / 86400
            for state, mask in (("completed", complete), ("pending", pending)):
                for low, high in AGE_BINS[window]:
                    interval = age.ge(low) & (age.le(high) if high == window else age.lt(high))
                    values[f"{state}_age_{low}_{high}"] = int((mask & interval).sum())
            for name in columns:
                columns[name].append(float(values[name]))
        extra[f"audit_{basis}_key_known"] = known_values
        extra.update({f"audit_{basis}_{name}": values for name, values in columns.items()})
        quality[basis] = {"window_days": window, "known_query_rows": int(sum(known_values)),
                          "unknown_query_rows": len(query) - int(sum(known_values)),
                          "distinct_history_rows_used": len(used), "query_history_occurrences": occurrences}
    return pd.concat([query.copy(), pd.DataFrame(extra, index=query.index)], axis=1), quality


class HistoryRepresentativenessTests(unittest.TestCase):
    def test_all_counters_against_independent_oracle_and_input_shuffle(self):
        rng = np.random.default_rng(173)
        rows = []
        for i in range(90):
            approval = pd.Timestamp("2017-01-01") + pd.Timedelta(hours=int(rng.integers(0, 24*180)))
            delivery = None if i % 5 == 0 else approval + pd.Timedelta(hours=int(rng.integers(-8, 24*120)))
            promise = None if i % 7 == 0 else approval.normalize() + pd.Timedelta(days=int(rng.integers(-2, 60)))
            carrier = None if i % 4 == 0 else approval + pd.Timedelta(hours=int(rng.integers(-5, 24*60)))
            seller = None if i % 13 == 0 else "s1" if i % 2 else "s2"
            route = None if i % 11 == 0 else "SP->RJ" if i % 3 else "SP->SC"
            legacy = delivery is not None and delivery >= approval and promise is not None and promise >= approval.normalize() and i % 3 == 0
            rows.append((f"raw-{i}", approval, delivery, promise, carrier, seller, route, legacy))
        raw = history(rows)
        query = queries(pd.date_range("2017-01-01", periods=75, freq="3D"))
        query.loc[query.index % 5 == 0, "primary_seller_id"] = "s2"
        query.loc[query.index % 7 == 0, "state_route"] = "SP->SC"
        query.loc[query.index % 11 == 0, "primary_seller_id"] = None
        query.loc[query.index % 13 == 0, "state_route"] = None
        query.index = np.arange(len(query)) % 4
        actual, quality = build_representation(query, raw)
        expected, qexpected = independent_oracle(query, raw)
        assert_frame_equal(actual, expected, check_exact=True)
        self.assertEqual(quality["bases"], qexpected)
        shuffled, qshuffled = build_representation(query.sample(frac=1, random_state=49), raw.sample(frac=1, random_state=63))
        assert_frame_equal(actual.set_index("order_id").sort_index(), shuffled.set_index("order_id").sort_index())
        self.assertEqual(quality, qshuffled)

    def test_inclusive_window_and_exact_age_boundaries(self):
        now = pd.Timestamp("2017-08-01 12:00")
        ages = [0, 1, 7, 14, 30, 60, 90]
        rows = [(f"pending-{age}", now-pd.Timedelta(days=age), None, now, None, "s1", "SP->RJ", False) for age in ages]
        rows += [("too-old", now-pd.Timedelta(days=90, nanoseconds=1), None, now, None, "s1", "SP->RJ", False)]
        result, _ = build_representation(queries([now]), history(rows))
        row = result.iloc[0]
        self.assertEqual(row.audit_seller90_approved, 6)
        self.assertEqual(row.audit_route30_approved, 4)
        self.assertEqual([row[f"audit_seller90_pending_age_{a}_{b}"] for a,b in AGE_BINS[90]], [1, 1, 1, 1, 2])
        self.assertEqual([row[f"audit_route30_pending_age_{a}_{b}"] for a,b in AGE_BINS[30]], [1, 1, 2])

    def test_delivery_equality_is_pending_and_next_nanosecond_is_completed(self):
        now = pd.Timestamp("2017-02-01")
        raw = history([("equal", now-pd.Timedelta(days=3), now, now, now, "s1", "SP->RJ", True)])
        result, _ = build_representation(queries([now, now+pd.Timedelta(nanoseconds=1)]), raw)
        self.assertEqual(result.audit_seller90_pending.tolist(), [1, 0])
        self.assertEqual(result.audit_seller90_completed.tolist(), [0, 1])
        self.assertEqual(result.audit_seller90_delivery_equal_query.tolist(), [1, 0])
        self.assertEqual(result.audit_seller90_pending_no_carrier_event.tolist(), [1, 0])

    def test_deadline_midnight_missing_and_negative_promises(self):
        raw = history([
            ("valid", "2017-01-01", None, "2017-01-10 23:59", None, "s1", "SP->RJ", False),
            ("negative", "2017-01-01", None, "2016-12-31", None, "s1", "SP->RJ", False),
            ("missing", "2017-01-01", None, None, None, "s1", "SP->RJ", False),
        ])
        result, _ = build_representation(queries(["2017-01-10 23:59:59", "2017-01-11"]), raw)
        self.assertEqual(result.audit_seller90_pending_overdue.tolist(), [0, 1])
        self.assertEqual(result.audit_seller90_pending_active.tolist(), [1, 0])
        self.assertEqual(result.audit_seller90_pending_missing_promise.tolist(), [1, 1])
        self.assertEqual(result.audit_seller90_pending_negative_promise.tolist(), [1, 1])
        self.assertEqual(result.audit_seller90_pending_invalid_promise.tolist(), [2, 2])
        self.assertEqual(result.audit_seller90_pending_promise_days_sum.tolist(), [9, 9])

    def test_invalid_observed_delivery_separate_and_any_known_carrier_ends_proxy(self):
        raw = history([
            ("bad-delivery", "2017-01-02", "2017-01-01", "2017-01-10", None, "s1", "SP->RJ", False),
            ("bad-carrier", "2017-01-02", None, "2017-01-10", "2017-01-01", "s1", "SP->RJ", False),
        ])
        result, _ = build_representation(queries(["2017-01-03"]), raw)
        row = result.iloc[0]
        self.assertEqual(row.audit_seller90_approved, 2)
        self.assertEqual(row.audit_seller90_completed, 0)
        self.assertEqual(row.audit_seller90_invalid_delivery, 1)
        self.assertEqual(row.audit_seller90_pending, 1)
        self.assertEqual(row.audit_seller90_pending_no_carrier_event, 0)

    def test_legacy_window_bridge_distinguishes_old_approvals(self):
        raw = history([
            ("old-approval", "2017-01-01", "2017-05-01", "2017-01-20", None, "s1", "SP->RJ", True),
            ("recent-approval", "2017-04-01", "2017-05-01", "2017-04-20", None, "s1", "SP->RJ", True),
            ("excluded-complete", "2017-04-01", "2017-05-01", "2017-04-20", None, "s1", "SP->RJ", False),
        ])
        result, _ = build_representation(queries(["2017-05-15"]), raw)
        row = result.iloc[0]
        self.assertEqual(row.audit_seller90_legacy_delivery_window, 2)
        self.assertEqual(row.audit_seller90_completed_legacy, 1)
        self.assertEqual(row.audit_seller90_legacy_delivery_old_approval, 1)
        self.assertEqual(row.audit_seller90_completed_legacy_excluded, 1)
        self.assertEqual(row.audit_route30_legacy_delivery_old_approval, 2)

    def test_future_timestamps_status_and_query_outcomes_do_not_change_asof_state(self):
        now = pd.Timestamp("2017-02-01")
        raw = history([("future", "2017-01-01", "2017-03-01", "2017-01-20", "2017-02-10", "s1", "SP->RJ", True)])
        raw["order_status"] = "delivered"
        query = queries([now])
        query["delayed"], query["label_available_time"] = 1, pd.Timestamp("2099-01-01")
        before_raw, before_query = raw.copy(deep=True), query.copy(deep=True)
        expected, quality = build_representation(query, raw)
        assert_frame_equal(raw, before_raw)
        assert_frame_equal(query, before_query)
        raw["order_status"] = "canceled"
        raw["delivery_time"], raw["carrier_time"] = pd.Timestamp("2017-04-01"), pd.Timestamp("2017-03-01")
        actual, qactual = build_representation(query, raw)
        assert_frame_equal(actual, expected)
        self.assertEqual(quality, qactual)
        raw["legacy_eligible"] = False
        actual, _ = build_representation(query, raw)
        legacy_columns = [c for c in actual if "legacy" in c]
        assert_frame_equal(actual.drop(columns=legacy_columns), expected.drop(columns=legacy_columns))
        self.assertEqual(actual.audit_seller90_pending_legacy.iloc[0], 0)
        self.assertEqual(expected.audit_seller90_pending_legacy.iloc[0], 1)

    def test_unknown_keys_not_pooled_and_known_empty_is_zero(self):
        raw = history([("unknown", "2017-01-01", None, None, None, None, None, False)])
        query = queries(["2017-02-01", "2017-02-01"])
        query.loc[1, "primary_seller_id"] = None
        actual, quality = build_representation(query, raw)
        self.assertTrue(actual.loc[0, [f"audit_seller90_{c}" for c in counter_names(90)]].eq(0).all())
        self.assertTrue(actual.loc[1, [f"audit_seller90_{c}" for c in counter_names(90)]].isna().all())
        self.assertTrue(actual.loc[1, [f"audit_joint90_{c}" for c in counter_names(90)]].isna().all())
        self.assertEqual(actual.audit_route90_key_known.tolist(), [1, 1])
        self.assertEqual(quality["bases"]["seller90"]["unknown_query_rows"], 1)

    def test_shared_identity_uses_actual_approval_and_excludes_itself(self):
        raw = history([("self", "2017-01-01", None, "2017-01-10", None, "s1", "SP->RJ", False)])
        query = queries(["2017-01-01"])
        query["order_id"] = "self"
        actual, _ = build_representation(query, raw)
        self.assertEqual(actual.audit_seller90_approved.iloc[0], 0)
        query["prediction_time"] = pd.Timestamp("2017-01-02")
        with self.assertRaisesRegex(ValueError, "Shared order IDs"):
            build_representation(query, raw)

    def test_empty_history_and_empty_queries(self):
        raw = history([])
        actual, quality = build_representation(queries(["2017-01-01"]), raw)
        self.assertEqual(actual.audit_seller90_approved.iloc[0], 0)
        self.assertEqual(quality["history_rows"], 0)
        empty, quality = build_representation(queries([]), raw)
        self.assertEqual(len(empty), 0)
        self.assertEqual(quality["bases"]["route30"]["distinct_history_rows_used"], 0)

    def test_validation_rejects_bad_ids_clocks_flags_and_existing_output(self):
        raw = history([("raw", "2017-01-01", "2017-01-03", "2017-01-10", None, "s1", "SP->RJ", True)])
        query = queries(["2017-02-01"])
        mutations = [
            ("order_id", None, "IDs"),
            ("purchase_time", pd.Timestamp("2017-01-02"), "purchase"),
            ("prediction_time", pd.Timestamp("2018-05-01"), "precede May"),
            ("delivery_time", pd.Timestamp("2018-05-01"), "masked"),
            ("carrier_time", pd.Timestamp("2018-05-01"), "masked"),
            ("legacy_eligible", 1, "booleans"),
            ("delivery_time", pd.Timestamp("2016-12-31"), "Legacy eligibility"),
            ("promise_time", pd.NaT, "Legacy eligibility"),
        ]
        for column, value, message in mutations:
            with self.subTest(column=column, value=value):
                changed = raw.copy()
                changed[column] = value
                with self.assertRaisesRegex(ValueError, message):
                    build_representation(query, changed)
        with self.assertRaisesRegex(ValueError, "Missing History"):
            build_representation(query, raw.drop(columns="carrier_time"))
        changed = query.copy()
        changed["prediction_time"] = pd.to_datetime(changed.prediction_time, utc=True)
        with self.assertRaisesRegex(ValueError, "timezone-naive"):
            build_representation(changed, raw)
        actual, _ = build_representation(query, raw)
        with self.assertRaisesRegex(ValueError, "already exist"):
            build_representation(actual, raw)


if __name__ == "__main__":
    unittest.main()
