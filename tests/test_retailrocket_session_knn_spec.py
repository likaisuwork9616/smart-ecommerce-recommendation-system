"""Metadata guard regressions only; never execute K1 or decode research rows."""
import copy
import contextlib
import uuid
import unittest
from pathlib import Path
from scripts import freeze_retailrocket_session_knn_v1 as spec


@contextlib.contextmanager
def fixture():
    # Retain tiny synthetic evidence inside the ignored workspace; no recursive deletion.
    root = spec.path(spec.ROOT, spec.EVIDENCE+'/synthetic/'+uuid.uuid4().hex)
    root.mkdir(parents=True)
    yield root


class ProtocolTests(unittest.TestCase):
    def setUp(self):
        self.p = spec.read(spec.ROOT,spec.POLICY)
        self.i = spec.read(spec.ROOT,spec.INVENTORY)
        self.parent = spec.read(spec.ROOT,'docs/contracts/retailrocket_directed_paired_v1.json')

    def test_valid_spec(self):
        self.assertGreater(len(spec.validate(self.p,self.i,self.parent)),50)

    def test_reject_method_or_neighbor_changes(self):
        for section,key,value in [('model','neighbor_count',100),('model','self_item_votes',False),
                                  ('model','unknown_seeds','drop unknowns'),('model','index','sample sessions'),
                                  ('model','neighbor_eligibility','include current session'),
                                  ('comparison','search',True)]:
            with self.subTest(key=key):
                p=copy.deepcopy(self.p); p[section][key]=value
                with self.assertRaises(ValueError): spec.validate(p,self.i,self.parent)

    def test_reject_test_or_refit_unlock(self):
        for section,key,value in [('reserved_test','state','open'),('reserved_test','K1_test_authorized',True),
                                  ('comparison','test_ranking',True),('comparison','final_refit',True)]:
            with self.subTest(key=key):
                p=copy.deepcopy(self.p); p[section][key]=value
                with self.assertRaises(ValueError): spec.validate(p,self.i,self.parent)

    def test_reject_changed_roster_or_primary(self):
        for section,key,value in [('fixed_validation','queries',161211),('comparison','primary_control','P0'),
                                  ('evaluation','primary_estimand','choose best arm'),('ranking','negative_sampling',True)]:
            with self.subTest(key=key):
                p=copy.deepcopy(self.p); p[section][key]=value
                with self.assertRaises(ValueError): spec.validate(p,self.i,self.parent)

    def test_reject_bootstrap_changes(self):
        p=copy.deepcopy(self.p); p['uncertainty']['replicates']=100
        with self.assertRaises(ValueError): spec.validate(p,self.i,self.parent)

    def test_reject_bool_as_count(self):
        p=copy.deepcopy(self.p); p['comparison']['challenger_count']=True
        with self.assertRaises(ValueError): spec.validate(p,self.i,self.parent)

    def test_reject_false_availability_claim(self):
        i=copy.deepcopy(self.i); i['new_temporal_sources_accepted']=1
        with self.assertRaises(ValueError): spec.validate(self.p,i,self.parent)

    def test_reject_changed_resource_limit(self):
        p=copy.deepcopy(self.p); p['resources']['limits']['maximum_elapsed_seconds']=999999
        with self.assertRaises(ValueError): spec.validate(p,self.i,self.parent)

    def test_reject_data_row_decoder(self):
        for name in ['anything.csv','queries.jsonl']:
            with self.assertRaisesRegex(ValueError,'metadata JSON'): spec.read(spec.ROOT,name)

    def test_reject_unsafe_paths(self):
        for name in ['../escape.json','C:/escape.json','/absolute.json','a\\b.json','CON.json']:
            with self.subTest(name=name):
                with self.assertRaises(ValueError): spec.path(spec.ROOT,name)

    def test_detect_same_size_tampering_and_refuse_overwrite(self):
        # Temporary fixture paths are isolated; no real study source is edited.
        with fixture() as folder:
            root=Path(folder).resolve()
            spec.write_new(root,'fixture.json',{'x':1})
            record=spec.describe(root,'fixture.json')
            spec.check(root,record)
            with self.assertRaises(FileExistsError): spec.write_new(root,'fixture.json',{'x':2})
            target=spec.path(root,'fixture.json')
            target.write_text(target.read_text(encoding='utf-8').replace('1','2'),encoding='utf-8')
            with self.assertRaisesRegex(ValueError,'Frozen bytes differ'): spec.check(root,record)

    def test_partial_namespace_blocks_freeze(self):
        with fixture() as folder:
            root=Path(folder).resolve()
            spec.path(root,spec.PRIVATE).mkdir(parents=True)
            with self.assertRaisesRegex(ValueError,'not empty'): spec.freeze(root)


if __name__ == '__main__':
    unittest.main()
