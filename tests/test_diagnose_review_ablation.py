"""Synthetic source-chain, no-model and publication-stop checks."""
from contextlib import contextmanager
import hashlib
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from scripts import diagnose_review_ablation as runner
from scripts import freeze_review_dataset as files


class GuardTests(unittest.TestCase):
    def test_both_builders_and_model_construction_forbidden(self):
        from scripts import review_baseline_pipeline as control
        from scripts import review_month_ablation_pipeline as treatment
        from scripts import review_baseline_evaluation as evaluation
        from sklearn.linear_model import LogisticRegression
        calls=[lambda:control.build_primary_features(None),lambda:treatment.build_primary_features(None),
               lambda:control.GuardedReviewBaseline(),lambda:treatment.GuardedReviewMonthAblation(),
               lambda:LogisticRegression(),lambda:evaluation.select_candidate([])]
        for call in calls:
            with self.subTest(call=call),self.assertRaises(RuntimeError):
                with runner.forbid_model_execution():call()

    def test_swallowed_forbidden_attempt_still_fails(self):
        from sklearn.preprocessing import StandardScaler
        with self.assertRaises(RuntimeError):
            with runner.forbid_model_execution():
                try:StandardScaler().fit([[1]])
                except RuntimeError:pass


class SnapshotTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory(dir=runner.ROOT/'.runtime',prefix='paired_diag_test_')
        self.addCleanup(self.tmp.cleanup);self.root=Path(self.tmp.name)
        self.bundle=SimpleNamespace(public_sources=[],private_sources=[])
        def write(n,v):
            p=self.root/n;p.parent.mkdir(parents=True,exist_ok=True)
            p.write_bytes(v if isinstance(v,bytes) else files.json_bytes(v))
            return files.descriptor(p,self.root)
        self.write=write
        execspec=write('reports/stage5/fixture_execution.json',{'version':1})
        dispatch=write(runner.DISPATCH,{'execution_specification':execspec,'public_sources':[]})
        controlmanifest=write(runner.codec.PRIVATE+'/manifest.json',{})
        guard=write(runner.INPUT_GUARD,{'specification':dispatch,'private_sources':[]})
        refs={'execution_specification':execspec,'training_dispatcher_binding':dispatch,
              'control_manifest':controlmanifest,'input_guard':guard}
        report={'status':'completed_real_offline_month_ablation','execution_specification':execspec,
                'training_dispatcher_binding':dispatch,'results':{'fixture':True}}
        public=write(runner.TREATMENT,report)
        accepted=write(runner.ACCEPTANCE,{'status':'passed_real_offline_month_ablation_delivery_acceptance'})
        baseline=write(runner.codec.REPORT,{'fixture':'control'})
        payloads={n:write(runner.PRIVATE+'/'+n,b'fixture') for n in ['inner_scores.csv','outer_scores.csv','fit_audit.json']}
        data=files.json_bytes(report['results'])
        evidence={'status':'passed_complete_same_ID_treatment_control_pairing','score_blocks':18,
                  'score_rows_per_arm':108744,'accepted_public_results_digest':{
                      'bytes':len(data),'sha256':hashlib.sha256(data).hexdigest()},
                  'accepted_treatment_file_digests':{n:{k:d[k] for k in ('bytes','sha256')} for n,d in payloads.items()}}
        paired=write(runner.PRIVATE+'/paired_acceptance.json',{
            **refs,'treatment_file_digests':payloads.copy(),'acceptance':evidence})
        payloads['paired_acceptance.json']=paired
        write(runner.PRIVATE+'/manifest.json',{**refs,'completed_estimator_fits':12,'no_training_replay':True,
             'public_report':public,'files':payloads,'paired_acceptance':paired})
        write(runner.PROOF,{'status':'passed','invocations':1,'automatic_retries':0,
              'actual_estimator_fits_completed':12,'result':public})
        self.pins={d['path']:d['sha256'] for d in (public,accepted,baseline)}
        self.addCleanup(patch.stopall)
        patch.object(runner,'PARENTS',self.pins).start()

    def verify(self):return runner.verify_snapshot(self.bundle,self.root)

    def test_exact_completed_snapshot_passes_without_private_public_digest(self):
        report,public,private=self.verify()
        self.assertEqual(report['status'],'completed_real_offline_month_ablation')
        self.assertTrue(all(not d['path'].startswith('.runtime') for d in public))
        self.assertTrue(any(d['path'].endswith('fit_audit.json') for d in private))

    def test_any_payload_mutation_stops(self):
        for n in ['inner_scores.csv','outer_scores.csv','fit_audit.json','paired_acceptance.json']:
            p=self.root/runner.PRIVATE/n;original=p.read_bytes()
            with self.subTest(n=n):
                p.write_bytes(original+b'changed')
                with self.assertRaises(ValueError):self.verify()
                p.write_bytes(original)

    def test_missing_success_file_stops(self):
        p=self.root/runner.PRIVATE/'inner_scores.csv';p.unlink()
        with self.assertRaises(ValueError):self.verify()

    def test_failure_receipt_stops(self):
        self.write(runner.PRIVATE+'/failure_receipt.json',{})
        with self.assertRaises(ValueError):self.verify()

    def test_unknown_namespace_file_stops(self):
        self.write(runner.PRIVATE+'/extra.txt',b'unknown')
        with self.assertRaises(ValueError):self.verify()

    def test_parent_report_changed_stops(self):
        p=self.root/runner.TREATMENT;p.write_bytes(p.read_bytes()+b' ')
        with self.assertRaises(ValueError):self.verify()

    def test_original_execution_retry_claim_stops(self):
        proof=files.read_json(self.root/runner.PROOF);proof['invocations']=2
        self.write(runner.PROOF,proof)
        with self.assertRaises(ValueError):self.verify()

    def test_guard_binding_changed_stops(self):
        self.write(runner.INPUT_GUARD,{'specification':{},'private_sources':[]})
        with self.assertRaises(ValueError):self.verify()

    def test_manifest_public_report_mismatch_stops(self):
        p=runner.PRIVATE+'/manifest.json';v=files.read_json(self.root/p)
        v['public_report']['bytes']+=1;self.write(p,v)
        with self.assertRaises(ValueError):self.verify()


