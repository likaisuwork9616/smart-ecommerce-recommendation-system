"""Invocation-local wall observers over frozen source/store/verifier bytecode.

No module monkeypatch, source caching, new descriptor read or SQL change.
Private events retain paths. Public summaries expose aggregate purposes only.
"""
from contextlib import contextmanager, ExitStack
from pathlib import Path
import sys
from time import perf_counter, perf_counter_ns

from scripts import retailrocket_session_knn_checkpoint_v2 as cp
from scripts import retailrocket_session_knn_pair_v4 as pair
from scripts import run_retailrocket_session_knn_v2 as io
from scripts import run_retailrocket_session_knn_overlap_v22 as entry
from scripts.retailrocket_session_knn_detailed_cost_v6 import DetailedTimedStore
from scripts.retailrocket_session_knn_diagnostics_v20 import _clone


class Observation:
    def __init__(self, clock=perf_counter_ns):
        self.clock, self.events, self.stack = clock, [], []

    @contextmanager
    def span(self, phase, **metadata):
        event = dict(id=len(self.events), parent=self.stack[-1] if self.stack else None,
                     phase=phase, metadata=metadata, start_ns=self.clock(), end_ns=None,
                     completed=False, error_type=None)
        self.events.append(event)
        self.stack.append(event['id'])
        try:
            yield event
        except BaseException as error:
            event['error_type'] = type(error).__name__
            raise
        else:
            event['completed'] = True
        finally:
            event['end_ns'] = self.clock()
            if self.stack.pop() != event['id']:
                raise ValueError('Observation scopes were not closed in order')

    def call(self, phase, function, *args, **kwargs):
        with self.span(phase):
            return function(*args, **kwargs)

    def wrapped(self, phase, function):
        def observed(*args, **kwargs):
            return self.call(phase, function, *args, **kwargs)
        return observed

    def descriptor(self, function, phase, identity, *args, **kwargs):
        with self.span(phase, identity=identity) as event:
            value = function(*args, **kwargs)
            event['metadata']['descriptor'] = dict(value)
            return value

    def verify_bindings(self, records, watch=lambda: None):
        def describe(path, watch=lambda: None):
            return self.descriptor(io.describe, 'closure.descriptor', str(path), path, watch)
        original = _clone(io.verify_bindings, describe=describe)
        return self.call('closure.verify_bindings', original, records, watch)

    def verify_sources(self, root, records):
        def descriptor(source_root, name):
            return self.descriptor(cp.descriptor, 'binding.descriptor',
                                   str(Path(source_root)/name), source_root, name)
        original = _clone(cp.verify_sources, descriptor=descriptor)
        return self.call('binding.verify_sources', original, root, records)

    def publisher(self, callback, *args, **kwargs):
        # Final publication is inside this timer when performed by callback.
        # Persist this observation only after return/exception; its own emission
        # is deliberately outside the observed publisher to avoid recursion.
        return self.call('publisher.total', callback, *args, **kwargs)

    def summary(self):
        if self.stack:
            raise ValueError('An observation scope is still active')
        return summarize_events(self.events)


def summarize_events(events):
    children = {None: []}
    for index, event in enumerate(events):
        parent = event['parent']
        if (event['id'] != index or type(event['start_ns']) is not int
                or type(event['end_ns']) is not int or event['start_ns'] < 0
                or event['end_ns'] < event['start_ns']
                or parent is not None and (type(parent) is not int or not 0 <= parent < index)
                or type(event['completed']) is not bool
                or event['completed'] != (event['error_type'] is None)):
            raise ValueError('Incomplete, nonmonotonic or invalid observation event')
        children.setdefault(parent, []).append(index)
        children.setdefault(index, [])
        if parent is not None:
            owner = events[parent]
            if not owner['start_ns'] <= event['start_ns'] <= event['end_ns'] <= owner['end_ns']:
                raise ValueError('Child observation exceeds its original enclosing span')
    for siblings in children.values():
        for left, right in zip(siblings, siblings[1:]):
            if events[left]['end_ns'] > events[right]['start_ns']:
                raise ValueError('Sibling observations overlap or scopes cross')
    phases, unique = {}, set()
    logical_bytes = completed_descriptors = attempted_descriptors = 0
    for event in events:
        duration = event['end_ns']-event['start_ns']
        exclusive = duration-sum(events[i]['end_ns']-events[i]['start_ns'] for i in children[event['id']])
        if exclusive < 0:
            raise ValueError('Observed child time exceeds its parent')
        part = phases.setdefault(event['phase'], dict(calls=0, completed=0, failed=0,
                                  inclusive_wall_ns=0, exclusive_wall_ns=0))
        part['calls'] += 1
        part['completed'] += int(event['completed'])
        part['failed'] += int(not event['completed'])
        part['inclusive_wall_ns'] += duration
        part['exclusive_wall_ns'] += exclusive
        if event['phase'] in ('closure.descriptor', 'binding.descriptor'):
            attempted_descriptors += 1
            value = event['metadata'].get('descriptor')
            if event['completed']:
                if (not isinstance(value, dict) or type(value.get('bytes')) is not int or value['bytes'] < 0
                        or not isinstance(value.get('sha256'), str) or len(value['sha256']) != 64):
                    raise ValueError('Completed descriptor has no valid original byte coverage')
                completed_descriptors += 1
                logical_bytes += value['bytes']
                unique.add((event['metadata']['identity'], value['bytes'], value['sha256']))
            elif value is not None:
                raise ValueError('A failed descriptor cannot claim completed byte coverage')
    roots = sum(events[i]['end_ns']-events[i]['start_ns'] for i in children[None])
    if sum(v['exclusive_wall_ns'] for v in phases.values()) != roots:
        raise ValueError('The event tree does not conserve its root wall observations')
    return {'events': len(events), 'phases': phases, 'root_wall_ns': roots,
            'source_descriptors': {'attempted_calls': attempted_descriptors,
                'completed_calls': completed_descriptors, 'failed_calls': attempted_descriptors-completed_descriptors,
                'completed_logical_bytes': logical_bytes, 'unique_completed_descriptors': len(unique),
                'unique_completed_logical_bytes': sum(v[1] for v in unique),
                'failed_operation_byte_coverage': None},
            'interpretation': 'Inclusive phases are nested and cannot be added. Exclusive phases conserve roots. '
                'Descriptor bytes describe successful logical coverage, including a descriptor that later fails an expected-hash comparison. '
                'Failure before descriptor return has unknown byte coverage. Repeated reads are retained; unique descriptors use lexical path, '
                'size and content hash without an extra stat/resolve. No physical I/O, CPU wait or speedup is inferred.'}


