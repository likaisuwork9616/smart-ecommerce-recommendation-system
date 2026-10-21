"""Synthetic historical-use evidence and label-blind publication gates."""
from contextlib import contextmanager
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

import pandas as pd
from scripts import audit_review_validation_windows as runner
from scripts import freeze_review_dataset as files


class EvidenceTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory(dir=runner.ROOT/'.runtime',prefix='window_evidence_test_')
        self.addCleanup(self.tmp.cleanup);self.root=Path(self.tmp.name)
        def write(n,v):
            p=self.root/n;p.parent.mkdir(parents=True,exist_ok=True)
            p.write_bytes(v if isinstance(v,bytes) else files.json_bytes(v));return files.descriptor(p,self.root)
        self.write=write
        for n in runner.EVIDENCE:write(n,b'fixture')
        plans=[{'inner_query_start':m+'-01'} for m in ['2017-09','2017-11','2017-12']]
        write('reports/stage5/review_dataset_specification.json',{
            'protocol':{'cohort':{'approval_cutoff_exclusive':'2018-05-01'},'observation_cutoff_exclusive':'2018-07-01'},
            'calendar_split_plan':plans})
        for n in ['reports/stage5/review_baseline_training.json','reports/stage5/review_month_ablation_training.json']:
            write(n,{'results':{'outer_folds':[{'outer_fold':m} for m in ['2017-12','2018-02','2018-04']],
                               'execution':{'estimator_fits_completed':12}}})
        write('reports/stage4/monthly_error_diagnostics.json',{'split':{'test_start':'2018-05-26T00:00:00',
            'partitions':{'test':{'prediction_time_max':'2018-08-29T15:10:26'}}},
            'test_months':[{'month':m} for m in ['2018-05','2018-06','2018-07','2018-08']]})
        self.sql=b'SELECT review_score,COUNT(*) FROM order_reviews GROUP BY review_score;'
        write('sql/03_business_analysis.sql',self.sql)
        write('notebooks/03_olist_business_analysis.ipynb',{'cells':[{'cell_type':'code','source':[self.sql.decode()]}]})
        guard_path='.runtime/stage5_review_mature_prior_v1/input_guard.json'
        sp=write(runner.PARENT_SPEC,{'public_sources':[],'private_source_guard':{'path':guard_path,'input_paths':[]}})
        write(guard_path,{'specification':sp,'private_sources':[]})
        rp=write(runner.PARENT_REPORT,{'status':'completed_read_only_mature_prior_temporal_audit','specification':sp})
        vp=write(runner.PARENT_VERIFY,{'status':'passed_read_only_mature_prior_verification'})
        write(runner.SOURCE_METADATA,{})
        self.addCleanup(patch.stopall)
        patch.object(runner,'PINS',{v['path']:v['sha256'] for v in [sp,rp,vp]}).start()
        patch.object(runner.sources,'load_verified_sources',return_value=SimpleNamespace(public_sources=[],private_sources=[])).start()
        patch.object(runner.subprocess,'check_output',return_value='a'*40+'\n').start()

    def test_committed_use_evidence_does_not_invent_external_nonuse(self):
        h,d=runner.capture_history(self.root);u=runner.usage_ledger(self.root,h)
        self.assertEqual(u['stage5_inner_months'],['2017-09','2017-11','2017-12'])
        self.assertEqual(u['stage4_test_start'],'2018-05-26T00:00:00')
        self.assertFalse(u['stage4_target_is_review_score'])
        self.assertTrue(u['stage3_source_wide_review_aggregation'])
        self.assertFalse(h['unlogged_usage_ruled_out'])

    def test_no_silent_recreation_of_missing_usage_history(self):
        with self.assertRaises(ValueError):runner.verify_history(self.root)

    def test_changed_committed_evidence_stops(self):
        runner.capture_history(self.root);self.write('sql/03_business_analysis.sql',self.sql+b' changed')
        with self.assertRaises(ValueError):runner.verify_history(self.root)

    def test_date_filtered_EDA_cannot_be_called_source_wide(self):
        self.write('sql/03_business_analysis.sql',b'SELECT review_score FROM order_reviews WHERE x=1 GROUP BY review_score;')
        h,_=runner.capture_history(self.root)
        with self.assertRaises(ValueError):runner.usage_ledger(self.root,h)

    def test_changed_historical_calendar_stops(self):
        path='reports/stage5/review_dataset_specification.json';v=files.read_json(self.root/path)
        v['protocol']['observation_cutoff_exclusive']='2018-09-01';self.write(path,v)
        h,_=runner.capture_history(self.root)
        with self.assertRaises(ValueError):runner.usage_ledger(self.root,h)

    def test_complete_source_load_keeps_private_history_hash_out_of_public(self):
        _,public,private,usage=runner.load_sources(self.root,freeze_history=True)
        self.assertTrue(all(not x['path'].startswith('.runtime') for x in public))
        self.assertTrue(any(x['path']==runner.HISTORY for x in private))

    def test_parent_byte_change_stops_before_inventory(self):
        p=self.root/runner.PARENT_REPORT;p.write_bytes(p.read_bytes()+b' ')
        with self.assertRaises(ValueError):runner.load_sources(self.root,freeze_history=True)

    def test_guard_specification_changed_stops(self):
        self.write('.runtime/stage5_review_mature_prior_v1/input_guard.json',{'specification':{},'private_sources':[]})
        with self.assertRaises(ValueError):runner.load_sources(self.root,freeze_history=True)


