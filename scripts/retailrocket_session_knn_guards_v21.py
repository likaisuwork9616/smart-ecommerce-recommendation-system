"""Invocation-local observers for the original direct append guards.

Keep V20/V6/V2 bytecode, filesystem call counts, short circuits and exceptions.
Nested checkpoint operations stay bound to the original store, not this view.
"""
import os

from scripts import retailrocket_session_knn_diagnostics_v20 as prior
from scripts import retailrocket_session_knn_checkpoint_v2 as checkpoint
from scripts.retailrocket_session_knn_detailed_cost_v6 import DetailedTimedStore

make_verifier = prior.make_verifier
PURPOSES = {'acceptance.json': 'acceptance', 'candidate.json': 'candidate',
            'stages/global.json': 'global'}


def _observe(events, operation, **labels):
    event = dict(labels, completed=False)
    events.append(event)
    start = prior._stamp()
    try:
        result = operation()
        event['completed'] = True
        return result
    finally:
        event['total'] = prior._span(start, prior._stamp())


class _ObservedPath:
    def __init__(self, path, root, event):
        self.path, self.root, self.event = path, root, event

    def __truediv__(self, name):
        return _ObservedPath(self.path/name, self.root, self.event)

    def __fspath__(self):
        return os.fspath(self.path)

    def __getattr__(self, name):
        return getattr(self.path, name)

    def exists(self):
        purpose = PURPOSES[self.path.relative_to(self.root).as_posix()]
        result = _observe(self.event['exists'], self.path.exists, purpose=purpose)
        self.event['exists'][-1]['result'] = result
        return result


class _StoreView:
    def __init__(self, store, event):
        object.__setattr__(self, '_store', store)
        object.__setattr__(self, '_event', event)

    def __getattr__(self, name):
        if name == 'folder':
            return _ObservedPath(self._store.folder, self._store.folder, self._event)
        return getattr(self._store, name)

    def __setattr__(self, name, value):
        setattr(self._store, name, value)

    def _require_writer(self):
        return _observe(self._event['writer_checks'],
                        lambda: checkpoint.CheckpointStore._require_writer(self))

    def _key(self, key):
        return _observe(self._event['identity'], lambda: self._store._key(key))


class DiagnosticTimedStore(prior.DiagnosticTimedStore):
    def append_verified(self, ordinal, key, payload):
        event = {'subset_ordinal': ordinal, 'completed': False,
                 'exists': [], 'identity': [], 'writer_checks': []}
        before = len(self.append_diagnostics)

        def clone_append(function, **overrides):
            if function is not DetailedTimedStore.append_verified:
                raise ValueError('Expected the unchanged V6 append bytecode')
            original = prior._clone(function, **overrides)
            def observed(store, *args, **kwargs):
                return original(_StoreView(store, event), *args, **kwargs)
            return observed

        original = prior._clone(prior.DiagnosticTimedStore.append_verified, _clone=clone_append)
        try:
            result = original(self, ordinal, key, payload)
            event['completed'] = True
            return result
        finally:
            if len(self.append_diagnostics) == before+1:
                self.append_diagnostics[-1]['guard_detail'] = event


def diagnostic_rows(measured, observations, diagnostics):
    rows = prior.diagnostic_rows(measured, observations, diagnostics)
    for index, (row, raw) in enumerate(zip(rows, diagnostics['append'], strict=True)):
        event = raw['guard_detail']
        if (event['subset_ordinal'] != index or event['completed'] is not True
                or [e['purpose'] for e in event['exists']] != ['acceptance', 'candidate', 'global']
                or any(e['completed'] is not True or e['result'] is not False for e in event['exists'])
                or len(event['identity']) != 1 or len(event['writer_checks']) != 1
                or any(e['completed'] is not True for e in event['identity']+event['writer_checks'])):
            raise ValueError('Original direct guard count, order, result or identity validation changed')
        exists = {e['purpose']: prior._raw_span(e['total']) for e in event['exists']}
        identity = prior._raw_span(event['identity'][0]['total'])
        writer = prior._raw_span(event['writer_checks'][0]['total'])
        guards = {'candidate_exists': exists['candidate'], 'global_exists': exists['global'],
                  'identity_format': identity}
        guards['order_reconstruction_dispatch_other'] = prior._residual(
            row['append_phases']['guards_and_key'], list(guards.values()))
        row['guard_check_parts'] = guards
        row['writer_check_parts'] = {
            'acceptance_exists': exists['acceptance'],
            'writer_state_dispatch_other': prior._residual(writer, [exists['acceptance']]),
            'context_and_observer_other': prior._residual(
                row['append_budget_check_parts']['writer_context_and_observer_other'], [writer])}
        row['guard_counts'] = {'acceptance_exists': 1, 'candidate_exists': 1, 'global_exists': 1,
                               'identity_format': 1, 'writer_check': 1}
    return rows


def summarize_diagnostics(measured, observations, diagnostics):
    rows = diagnostic_rows(measured, observations, diagnostics)
    result = prior.summarize_diagnostics(measured, observations, diagnostics)
    result['kind'] = 'v21_observed_original_append_guards_and_overlap_diagnostics'
    for group in ('guard_check_parts', 'writer_check_parts'):
        result[group] = {part: {clock: prior._stats(row[group][part][clock] for row in rows)
                        for clock in rows[0][group][part]} for part in rows[0][group]}
    result['guard_counts'] = {key: sum(row['guard_counts'][key] for row in rows)
                              for key in rows[0]['guard_counts']}
    result['interpretation'] += (' Direct append observes only the three original exists calls and the original '
        'key format validation. Writer includes acceptance; guard residual retains ordinal/key ordering, '
        'first reconstruction checks and observer dispatch. Nested checkpoint calls are unmodified. '
        'No exists call is added, cached or suppressed. No residual is pure identity validation or I/O wait.')
    return result
