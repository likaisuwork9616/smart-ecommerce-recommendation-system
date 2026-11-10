"""Invocation-local cold/S1 observations; no query or ranking entry point.

Traversal spans are gross observed work. Sampled watch durations include timer cost;
they are neither total watch time nor deductions from a historical V31 duration.
The original prepare_catalog and C1/V30 load bytecode remain unchanged.
"""
from contextlib import contextmanager
from time import perf_counter_ns
from types import MappingProxyType,SimpleNamespace

from scripts import retailrocket_session_knn_reuse_v27 as c1
from scripts import retailrocket_session_knn_snapshot_adapter_v30 as s1
from scripts import retailrocket_session_knn_snapshot_v30 as codec
from scripts.retailrocket_session_knn_diagnostics_v20 import _clone

SCHEME=codec.SCHEME
PREFIX=codec.PREFIX
WATCH_SAMPLE_EVERY=1024
VALIDATION_PHASES=('snapshot.validation.schema','snapshot.validation.first.traversal_copy',
    'snapshot.validation.first.sort','snapshot.validation.counts.traversal_copy',
    'snapshot.validation.counts.sort','snapshot.validation.first_times',
    'snapshot.validation.fallback','snapshot.validation.final_watch')
COLD_PHASES=('cold.buffer.acquire','cold.parse.config','cold.parse.model',
    'cold.canonical.compare','cold.canonical.expected','cold.buffer.view',
    'cold.prepare.mapping_view','cold.prepare.frozen_catalog','cold.expected_fingerprint')


class WatchCounter:
    """Invoke every original watch; time only every 1024th call, never extrapolate."""
    def __init__(self,watch,sample_every=WATCH_SAMPLE_EVERY,clock=None):
        if type(sample_every) is not int or sample_every<1024:
            raise ValueError('Amortized watch sampling requires an interval of at least 1024 calls')
        self.watch,self.sample_every,self.clock=watch,sample_every,clock or perf_counter_ns
        self.watch_calls=0;self.sampled_calls=0;self.sample_ns=0
        self.started_sampling_counter=0;self.stopped_sampling_counter=0
        self.fields={};self.current=self._field('outside_validation')

    def _field(self,name):
        return self.fields.setdefault(name,dict(watch_calls=0,sampled_calls=0,sample_ns=0))

    @contextmanager
    def field(self,name):
        previous=self.current;self.current=self._field(name)
        try:yield
        finally:self.current=previous

    def __call__(self):
        self.watch_calls+=1;self.current['watch_calls']+=1
        if self.watch_calls%self.sample_every:return self.watch()
        self.started_sampling_counter+=1;start=self.clock()
        try:return self.watch()
        finally:
            elapsed=self.clock()-start
            if elapsed<0:raise ValueError('Watch observation clock moved backwards')
            self.stopped_sampling_counter+=1;self.sampled_calls+=1;self.sample_ns+=elapsed
            self.current['sampled_calls']+=1;self.current['sample_ns']+=elapsed

    def report(self,completed):
        return dict(watch_calls=self.watch_calls,sampled_calls=self.sampled_calls,
            sample_seconds=self.sample_ns/1e9,unsampled_count=self.watch_calls-self.sampled_calls,
            started_sampling_counter=self.started_sampling_counter,stopped_sampling_counter=self.stopped_sampling_counter,
            sample_every=self.sample_every,completed=completed,
            fields={name:dict(watch_calls=row['watch_calls'],sampled_calls=row['sampled_calls'],
                sample_seconds=row['sample_ns']/1e9,unsampled_count=row['watch_calls']-row['sampled_calls'])
                for name,row in self.fields.items()},
            interpretation='Every original watch is invoked. Only each sampling-interval call is timed; samples include timer overhead. No extrapolated total watch time and no subtraction from gross traversal or historical costs.')


def _rows(prepared,observer,watch):
    # Same checks, values, ordering and watch boundaries as V30._rows.
    with codec._span(observer,'snapshot.validation.schema'):
        if type(prepared) is not codec.FrozenCatalog:raise ValueError('Exact accepted FrozenCatalog required')
        try:first,counts,times,fallback=(prepared.first,prepared.counts,prepared.first_times,prepared.fallback)
        except AttributeError as error:raise ValueError('All four snapshot fields required') from error
        if (type(first) is not MappingProxyType or type(counts) is not MappingProxyType
                or type(times) is not tuple or type(fallback) is not tuple):
            raise ValueError('Exact read-only mappings and tuple fields required')
    result=[]
    for name,mapping in (('first',first),('counts',counts)):
        with codec._span(observer,'snapshot.validation.'+name+'.traversal_copy'),watch.field(name):
            rows=[]
            for item,value in mapping.items():
                watch();codec._identifier(item);codec._integer(value);rows.append((item,value))
        with codec._span(observer,'snapshot.validation.'+name+'.sort'):
            rows.sort(key=lambda row:row[0])
        result.append((name,rows))
    with codec._span(observer,'snapshot.validation.first_times'),watch.field('first_times'):
        copied_times=[]
        for value in times:
            watch();codec._integer(value);copied_times.append(value)
    with codec._span(observer,'snapshot.validation.fallback'),watch.field('fallback'):
        copied_fallback=[]
        for item in fallback:
            watch();codec._identifier(item);copied_fallback.append(item)
    result.extend((('first_times',copied_times),('fallback',copied_fallback)))
    with codec._span(observer,'snapshot.validation.final_watch'),watch.field('final_validation'):
        watch()
    return result


