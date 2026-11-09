"""Synthetic entry, full ledger, fault and balanced-adapter checks for V22."""
from copy import deepcopy
from datetime import timedelta
import unittest
from unittest.mock import patch

from scripts import run_retailrocket_session_knn_overlap_v22 as entry
from scripts import retailrocket_session_knn_overlap_v22 as adapter
from scripts import retailrocket_session_knn_checkpoint_v2 as checkpoint
from scripts import retailrocket_session_knn_pair_v4 as pair
from tests import test_retailrocket_session_knn_vote_v17 as old
from tests import test_retailrocket_session_knn_diagnostics_v20 as complete
from tests import test_retailrocket_session_knn_reinforcement_v18 as load_fixture


class EntryTests(unittest.TestCase):
    put = old.VoteEntryTests.put

    def setUp(self):
        context=patch.object(old,'entry',entry);context.start();self.addCleanup(context.stop)
        old.VoteEntryTests.setUp(self)
        self.stack.enter_context(patch.object(entry,'preregistration',side_effect=lambda:self.spec))

    def comparison(self, create_runs=True):
        folder,probes,reference,frame_bytes=old.VoteEntryTests.comparison(self,create_runs=create_runs)
        sources,meta=self.contracts['compare48']
        meta['candidate']='group_before_size_join'
        meta['old_run']='compare48_reference/verified_subset/run.json'
        sources.append(entry.describe(self.root/meta['old_run']))
        request=entry.read(folder/'request.json');request.update(metadata=meta,sources=sources)
        self.put(folder/'request.json',request)
        if create_runs:
            done=entry.read(folder/'done.json');done['candidate']=meta['candidate'];self.put(folder/'done.json',done)
            for phase in ('initial','final'):
                self.put(folder/(phase+'_hash.json'),{'count':len(sources),'seconds':.1})
            for i,(label,mode) in enumerate(entry.schedule('compare48',meta['candidate'])):
                path=folder/label
                event=entry.read(path/'entry.json');event['mode']=mode;self.put(path/'entry.json',event)
                measured=entry.read(path/'measured.json')
                for q in measured['queries']:
                    q['rank_stages_seconds']['sql_positive_overlaps']=q['verification_seconds']*.1
                    q['rank_stages_seconds']['exact_neighbor_selection']=q['verification_seconds']*.3
                self.put(path/'measured.json',measured)
                records=load_fixture.telemetry_case(0,tuple(i*100.+v for v in (1.,1.2,1.4,1.6)))
                for record in records:
                    record['observed_utc']=(self.start+timedelta(seconds=record['monotonic_seconds'])).isoformat()
                span=dict(label=label,mode=mode,repeat_index=0,completed=True,
                    start_monotonic_seconds=i*100.+1.02,end_monotonic_seconds=i*100.+1.58,
                    start_utc=(self.start+timedelta(seconds=i*100.+1.02)).isoformat(),
                    end_utc=(self.start+timedelta(seconds=i*100.+1.58)).isoformat())
                self.put(path/'telemetry_records.json',dict(label=label,mode=mode,records=records))
                self.put(path/'entry_span.json',span)
        return folder,probes,reference,frame_bytes

    def test_all_four_arm_verifier_payloads_and_workload_match_with_symmetric_adapters(self):
        # Reuse the frozen multi-arm synthetic fixture; both native/reference
        # and the new candidate must match its complete nested payload bytes.
        original=complete.diagnostic.make_verifier
        def verifier(mode,events=None):
            if mode=='R':return adapter.make_verifier('group_before_size_join')
            return original(mode,events)
        with patch.object(complete.diagnostic,'make_verifier',side_effect=verifier):
            complete.InstrumentationTests.test_complete_verifier_keeps_all_four_arm_payloads_and_nested_commit_diagnostics(self)
        self.assertIs(pair.sql.predict,adapter.native.predict)

    def test_complete_fourteen_ledgers_physical_frames_warmup_exclusion_and_reaudit(self):
        folder,_,reference,_=self.comparison()
        report=entry._publish(folder)
        self.assertEqual(report['repeat_query_checks'],672)
        self.assertEqual(report['paired_query_checks'],576)
        self.assertEqual(report['warmup_query_checks'],96)
        self.assertEqual(len(report['continuous_load']),14)
        self.assertEqual(report['decision']['faster_pairs'],6)
        self.assertTrue(report['decision']['supports_candidate'])
        self.assertEqual(entry._publish(folder),report)

    def test_forged_payload_deadline_missing_run_timing_or_load_withholds_publication(self):
        folder,_,_,_=self.comparison()
        cases=[('done.json',lambda x:x.update(runs=13)),
            ('pair_6_A/profile.json',lambda x:x.append({'forbidden':True})),
            ('pair_6_A/entry_span.json',lambda x:x.update(completed=False)),
            ('pair_6_A/telemetry_records.json',lambda x:x.update(mode='group_before_size_join')),
            ('pair_6_A/measured.json',lambda x:x['queries'][0].update(rank_seconds=-1.)),
            ('pair_6_A/verified_subset/run.json',lambda x:x.update(budget_seconds=1801))]
        for rel,change in cases:
            p=folder/rel;raw=p.read_bytes();value=entry.read(p);change(value);self.put(p,value)
            try:
                with self.subTest(source=rel),self.assertRaises(ValueError):entry._publish(folder)
                self.assertFalse((self.root/entry.OUTPUT['compare48']).exists())
            finally:p.write_bytes(raw)
        payload=next((folder/'pair_6_A/verified_subset/payloads').glob('*.jsonl'))
        payload.write_bytes(payload.read_bytes()+b'{}\n')
        with self.assertRaises(ValueError):entry._publish(folder)

    def test_request_change_fails_before_run_and_failed_run_preserves_evidence(self):
        folder,_,_,_=self.comparison(create_runs=False)
        request=entry.read(folder/'request.json');bad=deepcopy(request);bad['metadata']['candidate']='rank_counts'
        self.put(folder/'request.json',bad)
        with patch.object(entry,'_observed_run') as run,self.assertRaises(ValueError):entry.worker(folder)
        run.assert_not_called()
        self.put(folder/'request.json',request)
        watch=lambda:None;watch.force=watch
        with patch.object(entry,'_observed_run',side_effect=RuntimeError('synthetic stop')),patch.object(entry,'clear_caches'),patch.object(entry,'ThrottledWatch',return_value=watch):
            with self.assertRaises(RuntimeError):entry.worker(folder)
        self.assertEqual(entry.read(folder/'failure.json')['error_type'],'RuntimeError')
        self.assertTrue((folder/'warm_A_resources_before.json').exists())
        self.assertTrue((folder/'warm_A_resources_after.json').exists())
        self.assertFalse((folder/'done.json').exists())

    def test_all_original_scope_and_deadline_checks_reject_breaches(self):
        old.VoteEntryTests.test_window_scope_resource_and_original_deadline_fail_closed(self)
        for stage in ('compare34','profile','new_sample'):
            with self.assertRaises(ValueError):entry._validate_stage(stage)


