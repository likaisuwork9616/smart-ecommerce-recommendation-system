"""D1 entry, budget/no-replay and independent train-only cost safety tests."""
from contextlib import redirect_stderr
import csv
import io
import json
from pathlib import Path
import unittest
from unittest.mock import patch,Mock
import uuid

from scripts import run_retailrocket_directed_v1 as entry
from scripts import retailrocket_directed_cost as cost

ROOT=Path(__file__).resolve().parents[1]


class EntryTests(unittest.TestCase):
    def setUp(self):
        self.root=ROOT/'shop-mysql-runtime/verification/retailrocket-directed-implementation-v1/entry-tests'/uuid.uuid4().hex
        self.root.mkdir(parents=True)
        self.gate={'state':'locked','D1_test_authorized':False,'logical_test_runs_consumed_this_round':0}
        self.values={'RSS':1,'disk':1,'free_disk':100*1024**3,'available_memory':16*1024**3,'elapsed':0}
    def test_only_explicit_separate_prepare_validation_verify(self):
        for mode in ('--prepare','--run-validation','--verify'):entry.parser().parse_args([mode])
        with redirect_stderr(io.StringIO()):
            for args in ([],['--prepare','--run-validation'],['--run-test'],['--final-refit']):
                with self.subTest(args=args),self.assertRaises(SystemExit):entry.parser().parse_args(args)
    def test_consumed_unlocked_and_boolean_gate_rejected(self):
        entry.require_locked(self.gate,self.root)
        for field,value in [('D1_test_authorized',True),('logical_test_runs_consumed_this_round',1),('logical_test_runs_consumed_this_round',False),('state','ready')]:
            with self.subTest(field=field,value=value),self.assertRaises(ValueError):entry.require_locked(dict(self.gate,**{field:value}),self.root)
    def test_foreign_test_and_final_namespaces_rejected(self):
        for relative in ('retailrocket_cooccurrence_final_v1','retailrocket_directed_final_v1','retailrocket_directed_paired_v1/test_usage.jsonl','retailrocket_popularity_v1/reserved_test'):
            base=self.root/uuid.uuid4().hex;(base/relative).mkdir(parents=True)
            with self.subTest(path=relative),self.assertRaises(ValueError):entry.require_locked(self.gate,base)
    def test_unprepared_run_does_not_fit(self):
        with patch.object(entry,'ROOT',self.root),patch.object(entry.adapter,'build') as fit,self.assertRaises(ValueError):entry.run_validation()
        fit.assert_not_called()
    def test_partial_run_and_verify_refuse_replay(self):
        (self.root/entry.DEV).mkdir(parents=True)
        with patch.object(entry,'ROOT',self.root),patch.object(entry.adapter,'build') as fit:
            with self.assertRaises(FileExistsError):entry.run_validation()
            with self.assertRaises(FileExistsError):entry.verify()
        fit.assert_not_called()
    def test_completed_run_only_verifies(self):
        folder=self.root/entry.DEV;folder.mkdir(parents=True);(folder/'output_guard.json').write_text('{}')
        with patch.object(entry,'ROOT',self.root),patch.object(entry,'verify_real',return_value={'verified':True}) as verify,patch.object(entry.adapter,'build') as fit:
            self.assertEqual(entry.run_validation(),{'verified':True});verify.assert_called_once_with()
        fit.assert_not_called()
    def test_failed_budget_retains_evidence_and_refuses_replay(self):
        private=self.root/entry.PRIVATE;private.mkdir(parents=True)
        (private/'output_guard.json').write_text('{}');(private/'test_gate_snapshot.json').write_text(json.dumps(self.gate))
        spec=self.root/entry.SPEC;spec.parent.mkdir(parents=True);spec.write_text('{}')
        monitor=Mock(side_effect=RuntimeError('synthetic budget exceeded'))
        with patch.object(entry,'ROOT',self.root),patch.object(entry,'verify_prepared',return_value={}),patch.object(entry,'Budget',return_value=monitor),patch.object(entry.adapter,'build') as fit:
            with self.assertRaisesRegex(RuntimeError,'synthetic budget exceeded'):entry.run_validation()
            self.assertTrue((self.root/entry.DEV/'started.json').is_file());self.assertTrue((self.root/entry.DEV/'failure.json').is_file())
            with self.assertRaises(FileExistsError):entry.run_validation()
        fit.assert_not_called()
    def test_partial_preparation_preserved(self):
        (self.root/entry.PRIVATE).mkdir(parents=True)
        with patch.object(entry,'ROOT',self.root),self.assertRaises(FileExistsError):entry.prepare()
    def test_failure_marker_overrides_guard(self):
        (self.root/'output_guard.json').write_text('{}');(self.root/'failure.json').write_text('{}')
        self.assertEqual(entry.state(self.root),'partial')
    def test_path_tamper_and_exclusive_write(self):
        with patch.object(entry,'ROOT',self.root):
            with self.assertRaises(ValueError):entry.inside('../outside')
            entry.write_new('a.json',{'ok':True});record=entry.descriptor('a.json');entry.check([record])
            with self.assertRaises(FileExistsError):entry.write_new('a.json',{})
            (self.root/'a.json').write_text('{}')
            with self.assertRaises(ValueError):entry.check([record])
    def test_all_five_resource_limits(self):
        entry.validate_measurements(self.values)
        for key,value in [('RSS',8*1024**3+1),('disk',20*1024**3+1),('free_disk',8*1024**3-1),('available_memory',4*1024**3-1),('elapsed',21601)]:
            with self.subTest(key=key),self.assertRaises(RuntimeError):entry.validate_measurements(dict(self.values,**{key:value}))
    def test_budget_receipt(self):
        receipt=entry.Budget(self.root).receipt();self.assertGreater(receipt['samples'],0);self.assertEqual(receipt['limits'],entry.LIMITS)


