"""C1-only artificial sources and full four-arm differential acceptance."""
from copy import deepcopy
from datetime import datetime,timedelta,timezone
import hashlib
import json
import os
from pathlib import Path
import pickle
import tempfile
import unittest
from unittest.mock import patch

from scripts import retailrocket_session_knn_reuse_v27 as reuse
from scripts import retailrocket_session_knn_sources_v24 as observed
from scripts import retailrocket_session_knn_checkpoint_v2 as cp
from scripts import retailrocket_session_knn_pair_v4 as pair
from scripts import run_retailrocket_session_knn_v2 as io
from tests import test_retailrocket_session_knn_pair_v4 as four
from tests import test_retailrocket_session_knn_validation as fixture


class ContextTests(unittest.TestCase):
    def setUp(self):
        temp=tempfile.TemporaryDirectory();self.addCleanup(temp.cleanup);self.root=Path(temp.name)
        (self.root/'P0').mkdir();(self.root/'dataset').mkdir()
        (self.root/'P0/item_counts.csv').write_text('itemid,count\n1,3\n2,2\n',encoding='utf-8')
        (self.root/'dataset/catalog.csv').write_text('itemid,first_view_ms\n1,1\n2,2\n3,11\n',encoding='utf-8')
        self.config={'schemas':{'catalog.csv':['itemid','first_view_ms']},'train_window_ms':[0,10]}
        self.model={'support':{'1':2,'2':1},'fit_audit':{'fit_id':'artificial'}}
        self.paths={'P0':self.root/'P0','dataset':self.root/'dataset'}
        self.request={'kind':'artificial-only','deadline_utc':(datetime.now(timezone.utc)+timedelta(minutes=5)).isoformat(),'budget_seconds':300}
        self.counter=0;self.rebind()

    def rebind(self):
        (self.root/'configuration.json').write_text(json.dumps(self.config),encoding='utf-8')
        (self.root/'reconstruction.json').write_text(json.dumps({'receipt':self.model}),encoding='utf-8')
        records=cp.bind_sources(self.root,['P0/item_counts.csv','dataset/catalog.csv','configuration.json','reconstruction.json'])
        self.binding={'sources':records};d={x['path']:x for x in records}
        self.contract={'binding':self.binding,'dependencies':{k:d[p] for k,p in (
            ('counts','P0/item_counts.csv'),('catalog','dataset/catalog.csv'),('config','configuration.json'),('model','reconstruction.json'))},
            'methods':[io.describe(io.ROOT/'scripts/retailrocket_session_knn_reuse_v27.py')], 'environment':io.environment()}
        self.pool=reuse.WorkerContext(self.contract,self.root,io.ROOT)

    def store(self):
        self.counter+=1;obs=observed.Observation()
        store=reuse.ReuseStore.create(self.root/('store'+str(self.counter)),self.binding,
            self.request['deadline_utc'],300,source_root=self.root,observer=obs,
            expected_queries=1,required_stages=('reconstruction','queries'))
        return store,obs

    def load(self,store,obs,**kwargs):
        return self.pool.load(kwargs.get('paths',self.paths),kwargs.get('config',self.config),self.model['support'],lambda:None,
            model=kwargs.get('model',self.model),store=store,namespace=kwargs.get('namespace','artificial-window'),
            request=kwargs.get('request',self.request),observer=obs)

    def cycle(self):
        store,obs=self.store()
        with store.writer():
            counts,catalog=self.load(store,obs);prepared=self.pool.prepare(catalog,counts,lambda:None)
            self.pool.finish(obs,lambda:None)
        return store,obs,prepared

    def test_one_cold_build_six_hits(self):
        total=0
        for i in range(7):
            store,obs,p=self.cycle();total+=obs.summary()['source_descriptors']['completed_calls']
            self.assertEqual(store.full_checks,[dict(force=False,external=False),dict(force=True,external=False)])
            self.assertEqual(self.pool.calls[-1]['cold'],i==0)
        self.assertEqual(total,56)
        self.assertEqual(sum(x['cold'] for x in self.pool.calls),1)
        self.assertEqual(sum(x['hit'] for x in self.pool.calls),6)
        self.assertEqual(p.first_times,(1,2,11))
        self.assertEqual(p.fallback,('1','2','3'))
        self.assertEqual(self.pool.completed_summary()['hits'],6)

    def test_eighth_run_and_incomplete_summary_reject(self):
        self.cycle()
        with self.assertRaises(ValueError):self.pool.completed_summary()
        for _ in range(6):self.cycle()
        store,obs=self.store()
        with store.writer(),self.assertRaises(ValueError):self.load(store,obs)

    def test_accepted_environment_change_rejects(self):
        self.cycle();self.contract['environment']=dict(self.contract['environment'],python='changed')
        store,obs=self.store()
        with store.writer(),self.assertRaises(ValueError):self.load(store,obs)

    def test_source_changes_between_create_and_lock(self):
        store,obs=self.store();p=self.root/'P0/item_counts.csv';p.write_bytes(p.read_bytes().replace(b'1,3',b'1,4'))
        with self.assertRaises(cp.IntegrityError),store.writer():self.fail('Changed source reached borrower')
        self.assertIsNone(self.pool.prepared);self.assertIsNone(store._guard)

    def test_changed_source_on_warm_hit(self):
        self.cycle();p=self.root/'dataset/catalog.csv';p.write_bytes(p.read_bytes().replace(b'1,1',b'1,2'))
        with self.assertRaises(cp.IntegrityError):self.store()
        self.assertEqual(len(self.pool.calls),1)

    def test_same_bytes_different_path(self):
        self.cycle();(self.root/'other').mkdir();(self.root/'other/item_counts.csv').write_bytes((self.root/'P0/item_counts.csv').read_bytes())
        store,obs=self.store()
        with store.writer(),self.assertRaises(ValueError):self.load(store,obs,paths=dict(self.paths,P0=self.root/'other'))
        self.assertTrue(self.pool.poisoned)

    def test_changed_configuration(self):
        self.cycle();self.config['train_window_ms']=[0,12]
        store,obs=self.store()
        with store.writer(),self.assertRaises(ValueError):self.load(store,obs)

    def test_changed_complete_support_or_model_receipt(self):
        self.cycle();self.model['fit_audit']['unrelated_but_bound_field']=True
        store,obs=self.store()
        with store.writer(),self.assertRaises(ValueError):self.load(store,obs)

    def test_map_or_tuple_mutation_rejected(self):
        _,_,p=self.cycle()
        with self.assertRaises(TypeError):p.counts['1']=999
        with self.assertRaises(TypeError):p.first['1']=999
        with self.assertRaises(TypeError):p.first_times[0]=999
        object.__setattr__(p,'fallback',('3','2','1'))
        store,obs=self.store()
        with store.writer(),self.assertRaises(ValueError):self.load(store,obs)

    def test_forced_check_after_lock_before_cache_lookup(self):
        store,obs=self.store()
        with self.assertRaises(ValueError):self.load(store,obs)
        self.assertEqual(len(store.full_checks),1)

    def test_different_window_or_process(self):
        self.cycle();store,obs=self.store()
        with store.writer(),self.assertRaises(ValueError):self.load(store,obs,namespace='another-window')
        self.rebind();self.cycle();store,obs=self.store()
        with store.writer(),patch.object(reuse,'process_identity',return_value=(1,0.)),self.assertRaises(ValueError):self.load(store,obs)
        with self.assertRaises(TypeError):pickle.dumps(self.pool)

    def test_caller_model_or_config_mutation_rejected(self):
        store,obs=self.store()
        with store.writer():
            self.load(store,obs);self.model['support']['1']=1
            with self.assertRaises(ValueError):self.pool.finish(obs,lambda:None)
        self.assertTrue(self.pool.poisoned)


