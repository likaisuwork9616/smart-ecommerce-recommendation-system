"""Refit homepage popularity and the binary-session C1 model strictly before July 2015."""
from itertools import groupby
from operator import itemgetter

from scripts.audit_retailrocket_cart_support import GAP_MS
from scripts.evaluate_july_home_first_view_pair import ranking_digest
from scripts.export_home_popularity import ranked_counts
from scripts.retailrocket_cooccurrence import Basket, Ranker, fit
from scripts.retailrocket_popularity import Catalog


JULY_CUTOFF_MS = 1435708800000


def training_baskets(db, window):
    views = db.execute("""
        SELECT v, t, i FROM qualified
        WHERE role='train' AND e='view' AND t>=? AND t<? ORDER BY v, t
    """, window)
    for visitor, events in groupby(views, key=itemgetter(0)):
        previous = None
        for timestamp, simultaneous in groupby(events, key=itemgetter(1)):
            if previous is None or timestamp - previous > GAP_MS:
                session_start, index = timestamp, 0
            index += 1
            items = tuple(sorted({row[2] for row in simultaneous}, key=int))
            yield Basket(visitor, session_start, timestamp, "train", index, items)
            previous = timestamp


class HomepageC1(Ranker):
    def recommend(self, seed):
        """Adapt the frozen C1 ranker to the homepage's single-seed recommendation format."""
        support = self.model.support[seed]
        ranking = self.rank(self.model.audit["end_ms"], [seed])
        # With one seed C1's exact score is shared-session count / seed support.
        recommendations = [
            {"item_id": item, "source": "cooccurrence", "co_sessions": numerator * support // denominator}
            for item, (numerator, denominator) in zip(ranking["ids"], ranking["scores"], strict=True)
            if numerator
        ]
        return {"recommendations": recommendations}


def fit_model(db, window):
    """Fit all training pairs before any July visitor or target is considered."""
    start, end = window
    if not start < end <= JULY_CUTOFF_MS:
        raise ValueError("July homepage fitting requires a window ending on or before July 1")
    counts, first_seen = {}, {}
    for item, count, first in db.execute("""
        SELECT i, COUNT(*), MIN(t) FROM qualified
        WHERE role='train' AND e='view' AND t>=? AND t<? GROUP BY i
    """, window):
        counts[item] = count
        first_seen[item] = first
    popular = ranked_counts(counts)
    fitted = fit(training_baskets(db, window), start, end, counts)
    # All positive C1 and popularity scores are on fitted items. Warm-up-only
    # items stay eligible for the separate last-view slot when no pair exists.
    model = HomepageC1(fitted, counts, Catalog(first_seen.items()))
    training = {
        "qualified_view_events": sum(counts.values()),
        "baseline_rank_item_counts_sha256": ranking_digest(popular),
        "c1_fit": {**fitted.audit, "fit_id": fitted.fit_id},
    }
    return [item for item, _ in popular], model, training
