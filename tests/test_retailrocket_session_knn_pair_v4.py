"""Exact V4 paired payloads, unchanged global replay, and crash boundaries."""
from datetime import datetime,timezone,timedelta
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import unittest

from scripts import retailrocket_session_knn_pair_v4 as pair
from scripts import retailrocket_session_knn_checkpoint_v2 as cp
from scripts import retailrocket_session_knn_readback as v1
from scripts import retailrocket_session_knn_sql_v2 as sql
from scripts import retailrocket_session_knn_io as artificial
from tests.test_retailrocket_session_knn_validation import make_fixture


def fixture(boundary=False):
    root,paths,config=make_fixture(boundary=boundary)
    config['synthetic_acceptance_only']=True
    (root/'configuration.json').write_text(json.dumps(config),encoding='utf-8')
    primary=root/'primary';primary.mkdir();artificial.build(primary,paths,config)
    reference=v1.verify(primary,paths,config)
    import sqlite3
    database=primary/'oracle.sqlite';db=sqlite3.connect(database)
    try:
        sql.build_index(db);db.commit()
        support=dict(db.execute('SELECT i,COUNT(*) FROM m GROUP BY i'))
    finally:db.close()
    model={'fit_audit':reference['fit_audit'],'support':support}
    ordinals=[{'key':r['key'],'original_ordinal':i,'subset_ordinal':i}
              for i,r in enumerate(v1.rows(primary/'queries.jsonl'))]
    binding={'sources':cp.bind_sources(root,[p.relative_to(root).as_posix()
                         for p in root.rglob('*') if p.is_file()]),'configuration':config,'method':'v4_synthetic'}
    return root,paths,config,primary,reference,database,model,ordinals,binding


def create(root,config,binding,name='v4',**kwargs):
    return pair.TimedStore.create(root/name,binding,
        (datetime.now(timezone.utc)+timedelta(minutes=15)).isoformat(),900,
        source_root=root,expected_queries=config['fixed_validation']['queries'],
        required_stages=('reconstruction','queries','global','bootstrap'),chunk_queries=2,**kwargs)


def reconstruct_seal(store,model):
    if store.get_stage('reconstruction') is None:
        store.seal_stage('reconstruction',{'kind':'synthetic_verified_model','fit_audit':model['fit_audit']})


class Interrupted(Exception):pass


