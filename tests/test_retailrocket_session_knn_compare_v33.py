import copy
import unittest
from unittest.mock import patch

from scripts import analyze_retailrocket_session_knn_compare_v33 as a


class ProvenanceTests(unittest.TestCase):
    def setUp(self):
        self.request={'sources':[dict(a.ANCESTOR)]}
        self.ancestor={'methods':[dict(a.EXPECTED_HELPER)]}
        self.describe=patch.object(a,'describe',side_effect=lambda p:dict(a.ANCESTOR if p==a.ROOT/a.ANCESTOR['path'] else a.EXPECTED_HELPER))
        self.read=patch.object(a,'read',return_value=self.ancestor)
        self.describe.start();self.read.start();self.addCleanup(self.describe.stop);self.addCleanup(self.read.stop)

    def test_exact_indirect(self):
        result=a.attest(self.request)
        self.assertEqual(result['helper'],a.EXPECTED_HELPER);self.assertFalse(result['original_direct_source'])
        self.assertFalse(result['priority_runtime_direct_hash']);self.assertFalse(result['priority_per_borrow_method'])

    def test_missing_ancestor(self):
        with self.assertRaises(ValueError):a.attest({'sources':[]})

    def test_wrong_bound_ancestor_sha(self):
        self.request['sources'][0]['sha256']='0'*64
        with self.assertRaises(ValueError):a.attest(self.request)

    def test_changed_current_ancestor(self):
        with patch.object(a,'describe',return_value={**a.ANCESTOR,'bytes':1}):
            with self.assertRaises(ValueError):a.attest(self.request)

    def test_wrong_helper_binding(self):
        self.ancestor['methods'][0]['sha256']='0'*64
        with self.assertRaises(ValueError):a.attest(self.request)

    def test_multiple_helper_bindings(self):
        self.ancestor['methods'].append(dict(a.EXPECTED_HELPER))
        with self.assertRaises(ValueError):a.attest(self.request)

    def test_missing_helper_binding(self):
        self.ancestor['methods']=[]
        with self.assertRaises(ValueError):a.attest(self.request)

    def test_duplicate_source(self):
        self.request['sources'].append(dict(a.ANCESTOR))
        with self.assertRaises(ValueError):a.attest(self.request)

    def test_conflicting_direct_helper(self):
        self.request['sources'].append({**a.EXPECTED_HELPER,'bytes':1})
        with self.assertRaises(ValueError):a.attest(self.request)

    def test_changed_current_helper(self):
        with patch.object(a,'describe',side_effect=lambda p:dict(a.ANCESTOR) if p==a.ROOT/a.ANCESTOR['path'] else {**a.EXPECTED_HELPER,'bytes':1}):
            with self.assertRaises(ValueError):a.attest(self.request)


class AdapterTests(unittest.TestCase):
    def test_exact_clone_preserves_other_dependencies_and_numbers(self):
        source={'status':'old','dependencies':[{'path':p} for p in a.DIRECT],'checks':672,'decision':{'adopted':False},'formal_modes':{'C':123}}
        proof={'helper':dict(a.EXPECTED_HELPER),'kind':'indirect_provenance'}
        with patch.object(a,'read',side_effect=[{'namespace':'private'},{},{}]),patch.object(a,'attest',return_value=proof) as attest,\
                patch.object(a,'_clone',return_value=lambda:copy.deepcopy(source)) as clone,patch.object(a,'describe',return_value={'path':a.old31.METHOD}):
            result=a.build()
        clone.assert_called_once_with(a.old31.build,DEPENDENCIES=tuple(p for p in a.old31.DEPENDENCIES if p!=a.HELPER),METHOD=a.METHOD)
        self.assertEqual(attest.call_count,2);self.assertIn(a.old31.METHOD,a.DIRECT)
        self.assertEqual(result['dependencies'],source['dependencies']+[a.EXPECTED_HELPER])
        self.assertEqual(result['formal_modes'],source['formal_modes']);self.assertEqual(result['checks'],672)
        self.assertEqual(result['analysis_stage'],'postexit_only');self.assertEqual(result['new_real_runs'],0)

    def test_post_attestation_change_rejected(self):
        with patch.object(a,'read',side_effect=[{'namespace':'private'},{},{}]),\
                patch.object(a,'attest',side_effect=[{'helper':a.EXPECTED_HELPER},{'helper':{}}]),\
                patch.object(a,'_clone',return_value=lambda:{'dependencies':[]}):
            with self.assertRaises(ValueError):a.build()


if __name__=='__main__':unittest.main()
