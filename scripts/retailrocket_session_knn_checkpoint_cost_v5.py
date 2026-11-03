"""Observe the frozen checkpoint's actual budget.json publication wall time.

BudgetTimedStore delegates all checks, writes, commits, locks and failures to
V4 TimedStore. The exclusive event context avoids attributing the same forced
budget write to both an append and a nested commit. Events are process-local.
"""
from collections import Counter
from contextlib import ExitStack, contextmanager
import math
from time import perf_counter

from scripts.retailrocket_session_knn_pair_v4 import TimedStore


class BudgetTimedStore(TimedStore):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.budget_events = []
        self._budget_context = ('other', None, None)

    @property
    def budget_seconds(self):
        """All observed budget.json _atomic calls, across every context."""
        return math.fsum(event['seconds'] for event in self.budget_events)

    @contextmanager
    def _in_budget_context(self, name, ordinal=None, stage=None):
        previous = self._budget_context
        self._budget_context = (name, ordinal, stage)
        try:
            yield
        finally:
            self._budget_context = previous

    def _atomic(self, name, value, replace=False):
        if name != 'budget.json':
            return super()._atomic(name, value, replace=replace)
        context, ordinal, stage = self._budget_context
        if not replace:
            context = 'store_setup'
        started = perf_counter()
        completed = False
        try:
            result = super()._atomic(name, value, replace=replace)
            completed = True
            return result
        finally:
            seconds = perf_counter()-started
            self.budget_events.append({'context': context, 'subset_ordinal': ordinal, 'stage': stage,
                                       'completed': completed, 'seconds': seconds})

    @contextmanager
    def writer(self, role='worker'):
        # Entry and __exit__ remain the original context manager's operations.
        with self._in_budget_context('writer_teardown'), ExitStack() as stack:
            with self._in_budget_context('writer_setup'):
                active = stack.enter_context(super().writer(role))
            with self._in_budget_context('writer_body'):
                yield active

    def append_verified(self, ordinal, key, payload):
        with self._in_budget_context('query_append', ordinal=ordinal):
            return super().append_verified(ordinal, key, payload)

    def flush_chunk(self):
        # Even an empty flush can force budget persistence. TimedStore records
        # a chunk event only for a nonempty pending chunk.
        name = 'chunk_commit' if self._pending_count else 'empty_flush'
        with self._in_budget_context(name, ordinal=self._budget_context[1]):
            return super().flush_chunk()

    def seal_stage(self, name, receipt, artifacts=()):
        with self._in_budget_context('stage', stage=name):
            return super().seal_stage(name, receipt, artifacts)

    def budget_cost_summary(self, measured):
        """Split a fresh bounded V4 measurement; its original fields stay intact.

        The phase's query rows use subset ordinals. Only budget writes directly
        inside that row's append are split from append_without_commit_seconds.
        Nested commit budget writes already belong to V4 chunk commit time.
        No event is removed from total cost or used to claim a full-run bound.
        """
        rows = measured['queries']
        if (measured['committed_prefix_rows'] != 0 or measured['verified_subset_queries'] != len(rows)
                or not 1 <= len(rows) <= 64 or [r['subset_ordinal'] for r in rows] != list(range(len(rows)))):
            raise ValueError('A fresh contiguous bounded V4 measurement is required')
        if (measured['chunk_commits'] != self.commit_events or any(not c['completed'] for c in self.commit_events)
                or sum(c['records'] for c in self.commit_events) != len(rows)):
            raise ValueError('V4 commit events do not match this observation')
        if any(not e['completed'] for e in self.budget_events):
            raise ValueError('A failed budget write cannot certify a completed measurement')
        by_context = {}
        append_cost, append_writes = Counter(), Counter()
        for event in self.budget_events:
            context, ordinal = event['context'], event['subset_ordinal']
            if ordinal is not None and (type(ordinal) is not int or not 0 <= ordinal < len(rows)):
                raise ValueError('Budget event outside measured subset')
            bucket = by_context.setdefault(context, {'writes': 0, 'seconds': 0.0})
            bucket['writes'] += 1
            bucket['seconds'] += event['seconds']
            if context == 'query_append':
                append_cost[ordinal] += event['seconds']
                append_writes[ordinal] += 1
        breakdown = []
        for row in rows:
            ordinal = row['subset_ordinal']
            original = row['append_without_commit_seconds']
            verification = row['verification_seconds']
            for duration in (original, verification, row['chunk_commit_seconds']):
                if type(duration) not in (float, int) or not math.isfinite(duration) or duration < 0:
                    raise ValueError('Invalid V4 timing')
            cost = append_cost[ordinal]
            if cost > original:
                raise ValueError('Direct budget time exceeds its enclosing append measurement')
            breakdown.append({'subset_ordinal': ordinal, 'verification_seconds': verification,
                              'append_without_commit_seconds': original,
                              'query_append_budget_writes': append_writes[ordinal],
                              'query_append_budget_seconds': cost,
                              'append_without_commit_or_budget_seconds': original-cost,
                              'chunk_commit_seconds': row['chunk_commit_seconds']})
        return {'kind': 'observed_budget_json_atomic_publication_cost', 'rows': breakdown,
                'writes': len(self.budget_events), 'budget_seconds': self.budget_seconds,
                'by_context': by_context, 'query_append_budget_seconds': math.fsum(append_cost.values()),
                'interpretation': 'Only directly nested budget publication is split from per-row append. '
                                  'Commit, stage and setup budget writes remain within their original enclosing costs. '
                                  'All events and all raw row timings are retained.'}