class PairV4Tests(unittest.TestCase):
    def test_v3_baseline_v4_payload_bytes_and_full_global_equivalence(self):
        for boundary in (False,True):
            with self.subTest(boundary=boundary):
                root,paths,config,primary,reference,database,model,ordinals,binding=fixture(boundary)
                baseline=create(root,config,binding,'baseline')
                with baseline.writer():
                    reconstruct_seal(baseline,model)
                    pair.verify_selected(primary,paths,config,baseline,model,database,ordinals,baseline=True)
                current=create(root,config,binding)
                with current.writer():
                    reconstruct_seal(current,model)
                    result=pair.run_synthetic_acceptance(primary,paths,config,current,model,database,ordinals)
                self.assertEqual(result['aggregate'],reference['aggregate'])
                self.assertEqual(result['bootstrap_replicates'],2000)
                old=list(baseline.iter_records());new=list(current.iter_records())
                self.assertEqual([cp.encoded(r) for r in old],[cp.encoded(r) for r in new])
                self.assertFalse((current.folder/'acceptance.json').exists())
                cp.verify_sources(root,binding['sources'])

    def test_algorithm_and_commit_fault_recovery_matches_full_reference(self):
        root,paths,config,primary,reference,database,model,ordinals,binding=fixture()
        points=('query_work','before_append','query_verified','after_queries_sealed','global_replay',
                'bootstrap_draw','before_candidate','payload_half_written','after_payload_fsync',
                'before_manifest_commit','after_manifest_commit')
        for point in points:
            with self.subTest(point=point):
                seen=0
                def fault(event):
                    nonlocal seen
                    if event==point:
                        seen+=1
                        if seen==(3 if point in ('query_work','before_append','query_verified') else 1):
                            raise Interrupted(point)
                store=create(root,config,binding,'fault_'+point,fault=fault)
                with self.assertRaises(Interrupted),store.writer():
                    reconstruct_seal(store,model)
                    pair.run_synthetic_acceptance(primary,paths,config,store,model,database,ordinals,fault=fault)
                self.assertFalse((store.folder/'acceptance.json').exists())
                resumed=pair.TimedStore.open(store.folder,binding,source_root=root)
                with resumed.writer():
                    reconstruct_seal(resumed,model)
                    result=pair.run_synthetic_acceptance(primary,paths,config,resumed,model,database,ordinals)
                self.assertEqual(result['aggregate'],reference['aggregate'])
                self.assertEqual(resumed.recover()['records'],7)

    def test_commit_time_is_separate_but_not_removed(self):
        root,paths,config,primary,reference,database,model,ordinals,binding=fixture()
        store=create(root,config,binding)
        with store.writer():
            reconstruct_seal(store,model)
            result=pair.verify_selected(primary,paths,config,store,model,database,ordinals)
        self.assertEqual(sum(x['records'] for x in result['chunk_commits']),7)
        self.assertEqual(len(result['chunk_commits']),4)
        self.assertGreater(store.commit_seconds,0)
        for row in result['queries']:
            self.assertGreaterEqual(row['checkpoint_append_seconds'],row['chunk_commit_seconds'])
            self.assertAlmostEqual(row['append_without_commit_seconds']+row['chunk_commit_seconds'],
                                   row['checkpoint_append_seconds'],places=8)

    def test_committed_corruption_and_source_mutation_refuse_resume(self):
        root,paths,config,primary,reference,database,model,ordinals,binding=fixture()
        store=create(root,config,binding)
        with store.writer():
            reconstruct_seal(store,model)
            pair.verify_selected(primary,paths,config,store,model,database,ordinals)
        payload=next((store.folder/'payloads').glob('*.jsonl'))
        value=payload.read_bytes();payload.write_bytes(value.replace(b'expected',b'Expected',1))
        with self.assertRaises(cp.IntegrityError),store.writer():pass
        self.assertTrue((store.folder/'integrity_failed.json').exists())
        target=primary/'fit_audit.json';target.write_bytes(target.read_bytes().replace(b'fit_id',b'fit_iD'))
        with self.assertRaises(cp.IntegrityError):pair.TimedStore.open(store.folder,binding,source_root=root)

    def test_tolerated_metric_keeps_actual_binary_delta_bits(self):
        root,paths,config,primary,reference,database,model,ordinals,binding=fixture()
        values=list(v1.rows(primary/'queries.jsonl'));row=values[0]
        row['terms']['K1']['ndcg']+=1e-13
        for arm in ('C1','D1','P0'):
            row['delta']['K1_minus_'+arm]['ndcg']=row['terms']['K1']['ndcg']-row['terms'][arm]['ndcg']
        (primary/'queries.jsonl').write_text(''.join(json.dumps(r)+'\n' for r in values),encoding='utf-8')
        binding['sources']=cp.bind_sources(root,[r['path'] for r in binding['sources']])
        store=create(root,config,binding)
        with store.writer():
            reconstruct_seal(store,model)
            pair.verify_selected(primary,paths,config,store,model,database,ordinals)
        payload=next(store.iter_records())['payload']
        self.assertEqual(payload['expected']['terms']['K1'],row['terms']['K1'])
        self.assertEqual(payload['delta_hex']['K1_minus_C1']['ndcg'],row['delta']['K1_minus_C1']['ndcg'].hex())

    def test_real_full_entry_is_unavailable(self):
        root,paths,config,primary,reference,database,model,ordinals,binding=fixture()
        config.pop('synthetic_acceptance_only')
        with self.assertRaises(ValueError):
            pair.run_synthetic_acceptance(primary,paths,config,None,model,database,ordinals)
        with self.assertRaises(ValueError):
            pair.verify_selected(primary,paths,config,None,model,database,ordinals*10)

    def test_real_process_candidate_crash_replays_then_supervisor_accepts(self):
        root,paths,config,primary,reference,database,model,ordinals,binding=fixture()
        store=create(root,config,binding)
        request={'root':str(root),'paths':{k:str(v) for k,v in paths.items()},'config':config,
                 'primary':str(primary),'database':str(database),'model':model,'ordinals':ordinals,
                 'binding':binding,'store':str(store.folder)}
        path=root/'request.json';path.write_text(json.dumps(request),encoding='utf-8')
        code='''
import json,os,sys
from pathlib import Path
from scripts import retailrocket_session_knn_pair_v4 as pair
r=json.loads(Path(sys.argv[1]).read_text(encoding='utf-8'))
def fault(event):
 if sys.argv[2]=='crash' and event=='after_candidate_commit':os._exit(9)
s=pair.TimedStore.open(r['store'],r['binding'],source_root=r['root'],fault=fault)
with s.writer():
 if s.get_stage('reconstruction') is None:s.seal_stage('reconstruction',{'kind':'synthetic_verified_model','fit_audit':r['model']['fit_audit']})
 pair.run_synthetic_acceptance(Path(r['primary']),{k:Path(v) for k,v in r['paths'].items()},r['config'],s,r['model'],Path(r['database']),r['ordinals'])
'''
        command=[sys.executable,'-B','-c',code,str(path)]
        crashed=subprocess.run(command+['crash'],capture_output=True,text=True,timeout=120)
        self.assertEqual(crashed.returncode,9,crashed.stderr)
        old=cp.read(store.folder/'candidate.json')
        self.assertFalse((store.folder/'normal_worker_exit.json').exists())
        resumed=subprocess.run(command+['complete'],capture_output=True,text=True,timeout=120)
        self.assertEqual(resumed.returncode,0,resumed.stderr)
        new=cp.read(store.folder/'candidate.json')
        self.assertNotEqual(old['worker_identity'],new['worker_identity'])
        self.assertEqual(new['receipt']['aggregate'],reference['aggregate'])
        reopened=pair.TimedStore.open(store.folder,binding,source_root=root)
        accepted=reopened.finalize(cp.descriptor(store.folder,'candidate.json')['sha256'],
                                   new['worker_identity'],resumed.returncode)
        self.assertEqual(accepted['status'],'separate_v2_readback_complete')

    def test_real_process_query_crash_resumes_only_committed_prefix(self):
        root,paths,config,primary,reference,database,model,ordinals,binding=fixture()
        store=create(root,config,binding)
        request={'root':str(root),'paths':{k:str(v) for k,v in paths.items()},'config':config,
                 'primary':str(primary),'database':str(database),'model':model,'ordinals':ordinals,
                 'binding':binding,'store':str(store.folder)}
        path=root/'request.json';path.write_text(json.dumps(request),encoding='utf-8')
        code='''
import json,os,sys
from pathlib import Path
from scripts import retailrocket_session_knn_pair_v4 as pair
r=json.loads(Path(sys.argv[1]).read_text(encoding='utf-8'));n=0
def fault(event):
 global n
 if event=='query_verified':
  n+=1
  if sys.argv[2]=='crash' and n==3:os._exit(9)
s=pair.TimedStore.open(r['store'],r['binding'],source_root=r['root'])
with s.writer():
 if s.get_stage('reconstruction') is None:s.seal_stage('reconstruction',{'kind':'synthetic_verified_model','fit_audit':r['model']['fit_audit']})
 pair.run_synthetic_acceptance(Path(r['primary']),{k:Path(v) for k,v in r['paths'].items()},r['config'],s,r['model'],Path(r['database']),r['ordinals'],fault=fault)
'''
        command=[sys.executable,'-B','-c',code,str(path)]
        crashed=subprocess.run(command+['crash'],capture_output=True,text=True,timeout=120)
        self.assertEqual(crashed.returncode,9,crashed.stderr)
        self.assertEqual(store.recover()['records'],2)
        self.assertFalse((store.folder/'candidate.json').exists())
        resumed=subprocess.run(command+['complete'],capture_output=True,text=True,timeout=120)
        self.assertEqual(resumed.returncode,0,resumed.stderr)
        candidate=cp.read(store.folder/'candidate.json')
        self.assertEqual(candidate['receipt']['aggregate'],reference['aggregate'])
        self.assertEqual(store.recover()['records'],7)


if __name__=='__main__':unittest.main()
