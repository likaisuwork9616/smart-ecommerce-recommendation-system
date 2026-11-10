"""New source-anchored worker tests; frozen C1/S1 fixtures remain unchanged."""
from collections import Counter
from collections.abc import Mapping
from contextlib import contextmanager
from copy import deepcopy
from datetime import datetime,timedelta,timezone
import gc
import sys
from time import perf_counter_ns
from types import MappingProxyType,SimpleNamespace
import unittest
from unittest.mock import patch
from weakref import ref

from scripts import retailrocket_session_knn_typed_adapter_v39 as adapter
from scripts import retailrocket_session_knn_typed_v39 as typed
from scripts import retailrocket_session_knn_reuse_v27 as c1
from scripts import retailrocket_session_knn_snapshot_v30 as codec
from scripts import retailrocket_session_knn_sources_v24 as observed
from scripts import run_retailrocket_session_knn_v2 as io
from scripts.retailrocket_session_knn_diagnostics_v20 import _clone
from tests import test_retailrocket_session_knn_reuse_v27 as focused
from tests import test_retailrocket_session_knn_reuse_acceptance_v27 as legacy
from tests import test_retailrocket_session_knn_snapshot_integration_v30 as previous


METHODS=('scripts/retailrocket_session_knn_typed_v39.py','scripts/retailrocket_session_knn_typed_adapter_v39.py',
    'scripts/retailrocket_session_knn_snapshot_v30.py','scripts/retailrocket_session_knn_snapshot_adapter_v30.py')


def policy(request):
    request.setdefault('metadata',{}).update(fingerprint_scheme=codec.SCHEME,
        typed_reference_policy=adapter.POLICY,typed_reference_scheme=typed.SCHEME)
    return request


def bind_methods(contract):
    methods={record['path']:record for record in contract['methods']}
    for name in METHODS:methods[name]=io.describe(io.ROOT/name)
    contract['methods']=[methods[name] for name in sorted(methods)]


def rebind(self):
    focused.ContextTests.rebind(self);policy(self.request);bind_methods(self.contract)
    self.pool=adapter.WorkerContext(self.contract,self.root,io.ROOT)


@contextmanager
def counted_calls():
    """Count real code entries without wrappers that would change call depth."""
    counts=Counter();order=[];previous_profile=sys.getprofile()
    canonical_code=c1.canonical.__code__;digest_code=c1.digest.__code__
    compare_code=typed.compare_with_stats.__code__;build_code=typed._build_verified_reference.__code__
    snapshot_code=codec.fingerprint.__code__
    def profile(frame,event,arg):
        if event!='call':return
        code=frame.f_code
        if code is canonical_code:
            value=frame.f_locals['value']
            if 'namespace' in value:kind='identity_key'
            elif 'schemas' in value:kind='config'
            elif 'support' in value:kind='model'
            else:kind='binding'
            counts[kind]+=1;order.append('canonical:'+kind)
        elif code is digest_code:counts['key_digest']+=1
        elif code is compare_code:counts['typed']+=1;order.append('typed')
        elif code is build_code:counts['reference_root_build']+=1;order.append('build')
        elif code is snapshot_code:counts['snapshot']+=1
    sys.setprofile(profile)
    try:yield counts,order
    finally:sys.setprofile(previous_profile)


class InheritedContextTests(focused.ContextTests):
    rebind=rebind


