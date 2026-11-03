"""Bounded append diagnostics; preserve the frozen V2 checkpoint protocol.

Only append_verified is spelled out to place timers between the original
operations. Budget/commit publication, locking, recovery and ranking delegate
to V5/V4/V2. Differential tests guard bytes, fault boundaries and deadlines.
"""
import math
import uuid
from time import perf_counter

from scripts.retailrocket_session_knn_checkpoint_cost_v5 import BudgetTimedStore
from scripts.retailrocket_session_knn_checkpoint_v2 import IntegrityError, _inside, encoded


class DetailedTimedStore(BudgetTimedStore):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.append_events = []

    def append_verified(self, ordinal, key, payload):
        event = {'subset_ordinal': ordinal, 'completed': False, 'parts_seconds': {}}
        parts = event['parts_seconds']
        started = phase = perf_counter()

        def mark(name):
            nonlocal phase
            now = perf_counter()
            parts[name] = now-phase
            phase = now

        try:
            with self._in_budget_context('query_append', ordinal=ordinal):
                self._require_writer(); self.check_budget()
                mark('budget_check')
                if 'reconstruction' in self.run['required_stages'] and not self._reconstruction_checked:
                    if self.get_stage('reconstruction') is None:
                        raise IntegrityError('Independent reconstruction must be sealed before queries')
                    self._reconstruction_checked = True
                if (self.folder/'candidate.json').exists() or (self.folder/'stages/global.json').exists():
                    raise IntegrityError('Query stage already sealed')
                expected = self._summary['records'] + self._pending_count
                normalized = self._key(key)
                prior = self._last_pending_key if self._pending_count else self._summary['last_key']
                if type(ordinal) is not int or ordinal != expected or prior is not None and normalized <= tuple(prior):
                    raise IntegrityError('Noncontiguous ordinal or unordered query')
                mark('guards_and_key')
                data = encoded({'ordinal': ordinal, 'key': key, 'payload': payload})
                event['frame_bytes'] = len(data)
                mark('frame_encode')
                if self._pending is None:
                    self._pending_name = 'payloads/' + uuid.uuid4().hex + '.jsonl'
                    self._pending = _inside(self.folder, self._pending_name).open('xb', buffering=0)
                    self._pending_first = list(key)
                    self._chunk_started = self.clock.monotonic()
                mark('payload_open')
                split = len(data)//2
                self._pending.write(data[:split]); self.fault('payload_half_written')
                self._pending.write(data[split:])
                mark('payload_write')
                self._pending_count += 1; self._last_pending_key = list(key)
                due = (self._pending_count >= self.run['max_chunk_rows']
                       or self.clock.monotonic()-self._chunk_started >= self.run['max_chunk_seconds'])
                mark('pending_and_trigger')
                if due:
                    self.flush_chunk()
                mark('nested_flush')
                event['completed'] = True
        finally:
            event['seconds'] = perf_counter()-started
            event['unpartitioned_seconds'] = event['seconds']-math.fsum(parts.values())
            self.append_events.append(event)

    def detailed_cost_summary(self, measured):
        """Conserve the enclosing V4 append cost, including observer overhead."""
        budget = self.budget_cost_summary(measured)
        events = self.append_events
        if (len(events) != len(measured['queries']) or any(not e['completed'] for e in events)
                or [e['subset_ordinal'] for e in events] != list(range(len(events)))):
            raise ValueError('Complete contiguous fresh append events are required')
        result = []
        for row, split, event in zip(measured['queries'], budget['rows'], events):
            parts = event['parts_seconds']
            if (set(parts) != {'budget_check', 'guards_and_key', 'frame_encode', 'payload_open',
                              'payload_write', 'pending_and_trigger', 'nested_flush'}
                    or any(type(v) not in (int, float) or not math.isfinite(v) or v < 0
                           for v in [*parts.values(), event['seconds'], event['unpartitioned_seconds']])):
                raise ValueError('Invalid append partition')
            # Nested flush is reported by the original TimedStore too. Remove
            # its one inclusive event, never the budget write a second time.
            budget_seconds = split['query_append_budget_seconds']
            commit_seconds = row['chunk_commit_seconds']
            outer = row['checkpoint_append_seconds']-event['seconds']
            budget_other = parts['budget_check']-budget_seconds
            flush_other = parts['nested_flush']-commit_seconds
            if min(outer, budget_other, flush_other) < 0:
                raise ValueError('Nested timing exceeds its enclosing append')
            exclusive = {name: parts[name] for name in ('guards_and_key', 'frame_encode', 'payload_open',
                                                       'payload_write', 'pending_and_trigger')}
            exclusive.update(budget_publication=budget_seconds, budget_check_other=budget_other,
                             chunk_commit=commit_seconds, flush_dispatch_other=flush_other,
                             observer_and_outer_other=event['unpartitioned_seconds']+outer)
            if not math.isclose(math.fsum(exclusive.values()), row['checkpoint_append_seconds'],
                                rel_tol=1e-10, abs_tol=1e-12):
                raise ValueError('Append accounting does not conserve the original measurement')
            if row['rank_seconds'] > row['verification_seconds']:
                raise ValueError('Rank cost exceeds verification')
            result.append({'subset_ordinal': row['subset_ordinal'], 'frame_bytes': event['frame_bytes'],
                           'append_exclusive_seconds': exclusive,
                           'verification_other_seconds': row['verification_seconds']-row['rank_seconds']})
        return {'kind': 'v6_detailed_append_observation', 'rows': result, 'budget': budget,
                'interpretation': 'All append parts sum to the same raw V4 enclosing timer. '
                                  'Rank is nested in verification; commit includes its own budget I/O. '
                                  'Timers and fault hooks add overhead; no causal speedup is claimed.'}