class PublicationTests(unittest.TestCase):
    def test_source_change_after_write_retracts_only_new_report(self):
        @contextmanager
        def guard():yield {'forbidden_calls':0}
        with tempfile.TemporaryDirectory(dir=runner.ROOT/'.runtime',prefix='paired_publish_test_') as name:
            root=Path(name);private=[];public=[]
            bundle=SimpleNamespace(control_report={},verify_stable=lambda:None)
            spec={'public_sources':[],'protocol':{},'stage4':{'status':'pending_data'}}
            sp=root/runner.SPEC;sp.parent.mkdir(parents=True);sp.write_bytes(files.json_bytes(spec))
            source=files.descriptor(sp,root)
            gp=root/runner.GUARD;gp.parent.mkdir(parents=True)
            gp.write_bytes(files.json_bytes({'format_version':1,'specification':source,'private_sources':[]}))
            def safe(n,r):return Path(r)/n
            # Third verification occurs after publication; original inputs changed.
            with patch.object(runner,'forbid_model_execution',guard),\
                 patch.object(runner.sources,'load_prepared_sources',return_value=bundle),\
                 patch.object(runner,'verify_snapshot',return_value=({},public,private)),\
                 patch.object(runner,'make_specification',return_value=spec),\
                 patch.object(runner,'output',side_effect=safe),\
                 patch.object(runner,'load_blocks',return_value={}),\
                 patch.object(runner,'diagnose',return_value=[]),\
                 patch.object(runner.files,'verify_sources',side_effect=[0,0,ValueError('source changed')]):
                with self.assertRaises(ValueError):runner.run(root)
            self.assertFalse((root/runner.REPORT).exists())


if __name__=='__main__':unittest.main()
