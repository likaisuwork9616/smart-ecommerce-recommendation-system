"""Source-anchored late typed checks inside invocation-local original C1 bytecode."""
from copy import deepcopy
from time import perf_counter_ns as _PASSIVE_CLOCK
from types import SimpleNamespace

from scripts import retailrocket_session_knn_reuse_v27 as c1
from scripts import retailrocket_session_knn_snapshot_adapter_v30 as s1
from scripts import retailrocket_session_knn_typed_v39 as typed
from scripts.retailrocket_session_knn_diagnostics_v20 import _clone


POLICY = 'C1-S1-cold-late-typed-source-anchor-v1'
REFERENCE_SCHEME = typed.SCHEME
EXTRA_FIELDS = ('typed_reference_policy', 'typed_reference_scheme', 'typed_reference')
AUTHORITY_FIELDS = {'raw_sources', 'canonical', 'reference_statistics', 'reference_scheme', 'policy'}
CHECK_FIELDS = {'root', 'start_ns', 'end_ns', 'completed', 'equal', 'statistics'}
REFERENCE_STAT_FIELDS = {'nodes', 'maps', 'sequences', 'scalars', 'max_depth', 'encoded_depth'}
COMPARISON_STAT_FIELDS = {'nodes', 'maps', 'sequences', 'scalars', 'mapping_keys_checked',
                         'mapping_lookups', 'sequence_items', 'max_depth', 'ordinary_mismatches'}


def require_policy(request):
    s1.require_scheme(request)
    metadata = request.get('metadata', {})
    if (type(metadata.get('typed_reference_policy')) is not str
            or metadata['typed_reference_policy'] != POLICY
            or type(metadata.get('typed_reference_scheme')) is not str
            or metadata['typed_reference_scheme'] != REFERENCE_SCHEME):
        raise ValueError('Exact late typed source-reference policy and scheme required')


def context_contract(request, binding):
    require_policy(request)
    return s1.context_contract(request, binding)


def _bound_fields(value):
    if (value.get('typed_reference_policy') != POLICY
            or type(value.get('typed_reference_policy')) is not str
            or value.get('typed_reference_scheme') != REFERENCE_SCHEME
            or type(value.get('typed_reference_scheme')) is not str
            or not set(EXTRA_FIELDS).issubset(value)):
        raise ValueError('Mixed or missing late typed policy evidence')


def _authority(authority):
    if (type(authority) is not dict or set(authority) != AUTHORITY_FIELDS
            or authority['reference_scheme'] != REFERENCE_SCHEME or authority['policy'] != POLICY
            or any(set(authority[name]) != {'config', 'model'}
                   for name in ('raw_sources', 'canonical', 'reference_statistics'))):
        raise ValueError('Complete source authority for both typed roots required')
    for root in ('config', 'model'):
        raw=authority['raw_sources'][root];canonical=authority['canonical'][root]
        if (type(raw) is not dict or set(raw)!={'path','bytes','sha256'} or type(raw['path']) is not str
                or not raw['path'] or type(canonical) is not dict or set(canonical)!={'scheme','bytes','sha256'}
                or type(canonical['scheme']) is not str or canonical['scheme']!=REFERENCE_SCHEME):
            raise ValueError('Exact raw/canonical source authority descriptors required')
        for descriptor in (raw,canonical):
            if (type(descriptor['bytes']) is not int or descriptor['bytes']<0
                    or type(descriptor['sha256']) is not str or len(descriptor['sha256'])!=64
                    or any(c not in '0123456789abcdef' for c in descriptor['sha256'])):
                raise ValueError('Exact source-byte lengths and hashes required')
        statistics=authority['reference_statistics'][root]
        if (type(statistics) is not dict or set(statistics)!=REFERENCE_STAT_FIELDS
                or any(type(value) is not int or value<0 for value in statistics.values())):
            raise ValueError('Exact immutable-reference statistics required')


def _interval(value):
    return (type(value.get('start_ns')) is int and type(value.get('end_ns')) is int
            and 0<=value['start_ns']<=value['end_ns'])


def strip_use(value):
    """Validate new policy tags and return an independent original S1 projection."""
    _bound_fields(value)
    proof = value['typed_reference']
    if type(proof) is not dict or set(proof) != {'authority', 'build', 'checks'}:
        raise ValueError('Exact per-use typed-reference evidence required')
    _authority(proof['authority'])
    if type(value.get('cold')) is not bool or type(value.get('hit')) is not bool or value['cold']==value['hit']:
        raise ValueError('Exact cold/hit markers required')
    if value['cold']:
        build=proof['build'];checks=proof['checks']
        if (type(build) is not dict or set(build)!={'start_ns','end_ns','roots','completed'}
                or not _interval(build) or type(build['roots']) is not int or build['roots']!=2
                or build['completed'] is not True or type(checks) is not list or len(checks)!=2):
            raise ValueError('One complete two-root reference build required')
        for root,check in zip(('config','model'),checks):
            if (type(check) is not dict or set(check)!=CHECK_FIELDS or check['root']!=root
                    or not _interval(check) or check['completed'] is not True or check['equal'] is not True
                    or type(check['statistics']) is not dict or set(check['statistics'])!=COMPARISON_STAT_FIELDS
                    or any(type(count) is not int or count<0 for count in check['statistics'].values())
                    or check['statistics']['ordinary_mismatches']!=0):
                raise ValueError('Two exact successful ordered late-check records required')
    elif proof['build'] is not None or proof['checks']!=[]:
        raise ValueError('Hits cannot rebuild or recheck cold typed references')
    result = deepcopy(value)
    for name in EXTRA_FIELDS:result.pop(name)
    return result


