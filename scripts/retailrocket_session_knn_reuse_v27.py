"""C1 invocation-local immutable initialization; original source/SQL bytecode stays frozen."""
import hashlib
import io
import json
import math
import os
from pathlib import Path
from types import MappingProxyType

import psutil

from scripts import retailrocket_session_knn_pair_v4 as pair
from scripts import retailrocket_session_knn_readback as raw
from scripts import retailrocket_popularity_oracle as parser
from scripts import retailrocket_session_knn_sources_v24 as observed
from scripts import run_retailrocket_session_knn_overlap_v22 as entry
from scripts.retailrocket_session_knn_diagnostics_v20 import _clone

ORIGINALS=(pair.verify_selected,pair.core.load_context,pair.sql.prepare_catalog,
           raw.positive_table,raw.read_rows,parser.read_rows,parser.num)


def canonical(value):
    """Typed semantic identity: bool/int, tuple/list and floats cannot alias."""
    def typed(v):
        if v is None:return ['none']
        if type(v) is bool:return ['bool',v]
        if type(v) is int:return ['int',str(v)]
        if type(v) is float:
            if not math.isfinite(v):raise ValueError('Nonfinite semantic value')
            return ['float',v.hex()]
        if type(v) is str:return ['str',v]
        if type(v) in (list,tuple):return [type(v).__name__,[typed(x) for x in v]]
        if type(v) in (dict,MappingProxyType):
            if not all(type(k) is str for k in v):raise ValueError('Non-string semantic key')
            return ['map',[[k,typed(v[k])] for k in sorted(v)]]
        raise ValueError('Unsupported mutable or custom semantic value')
    return json.dumps(typed(value),ensure_ascii=False,separators=(',',':')).encode('utf-8')


def digest(value):return hashlib.sha256(canonical(value)).hexdigest()


def process_identity():
    p=psutil.Process();return p.pid,p.create_time()


def verified_buffer(root,record,watch=lambda:None):
    """Read no more than the expected bytes plus one; parse this exact hashed buffer."""
    from scripts.retailrocket_session_knn_checkpoint_v2 import _inside
    path=_inside(root,record['path']);blocks=[];remaining=record['bytes']+1
    with path.open('rb') as stream:
        while remaining:
            watch();block=stream.read(min(1024*1024,remaining))
            if not block:break
            blocks.append(block);remaining-=len(block)
    value=b''.join(blocks)
    if len(value)!=record['bytes'] or hashlib.sha256(value).hexdigest()!=record['sha256']:
        raise ValueError('Exact initialization buffer differs from bound source')
    return value


class BufferPath:
    def __init__(self,value):self.value=value
    def open(self,*,encoding,newline=None):
        if encoding!='utf-8':raise ValueError('Original UTF-8 parser required')
        return io.TextIOWrapper(io.BytesIO(self.value),encoding=encoding,newline=newline)


class BufferRoot:
    def __init__(self,name,value):self.name,self.value=name,value
    def __truediv__(self,name):
        if name!=self.name:raise ValueError('Unexpected buffered source')
        return BufferPath(self.value)


class ReuseStore(observed.ObservedStore):
    def __init__(self,*args,**kwargs):
        self.created_here=False;self.full_checks=[]
        super().__init__(*args,**kwargs)

    @classmethod
    def create(cls,*args,**kwargs):
        store=super().create(*args,**kwargs);store.created_here=True;return store

    def _check_sources(self,force=False):
        cached=self._sources_checked
        super()._check_sources(force=force)
        if not cached or force:
            # C1 never substitutes an external receipt for original full source checks.
            self.full_checks.append(dict(force=force,external=self.external_source_verifier is not None))


class StoreFactory:
    def __init__(self,observer):self.observer=observer
    def create(self,*args,**kwargs):return ReuseStore.create(*args,observer=self.observer,**kwargs)


