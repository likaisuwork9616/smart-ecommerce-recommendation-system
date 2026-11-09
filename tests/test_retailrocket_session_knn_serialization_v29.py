"""Byte/exception fidelity and actual artificial C1 operation counts for replay only."""
from collections import Counter
import hashlib
from types import MappingProxyType
import unittest
from scripts import retailrocket_session_knn_reuse_v27 as c1
from scripts import inventory_retailrocket_session_knn_serialization_v29 as inventory
from scripts.retailrocket_session_knn_diagnostics_v20 import _clone
from tests.test_retailrocket_session_knn_reuse_v27 import ContextTests
from scripts.run_retailrocket_session_knn_v2 import ROOT


class SerializationTests(unittest.TestCase):
    def test_full_bytes_for_nested_typed_unicode_and_sorted_maps(self):
        measured=inventory.measured_canonical()
        for value in ({'漢字':'quote"\n\\','none':None,'int':-123,'bool':True},
                [False,0,1,0.0,-0.0,3.5,('1',2)],MappingProxyType({'b':2,'a':1}),
                {'first':MappingProxyType({'2':10,'1':1}),'first_times':(1,10),'fallback':('2','1')}):
            data,timing=measured(value);self.assertEqual(data,c1.canonical(value))
            self.assertEqual(timing['canonical_ns'],sum(timing[p] for p in inventory.PLAN['phases'][:3]))
            self.assertTrue(all(v>=0 for v in timing.values()))

    def test_type_tags_remain_distinct(self):
        measured=inventory.measured_canonical()
        for a,b in ((True,1),(False,0),([1],(1,)),(0.0,-0.0),(1,1.0)):
            self.assertNotEqual(measured(a)[0],measured(b)[0])

    def test_original_error_classes_are_preserved(self):
        measured=inventory.measured_canonical()
        for value in ({1:'bad key'},set(),float('nan'),float('inf'),'\ud800'):
            errors=[]
            for function in (c1.canonical,lambda x:measured(x)[0]):
                try:function(value)
                except Exception as error:errors.append(type(error))
            self.assertEqual(len(errors),2);self.assertIs(errors[0],errors[1])

    def test_digest_bytes_are_identical_to_frozen_digest(self):
        value={'first':MappingProxyType({'1':2}),'counts':MappingProxyType({'1':3}),'first_times':(2,),'fallback':('1',)}
        data,_=inventory.measured_canonical()(value)
        self.assertEqual(hashlib.sha256(data).hexdigest(),c1.digest(value))

    def test_phase_accounting_includes_tree_and_text_release_boundaries(self):
        measured=inventory.measured_canonical(clock=iter((100,200,500,700)).__next__)
        _,timing=measured({'a':1})
        self.assertEqual(timing,dict(typed_tree_ns=100,json_and_tree_release_ns=300,utf8_and_text_release_ns=200,canonical_ns=600))

    def test_56_canonical_22_digest_calls_match_unmodified_artificial_control_flow(self):
        fixture=ContextTests('runTest');fixture.setUp();self.addCleanup(fixture.doCleanups)
        calls=Counter();hashes=Counter()
        def role(v):
            if 'first_times' in v:return 'snapshot'
            if 'namespace' in v:return 'identity_key'
            if 'schemas' in v:return 'config'
            if 'support' in v:return 'model'
            return 'binding'
        def canonical(v):calls[role(v)]+=1;return c1.canonical(v)
        def digest(v):hashes[role(v)]+=1;return hashlib.sha256(canonical(v)).hexdigest()
        class Counted(c1.WorkerContext):pass
        for name in ('_identity','load','finish','_snapshot_digest'):
            setattr(Counted,name,_clone(getattr(c1.WorkerContext,name),canonical=canonical,digest=digest))
        fixture.pool=Counted(fixture.contract,fixture.root,ROOT)
        for _ in range(7):fixture.cycle()
        self.assertEqual(dict(calls),inventory.operation_counts()['all7'])
        self.assertEqual(sum(hashes.values()),22)
        self.assertEqual(dict(hashes),dict(identity_key=7,snapshot=15))


if __name__=='__main__':unittest.main()
