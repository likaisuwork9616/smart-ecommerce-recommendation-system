"""Original mutable ownership observations; no ownership/canonical reuse candidate."""
from contextlib import contextmanager
from types import MappingProxyType
import unittest

from scripts import retailrocket_session_knn_reuse_v27 as c1
from scripts import retailrocket_session_knn_sources_v24 as observed
from tests import test_retailrocket_session_knn_reuse_v27 as focused


class ExistingOwnershipTests(unittest.TestCase):
    rebind=focused.ContextTests.rebind
    store=focused.ContextTests.store

    def setUp(self):
        focused.ContextTests.setUp(self)
        self.config['ownership_fixture']={'values':['A']}
        self.model['fit_audit']['ownership_fixture']={'values':['A']}
        self.rebind()

    @staticmethod
    def inside(observer,phase):
        return any(observer.events[index]['phase']==phase for index in observer.stack)

    def borrow(self,store,observer,watch=lambda:None,*,config=None,support=None):
        config=self.config if config is None else config
        support=self.model['support'] if support is None else support
        counts,catalog=self.pool.load(self.paths,config,support,watch,model=self.model,store=store,
            namespace='artificial-window',request=self.request,observer=observer)
        prepared=self.pool.prepare(catalog,counts,watch)
        self.assertEqual(store.full_checks,[dict(force=False,external=False),dict(force=True,external=False)])
        return prepared

    def poisoned(self):
        self.assertTrue(self.pool.poisoned);self.assertIsNone(self.pool.prepared);self.assertIsNone(self.pool.active)

    def test_nested_config_caller_alias_is_live_after_prepare_and_finish_rejects(self):
        alias=self.config['ownership_fixture']['values'];store,obs=self.store()
        with store.writer():
            self.borrow(store,obs)
            self.assertIs(self.pool.active[1],self.config)
            self.assertIs(self.pool.active[1]['ownership_fixture']['values'],alias)
            alias[0]='B'
            with self.assertRaisesRegex(ValueError,'Snapshot/caller changed'):self.pool.finish(obs,lambda:None)
        self.poisoned()

    def test_nested_model_caller_alias_is_live_after_prepare_and_finish_rejects(self):
        alias=self.model['fit_audit']['ownership_fixture']['values'];store,obs=self.store()
        with store.writer():
            self.borrow(store,obs);self.assertIs(self.pool.active[2],self.model)
            self.assertIs(self.pool.active[2]['fit_audit']['ownership_fixture']['values'],alias)
            alias.append('B')
            with self.assertRaisesRegex(ValueError,'Snapshot/caller changed'):self.pool.finish(obs,lambda:None)
        self.poisoned()

    def test_equal_support_copy_is_rejected_because_original_API_requires_model_alias(self):
        copied=dict(self.model['support']);self.assertEqual(copied,self.model['support']);self.assertIsNot(copied,self.model['support'])
        store,obs=self.store()
        with store.writer(),self.assertRaisesRegex(ValueError,'Caller support differs'):self.borrow(store,obs,support=copied)
        self.poisoned();self.assertFalse(self.pool.calls)

    def test_shared_support_alias_can_change_to_valid_value_during_original_load(self):
        support=self.model['support'];before=c1.canonical(self.model);store,obs=self.store();changed=False
        def watch():
            nonlocal changed
            if not changed and self.inside(obs,'cache.original_load_context'):
                support['1']=3;changed=True
        with store.writer():
            self.borrow(store,obs,watch);self.assertTrue(changed)
            self.assertIs(self.pool.active[2]['support'],support);self.assertEqual(support['1'],3)
            self.assertNotEqual(before,self.pool.expected_model);self.assertEqual(self.pool.expected_model,c1.canonical(self.model))
            self.pool.finish(obs,watch)
        self.assertFalse(self.pool.poisoned);self.assertIsNone(self.pool.active)

    def test_shared_support_alias_invalid_during_load_is_rejected_and_poisoned(self):
        support=self.model['support'];store,obs=self.store();changed=False
        def watch():
            nonlocal changed
            if not changed and self.inside(obs,'cache.original_load_context'):
                support['1']=4;changed=True
        with store.writer(),self.assertRaisesRegex(ValueError,'Oracle P0/C1 support mismatch'):self.borrow(store,obs,watch)
        self.assertTrue(changed);self.poisoned();self.assertFalse(self.pool.calls)

    def test_watch_callback_can_mutate_nested_config_before_original_late_capture(self):
        alias=self.config['ownership_fixture']['values'];before=c1.canonical(self.config);store,obs=self.store();changed=False
        def watch():
            nonlocal changed
            if not changed and self.inside(obs,'cache.original_prepare_catalog'):
                alias[0]='B';changed=True
        with store.writer():
            self.borrow(store,obs,watch);self.assertTrue(changed);self.assertNotEqual(before,self.pool.expected_config)
            self.assertEqual(self.pool.expected_config,c1.canonical(self.config));self.pool.finish(obs,watch)
        self.assertFalse(self.pool.poisoned)

    def test_observer_callback_can_mutate_nested_model_before_original_late_capture(self):
        owner=self;changed=[];before=c1.canonical(self.model)
        class MutatingObserver(observed.Observation):
            @contextmanager
            def span(inner,phase,**metadata):
                with super().span(phase,**metadata) as event:
                    if phase=='cache.original_prepare_catalog':
                        owner.model['fit_audit']['ownership_fixture']['values'][0]='B';changed.append(phase)
                    yield event
        obs=MutatingObserver()
        store=c1.ReuseStore.create(self.root/'observer-store',self.binding,self.request['deadline_utc'],300,
            source_root=self.root,observer=obs,expected_queries=1,required_stages=('reconstruction','queries'))
        with store.writer():
            self.borrow(store,obs);self.assertEqual(changed,['cache.original_prepare_catalog'])
            self.assertNotEqual(before,self.pool.expected_model);self.assertEqual(self.pool.expected_model,c1.canonical(self.model))
            self.pool.finish(obs,lambda:None)
        self.assertFalse(self.pool.poisoned);self.assertFalse(obs.stack)

    def test_mappingproxy_is_shallow_and_nested_alias_still_reaches_live_config(self):
        proxy=MappingProxyType(self.config);alias=proxy['ownership_fixture']['values'];store,obs=self.store()
        with store.writer():
            self.borrow(store,obs,config=proxy);self.assertIs(self.pool.active[1],proxy)
            with self.assertRaises(TypeError):proxy['ownership_fixture']={}
            alias[0]='B';self.assertEqual(proxy['ownership_fixture']['values'],['B'])
            with self.assertRaisesRegex(ValueError,'Snapshot/caller changed'):self.pool.finish(obs,lambda:None)
        self.poisoned()

    def test_mappingproxy_does_not_own_its_mutable_backing_dictionary(self):
        backing=self.config;proxy=MappingProxyType(backing);store,obs=self.store()
        with store.writer():
            self.borrow(store,obs,config=proxy);backing['new_caller_field']='B'
            self.assertEqual(proxy['new_caller_field'],'B')
            with self.assertRaisesRegex(ValueError,'Snapshot/caller changed'):self.pool.finish(obs,lambda:None)
        self.poisoned()

    def test_retained_immutable_bytes_are_not_proof_of_live_caller_ownership(self):
        store,obs=self.store()
        with store.writer():
            self.borrow(store,obs);retained=self.pool.expected_config;self.assertIs(type(retained),bytes)
            original_copy=bytes(retained);self.config['ownership_fixture']['values'][0]='B'
            self.assertEqual(retained,original_copy);self.assertNotEqual(retained,c1.canonical(self.config))
            with self.assertRaisesRegex(ValueError,'Snapshot/caller changed'):self.pool.finish(obs,lambda:None)
        self.poisoned()

    def test_after_late_capture_expected_A_then_B_restored_A_original_finish_still_accepts(self):
        store,obs=self.store();alias=self.config['ownership_fixture']['values']
        with store.writer():
            self.borrow(store,obs);expected_A=self.pool.expected_config
            self.assertEqual(expected_A,c1.canonical(self.config));alias[0]='B'
            self.assertNotEqual(expected_A,c1.canonical(self.config));alias[0]='A'
            self.assertEqual(expected_A,c1.canonical(self.config));self.pool.finish(obs,lambda:None)
        self.assertFalse(self.pool.poisoned);self.assertIsNone(self.pool.active)

    def test_list_to_tuple_freezing_changes_typed_canonical_and_original_receipt_comparison(self):
        changed=dict(self.config,train_window_ms=tuple(self.config['train_window_ms']))
        self.assertEqual(list(changed['train_window_ms']),self.config['train_window_ms'])
        self.assertNotEqual(c1.canonical(changed),c1.canonical(self.config))
        store,obs=self.store()
        with store.writer(),self.assertRaisesRegex(ValueError,'Live configuration/model differs from exact verified receipt'):
            self.borrow(store,obs,config=changed)
        self.poisoned();self.assertFalse(self.pool.calls)


if __name__=='__main__':unittest.main()