class CostTests(unittest.TestCase):
    HEADER=['visitorid','session_start_ms','query_ms','role','basket_index','items']
    def make(self,rows):
        folder=ROOT/'shop-mysql-runtime/verification/retailrocket-directed-implementation-v1/cost-tests'/uuid.uuid4().hex
        folder.mkdir(parents=True);source=folder/'baskets.csv'
        with source.open('x',encoding='utf-8',newline='') as f:
            w=csv.writer(f,lineterminator='\n');w.writerow(self.HEADER);w.writerows(rows)
        return folder,source
    def test_hand_repeat_reverse_singleton_gap_and_no_other_role_decode(self):
        rows=[['1',0,5,'warmup',1,'NOT JSON'],['1',0,10,'train',2,'["1","2"]'],
          ['1',0,11,'train',3,'["2","3"]'],['1',0,12,'train',4,'["1","2"]'],
          ['1',0,13,'train',5,'["2","3"]'],['1',0,14,'validation',6,'NOT JSON'],
          ['2',10,10,'train',1,'["4"]'],['3',10,10,'train',1,'["5"]'],['3',10,13,'train',3,'["6"]'],
          ['3',10,14,'test',4,'NOT JSON']]
        folder,source=self.make(rows);result=cost.audit(source,self.HEADER,10,14,folder/'audit')
        self.assertEqual(result['eligible_adjacent_pairs'],3)
        self.assertEqual(result['raw_directed_emissions'],9)
        self.assertEqual(result['session_unique_directed_emissions'],6)
        self.assertEqual(result['repeated_directed_emissions'],3)
        self.assertEqual(result['zero_directed_edge_sessions'],2)
        self.assertEqual(result['singleton_sessions'],1)
        self.assertEqual(result['independent_cells_checked'],27)
        self.assertFalse(result['global_directed_count_model_built']);self.assertFalse(result['validation_or_test_items_decoded'])
        with self.assertRaises(FileExistsError):cost.audit(source,self.HEADER,10,14,folder/'audit')
    def test_gap_over_30_minutes_is_not_edge(self):
        folder,source=self.make([['1',10,10,'train',1,'["1"]'],['1',10,1800011,'train',2,'["2"]']])
        result=cost.audit(source,self.HEADER,10,2000000,folder/'audit')
        self.assertEqual(result['eligible_adjacent_pairs'],0);self.assertEqual(result['raw_directed_emissions'],0)
    def test_duplicate_members_and_bad_train_clock_stop(self):
        for row in (['1',10,10,'train',1,'["1","1"]'],['1',10,20,'train',1,'["1"]']):
            folder,source=self.make([row])
            with self.subTest(row=row),self.assertRaises(ValueError):cost.audit(source,self.HEADER,10,20,folder/'audit')
    def test_budget_callback_stops_before_cost_completion(self):
        folder,source=self.make([['1',10,10,'train',1,'["1"]']])
        with self.assertRaises(RuntimeError):cost.audit(source,self.HEADER,10,20,folder/'audit',Mock(side_effect=RuntimeError('stop')))
        self.assertTrue((folder/'audit/train_session_costs.csv').exists());self.assertFalse((folder/'audit/cost.json').exists())


if __name__=='__main__':unittest.main()
