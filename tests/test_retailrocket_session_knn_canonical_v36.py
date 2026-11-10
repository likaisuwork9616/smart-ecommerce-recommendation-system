"""Original late canonical guards: timing counterexamples, not candidate acceptance."""
import unittest

from scripts import retailrocket_session_knn_reuse_v27 as c1
from tests import test_retailrocket_session_knn_reuse_v27 as focused


class OriginalLateGuardTests(unittest.TestCase):
    setUp=focused.ContextTests.setUp
    rebind=focused.ContextTests.rebind
    store=focused.ContextTests.store

    def initialize(self):
        self.config['unrelated_sentinel']='A'
        self.model['fit_audit']['unrelated_sentinel']='A'
        self.rebind()
        return c1.canonical(self.config),c1.canonical(self.model)

    def borrow(self,store,observer,watch):
        counts,catalog=self.pool.load(self.paths,self.config,self.model['support'],watch,
            model=self.model,store=store,namespace='artificial-window',request=self.request,observer=observer)
        return self.pool.prepare(catalog,counts,watch)

    @staticmethod
    def inside(observer,phase):
        return any(observer.events[index]['phase']==phase for index in observer.stack)

    def test_config_ABA_after_initial_validation_is_rejected_by_original_late_guard(self):
        early,_=self.initialize();store,obs=self.store();changed=False
        def watch():
            nonlocal changed
            if not changed and self.inside(obs,'cache.original_load_context'):
                self.config['unrelated_sentinel']='B';changed=True
        with store.writer():
            self.borrow(store,obs,watch);self.assertTrue(changed)
            late=c1.canonical(self.config);self.assertEqual(self.pool.expected_config,late);self.assertNotEqual(late,early)
            self.config['unrelated_sentinel']='A'
            # This equality is the proposed naive reuse rule's counterexample.
            self.assertEqual(early,c1.canonical(self.config))
            with self.assertRaises(ValueError):self.pool.finish(obs,watch)
        self.assertTrue(self.pool.poisoned);self.assertIsNone(self.pool.prepared)

    def test_model_ABA_during_prepare_is_rejected_by_original_late_guard(self):
        _,early=self.initialize();store,obs=self.store();changed=False
        def watch():
            nonlocal changed
            if not changed and self.inside(obs,'cache.original_prepare_catalog'):
                self.model['fit_audit']['unrelated_sentinel']='B';changed=True
        with store.writer():
            self.borrow(store,obs,watch);self.assertTrue(changed)
            late=c1.canonical(self.model);self.assertEqual(self.pool.expected_model,late);self.assertNotEqual(late,early)
            self.model['fit_audit']['unrelated_sentinel']='A'
            self.assertEqual(early,c1.canonical(self.model))
            with self.assertRaises(ValueError):self.pool.finish(obs,watch)
        self.assertTrue(self.pool.poisoned);self.assertIsNone(self.pool.prepared)

    def test_persistent_B_is_accepted_by_original_late_baseline_despite_source_A(self):
        early_config,early_model=self.initialize();store,obs=self.store();changed=False
        def watch():
            nonlocal changed
            if not changed and self.inside(obs,'cache.original_load_context'):
                self.config['unrelated_sentinel']='B';self.model['fit_audit']['unrelated_sentinel']='B';changed=True
        with store.writer():
            self.borrow(store,obs,watch);self.assertTrue(changed)
            self.assertNotEqual(early_config,self.pool.expected_config);self.assertNotEqual(early_model,self.pool.expected_model)
            self.assertEqual(self.pool.expected_config,c1.canonical(self.config));self.assertEqual(self.pool.expected_model,c1.canonical(self.model))
            self.pool.finish(obs,watch)
        self.assertFalse(self.pool.poisoned);self.assertIsNone(self.pool.active)
        # An early-source equality condition would be stricter than this baseline.
        self.assertNotEqual(early_config,c1.canonical(self.config));self.assertNotEqual(early_model,c1.canonical(self.model))

    def test_restore_A_before_original_late_capture_remains_accepted(self):
        early_config,early_model=self.initialize();store,obs=self.store();changed=False;restored=False
        def watch():
            nonlocal changed,restored
            if not changed and self.inside(obs,'cache.original_load_context'):
                self.config['unrelated_sentinel']='B';self.model['fit_audit']['unrelated_sentinel']='B';changed=True
            elif changed and not restored and self.inside(obs,'cache.original_prepare_catalog'):
                self.config['unrelated_sentinel']='A';self.model['fit_audit']['unrelated_sentinel']='A';restored=True
        with store.writer():
            self.borrow(store,obs,watch);self.assertTrue(changed);self.assertTrue(restored)
            self.assertEqual(self.pool.expected_config,early_config);self.assertEqual(self.pool.expected_model,early_model)
            self.pool.finish(obs,watch)
        self.assertFalse(self.pool.poisoned)

    def test_NaN_at_original_late_config_capture_rejects_before_borrow(self):
        self.initialize();store,obs=self.store();changed=False
        def watch():
            nonlocal changed
            if not changed and self.inside(obs,'cache.original_load_context'):
                self.config['unrelated_sentinel']=float('nan');changed=True
        with store.writer(),self.assertRaisesRegex(ValueError,'Nonfinite semantic value'):
            self.borrow(store,obs,watch)
        self.assertTrue(changed);self.assertTrue(self.pool.poisoned);self.assertFalse(self.pool.calls)
        self.assertFalse(any(event['phase']=='cache.use' for event in obs.events))

    def test_custom_value_at_original_late_model_capture_rejects_before_borrow(self):
        self.initialize();store,obs=self.store();changed=False
        def watch():
            nonlocal changed
            if not changed and self.inside(obs,'cache.original_prepare_catalog'):
                self.model['fit_audit']['unrelated_sentinel']=object();changed=True
        with store.writer(),self.assertRaisesRegex(ValueError,'Unsupported mutable or custom semantic value'):
            self.borrow(store,obs,watch)
        self.assertTrue(changed);self.assertTrue(self.pool.poisoned);self.assertFalse(self.pool.calls)
        self.assertFalse(any(event['phase']=='cache.use' for event in obs.events))


if __name__=='__main__':unittest.main()