class InheritedAdversarialTests(previous.InheritedAdversarialTests):
    rebind=rebind

    def test_body_exception_cleanup(self):
        with legacy.tempfile_artificial_four() as data:
            root,paths,config,primary,database,model,ordinals,binding,contract=data
            bind_methods(contract);pool=adapter.WorkerContext(contract,root,io.ROOT);obs=observed.Observation()
            request=policy(dict(deadline_utc=(datetime.now(timezone.utc)+timedelta(minutes=3)).isoformat(),budget_seconds=180))
            store=c1.ReuseStore.create(root/'failed-typed',binding,request['deadline_utc'],180,source_root=root,observer=obs,
                expected_queries=len(ordinals),required_stages=('reconstruction','queries'))
            def interrupt(point):
                if point=='query_work':raise RuntimeError('artificial typed verifier interruption')
            with self.assertRaises(RuntimeError),store.writer():
                legacy.four.reconstruct_seal(store,model)
                adapter.make_verifier(obs,pool,'artificial-window',request)(primary,paths,config,store,model,database,ordinals,fault=interrupt)
            self.assertTrue(pool.poisoned);self.assertIsNone(pool._typed_references);self.assertIsNone(pool.expected_config)
            self.assertIsNone(store._guard);self.assertFalse(obs.stack)


class FullVerifierTests(previous.FullVerifierTests):
    @classmethod
    def setUpClass(cls):
        def pool(contract,source_root,method_root):
            bind_methods(contract);return adapter.WorkerContext(contract,source_root,method_root)
        def verifier(observer,context,namespace,request):
            policy(request);return adapter.make_verifier(observer,context,namespace,request)
        facade=SimpleNamespace(WorkerContext=pool,make_verifier=verifier)
        # The original fixture still constructs each ledger and runs all four
        # scientific arms; only its explicit worker/verifier globals are new.
        _clone(previous.FullVerifierTests.setUpClass.__func__,adapter=facade)(cls)


class SchemeTests(previous.SchemeTests):
    rebind=rebind

    def test_15_live_snapshot_checks_and22_digests_retained(self):
        """V38 supersedes generic41 with actual generic39 plus two full checks."""
        with counted_calls() as (counts,order):
            events=[]
            for _ in range(7):
                _,obs,_=self.cycle();events.extend(obs.events)
            receipt=self.pool.completed_summary()
        self.assertEqual({name:counts[name] for name in ('binding','identity_key','config','model')},
            dict(binding=14,identity_key=7,config=9,model=9))
        self.assertEqual(sum(counts[name] for name in ('binding','identity_key','config','model')),39)
        self.assertEqual(counts['typed'],2);self.assertEqual(counts['reference_root_build'],2)
        self.assertEqual(counts['snapshot'],15);self.assertEqual(counts['key_digest'],7)
        self.assertEqual(counts['snapshot']+counts['key_digest'],22)
        self.assertEqual(sum(e['phase']=='snapshot.fingerprint' for e in events),15)
        self.assertEqual(receipt['typed_reference']['late_comparisons'],2)
        self.assertEqual(receipt['typed_reference']['reference_builds'],1)
        self.assertEqual(receipt['hits'],6)
        type(self).executed_counts=dict(
            generic_canonical=sum(counts[name] for name in ('binding','identity_key','config','model')),
            full_typed_comparisons=counts['typed'],reference_roots=counts['reference_root_build'],
            live_snapshot_fingerprints=counts['snapshot'],identity_key_digests=counts['key_digest'],
            total_digests=counts['snapshot']+counts['key_digest'])

    def test_policy_request_use_and_complete_receipt_cannot_mix(self):
        self.request['metadata']['typed_reference_policy']='other-policy';store,obs=self.store()
        with store.writer(),self.assertRaises(ValueError):self.load(store,obs)
        self.assertTrue(self.pool.poisoned);self.assertIsNone(self.pool._typed_references)
        self.rebind()
        for _ in range(7):self.cycle()
        receipt=self.pool.completed_summary()
        self.assertNotIn('typed_reference',adapter.strip_summary(receipt))
        bad=deepcopy(receipt);bad['typed_reference_scheme']='other-scheme'
        with self.assertRaises(ValueError):adapter.strip_summary(bad)
        self.pool.calls[2]['typed_reference_scheme']='other-scheme'
        with self.assertRaises(ValueError):self.pool.completed_summary()
        self.assertTrue(self.pool.poisoned);self.assertIsNone(self.pool.expected_config)