def strip_summary(value):
    """Project a policy-bound complete receipt for the unchanged strict S1 audit."""
    _bound_fields(value)
    summary = value['typed_reference']
    if (type(summary) is not dict or set(summary) != {'authority', 'reference_builds', 'reference_roots',
            'late_comparisons', 'cold_calls', 'hit_calls'}):
        raise ValueError('Exact completed typed-reference summary required')
    _authority(summary['authority'])
    expected=dict(reference_builds=1,reference_roots=2,late_comparisons=2,cold_calls=1,hit_calls=6)
    if any(type(summary[name]) is not int or summary[name]!=count for name,count in expected.items()):
        raise ValueError('Exact integer completed reference/check counts required')
    result = deepcopy(value)
    result['call_observations'] = [strip_use(row) for row in value['call_observations']]
    for name in EXTRA_FIELDS:result.pop(name)
    return result


class _Load:
    """One invocation's retained source bytes and passive cold observations."""
    def __init__(self, pool, config, model):
        self.pool = pool
        self.clock = _PASSIVE_CLOCK
        self.canonical_calls = 0
        self.source_bytes = [None, None]
        self.source_runtime = [None, None]
        self.live_roots = (config, model)
        self.references = None
        self.build = None
        self.checks = []

    def canonical(self, value):
        self.canonical_calls += 1
        ordinal = self.canonical_calls
        if ordinal <= 4:
            before = typed.capture_runtime() if ordinal in (2, 4) else None
            result = c1.canonical(value)
            if ordinal in (2, 4):
                after = typed.capture_runtime()
                index = 0 if ordinal == 2 else 1
                self.source_bytes[index] = result
                self.source_runtime[index] = (before, after)
            return result
        if ordinal not in (5, 6) or self.references is None:
            raise ValueError('Original four early and two late content checks required')
        pool = self.pool
        if pool.poisoned or pool._typed_references is not self.references or pool._typed_comparing:
            raise ValueError('Typed comparison authority changed or reentered')
        if ordinal == 6:
            if value is not self.live_roots[1] or len(self.checks) != 2:
                raise ValueError('Both late roots must complete before expected bytes publish')
            return self.source_bytes[1]
        if value is not self.live_roots[0] or self.checks:
            raise ValueError('Late typed config/model check order changed')
        compare = typed.compare_with_stats
        clock = self.clock
        pool._typed_comparing = True
        try:
            # The original prepare span has exited. These bound passive clock
            # reads and the full comparator add no watch/observer/user hooks.
            # Finish BOTH roots before returning source config to the original
            # first expected_* assignment. Ordinal6 only publishes source model.
            for root, live, reference in zip(('config', 'model'), self.live_roots, self.references):
                start = clock()
                runtime = typed.capture_runtime()
                equal, statistics = compare(live, reference, runtime=runtime)
                end = clock()
                if pool.poisoned or pool._typed_references is not self.references:
                    raise ValueError('Reentry invalidated late typed authority')
                if end < start:raise ValueError('Passive comparison clock moved backwards')
                if equal is not True:
                    raise ValueError('Late ' + root + ' differs from validated source authority')
                self.checks.append(dict(root=root, start_ns=start, end_ns=end, completed=True,
                                        equal=True, statistics=statistics))
        finally:
            pool._typed_comparing = False
        return self.source_bytes[0]

    def buffer_root(self, name, value):
        if self.build is None:
            if self.canonical_calls != 4 or any(type(source) is not bytes for source in self.source_bytes):
                raise ValueError('References require four successful original early canonical checks')
            start = self.clock()
            references = tuple(typed._build_verified_reference(source,
                runtime_before=runtime[0], runtime_after=runtime[1],
                oracle=typed.ORIGINAL_CANONICAL, source_role=root)
                for root, source, runtime in zip(('config', 'model'), self.source_bytes, self.source_runtime))
            authority = dict(
                raw_sources={root: dict(self.pool.contract['dependencies'][root]) for root in ('config', 'model')},
                canonical={root: dict(reference.source_descriptor) for root, reference in zip(('config', 'model'), references)},
                reference_statistics={root: reference.statistics() for root, reference in zip(('config', 'model'), references)},
                reference_scheme=REFERENCE_SCHEME, policy=POLICY)
            _authority(authority)
            if self.pool.poisoned:raise ValueError('Reference build context was invalidated')
            self.references = references
            self.pool._typed_references = references
            self.pool._typed_authority = authority
            end = self.clock()
            if end < start:raise ValueError('Passive reference clock moved backwards')
            self.build = dict(start_ns=start, end_ns=end, roots=2, completed=True)
        return c1.BufferRoot(name, value)


