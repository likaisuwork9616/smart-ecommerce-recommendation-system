"""Score visitor histories on the frozen C1 graph using exact rational votes."""

from collections import defaultdict
from contextlib import closing
from fractions import Fraction
from functools import lru_cache
from heapq import nlargest
from pathlib import Path
import json
import sqlite3

from scripts.c1_demo_model import EDGES, POPULARITY, RELEASE, SUPPORT, read_counts
from scripts.evaluate_cart_recommendations import sha
from scripts.retailrocket_popularity import K


WEIGHTS = {"view": 1, "addtocart": 3, "transaction": 5}


@lru_cache(maxsize=8192)
def contribution(numerator, support):
    return Fraction(numerator, support)


class PersonalizationRanker:
    def __init__(self, support, popularity, neighbors, catalog):
        if support.keys() != popularity.keys() or not support.keys() <= catalog.first.keys():
            raise ValueError("Training support, popularity and catalog items disagree")
        self.support = support
        self.neighbors = neighbors
        self.catalog = catalog
        self.last_training_first_view = max((catalog.first[i] for i in support), default=-1)
        self.fallback = sorted(catalog.numeric, key=lambda i: (-popularity.get(i, 0), int(i)))
        self.tie_priority = {item: -index for index, item in enumerate(self.fallback)}

    @classmethod
    def from_frozen(cls, root, catalog):
        root = Path(root)
        release = json.loads((root / RELEASE).read_bytes())
        sources = {entry["path"]: entry for entry in release["sources"]}
        for name in (EDGES, SUPPORT, POPULARITY):
            if sha(root / name) != sources[name]["sha256"]:
                raise ValueError(f"Unexpected frozen C1 source: {name}")
        support = read_counts(root / SUPPORT, "support")
        popularity = read_counts(root / POPULARITY, "count")
        # Reuse one ID string per fitted item in both adjacency lists.
        ids = {item: item for item in support}
        neighbors = defaultdict(list)
        uri = (root / EDGES).resolve().as_uri() + "?mode=ro&immutable=1"
        with closing(sqlite3.connect(uri, uri=True)) as database:
            for left, right, count in database.execute("SELECT a, b, n FROM edges"):
                left, right = ids[left], ids[right]
                neighbors[left].append((right, count))
                neighbors[right].append((left, count))
        return cls(support, popularity, neighbors, catalog)

    def new_profile(self):
        return VisitorProfile(self)

    def new_ablation_profile(self):
        return AblationProfile(self)


class _Votes:
    def __init__(self, model):
        self.model = model
        self.scores = {}
        self.changed = set()
        self.top = ()
        self.all_training_eligible = False

    def copy(self):
        result = _Votes(self.model)
        result.scores = self.scores.copy()
        result.changed = self.changed.copy()
        result.top = self.top
        result.all_training_eligible = self.all_training_eligible
        return result

    def add(self, neighbors, support, weight):
        for other, count in neighbors:
            vote = contribution(count * weight, support)
            previous = self.scores.get(other)
            self.scores[other] = vote if previous is None else previous + vote
            self.changed.add(other)

    def ranking(self, when):
        catalog = self.model.catalog
        all_eligible = when > self.model.last_training_first_view
        if all_eligible and self.all_training_eligible:
            # Scores only increase. An unchanged item outside the previous top
            # ten cannot overtake it while the fitted catalog stays eligible.
            candidates = self.changed.union(self.top)
        else:
            candidates = (item for item in self.scores if catalog.contains(item, when))
        if self.changed or not (all_eligible and self.all_training_eligible):
            self.top = tuple(nlargest(K, candidates, key=lambda i: (self.scores[i], self.model.tie_priority[i])))
        self.changed.clear()
        self.all_training_eligible = all_eligible

        wanted = min(K, catalog.size(when))
        if len(self.top) == wanted:
            return self.top
        ranked = list(self.top)
        for item in self.model.fallback:
            if item not in self.top and catalog.contains(item, when):
                ranked.append(item)
                if len(ranked) == wanted:
                    break
        return tuple(ranked)


class VisitorProfile:
    """Caller supplies only events known by the query's observation time."""

    def __init__(self, model):
        self.model = model
        self.seen = {event: set() for event in WEIGHTS}
        self.views = _Votes(model)
        self.weighted = None

    @property
    def has_paired_action(self):
        return self.weighted is not None

    def observe(self, item, event):
        if not isinstance(item, str) or event not in WEIGHTS:
            raise ValueError("Expected a string item ID and a supported event type")
        if item in self.seen[event]:
            return
        self.seen[event].add(item)
        neighbors = self.model.neighbors.get(item)
        if not neighbors:
            return
        support = self.model.support[item]
        self._add_votes(event, neighbors, support)

    def _add_votes(self, event, neighbors, support):
        if event == "view":
            self.views.add(neighbors, support, WEIGHTS[event])
        elif self.weighted is None:
            self.weighted = self.views.copy()
        if self.weighted is not None:
            self.weighted.add(neighbors, support, WEIGHTS[event])

    def rank(self, query_ms):
        views = self.views.ranking(query_ms)
        weighted = self.weighted.ranking(query_ms) if self.weighted is not None else views
        return views, weighted


class AblationProfile(VisitorProfile):
    """Compare views, views+cart, views+purchase and all three actions in order."""

    def __init__(self, model):
        super().__init__(model)
        self.single_action = {}

    @property
    def has_paired_action(self):
        return bool(self.single_action)

    @property
    def has_paired_cart(self):
        return "addtocart" in self.single_action

    @property
    def has_paired_purchase(self):
        return "transaction" in self.single_action

    def _add_votes(self, event, neighbors, support):
        weight = WEIGHTS[event]
        if event == "view":
            self.views.add(neighbors, support, weight)
            for votes in self.single_action.values():
                votes.add(neighbors, support, weight)
        else:
            if event not in self.single_action:
                if self.single_action:
                    # Until the second supported action, the combined arm is
                    # identical to the first single-action arm.
                    first_action = next(iter(self.single_action.values()))
                    self.weighted = first_action.copy()
                self.single_action[event] = self.views.copy()
            self.single_action[event].add(neighbors, support, weight)
        if self.weighted is not None:
            self.weighted.add(neighbors, support, weight)

    def rank(self, query_ms):
        views = self.views.ranking(query_ms)
        singles = {event: votes.ranking(query_ms) for event, votes in self.single_action.items()}
        combined = (self.weighted.ranking(query_ms) if self.weighted is not None
                    else next(iter(singles.values()), views))
        return views, singles.get("addtocart", views), singles.get("transaction", views), combined