class FullVerifierTests(unittest.TestCase):
    def test_full_bytes_metrics_delta_hex_and_sql_workload_identical(self):
        with tempfile.TemporaryDirectory() as temp:
            with patch.object(four,'make_fixture',side_effect=lambda **kw:fixture.make_fixture(base=temp,**kw)):
                root,paths,config,primary,_,database,model,ordinals,binding=four.fixture(boundary=True)
            (root/'reconstruction.json').write_text(json.dumps({'receipt':model}),encoding='utf-8')
            binding['sources']=cp.bind_sources(root,[x['path'] for x in binding['sources']]+['reconstruction.json'])
            d={x['path']:x for x in binding['sources']}
            contract=dict(binding=binding,dependencies={k:d[p] for k,p in (
                ('counts','P0/item_counts.csv'),('catalog','dataset/catalog.csv'),('config','configuration.json'),('model','reconstruction.json'))},
                methods=[io.describe(io.ROOT/'scripts/retailrocket_session_knn_reuse_v27.py')],environment=io.environment())
            pool=reuse.WorkerContext(contract,root,io.ROOT);outputs=[];work=[]
            request=dict(deadline_utc=(datetime.now(timezone.utc)+timedelta(minutes=5)).isoformat(),budget_seconds=300)
            for label,mode in [('R','R'),('cold','C'),('hit','C')]:
                obs=observed.Observation();store=reuse.ReuseStore.create(root/label,binding,request['deadline_utc'],300,
                    source_root=root,observer=obs,expected_queries=len(ordinals),required_stages=('reconstruction','queries'))
                with store.writer():
                    four.reconstruct_seal(store,model)
                    verifier=observed.make_verifier(obs) if mode=='R' else reuse.make_verifier(obs,pool,'artificial-window',request)
                    measured=verifier(primary,paths,config,store,model,database,ordinals)
                outputs.append([cp.encoded(x) for x in store.iter_records()]);work.append([x['sql_workload'] for x in measured['queries']])
                self.assertEqual(obs.summary()['phases']['context.load_context']['calls'],1)
                self.assertEqual(obs.summary()['phases']['context.prepare_catalog']['calls'],1)
                self.assertGreater(measured['setup_seconds'],0)
            self.assertEqual(outputs[0],outputs[1]);self.assertEqual(outputs[1],outputs[2])
            self.assertEqual(work[0],work[1]);self.assertEqual(work[1],work[2])
            self.assertEqual([x['cold'] for x in pool.calls],[True,False])


if __name__=='__main__':unittest.main()