class WorkerContext:
    """One lazy snapshot. Constructor retains contract refs, never preloads context."""
    def __init__(self,contract,source_root,method_root):
        self.contract,self.source_root,self.method_root=contract,Path(source_root),Path(method_root)
        self.creator_pid=os.getpid()
        self.owner=None;self.key=None;self.prepared=None;self.expected_digest=None
        self.expected_config=None;self.expected_model=None;self.poisoned=False
        self.used=set();self.calls=[];self.active=None

    def __getstate__(self):raise TypeError('Worker snapshot cannot cross a process boundary')

    def invalidate(self):
        self.poisoned=True;self.prepared=None;self.active=None

    def _identity(self,store,config,model,namespace,request,observer,watch):
        with observer.span('cache.identity'):
            watch()
            if self.poisoned:raise ValueError('Failed context cannot be reused')
            if len(self.calls)>=7:raise ValueError('Only one cold plus six hits are authorized by this context')
            if os.getpid()!=self.creator_pid or self.owner is not None and process_identity()!=self.owner:
                raise ValueError('Context process identity changed')
            if not isinstance(store,ReuseStore) or not store.created_here or store._guard is None:
                raise ValueError('Fresh original store under writer lock required')
            if store.source_root!=self.source_root.resolve() or store.full_checks!=[
                    dict(force=False,external=False),dict(force=True,external=False)]:
                raise ValueError('Both original full source checks required before lookup')
            if store._token in self.used or store.recover()['records']:
                raise ValueError('Fresh one-use writer required; resume cannot reuse context')
            if canonical(store.binding)!=canonical(self.contract['binding']):raise ValueError('Source binding changed')
            current=(pair.verify_selected,pair.core.load_context,pair.sql.prepare_catalog,
                     raw.positive_table,raw.read_rows,parser.read_rows,parser.num)
            if current!=ORIGINALS:raise ValueError('Original semantic function changed')
            for record in self.contract['methods']:
                verified_buffer(self.method_root,record,watch)
            from scripts.run_retailrocket_session_knn_v2 import environment
            if environment()!=self.contract['environment']:raise ValueError('Accepted environment changed')
            key=digest(dict(binding=store.binding,dependencies=self.contract['dependencies'],methods=self.contract['methods'],
                environment=self.contract['environment'],namespace=namespace,request=request,owner=list(process_identity()),
                source_root=str(self.source_root.resolve()),method_root=str(self.method_root.resolve()),
                config=config,model=model))
            if self.key is not None and key!=self.key:raise ValueError('Complete context identity changed')
            return key

    def _snapshot_digest(self):
        p=self.prepared
        if (type(p) is not pair.sql.FrozenCatalog or type(p.first) is not MappingProxyType
                or type(p.counts) is not MappingProxyType or type(p.first_times) is not tuple or type(p.fallback) is not tuple):
            raise ValueError('Snapshot is not deeply immutable')
        return digest(dict(first=p.first,counts=p.counts,first_times=p.first_times,fallback=p.fallback))

    def load(self,paths,config,support,watch,*,model,store,namespace,request,observer):
        try:
            key=self._identity(store,config,model,namespace,request,observer,watch)
            if support is not model['support']:raise ValueError('Caller support differs from complete model')
            expected_paths={name:(self.source_root/record['path']).resolve() for name,record in self.contract['dependencies'].items()}
            if ((paths['P0']/'item_counts.csv').resolve()!=expected_paths['counts']
                    or (paths['dataset']/'catalog.csv').resolve()!=expected_paths['catalog']):
                raise ValueError('Initialization source path changed')
            cold=self.prepared is None
            if cold:
                if self.key is not None:raise ValueError('Unexpected miss cannot rebuild')
                with observer.span('cache.cold_build'):
                    values={name:verified_buffer(self.source_root,record,watch) for name,record in self.contract['dependencies'].items()}
                    expected_config=json.loads(values['config']);receipt=json.loads(values['model'])
                    expected_model=receipt['receipt']
                    if canonical(config)!=canonical(expected_config) or canonical(model)!=canonical(expected_model):
                        raise ValueError('Live configuration/model differs from exact verified receipt')
                    buffered=dict(paths,P0=BufferRoot('item_counts.csv',values['counts']),dataset=BufferRoot('catalog.csv',values['catalog']))
                    with observer.span('cache.original_load_context'):
                        counts,catalog=ORIGINALS[1](buffered,config,support,watch)
                    with observer.span('cache.original_prepare_catalog'):
                        self.prepared=ORIGINALS[2](catalog,counts,watch)
                    self.expected_config=canonical(config);self.expected_model=canonical(model)
                    self.expected_digest=self._snapshot_digest();self.owner=process_identity();self.key=key
            with observer.span('cache.pre_use_digest'):
                if self._snapshot_digest()!=self.expected_digest:raise ValueError('Snapshot content changed')
            if self.active is not None:raise ValueError('Concurrent snapshot borrower forbidden')
            self.used.add(store._token);self.active=(store,config,model)
            self.calls.append(dict(cold=cold,hit=not cold,
                buffer_logical_bytes=sum(x['bytes'] for x in self.contract['dependencies'].values()) if cold else 0,
                context_source_logical_bytes=sum(self.contract['dependencies'][n]['bytes'] for n in ('counts','catalog')) if cold else 0,
                catalog_rows=len(self.prepared.first),count_rows=len(self.prepared.counts)))
            return self.prepared.counts,self.prepared.first
        except BaseException:
            self.invalidate();raise

    def prepare(self,catalog,counts,watch):
        watch()
        if self.active is None or catalog is not self.prepared.first or counts is not self.prepared.counts:
            raise ValueError('Prepared context argument identity differs')
        return self.prepared

    def finish(self,observer,watch):
        with observer.span('cache.final_guard'):
            try:
                watch()
                if self.active is None:raise ValueError('No active context')
                _,config,model=self.active
                if (canonical(config)!=self.expected_config or canonical(model)!=self.expected_model
                        or self._snapshot_digest()!=self.expected_digest):raise ValueError('Snapshot/caller changed during verifier')
                self.active=None
            except BaseException:
                self.invalidate();raise

    def close(self):self.invalidate()

    def completed_summary(self):
        if self.poisoned or self.active is not None or len(self.calls)!=7 or [x['cold'] for x in self.calls]!=[True]+[False]*6:
            raise ValueError('Complete one-build/six-hit context receipt required')
        return dict(candidate_runs=7,cold_builds=1,hits=6,
            buffer_logical_bytes=sum(x['buffer_logical_bytes'] for x in self.calls),
            context_source_logical_bytes=sum(x['context_source_logical_bytes'] for x in self.calls),
            call_observations=[dict(x) for x in self.calls])