class AdapterTests(unittest.TestCase):
    def test_same_proxy_both_arms_only_exact_overlap_statement_replaced(self):
        class DB:
            def __init__(self):self.calls=[]
            def execute(self,*args,**kw):self.calls.append((args,kw));return self
        for statement in (adapter.OVERLAP_SQL,adapter.CANDIDATE_SQL):
            db=DB();proxy=adapter.StatementConnection(db,statement)
            self.assertIs(proxy.execute(adapter.OVERLAP_SQL),db)
            self.assertIs(proxy.execute('SELECT ?', (3,)),db)
            self.assertEqual(db.calls,[((statement,),{}),(('SELECT ?',(3,)),{})])
        with self.assertRaises(ValueError):adapter.make_verifier('rank_counts')

    def test_seal_protocol_candidate_and_scope_are_validated_before_entry(self):
        spec=entry.read(entry.ROOT/entry.SPEC)
        self.assertEqual(entry.preregistration(),spec)
        for key,value in (('candidate','rank_counts'),('status','draft'),('scope',dict(spec['scope'],compare34_enabled=True)),('protocol',dict(spec['protocol'],minimum_median_saving_percent=1))):
            changed=dict(spec,**{key:value})
            with patch.object(entry,'read',return_value=changed),patch.object(entry,'describe',return_value={'sha256':entry.SPEC_SHA256}),self.assertRaises(ValueError):
                entry.preregistration()


if __name__=='__main__':unittest.main()