class ProbeMapping(Mapping):
    def __init__(self,values,hook):self.values,self.hook=values,hook
    def __iter__(self):self.hook('iter',None);return iter(self.values)
    def __len__(self):self.hook('length_hint',None);return len(self.values)
    def __getitem__(self,key):self.hook('get',key);return self.values[key]


class LateAuthorityTests(unittest.TestCase):
    setUp=focused.ContextTests.setUp
    rebind=rebind
    store=focused.ContextTests.store
    load=focused.ContextTests.load
    cycle=focused.ContextTests.cycle

    def initialize(self):
        self.config['typed_sentinel']='A';self.model['fit_audit']['typed_sentinel']='A';self.rebind()

    @staticmethod
    def inside(observer,phase):return any(observer.events[index]['phase']==phase for index in observer.stack)

    def borrow(self,store,observer,watch=lambda:None,*,config=None,model=None):
        config=self.config if config is None else config;model=self.model if model is None else model
        counts,catalog=self.pool.load(self.paths,config,model['support'],watch,model=model,store=store,
            namespace='artificial-window',request=self.request,observer=observer)
        return self.pool.prepare(catalog,counts,watch)

    def poisoned(self,observer):
        self.assertTrue(self.pool.poisoned)
        for name in ('_typed_references','_typed_authority','expected_config','expected_model','prepared','key','owner','active'):
            self.assertIsNone(getattr(self.pool,name),name)
        self.assertFalse(any(e['phase']=='cache.use' for e in observer.events))

    def test_source_reference_build_and_late_order_stay_inside_original_cold_boundary(self):
        self.initialize();store,obs=self.store()
        with store.writer():
            self.borrow(store,obs);refs=self.pool._typed_references
            self.assertEqual(refs[0].source_bytes,self.pool.expected_config);self.assertEqual(refs[1].source_bytes,self.pool.expected_model)
            self.assertEqual(refs[0].source_bytes,c1.canonical(self.config));self.assertEqual(refs[1].source_bytes,c1.canonical(self.model))
            with self.assertRaises((TypeError,AttributeError)):object.__setattr__(refs[0],'source_bytes',b'forged')
            self.pool.finish(obs,lambda:None)
        use=next(e['metadata'] for e in obs.events if e['phase']=='cache.use');proof=use['typed_reference']
        self.assertEqual(proof['authority']['raw_sources'],{name:self.contract['dependencies'][name] for name in ('config','model')})
        cold=next(e for e in obs.events if e['phase']=='cache.cold_build')
        load=next(e for e in obs.events if e['phase']=='cache.original_load_context')
        prepare=next(e for e in obs.events if e['phase']=='cache.original_prepare_catalog')
        self.assertLessEqual(cold['start_ns'],proof['build']['start_ns']);self.assertLessEqual(proof['build']['end_ns'],load['start_ns'])
        self.assertEqual([x['root'] for x in proof['checks']],['config','model'])
        self.assertLessEqual(prepare['end_ns'],proof['checks'][0]['start_ns'])
        self.assertLessEqual(proof['checks'][0]['end_ns'],proof['checks'][1]['start_ns'])
        self.assertLessEqual(proof['checks'][1]['end_ns'],cold['end_ns'])

    def test_persistent_config_change_rejects_before_borrow_and_does_not_compare_model(self):
        self.initialize();store,obs=self.store();changed=False
        def watch():
            nonlocal changed
            if not changed and self.inside(obs,'cache.original_load_context'):
                self.config['typed_sentinel']='B';changed=True
        with counted_calls() as (counts,_),store.writer(),self.assertRaisesRegex(ValueError,'Late config differs'):
            self.borrow(store,obs,watch)
        self.assertTrue(changed);self.assertEqual(counts['typed'],1);self.poisoned(obs)

    def test_persistent_model_change_rejects_after_complete_config_and_before_borrow(self):
        self.initialize();store,obs=self.store();changed=False
        def watch():
            nonlocal changed
            if not changed and self.inside(obs,'cache.original_prepare_catalog'):
                self.model['fit_audit']['typed_sentinel']='B';changed=True
        with counted_calls() as (counts,_),store.writer(),self.assertRaisesRegex(ValueError,'Late model differs'):
            self.borrow(store,obs,watch)
        self.assertTrue(changed);self.assertEqual(counts['typed'],2);self.poisoned(obs)

    def test_ABA_crossing_late_is_rejected_without_adopting_original_late_B(self):
        for root in ('config','model'):
            self.initialize();early=c1.canonical(self.config if root=='config' else self.model);store,obs=self.store();changed=False
            def watch():
                nonlocal changed
                if not changed and self.inside(obs,'cache.original_load_context'):
                    target=self.config if root=='config' else self.model['fit_audit'];target['typed_sentinel']='B';changed=True
            with self.subTest(root=root),store.writer():
                with self.assertRaises(ValueError):self.borrow(store,obs,watch)
                target=self.config if root=='config' else self.model['fit_audit'];target['typed_sentinel']='A'
                self.assertEqual(c1.canonical(self.config if root=='config' else self.model),early)
            self.assertTrue(changed);self.poisoned(obs)

    def test_restore_before_late_and_after_late_restore_discrete_guard_boundaries(self):
        self.initialize();store,obs=self.store();changed=False;restored=False
        def watch():
            nonlocal changed,restored
            if not changed and self.inside(obs,'cache.original_load_context'):
                self.config['typed_sentinel']='B';changed=True
            elif changed and not restored and self.inside(obs,'cache.original_prepare_catalog'):
                self.config['typed_sentinel']='A';restored=True
        with store.writer():
            self.borrow(store,obs,watch);self.assertTrue(restored)
            source=self.pool.expected_config;self.config['typed_sentinel']='B';self.assertNotEqual(c1.canonical(self.config),source)
            self.config['typed_sentinel']='A';self.pool.finish(obs,watch)
        self.assertFalse(self.pool.poisoned)

    def test_original_prepare_observer_exit_mutation_is_checked_before_borrow(self):
        self.initialize();owner=self;changed=[]
        class ExitObserver(observed.Observation):
            @contextmanager
            def span(inner,phase,**metadata):
                with super().span(phase,**metadata) as event:yield event
                if phase=='cache.original_prepare_catalog':owner.config['typed_sentinel']='B';changed.append(True)
        obs=ExitObserver();store=c1.ReuseStore.create(self.root/'exit-store',self.binding,self.request['deadline_utc'],300,
            source_root=self.root,observer=obs,expected_queries=1,required_stages=('reconstruction','queries'))
        with store.writer(),self.assertRaisesRegex(ValueError,'Late config differs'):self.borrow(store,obs)
        self.assertEqual(changed,[True]);self.poisoned(obs)

    def test_no_new_watch_or_observer_clock_hook_inside_both_late_comparisons(self):
        self.initialize();calls=Counter();owner=self
        def clock():
            if owner.pool._typed_comparing:raise AssertionError('New observer callback in late comparison')
            calls['clock']+=1;return perf_counter_ns()
        obs=observed.Observation(clock=clock)
        store=c1.ReuseStore.create(self.root/'no-hook-store',self.binding,self.request['deadline_utc'],300,
            source_root=self.root,observer=obs,expected_queries=1,required_stages=('reconstruction','queries'))
        def watch():
            if owner.pool._typed_comparing:raise AssertionError('New watch callback in late comparison')
            calls['watch']+=1
        with store.writer():self.borrow(store,obs,watch);self.pool.finish(obs,watch)
        self.assertGreater(calls['clock'],0);self.assertGreater(calls['watch'],0)
        self.assertEqual(len(self.pool.calls[0]['typed_reference']['checks']),2)

    def test_model_read_hook_sees_neither_expected_field_until_both_checks_complete(self):
        self.initialize();seen=[]
        def hook(operation,key):
            if self.pool._typed_comparing:seen.append((self.pool.expected_config,self.pool.expected_model))
        model=MappingProxyType(ProbeMapping(self.model,hook));store,obs=self.store()
        with store.writer():
            self.borrow(store,obs,model=model);self.assertTrue(seen);self.assertEqual(set(seen),{(None,None)})
            self.assertEqual(self.pool.expected_config,c1.canonical(self.config));self.assertEqual(self.pool.expected_model,c1.canonical(model))
            self.pool.finish(obs,lambda:None)

    def test_reentry_from_existing_proxy_protocol_poison_cannot_be_caught_into_success(self):
        self.initialize();attempts=[];store,obs=self.store()
        def hook(operation,key):
            if self.pool._typed_comparing and not attempts:
                try:self.pool.finish(obs,lambda:None)
                except ValueError as error:attempts.append(str(error))
        config=MappingProxyType(ProbeMapping(self.config,hook))
        with store.writer(),self.assertRaises(ValueError):self.borrow(store,obs,config=config)
        self.assertTrue(attempts);self.poisoned(obs)

    def test_caught_direct_comparator_reentry_via_proxy_read_rejects_outer_worker_before_borrow(self):
        self.initialize();attempts=[];caught=[];store,obs=self.store()
        def hook(operation,key):
            if operation=='get' and self.pool._typed_comparing and not attempts:
                attempts.append(key)
                try:typed.compare_full(config,self.pool._typed_references[0])
                except (ValueError,RuntimeError) as error:caught.append(type(error).__name__)
        config=MappingProxyType(ProbeMapping(self.config,hook))
        with store.writer(),self.assertRaises((ValueError,RuntimeError)):
            self.borrow(store,obs,config=config)
        self.assertEqual(len(attempts),1);self.assertEqual(len(caught),1)
        self.assertFalse(self.pool.calls);self.poisoned(obs)

    def test_model_last_read_runtime_limit_change_rejects_before_expected_publication(self):
        controls=[('recursion',sys.getrecursionlimit,sys.setrecursionlimit)]
        if hasattr(sys,'get_int_max_str_digits'):
            controls.append(('integer_digits',sys.get_int_max_str_digits,sys.set_int_max_str_digits))
        for name,get_limit,set_limit in controls:
            saved=get_limit();self.initialize();store,obs=self.store();changed=[]
            replacement=saved-1 if name=='recursion' else (640 if saved!=640 else 641)
            def hook(operation,key):
                if operation=='get' and key=='support' and self.pool._typed_comparing and not changed:
                    set_limit(replacement);changed.append(get_limit())
            model=MappingProxyType(ProbeMapping(self.model,hook))
            try:
                with self.subTest(control=name),store.writer(),self.assertRaises((ValueError,RuntimeError,RecursionError)):
                    self.borrow(store,obs,model=model)
            finally:set_limit(saved)
            self.assertEqual(changed,[replacement]);self.assertEqual(get_limit(),saved)
            self.assertFalse(self.pool.calls);self.poisoned(obs)

    def test_reference_replacement_before_late_rejects_without_fallback(self):
        self.initialize();store,obs=self.store();changed=False
        def watch():
            nonlocal changed
            if not changed and self.inside(obs,'cache.original_prepare_catalog'):
                self.pool._typed_references=tuple(reversed(self.pool._typed_references));changed=True
        with store.writer(),self.assertRaisesRegex(ValueError,'authority changed'):self.borrow(store,obs,watch)
        self.assertTrue(changed);self.poisoned(obs)

    def test_second_reference_root_build_failure_clears_all_state_and_forbids_retry(self):
        self.initialize();store,obs=self.store();builder=typed._build_verified_reference;built=[]
        def fail_second(source,**kwargs):
            built.append(kwargs['source_role'])
            if len(built)==2:raise RuntimeError('artificial second reference root build failure')
            return builder(source,**kwargs)
        with patch.object(typed,'_build_verified_reference',side_effect=fail_second) as controlled:
            with store.writer(),self.assertRaisesRegex(RuntimeError,'second reference root build failure'):
                self.borrow(store,obs)
            self.assertEqual(built,['config','model']);self.assertEqual(controlled.call_count,2)
            self.poisoned(obs);self.assertFalse(self.pool.calls)
            retry,retry_obs=self.store()
            with retry.writer(),self.assertRaisesRegex(ValueError,'Failed context cannot be reused'):
                self.borrow(retry,retry_obs)
            self.assertEqual(controlled.call_count,2);self.poisoned(retry_obs)

    def test_original_load_or_prepare_failure_after_reference_build_clears_all_state(self):
        for phase in ('cache.original_load_context','cache.original_prepare_catalog'):
            self.initialize();store,obs=self.store();entered=[]
            def watch():
                if self.inside(obs,phase):
                    entered.append((len(self.pool._typed_references),self.pool._typed_authority is not None))
                    raise RuntimeError('artificial original initialization failure')
            with self.subTest(phase=phase),store.writer(),self.assertRaisesRegex(RuntimeError,'original initialization failure'):
                self.borrow(store,obs,watch)
            self.assertEqual(entered,[(2,True)]);self.poisoned(obs);self.assertFalse(self.pool.calls)
            event=next(event for event in obs.events if event['phase']==phase)
            self.assertFalse(event['completed']);self.assertEqual(event['error_type'],'RuntimeError')

    def test_late_unsupported_utf8_and_cycle_errors_clear_all_reference_state(self):
        for kind in ('nonfinite','custom','utf8','cycle'):
            self.initialize();store,obs=self.store();changed=False
            def watch():
                nonlocal changed
                if not changed and self.inside(obs,'cache.original_prepare_catalog'):
                    if kind=='nonfinite':value=float('nan')
                    elif kind=='custom':value=object()
                    elif kind=='utf8':value='\ud800'
                    else:value=[];value.append(value)
                    self.config['typed_sentinel']=value;changed=True
            with self.subTest(kind=kind),store.writer(),self.assertRaises((ValueError,UnicodeEncodeError,RecursionError)):
                self.borrow(store,obs,watch)
            self.assertTrue(changed);self.poisoned(obs)

    def test_success_close_releases_both_references_and_expected_bytes(self):
        self.initialize();self.cycle();self.assertIsNotNone(self.pool._typed_references)
        self.pool.close()
        for name in ('_typed_references','_typed_authority','expected_config','expected_model','prepared','active'):
            self.assertIsNone(getattr(self.pool,name))

    def test_reference_release_in_seventh_finish_is_charged_without_gc(self):
        self.initialize();enabled=gc.isenabled();gc.disable();leases=None
        try:
            for ordinal in range(7):
                store,obs=self.store()
                with obs.span('run.total'),store.writer():
                    self.borrow(store,obs)
                    if ordinal==0:
                        leases=tuple(ref(tuple.__getitem__(reference,7)) for reference in self.pool._typed_references)
                        self.assertEqual(len(leases),2)
                    self.assertTrue(all(lease() is not None for lease in leases))
                    self.pool.finish(obs,lambda:None)
                    self.assertTrue(any(obs.events[index]['phase']=='run.total' for index in obs.stack))
                    if ordinal<6:
                        self.assertIsNotNone(self.pool._typed_references)
                        self.assertTrue(all(lease() is not None for lease in leases))
                    else:
                        self.assertIsNone(self.pool._typed_references)
                        self.assertTrue(all(lease() is None for lease in leases))
            receipt=self.pool.completed_summary()
            self.assertEqual(receipt['hits'],6);self.assertEqual(receipt['typed_reference']['reference_roots'],2)
        finally:
            if enabled:gc.enable()


if __name__=='__main__':unittest.main()