def make_verifier(observer,pool,namespace,request):
    def verify(primary,paths,config,store,model,database,ordinals,watch=lambda:None,fault=lambda point:None):
        with observer.span('verifier.total') as event:
            clock=observed._SetupClock(observer)
            def load(p,c,s,w):return pool.load(p,c,s,w,model=model,store=store,namespace=namespace,request=request,observer=observer)
            core=observed._ModuleView(pair.core,load_context=observer.wrapped('context.load_context',load),
                seal_consistent=observer.wrapped('verifier.seal_consistent',pair.core.seal_consistent))
            sql=observed._ModuleView(pair.sql,prepare_catalog=observer.wrapped('context.prepare_catalog',pool.prepare))
            original=_clone(ORIGINALS[0],core=core,sql=sql,perf_counter=clock)
            try:
                result=original(primary,paths,config,store,model,database,ordinals,watch,fault)
                pool.finish(observer,watch)
            except BaseException:
                pool.invalidate();raise
            finally:
                import sys
                clock.close(sys.exc_info())
            if len(clock.samples)<3 or result['setup_seconds']!=clock.samples[2]-clock.samples[0]:
                pool.invalidate();raise ValueError('Original setup clock changed')
            event['metadata']['original_setup_seconds']=result['setup_seconds']
            return result
    return verify


def run_fixed48(folder,request,label,mode,data,*,observer,pool=None,source_root=entry.ROOT,watch=lambda:None):
    if mode not in ('R','C'):raise ValueError('Expected R or C1')
    if len(data[5])!=48 or len(data[6])!=48 or data[1]['fixed_validation']['queries']!=48:
        raise ValueError('Only the original fixed48 run shape is accepted')
    if mode=='C' and pool is None:raise ValueError('C1 requires one worker-owned pool')
    verifier=(make_verifier(observer,pool,str(Path(folder).resolve()),request) if mode=='C' else observed.make_verifier(observer))
    original=_clone(entry._run,ROOT=Path(source_root),DetailedTimedStore=StoreFactory(observer),
        make_verifier=lambda _:verifier,ledger_proof=observer.wrapped('run.ledger_proof',entry.ledger_proof),
        write=observer.wrapped('run.output_write',entry.write))
    try:return observer.call('run.total',original,folder,request,label,'baseline',data,watch)
    except BaseException:
        if pool is not None:pool.invalidate()
        raise