class GuardAndPublicationTests(unittest.TestCase):
    def test_label_builders_models_and_metrics_forbidden(self):
        from sklearn.linear_model import LogisticRegression
        from scripts import review_baseline_evaluation as metrics
        for call in [lambda:files.label_asof(None,None,None),lambda:files.prepare_reviews(None),
                     lambda:LogisticRegression(),lambda:metrics.evaluate_role(None,None)]:
            with self.subTest(call=call),self.assertRaises(RuntimeError):
                with runner.forbid_execution():call()

    def test_swallowed_target_builder_still_stops(self):
        with self.assertRaises(RuntimeError):
            with runner.forbid_execution():
                try:files.build_membership(None,None)
                except RuntimeError:pass

    def test_outside_output_stops(self):
        with self.assertRaises(ValueError):runner.output('../outside.json',runner.ROOT)

    def test_source_change_after_write_retracts_new_report(self):
        @contextmanager
        def guard():yield {'forbidden_calls':0}
        with tempfile.TemporaryDirectory(dir=runner.ROOT/'.runtime',prefix='window_publish_test_') as n:
            root=Path(n)
            spec={'public_sources':[],'protocol':{},'future_validation_gates':[],'stage4':{'status':'pending_data'}}
            p=root/runner.SPEC;p.parent.mkdir(parents=True);p.write_bytes(files.json_bytes(spec));sd=files.descriptor(p,root)
            p=root/runner.GUARD;p.parent.mkdir(parents=True);p.write_bytes(files.json_bytes({'format_version':1,'specification':sd,'private_sources':[]}))
            p=root/files.REVIEWS;p.parent.mkdir(parents=True)
            p.write_text(','.join(runner.core.REVIEW_COLUMNS+('review_score',))+'\n',encoding='utf8')
            p=root/runner.SOURCE_METADATA;p.parent.mkdir(parents=True)
            p.write_bytes(files.json_bytes({'public_sources':[{'id':'olist_ecommerce_card','live_current_version_field':2,'live_last_updated':'fixture','version_caution':'fixture'}]}))
            bundle=SimpleNamespace(raw_orders=pd.DataFrame(columns=runner.core.ORDER_COLUMNS),
                membership=pd.DataFrame(columns=runner.core.MEMBER_COLUMNS),verify_stable=lambda:None)
            with patch.object(runner,'forbid_execution',guard),\
                 patch.object(runner,'load_sources',return_value=(bundle,[],[],{})),\
                 patch.object(runner,'make_specification',return_value=spec),\
                 patch.object(runner,'output',side_effect=lambda n,r:Path(r)/n),\
                 patch.object(runner.core,'inventory',return_value={}),\
                 patch.object(runner.files,'verify_sources',side_effect=[0,0,ValueError('changed')]):
                with self.assertRaises(ValueError):runner.run(root)
            self.assertFalse((root/runner.REPORT).exists())


if __name__=='__main__':unittest.main()