class WorkerContext(s1.WorkerContext):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._typed_references = None
        self._typed_authority = None
        self._typed_comparing = False

    def invalidate(self):
        self._typed_references = None
        self._typed_authority = None
        self._typed_comparing = False
        super().invalidate()

    def _no_reentry(self):
        if self._typed_comparing:
            self.invalidate()
            raise ValueError('Late typed comparison cannot reenter its worker')

    def _identity(self, store, config, model, namespace, request, observer, watch):
        try:
            self._no_reentry();require_policy(request)
            return super()._identity(store, config, model, namespace, request, observer, watch)
        except BaseException:
            self.invalidate();raise

    def load(self, paths, config, support, watch, *, model, store, namespace, request, observer):
        try:
            self._no_reentry();require_policy(request)
            state = _Load(self, config, model)
            original = _clone(c1.WorkerContext.load, canonical=state.canonical, BufferRoot=state.buffer_root)
            # A dynamically created class has GC-managed type cycles that can
            # retain its closure and the cold references past the entry timer.
            parent = SimpleNamespace(load=lambda *args, **kwargs: original(self, *args, **kwargs))
            adapter = _clone(s1.WorkerContext.load, super=lambda: parent)
            first = len(observer.events)
            result = adapter(self, paths, config, support, watch, model=model, store=store,
                             namespace=namespace, request=request, observer=observer)
            if self._typed_references is None or self._typed_authority is None:
                raise ValueError('Borrow lacks its immutable source references')
            cold = self.calls[-1]['cold']
            if (cold and (state.canonical_calls != 6 or state.build is None or len(state.checks) != 2)
                    or not cold and (state.canonical_calls or state.build is not None or state.checks)):
                raise ValueError('One cold build/two complete late checks; hits may not rebuild')
            uses = [event for event in observer.events[first:] if event['phase'] == 'cache.use']
            if len(uses) != 1 or uses[0]['metadata'] != self.calls[-1]:
                raise ValueError('Original S1 cache metadata differs')
            proof = dict(authority=deepcopy(self._typed_authority), build=state.build, checks=state.checks)
            extra = dict(typed_reference_policy=POLICY, typed_reference_scheme=REFERENCE_SCHEME, typed_reference=proof)
            self.calls[-1].update(deepcopy(extra));uses[0]['metadata'].update(deepcopy(extra))
            return result
        except BaseException:
            self.invalidate();raise

    def prepare(self, catalog, counts, watch):
        self._no_reentry()
        return super().prepare(catalog, counts, watch)

    def finish(self, observer, watch):
        try:
            self._no_reentry();require_policy(self._s1_request)
            result = super().finish(observer, watch)
            if len(self.calls) == 7:
                # Called by the unchanged verifier inside the final C entry.
                # Primitive authority/proof remains available for the receipt.
                self._typed_references = None
            return result
        except BaseException:
            self.invalidate();raise

    def completed_summary(self):
        self._no_reentry()
        try:require_policy(self._s1_request)
        except BaseException:
            self.invalidate();raise
        # Incomplete-summary refusal retains the original ability to finish the
        # remaining authorized cycles; evidence/policy tampering invalidates.
        result = super().completed_summary()
        try:
            for index, row in enumerate(result['call_observations']):
                strip_use(row);proof = row['typed_reference']
                if (proof['authority'] != self._typed_authority
                        or (index == 0 and (proof['build'] is None or len(proof['checks']) != 2))
                        or (index > 0 and (proof['build'] is not None or proof['checks']))):
                    raise ValueError('Completed typed reference evidence changed')
            result = deepcopy(result)
            result.update(typed_reference_policy=POLICY, typed_reference_scheme=REFERENCE_SCHEME,
                typed_reference=dict(authority=deepcopy(self._typed_authority), reference_builds=1,
                    reference_roots=2, late_comparisons=2, cold_calls=1, hit_calls=6))
            return result
        except BaseException:
            self.invalidate();raise


make_verifier = c1.make_verifier


def run_fixed48(*args, **kwargs):
    request = kwargs.get('request', args[1] if len(args) > 1 else None)
    try:
        require_policy(request)
        return c1.run_fixed48(*args, **kwargs)
    except BaseException:
        pool = kwargs.get('pool')
        if pool is not None:pool.invalidate()
        raise
