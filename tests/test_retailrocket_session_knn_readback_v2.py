"""Synthetic full four-arm equivalence and interrupted verified-ledger replay."""
from datetime import datetime,timezone,timedelta
import json
import subprocess
import sys
import unittest

from scripts import retailrocket_session_knn_readback_v2 as v2
from scripts import retailrocket_session_knn_checkpoint_v2 as cp
from scripts import retailrocket_session_knn_readback as v1
from scripts import retailrocket_session_knn_io as synthetic_primary
from tests.test_retailrocket_session_knn_validation import make_fixture


def fixture(boundary=False):
    root,paths,config=make_fixture(boundary=boundary)
    primary=root/'primary';primary.mkdir()
    synthetic_primary.build(primary,paths,config)
    # Artificial primary creation is test-only. V2 never imports this adapter.
    reference=v1.verify(primary,paths,config)
    sources=[p.relative_to(root).as_posix() for p in root.rglob('*') if p.is_file()]
    binding={'sources':cp.bind_sources(root,sources),'configuration':config}
    return root,paths,config,primary,reference,binding


def create(root,config,binding,name='v2',**kwargs):
    return cp.CheckpointStore.create(root/name,binding,
        (datetime.now(timezone.utc)+timedelta(minutes=20)).isoformat(),1200,
        source_root=root,expected_queries=config['fixed_validation']['queries'],
        required_stages=('reconstruction','queries','global','bootstrap'),chunk_queries=2,**kwargs)


class Interrupted(Exception):pass


