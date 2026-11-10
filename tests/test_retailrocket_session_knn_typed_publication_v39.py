"""Real separate interpreters over artificial48; strict raw typed and log tamper gates."""
from copy import deepcopy
from datetime import datetime, timedelta, timezone
import hashlib
from pathlib import Path
import sys
import unittest
from unittest.mock import patch
from uuid import uuid4

from scripts import retailrocket_session_knn_typed_publication_v39 as pub
from scripts import retailrocket_session_knn_typed_adapter_v39 as adapter
from scripts import retailrocket_session_knn_typed_v39 as typed
from scripts import retailrocket_session_knn_snapshot_v30 as codec
from scripts import retailrocket_session_knn_entry_v34 as common
from scripts import retailrocket_session_knn_checkpoint_v2 as cp
from scripts import retailrocket_session_knn_pair_v4 as pair
from scripts import run_retailrocket_session_knn_v2 as io
from scripts.retailrocket_session_knn_diagnostics_v20 import _clone
from scripts.retailrocket_session_knn_sources_v24 import Observation
from scripts.retailrocket_session_knn_reuse_v27 import ReuseStore
from scripts.retailrocket_session_knn_cost_window_v5 import run_window, LIMITS
from scripts.retailrocket_session_knn_gap_v7 import ledger_proof
from tests import test_retailrocket_session_knn_validation as validation
from tests import test_retailrocket_session_knn_pair_v4 as four
from tests import test_retailrocket_session_knn_reuse_acceptance_v27 as fixture
from tests import test_retailrocket_session_knn_compare_v28 as previous
from tests import test_retailrocket_session_knn_snapshot_integration_v30 as inherited


def build_window():
    bundle = pub.PRIVATE/('knn-v39-synthetic-'+uuid4().hex); bundle.mkdir()
    with patch.object(validation,'fixture_inputs',side_effect=previous.artificial_inputs), \
            patch.object(four,'make_fixture',side_effect=lambda **kw:validation.make_fixture(base=bundle,**kw)):
        root,paths,config,primary,_,database,model,ordinals,binding = four.fixture()
    io.write(root/'reconstruction.json',dict(receipt=model))
    rel = lambda p:p.relative_to(io.ROOT).as_posix()
    records = cp.bind_sources(io.ROOT,[rel(p) for p in root.rglob('*') if p.is_file()])
    binding = dict(binding,sources=records); index = {r['path']:r for r in records}
    deadline = (datetime.now(timezone.utc)+timedelta(minutes=30)).isoformat()
    reference = ReuseStore.create(bundle/'reference/verified_subset',binding,deadline,1800,
        source_root=io.ROOT,observer=Observation(),expected_queries=48,required_stages=('reconstruction','queries'))
    with reference.writer():
        four.reconstruct_seal(reference,model); pair.verify_selected(primary,paths,config,reference,model,database,ordinals)
    probes = [dict(key=x['key'],original_ordinal=x['original_ordinal'],
                   key_sha256=hashlib.sha256(pair.dump(x['key']).encode()).hexdigest()) for x in ordinals]
    io.write(bundle/'reference.json',ledger_proof(reference,probes)); io.write(bundle/'probes.json',dict(probes=probes))
    deps = {k:index[rel(p)] for k,p in (('counts',paths['P0']/'item_counts.csv'),('catalog',paths['dataset']/'catalog.csv'),
                                     ('config',root/'configuration.json'),('model',root/'reconstruction.json'))}
    plan, diagnostics = common.quiet_contract(pub.preserved_plan)
    io.write(bundle/'preserved_plan_diagnostics.json',dict(diagnostics=diagnostics))
    io.write(bundle/'data.json',dict(contract=dict(binding=binding),model=model,database=rel(database),ordinals=ordinals,probes=probes))
    cohort = dict(selected_root=rel(root),model_root=rel(primary),old_run=rel(reference.folder/'run.json'),
                  probes=rel(bundle/'probes.json'),reference=rel(bundle/'reference.json'))
    schedule = [dict(label='warm_'+m,mode=m) for m in ('R','C')]+[
        dict(label=f'pair_{i}_{m}',mode=m) for i in range(1,7) for m in ('RC' if i%2 else 'CR')]
    sources = common.merge_methods([io.describe(p) for p in sorted(bundle.rglob('*')) if p.is_file()],
                                   [*plan['methods'],io.describe(io.ROOT/pub.design.SPEC)])
    meta = dict(cohort=cohort,schedule=schedule,context=dict(dependencies=deps,methods=plan['methods']),
        direct_methods=plan['direct'],environment=io.environment(),gates=io.check_gates(),
        synthetic_acceptance_only=True,synthetic_data=io.describe(bundle/'data.json'),
        specification={'artificial':True},acceptance={'artificial':True},fingerprint_scheme=codec.SCHEME,
        typed_reference_policy=adapter.POLICY,typed_reference_scheme=typed.SCHEME,
        typed_specification=io.describe(io.ROOT/pub.design.SPEC))
    folder = bundle/'window'
    completion = run_window(folder,[sys.executable,'-B','-m',pub.MODULE,'--pipeline',str(folder)],
        sources,'joint_tail',metadata=meta,budget_seconds=1800,limits=LIMITS)
    if completion['exit_code']!=0:
        raise AssertionError('\n'.join(p.read_text(encoding='utf-8',errors='replace')[-12000:] for p in folder.glob('*.log')))
    _,_,_,_,_,seal = pub.audit_completed(folder,io.read(folder/'request.json'))
    io.write(bundle/'closed_manifest.json',seal)
    return folder


class IntegratedTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls): cls.folder=build_window()

    def completed(self):
        seal=io.read(self.folder.parent/'closed_manifest.json')
        return pub.audit_completed(self.folder,io.read(self.folder/'request.json'),seal)[:5]

    def raw_reject(self, relative, mutate, regex):
        path=self.folder/relative; original=path.read_bytes(); value=io.read(path); mutate(value)
        # Deliberate tampering of an ignored artificial file. Production
        # atomic_json correctly refuses overwriting sealed evidence.
        path.write_bytes(cp.encoded(value))
        try:
            observer=Observation()
            with self.assertRaisesRegex(ValueError,regex):
                pub.audit_saved_runs(self.folder,io.read(self.folder/'request.json'),observer)
            self.assertFalse(observer.stack)
        finally: path.write_bytes(original)

    def test_independent_original_canonical_authority_and_policy_are_exact(self):
        result,*_=self.completed(); proof=result['typed_validation']
        self.assertIs(proof['worker_reference_deserialized'],False)
        self.assertEqual(proof['policy'],adapter.POLICY); self.assertEqual(proof['reference_scheme'],typed.SCHEME)
        self.assertEqual(proof['late_comparisons'],2); self.assertEqual(proof['independently_rebuilt_roots'],2)
        self.assertEqual(result['cache']['typed_reference']['authority'],proof['authority'])
        calls=result['cache']['call_observations']
        self.assertEqual([len(x['typed_reference']['checks']) for x in calls],[2]+[0]*6)

    def test_raw_source_canonical_reference_and_policy_tamper_reach_semantic_rejection(self):
        for field in ('canonical','raw_sources','reference_statistics'):
            def mutate(events,field=field):
                authority=next(e for e in events if e['phase']=='cache.use')['metadata']['typed_reference']['authority']
                if field=='canonical': authority[field]['model']['sha256']='0'*64
                elif field=='raw_sources': authority[field]['config']['path']='unbound.json'
                else: authority[field]['config']['nodes']+=1
            with self.subTest(field=field):self.raw_reject('warm_C/events.json',mutate,'Typed authority differs')
        self.raw_reject('pair_1_C/events.json',lambda es:next(e for e in es if e['phase']=='cache.use')['metadata'].__setitem__('typed_reference_policy','wrong'), 'Mixed or missing')

    def test_raw_late_order_counts_full_walk_and_original_time_boundary_tamper_rejected(self):
        for change in ('order','stats','incomplete','before_prepare','after_borrow','missing'):
            def mutate(events,change=change):
                use=next(e for e in events if e['phase']=='cache.use')
                checks=use['metadata']['typed_reference']['checks']
                if change=='order': checks.reverse()
                elif change=='stats': checks[0]['statistics']['nodes']-=1
                elif change=='incomplete': checks[1]['completed']=False
                elif change=='before_prepare': checks[0]['start_ns']=next(e for e in events if e['phase']=='cache.original_prepare_catalog')['start_ns']
                elif change=='after_borrow': checks[1]['end_ns']=use['end_ns']+1
                else: checks.pop()
            with self.subTest(change=change):self.raw_reject('warm_C/events.json',mutate,'late|complete.*reference|Two complete')
        self.raw_reject('pair_1_C/events.json',lambda es:next(e for e in es if e['phase']=='cache.use')['metadata']['typed_reference'].__setitem__('checks',[{}]),'Hit')

    def test_raw_summary_and_mixed_request_policy_rejected_independently(self):
        self.raw_reject('cache_receipt.json',lambda r:r['typed_reference'].__setitem__('late_comparisons',1),'reference/check counts|Typed summary')
        wrong=deepcopy(io.read(self.folder/'request.json')); wrong['metadata']['typed_reference_scheme']='old'
        with self.assertRaisesRegex(ValueError,'policy and scheme'):
            pub.audit_saved_runs(self.folder,wrong,Observation())

    def test_publisher_semantically_rejects_mixed_schemes(self):
        def changed_event(events):
            next(e for e in events if e['phase']=='cache.use')['metadata']['fingerprint_scheme']='old-C1-scheme'
        self.raw_reject('warm_C/events.json',changed_event,'Typed summary differs|Cache use differs')
        self.raw_reject('cache_receipt.json',lambda r:r.__setitem__('fingerprint_scheme','old-C1-scheme'),
                        'cache receipt differs|Typed summary differs')
        request=deepcopy(io.read(self.folder/'request.json'));request['metadata']['fingerprint_scheme']='old-C1-scheme'
        with self.assertRaisesRegex(ValueError,'request fingerprint scheme'):
            pub.audit_saved_runs(self.folder,request,Observation())

    def test_final_log_manifest_covers_buffered_top_level_and_rejects_append_or_new_file(self):
        self.completed()
        for role in ('pipeline','worker','publisher'):
            self.assertTrue((self.folder/(role+'_contract.json')).is_file())
        log=self.folder/'stdout_stderr.log'; original=log.read_bytes()
        self.assertIn(b'pipeline buffered diagnostic',original)
        try:
            log.write_bytes(original+b'late append\n')
            with self.assertRaises(ValueError):self.completed()
        finally:log.write_bytes(original)
        path=self.folder/'unsealed_new.json'; io.write(path,{})
        try:
            with self.assertRaises(ValueError):self.completed()
        finally:path.unlink()
        self.completed()

    def test_contract_preserves_original_scope_and_rejects_missing_direct_source(self):
        plan,_=common.quiet_contract(pub.preserved_plan)
        self.assertEqual(len(plan['original_sources']),2092); self.assertEqual(len(plan['original_methods']),168)
        self.assertEqual(len(plan['original_binding']),15)
        union={r['path']:r for r in plan['sources']}
        self.assertTrue(all(union[r['path']]==r for r in plan['original_sources']))
        request=io.read(self.folder/'request.json')
        with self.assertRaises(ValueError):
            wrong=deepcopy(request);wrong['metadata']['synthetic_acceptance_only']=False;pub.contract(wrong)
        wrong=deepcopy(request);wrong['sources']=[r for r in wrong['sources'] if r['path']!=common.PRIORITY_SOURCE]
        with self.assertRaisesRegex(ValueError,'outside|missing|Missing'):pub.contract(wrong)