class ObservedStore(DetailedTimedStore):
    def __init__(self, *args, observer, **kwargs):
        self.source_observer = observer
        super().__init__(*args, **kwargs)

    @classmethod
    def create(cls, *args, observer, **kwargs):
        with observer.span('checkpoint.create'):
            return super().create(*args, observer=observer, **kwargs)

    @classmethod
    def open(cls, *args, observer, **kwargs):
        with observer.span('checkpoint.open'):
            return super().open(*args, observer=observer, **kwargs)

    def _check_sources(self, force=False):
        with self.source_observer.span('checkpoint.check_sources', force=force,
                cached_before=self._sources_checked, external=self.external_source_verifier is not None):
            original = _clone(cp.CheckpointStore._check_sources, verify_sources=self.source_observer.verify_sources)
            return original(self, force=force)

    @contextmanager
    def writer(self, role='worker'):
        with self.source_observer.span('checkpoint.writer_lifetime'):
            with ExitStack() as stack:
                with self.source_observer.span('checkpoint.writer_acquire'):
                    value = stack.enter_context(super().writer(role))
                yield value


class _ModuleView:
    def __init__(self, module, **overrides):
        self.module, self.overrides = module, overrides

    def __getattr__(self, name):
        return self.overrides[name] if name in self.overrides else getattr(self.module, name)


class _SetupClock:
    def __init__(self, observer):
        self.observer, self.samples, self.scope = observer, [], None

    def __call__(self):
        if not self.samples:
            self.scope = self.observer.span('verifier.setup_envelope')
            self.scope.__enter__()
        value = perf_counter()
        self.samples.append(value)
        if len(self.samples) == 3:
            self.close((None, None, None))
        return value

    def close(self, exception):
        if self.scope is not None:
            scope, self.scope = self.scope, None
            scope.__exit__(*exception)


def make_verifier(observer):
    core = _ModuleView(pair.core, load_context=observer.wrapped('context.load_context', pair.core.load_context),
                       seal_consistent=observer.wrapped('verifier.seal_consistent', pair.core.seal_consistent))
    sql = _ModuleView(pair.sql, prepare_catalog=observer.wrapped('context.prepare_catalog', pair.sql.prepare_catalog))
    def verify(*args, **kwargs):
        with observer.span('verifier.total') as event:
            clock = _SetupClock(observer)
            original = _clone(pair.verify_selected, core=core, sql=sql, perf_counter=clock)
            try:
                result = original(*args, **kwargs)
            finally:
                clock.close(sys.exc_info())
            if len(clock.samples) < 3 or result['setup_seconds'] != clock.samples[2]-clock.samples[0]:
                raise ValueError('Original verifier setup clock boundaries changed')
            event['metadata'].update(original_setup_seconds=result['setup_seconds'],
                                     original_clock_samples=len(clock.samples))
            return result
    return verify


class StoreFactory:
    def __init__(self, observer):
        self.observer = observer

    def create(self, *args, **kwargs):
        return ObservedStore.create(*args, observer=self.observer, **kwargs)

    def open(self, *args, **kwargs):
        return ObservedStore.open(*args, observer=self.observer, **kwargs)


def run_fixed48(folder, request, label, inputs, *, observer=None, source_root=io.ROOT, watch=lambda: None):
    _, config, _, _, _, probes, ordinals, _ = inputs
    if len(probes) != 48 or len(ordinals) != 48 or config['fixed_validation']['queries'] != 48:
        raise ValueError('Only the original fixed48 run shape is accepted')
    overrides = dict(ROOT=Path(source_root), make_verifier=lambda mode: pair.verify_selected)
    if observer is not None:
        overrides.update(DetailedTimedStore=StoreFactory(observer),
            make_verifier=lambda mode: make_verifier(observer),
            ledger_proof=observer.wrapped('run.ledger_proof', entry.ledger_proof),
            write=observer.wrapped('run.output_write', entry.write))
    original = _clone(entry._run, **overrides)
    args = folder, request, label, 'baseline', inputs, watch
    if observer is None:
        return original(*args)
    return observer.call('run.total', original, *args)