def _observe_codec(function,prepared,observer,watch,sample_every,observations):
    counter=WatchCounter(watch,sample_every);completed=False
    encode=_clone(codec._encode,_rows=lambda value,_watch:_rows(value,observer,counter))
    original=_clone(function,_encode=encode)
    try:
        result=original(prepared,observer,counter);completed=True;return result
    finally:
        if observations is not None:observations.append(counter.report(completed))


def encode_snapshot(prepared,observer=None,watch=lambda:None,*,watch_sample_every=WATCH_SAMPLE_EVERY,watch_observations=None):
    return _observe_codec(codec.encode_snapshot,prepared,observer,watch,watch_sample_every,watch_observations)


def fingerprint(prepared,observer=None,watch=lambda:None,*,watch_sample_every=WATCH_SAMPLE_EVERY,watch_observations=None):
    return _observe_codec(codec.fingerprint,prepared,observer,watch,watch_sample_every,watch_observations)


def timer_overhead(samples=256,clock=None):
    """Isolated paired-read observations only; never a correction to original costs."""
    if type(samples) is not int or samples<1:raise ValueError('Positive timer calibration sample count required')
    clock=clock or perf_counter_ns;values=[]
    for _ in range(samples):
        start=clock();elapsed=clock()-start
        if elapsed<0:raise ValueError('Calibration clock moved backwards')
        values.append(elapsed)
    return dict(samples=samples,min_ns=min(values),max_ns=max(values),sum_ns=sum(values),
        interpretation='Isolated paired timer reads, not full observer/wrapper overhead. No overhead subtraction or historical elapsed-time attribution.')


class _Cold:
    def __init__(self,pool,observer):
        self.pool,self.observer=pool,observer;self.parse_calls=0;self.canonical_calls=0

    def buffer(self,root,record,watch):
        name=next((key for key,value in self.pool.contract['dependencies'].items() if value is record),'unknown')
        with self.observer.span('cold.buffer.acquire',dependency=name):
            return c1.verified_buffer(root,record,watch)

    def loads(self,value):
        self.parse_calls+=1;name='config' if self.parse_calls==1 else 'model'
        if self.parse_calls>2:raise ValueError('Unexpected cold JSON parse count')
        with self.observer.span('cold.parse.'+name):return c1.json.loads(value)

    def canonical(self,value):
        self.canonical_calls+=1;expected=self.canonical_calls>4
        with self.observer.span('cold.canonical.'+('expected' if expected else 'compare'),ordinal=self.canonical_calls):
            return c1.canonical(value)

    def buffer_root(self,name,value):
        with self.observer.span('cold.buffer.view',name=name):return c1.BufferRoot(name,value)

    def prepare(self,catalog,counts,watch):
        def mapping(value):
            with self.observer.span('cold.prepare.mapping_view'):return MappingProxyType(value)
        def frozen(*args):
            with self.observer.span('cold.prepare.frozen_catalog'):return c1.ORIGINALS[2].__globals__['FrozenCatalog'](*args)
        # All loop copies, schema checks and sorting use the original prepare bytecode.
        original=_clone(c1.ORIGINALS[2],MappingProxyType=mapping,FrozenCatalog=frozen)
        return original(catalog,counts,watch)


class WorkerContext(s1.WorkerContext):
    def __init__(self,contract,source_root,method_root,*,watch_sample_every=WATCH_SAMPLE_EVERY):
        if type(watch_sample_every) is not int or watch_sample_every<1024:raise ValueError('Amortized sampling interval required')
        super().__init__(contract,source_root,method_root)
        self.watch_sample_every=watch_sample_every;self.watch_observations=[]

    def _snapshot_digest(self):
        s1.require_scheme(self._s1_request)
        observer=self._s1_observer
        cold=any(observer.events[index]['phase']=='cache.cold_build' for index in observer.stack)
        def calculate():return fingerprint(self.prepared,observer,self._s1_watch,
            watch_sample_every=self.watch_sample_every,watch_observations=self.watch_observations)
        if cold:
            with observer.span('cold.expected_fingerprint'):return calculate()
        return calculate()

    def load(self,paths,config,support,watch,*,model,store,namespace,request,observer):
        try:
            cold=_Cold(self,observer)
            originals=list(c1.ORIGINALS);originals[2]=cold.prepare
            original=_clone(c1.WorkerContext.load,verified_buffer=cold.buffer,
                json=SimpleNamespace(loads=cold.loads),canonical=cold.canonical,
                BufferRoot=cold.buffer_root,ORIGINALS=tuple(originals))
            # Preserve V30's scheme/cache-use checks and exception invalidation bytecode.
            parent=SimpleNamespace(load=lambda *args,**kwargs:original(self,*args,**kwargs))
            adapter=_clone(s1.WorkerContext.load,super=lambda:parent)
            return adapter(self,paths,config,support,watch,model=model,store=store,
                namespace=namespace,request=request,observer=observer)
        except BaseException:
            self.invalidate();raise
