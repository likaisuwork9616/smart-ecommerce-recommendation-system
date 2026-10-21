"""Synthetic source gates, immutable policy and no-model publication tests."""
from contextlib import contextmanager
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from scripts import audit_review_mature_prior as runner
from scripts import freeze_review_dataset as files


class SnapshotTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory(dir=runner.ROOT/'.runtime',prefix='mature_prior_test_')
        self.addCleanup(self.tmp.cleanup);self.root=Path(self.tmp.name)
        def write(n,v):
            p=self.root/n;p.parent.mkdir(parents=True,exist_ok=True)
            p.write_bytes(v if isinstance(v,bytes) else files.json_bytes(v))
            return files.descriptor(p,self.root)
        self.write=write
        private=write('.runtime/fixture_source.txt',b'private synthetic')
        guard_path='.runtime/stage5_review_ablation_diagnostics_v1/input_guard.json'
        parent=write(runner.PARENT_SPEC,{'public_sources':[],
            'private_source_guard':{'path':guard_path,'input_paths':[private['path']]}})
        write(guard_path,{'specification':parent,'private_sources':[private]})
        report=write(runner.PARENT_REPORT,{'specification':parent,'status':'completed_read_only_paired_ablation_diagnostics'})
        proof=write(runner.PARENT_VERIFICATION,{'status':'passed_read_only_paired_diagnostic_verification'})
        self.bundle=SimpleNamespace(public_sources=[],private_sources=[],verify_stable=lambda:None)
        self.addCleanup(patch.stopall)
        patch.object(runner,'PINS',{v['path']:v['sha256'] for v in [parent,report,proof]}).start()
        patch.object(runner.sources,'load_verified_sources',return_value=self.bundle).start()

    def load(self):return runner.load_snapshot(self.root)

    def test_source_chain_passes_without_parsing_score_or_model_files(self):
        bundle,public,private=self.load()
        self.assertIs(bundle,self.bundle)
        self.assertTrue(all(not x['path'].startswith('.runtime') for x in public))
        self.assertEqual(len(private),2)

    def test_parent_byte_change_stops(self):
        p=self.root/runner.PARENT_REPORT;p.write_bytes(p.read_bytes()+b' ')
        with self.assertRaises(ValueError):self.load()

    def test_private_source_change_stops(self):
        self.write('.runtime/fixture_source.txt',b'changed')
        with self.assertRaises(ValueError):self.load()

    def test_missing_private_source_stops(self):
        (self.root/'.runtime/fixture_source.txt').unlink()
        with self.assertRaises(ValueError):self.load()

    def test_guard_specification_change_stops(self):
        path='.runtime/stage5_review_ablation_diagnostics_v1/input_guard.json'
        v=files.read_json(self.root/path);v['specification']['bytes']+=1;self.write(path,v)
        with self.assertRaises(ValueError):self.load()

    def test_frozen_policy_rejects_changed_source_bytes(self):
        _,public,private=self.load()
        for n in runner.CODE:self.write(n,b'fixture code\n')
        spec=runner.freeze(public,private,self.root)
        self.assertEqual(spec['protocol']['horizon_elapsed_days'],60)
        self.write(runner.CODE[0],b'changed code\n')
        with self.assertRaises(ValueError):runner.freeze(public,private,self.root)


class GuardTests(unittest.TestCase):
    def test_models_features_selection_and_performance_forbidden(self):
        from sklearn.linear_model import LogisticRegression
        from scripts import review_baseline_evaluation as evaluation
        targets=[lambda:LogisticRegression(),lambda:runner.model_guard.treatment_pipeline.build_primary_features(None),
                 lambda:evaluation.select_candidate([]),lambda:evaluation.evaluate_role(None,None)]
        for call in targets:
            with self.subTest(call=call),self.assertRaises(RuntimeError):
                with runner.model_guard.forbid_model_execution():call()

    def test_swallowed_model_call_still_stops(self):
        from sklearn.preprocessing import StandardScaler
        with self.assertRaises(RuntimeError):
            with runner.model_guard.forbid_model_execution():
                try:StandardScaler()
                except RuntimeError:pass


class PublicationTests(unittest.TestCase):
    def test_source_change_after_write_retracts_new_report(self):
        @contextmanager
        def guard():yield {'forbidden_calls':0}
        with tempfile.TemporaryDirectory(dir=runner.ROOT/'.runtime',prefix='mature_publish_test_') as n:
            root=Path(n);bundle=SimpleNamespace(verify_stable=lambda:None)
            spec={'public_sources':[],'protocol':{},'stage4':{'status':'pending_data'}}
            sp=root/runner.SPEC;sp.parent.mkdir(parents=True);sp.write_bytes(files.json_bytes(spec))
            source=files.descriptor(sp,root);gp=root/runner.GUARD;gp.parent.mkdir(parents=True)
            gp.write_bytes(files.json_bytes({'format_version':1,'specification':source,'private_sources':[]}))
            with patch.object(runner.model_guard,'forbid_model_execution',guard),\
                 patch.object(runner,'load_snapshot',return_value=(bundle,[],[])),\
                 patch.object(runner,'make_specification',return_value=spec),\
                 patch.object(runner,'output',side_effect=lambda n,r:Path(r)/n),\
                 patch.object(runner,'audit',return_value=([],0)),\
                 patch.object(runner.files,'verify_sources',side_effect=[0,0,ValueError('changed')]):
                with self.assertRaises(ValueError):runner.run(root)
            self.assertFalse((root/runner.REPORT).exists())

    def test_outside_project_output_rejected(self):
        with self.assertRaises(ValueError):runner.output('../outside.json',runner.ROOT)


if __name__=='__main__':unittest.main()