class CompleteReadbackTests(unittest.TestCase):
    def test_real_crash_after_candidate_commit_replays_without_inventing_exit(self):
        root,paths,config,primary,reference,binding=fixture()
        store=create(root,config,binding)
        request={'root':str(root),'paths':{k:str(v) for k,v in paths.items()},
                 'primary':str(primary),'configuration':config,'binding':binding,'folder':str(store.folder)}
        request_path=root/'candidate_worker_request.json';request_path.write_text(json.dumps(request))
        code='''
import json,os,sys
from pathlib import Path
from scripts import retailrocket_session_knn_checkpoint_v2 as cp
from scripts import retailrocket_session_knn_readback_v2 as core
r=json.loads(Path(sys.argv[1]).read_text())
def fault(point):
    if sys.argv[2]=='crash' and point=='after_candidate_commit':os._exit(9)
s=cp.CheckpointStore.open(r['folder'],r['binding'],source_root=r['root'],fault=fault)
with s.writer():
    core.verify(Path(r['primary']),{k:Path(v) for k,v in r['paths'].items()},r['configuration'],s)
'''
        command=[sys.executable,'-B','-c',code,str(request_path)]
        crashed=subprocess.run(command+['crash'],capture_output=True,text=True,timeout=120)
        self.assertEqual(crashed.returncode,9,crashed.stderr)
        old=cp.read(store.folder/'candidate.json')
        self.assertFalse((store.folder/'normal_worker_exit.json').exists())
        self.assertFalse((store.folder/'acceptance.json').exists())
        recovered=subprocess.run(command+['complete'],capture_output=True,text=True,timeout=120)
        self.assertEqual(recovered.returncode,0,recovered.stderr)
        new=cp.read(store.folder/'candidate.json')
        self.assertNotEqual(new['worker_identity'],old['worker_identity'])
        self.assertEqual(new['receipt']['aggregate'],reference['aggregate'])
        self.assertFalse((store.folder/'normal_worker_exit.json').exists())
        reopened=cp.CheckpointStore.open(store.folder,binding,source_root=root)
        accepted=reopened.finalize(cp.descriptor(store.folder,'candidate.json')['sha256'],
                                  new['worker_identity'],recovered.returncode)
        self.assertEqual(accepted['status'],'separate_v2_readback_complete')

    def test_real_process_crash_recovery_and_normal_exit_supervisor(self):
        root,paths,config,primary,reference,binding=fixture()
        store=create(root,config,binding)
        request={'root':str(root),'paths':{k:str(v) for k,v in paths.items()},
                 'primary':str(primary),'configuration':config,'binding':binding,'folder':str(store.folder)}
        request_path=root/'worker_request.json';request_path.write_text(json.dumps(request))
        code='''
import json,os,sys
from pathlib import Path
from scripts import retailrocket_session_knn_checkpoint_v2 as cp
from scripts import retailrocket_session_knn_readback_v2 as core
r=json.loads(Path(sys.argv[1]).read_text());n=0
s=cp.CheckpointStore.open(r['folder'],r['binding'],source_root=r['root'])
def fault(point):
    global n
    if point=='query_verified':
        n+=1
        if sys.argv[2]=='crash' and n==3:os._exit(9)
with s.writer():
    core.verify(Path(r['primary']),{k:Path(v) for k,v in r['paths'].items()},r['configuration'],s,fault=fault)
'''
        command=[sys.executable,'-B','-c',code,str(request_path)]
        crashed=subprocess.run(command+['crash'],capture_output=True,text=True,timeout=120)
        self.assertEqual(crashed.returncode,9,crashed.stderr)
        self.assertFalse((store.folder/'candidate.json').exists())
        self.assertEqual(store.recover()['records'],2)
        recovered=subprocess.run(command+['complete'],capture_output=True,text=True,timeout=120)
        self.assertEqual(recovered.returncode,0,recovered.stderr)
        candidate=cp.read(store.folder/'candidate.json')
        self.assertEqual(candidate['receipt']['aggregate'],reference['aggregate'])
        reopened=cp.CheckpointStore.open(store.folder,binding,source_root=root)
        accepted=reopened.finalize(cp.descriptor(store.folder,'candidate.json')['sha256'],
                                  candidate['worker_identity'],recovered.returncode)
        self.assertEqual(accepted['status'],'separate_v2_readback_complete')
        self.assertTrue((store.folder/'normal_worker_exit.json').exists())
        self.assertGreater(len(list((store.folder/'recovery').glob('*.json'))),0)

    def test_full_nested_four_arm_global_and_2000_draws(self):
        for boundary in (False,True):
            with self.subTest(boundary=boundary):
                root,paths,config,primary,reference,binding=fixture(boundary)
                store=create(root,config,binding)
                with store.writer():result=v2.verify(primary,paths,config,store)
                self.assertEqual(result['aggregate'],reference['aggregate'])
                self.assertEqual(result['fit_audit'],reference['fit_audit'])
                self.assertEqual(result['query_nested_scalars_checked'],reference['query_nested_scalars_checked'])
                self.assertEqual(result['bootstrap_replicates'],2000)
                self.assertTrue((store.folder/'candidate.json').exists())
                self.assertFalse((store.folder/'acceptance.json').exists())
                self.assertNotIn('all_session_visits',result)
                cp.verify_sources(root,binding['sources'])

    def test_recovery_matches_uninterrupted_at_every_algorithm_phase(self):
        root,paths,config,primary,reference,binding=fixture()
        for point in ('database_build','database_row','query_work','query_verified','global_replay','bootstrap','bootstrap_draw','before_candidate'):
            with self.subTest(point=point):
                store=create(root,config,binding,name='fault_'+point)
                seen=0
                def fault(event):
                    nonlocal seen
                    if event==point:
                        seen+=1
                        if seen==(3 if point in ('query_verified','query_work') else 10 if point in ('database_row','bootstrap_draw') else 1):raise Interrupted(point)
                with self.assertRaises(Interrupted),store.writer():
                    v2.verify(primary,paths,config,store,fault=fault)
                self.assertFalse((store.folder/'acceptance.json').exists())
                resumed=cp.CheckpointStore.open(store.folder,binding,source_root=root)
                with resumed.writer():result=v2.verify(primary,paths,config,resumed)
                self.assertEqual(result['aggregate'],reference['aggregate'])
                self.assertEqual(resumed.recover()['records'],7)
                self.assertEqual(len(list(resumed.iter_records())),7)

    def test_payload_flush_and_manifest_faults_recover_full_pipeline(self):
        root,paths,config,primary,reference,binding=fixture()
        for point in ('payload_half_written','after_payload_fsync','before_manifest_commit','after_manifest_commit'):
            with self.subTest(point=point):
                def fault(event):
                    if event==point:raise Interrupted(point)
                store=create(root,config,binding,name='chunk_'+point,fault=fault)
                with self.assertRaises(Interrupted),store.writer():v2.verify(primary,paths,config,store)
                resumed=cp.CheckpointStore.open(store.folder,binding,source_root=root)
                with resumed.writer():result=v2.verify(primary,paths,config,resumed)
                self.assertEqual(result['aggregate'],reference['aggregate'])
                self.assertFalse((resumed.folder/'acceptance.json').exists())

    def test_sources_changed_on_resume_are_rejected(self):
        root,paths,config,primary,reference,binding=fixture()
        store=create(root,config,binding)
        path=primary/'fit_audit.json';text=path.read_text();path.write_text(text.replace('fit_id','fit_iD'))
        with self.assertRaises(cp.IntegrityError):cp.CheckpointStore.open(store.folder,binding,source_root=root)

    def test_v2_rejects_missing_extra_duplicate_primary_queries(self):
        for change in ('missing','extra','duplicate','metric','neighbor','next_basket'):
            with self.subTest(change=change):
                root,paths,config,primary,reference,binding=fixture()
                if change=='next_basket':
                    path=paths['dataset']/'baskets.csv'
                    path.write_text(path.read_text().replace('POISON','STILL_POISON'))
                    # Poison roles stay unread; mutate an actual validation target instead.
                    values=list(v1.rows(primary/'queries.jsonl'));values[0]['targets']=['999999']
                else:
                    values=list(v1.rows(primary/'queries.jsonl'))
                    if change=='missing':values.pop()
                    elif change=='extra':values.append(values[-1])
                    elif change=='duplicate':values.insert(1,values[0])
                    elif change=='metric':values[0]['terms']['K1']['ndcg']+=.1
                    else:values[0]['predictions']['K1']['selected_neighbors'][0]['union']+=1
                (primary/'queries.jsonl').write_text(''.join(json.dumps(r)+'\n' for r in values))
                # Bind intentionally corrupted synthetic output, testing semantic checks.
                binding['sources']=cp.bind_sources(root,[r['path'] for r in binding['sources']])
                store=create(root,config,binding)
                with self.assertRaises(ValueError),store.writer():v2.verify(primary,paths,config,store)
                self.assertFalse((store.folder/'candidate.json').exists())


if __name__=='__main__':unittest.main()
