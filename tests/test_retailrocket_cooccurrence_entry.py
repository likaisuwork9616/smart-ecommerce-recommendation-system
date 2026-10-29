"""Resource, phase, source-identity and no-replay guards without real fitting."""
from contextlib import redirect_stderr
import io
import json
from pathlib import Path
import unittest
from unittest.mock import patch,Mock
import uuid

from scripts import run_retailrocket_cooccurrence_v1 as entry
from scripts import retailrocket_cooccurrence_cost as cost
from tests.test_retailrocket_cooccurrence import ROOT,fixture,SCHEMAS,START,END


class EntryTests(unittest.TestCase):
    def setUp(self):
        self.root=ROOT/'shop-mysql-runtime/verification/retailrocket-cooccurrence-implementation-v1/entry-tests'/uuid.uuid4().hex
        self.root.mkdir(parents=True)
        self.gate={'state':'locked','C1_test_authorized':False,'logical_test_runs_consumed_this_round':0}
        self.measurements={'RSS':1,'disk':1,'free_disk':100*1024**3,'available_memory':16*1024**3,'elapsed':0}
    def test_cli_prepare_and_validation_only(self):
        self.assertTrue(entry.parser().parse_args(['--prepare']).prepare)
        self.assertTrue(entry.parser().parse_args(['--run-validation']).run_validation)
    def test_test_flag_rejected(self):
        with redirect_stderr(io.StringIO()),self.assertRaises(SystemExit):entry.parser().parse_args(['--run-test'])
    def test_final_refit_flag_rejected(self):
        with redirect_stderr(io.StringIO()),self.assertRaises(SystemExit):entry.parser().parse_args(['--final-refit'])
    def test_no_implicit_mode(self):
        with redirect_stderr(io.StringIO()),self.assertRaises(SystemExit):entry.parser().parse_args([])
    def test_combined_prepare_and_run_rejected(self):
        with redirect_stderr(io.StringIO()),self.assertRaises(SystemExit):entry.parser().parse_args(['--prepare','--run-validation'])
    def test_locked_gate(self):entry.require_locked(self.gate,self.root)
    def test_unlocked_gate_rejected(self):
        self.gate['C1_test_authorized']=True
        with self.assertRaises(ValueError):entry.require_locked(self.gate,self.root)
    def test_consumed_gate_rejected(self):
        self.gate['logical_test_runs_consumed_this_round']=1
        with self.assertRaises(ValueError):entry.require_locked(self.gate,self.root)
    def test_existing_test_namespace_rejected(self):
        (self.root/'retailrocket_popularity_v1/reserved_test').mkdir(parents=True)
        with self.assertRaises(ValueError):entry.require_locked(self.gate,self.root)
    def test_unprepared_real_execution_rejected(self):
        with patch.object(entry,'ROOT',self.root),self.assertRaises(ValueError):entry.run_validation()
    def test_partial_execution_rejected_before_any_fit(self):
        (self.root/entry.DEV).mkdir(parents=True)
        with patch.object(entry,'ROOT',self.root),patch.object(entry.adapter,'build') as fit,self.assertRaises(FileExistsError):entry.run_validation()
        fit.assert_not_called()
    def test_partial_verify_not_success(self):
        (self.root/entry.DEV).mkdir(parents=True)
        with patch.object(entry,'ROOT',self.root),self.assertRaises(FileExistsError):entry.verify()
    def test_complete_execution_verifies_without_fit(self):
        folder=self.root/entry.DEV;folder.mkdir(parents=True)
        (folder/'output_guard.json').write_text('{"sources":[],"outputs":[]}')
        with patch.object(entry,'ROOT',self.root),patch.object(entry.adapter,'build') as fit:
            self.assertEqual(entry.run_validation()['status'],'existing_C1_paired_validation_bytes_verified')
        fit.assert_not_called()
    def test_budget_failure_preserves_marker_and_blocks_replay(self):
        private=self.root/entry.PRIVATE;private.mkdir(parents=True)
        (private/'output_guard.json').write_text('{}')
        (private/'test_gate_snapshot.json').write_text(json.dumps(self.gate))
        spec=self.root/entry.SPEC;spec.parent.mkdir(parents=True);spec.write_text('{}')
        monitor=Mock(side_effect=RuntimeError('synthetic budget stop'))
        with patch.object(entry,'ROOT',self.root),patch.object(entry,'verify_prepared',return_value={}),patch.object(entry,'Budget',return_value=monitor),patch.object(entry.adapter,'build') as fit:
            with self.assertRaisesRegex(RuntimeError,'synthetic budget stop'):entry.run_validation()
            self.assertTrue((self.root/entry.DEV/'started.json').is_file())
            self.assertTrue((self.root/entry.DEV/'failure.json').is_file())
            with self.assertRaises(FileExistsError):entry.run_validation()
        fit.assert_not_called()
    def test_partial_prepare_preserved(self):
        (self.root/entry.PRIVATE).mkdir(parents=True)
        with patch.object(entry,'ROOT',self.root),self.assertRaises(FileExistsError):entry.prepare()
    def test_complete_state(self):
        (self.root/'output_guard.json').write_text('{}')
        self.assertEqual(entry.state(self.root),'complete')
    def test_path_cannot_escape_shop(self):
        with self.assertRaises(ValueError):entry.inside('../outside-artifact')
    def test_source_byte_tamper_rejected(self):
        path=self.root/'source.json';path.write_text('{}');relative=path.relative_to(ROOT).as_posix()
        record=entry.descriptor(relative);entry.check([record]);path.write_text('{"x":1}')
        with self.assertRaises(ValueError):entry.check([record])
    def test_resource_valid(self):entry.validate_measurements(self.measurements)
    def test_memory_limit(self):
        self.measurements['RSS']=entry.LIMITS['maximum_process_RSS_bytes']+1
        with self.assertRaises(RuntimeError):entry.validate_measurements(self.measurements)
    def test_disk_limit(self):
        self.measurements['disk']=entry.LIMITS['maximum_execution_disk_bytes']+1
        with self.assertRaises(RuntimeError):entry.validate_measurements(self.measurements)
    def test_free_disk_floor(self):
        self.measurements['free_disk']=0
        with self.assertRaises(RuntimeError):entry.validate_measurements(self.measurements)
    def test_memory_floor(self):
        self.measurements['available_memory']=0
        with self.assertRaises(RuntimeError):entry.validate_measurements(self.measurements)
    def test_runtime_limit(self):
        self.measurements['elapsed']=21601
        with self.assertRaises(RuntimeError):entry.validate_measurements(self.measurements)
    def test_budget_receipt(self):
        budget=entry.Budget(self.root);receipt=budget.receipt()
        self.assertGreaterEqual(receipt['samples'],1)
        self.assertEqual(receipt['limits'],entry.LIMITS)
    def test_train_cost_independent_singletons_and_boundary(self):
        root,source,*_=fixture(base=self.root)
        result=cost.audit(source/'baskets.csv',SCHEMAS['baskets.csv'],START,END,root/'cost')
        self.assertEqual(result['exact_unordered_pair_emissions'],4)
        self.assertEqual(result['maximum_session_items'],3)
        self.assertFalse(result['pair_count_model_built'])
        self.assertFalse(result['validation_or_test_items_decoded'])


if __name__=='__main__':unittest.main()