# The inherited tests execute the new worker, publisher and closed manifest;
# they are not old-pool regressions counted as candidate coverage.
for _name in dir(inherited.IntegratedTests):
    if _name.startswith('test_') and _name not in IntegratedTests.__dict__:
        setattr(IntegratedTests,_name,_clone(getattr(inherited.IntegratedTests,_name),adapter=pub,MODULE=pub.MODULE))


def integration_evidence(folder=None):
    folder=pub.folder_path(IntegratedTests.folder if folder is None else folder)
    request=io.read(folder/'request.json')
    result,completion,exits,pub_summary,_,seal=pub.audit_completed(folder,request,io.read(folder.parent/'closed_manifest.json'))
    binding=io.read(io.ROOT/request['metadata']['cohort']['old_run'])['binding']['sources']
    snapshots=sum(r['diagnostic']['phases'].get('snapshot.fingerprint',{}).get('calls',0) for r in result['runs'].values())
    if snapshots!=15 or len(result['runs'])!=14 or pub_summary['phases']['checkpoint.open']['calls']!=14:
        raise ValueError('Complete artificial14/672 independent audit required')
    return dict(namespace=folder.relative_to(io.ROOT).as_posix(),synthetic_only=True,retained_runs=14,
        queries_per_run=48,synthetic_saved_checks=672,live_worker_fingerprints=snapshots,
        publisher_fingerprints=pub_summary['phases']['snapshot.fingerprint']['calls'],
        publisher_independent_contexts=pub_summary['phases']['publisher.independent_context']['calls'],
        publisher_opens=14,independent_processes=exits['worker']['pid']!=exits['publisher']['pid'],
        source_descriptors_per_worker_boundary=len(request['sources']),synthetic_binding_sources=len(binding),
        preserved_real_sources=2092,preserved_real_methods=168,preserved_real_binding=15,
        real_source_closure_rehashed=False,typed_validation=result['typed_validation'],cache=result['cache'],
        stopped_manifest=io.describe(folder.parent/'closed_manifest.json'),
        supervisor=dict(exit_code=completion['exit_code'],tracked_processes=completion['tracked_processes'],
                        live_after_cleanup=completion['tracked_processes_alive_after_cleanup']),
        evidence=[io.describe(p) for p in sorted(folder.rglob('*')) if p.is_file()]+[io.describe(folder.parent/'closed_manifest.json')],
        interpretation='Artificial inputs only. Real2092/168/15 are preserved additively, not relabelled as this synthetic binding or a new real48 measurement.')


if __name__=='__main__':unittest.main()
