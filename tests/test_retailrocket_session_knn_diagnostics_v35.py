from dataclasses import replace
from types import MappingProxyType
import unittest

from scripts import retailrocket_session_knn_diagnostics_v35 as d
from scripts import retailrocket_session_knn_snapshot_v30 as codec
from scripts import retailrocket_session_knn_sources_v24 as observed
from scripts import run_retailrocket_session_knn_v2 as io
from tests import test_retailrocket_session_knn_reuse_v27 as inherited
from tests.test_retailrocket_session_knn_snapshot_v30 import snapshot


class ValidationTests(unittest.TestCase):
    def test_full_exact_preimage_empty_repeats_and_large_integers(self):
        huge=10**100+17
        for value in (snapshot(),snapshot(first={},counts={},times=(),fallback=()),
                snapshot(first={'10':huge,'1':0},counts={'1':huge},times=(huge,0,huge),fallback=('10','1','10'))):
            self.assertEqual(d.encode_snapshot(value),codec.encode_snapshot(value))
            self.assertEqual(d.fingerprint(value),codec.fingerprint(value))

    def test_schema_and_every_field_rejected_like_original(self):
        original=snapshot()
        cases=[{},replace(original,first=dict(original.first)),replace(original,counts=dict(original.counts)),
            replace(original,first_times=[1]),replace(original,fallback=['1']),
            snapshot(first={'01':1}),snapshot(counts={'１':1}),snapshot(first={'1':True}),
            snapshot(counts={'1':1.0}),snapshot(times=(-1,)),snapshot(fallback=('١',))]
        missing=snapshot();object.__delattr__(missing,'counts');cases.append(missing)
        for value in cases:
            with self.subTest(value=repr(value) if value is not missing else 'missing'):
                with self.assertRaises(ValueError):codec.fingerprint(value)
                with self.assertRaises(ValueError):d.fingerprint(value)

    def test_no_stale_cache_and_complete_watch_calls(self):
        value=snapshot();base=[];measured=[];records=[]
        expected=codec.fingerprint(value,watch=lambda:base.append(None))
        self.assertEqual(d.fingerprint(value,watch=lambda:measured.append(None),watch_observations=records),expected)
        self.assertEqual(len(base),len(measured));self.assertEqual(records[0]['watch_calls'],len(base))
        object.__setattr__(value,'fallback',('1','2','10'))
        self.assertNotEqual(d.fingerprint(value),expected)

    def test_field_phases_conserve_observation_tree(self):
        obs=observed.Observation();d.fingerprint(snapshot(),obs);summary=obs.summary()
        for phase in d.VALIDATION_PHASES:self.assertEqual(summary['phases'][phase]['calls'],1)
        self.assertEqual(summary['phases']['snapshot.release']['calls'],2)
        self.assertEqual(sum(p['exclusive_wall_ns'] for p in summary['phases'].values()),summary['root_wall_ns'])
        self.assertTrue(all(e['metadata'].get('scheme')==codec.SCHEME for e in obs.events))

    def test_amortized_watch_counters_do_not_time_every_item(self):
        calls=[];ticks=iter((10,25,50,75));counter=d.WatchCounter(lambda:calls.append(None),clock=lambda:next(ticks))
        for _ in range(2051):counter()
        report=counter.report(True)
        self.assertEqual(len(calls),2051);self.assertEqual(report['watch_calls'],2051)
        self.assertEqual(report['sampled_calls'],2);self.assertEqual(report['unsampled_count'],2049)
        self.assertEqual(report['started_sampling_counter'],2);self.assertEqual(report['stopped_sampling_counter'],2)
        self.assertEqual(report['sample_seconds'],40/1e9)
        with self.assertRaises(ValueError):d.WatchCounter(lambda:None,1)

    def test_watch_failure_preserves_failure_and_balances_scopes(self):
        obs=observed.Observation();records=[]
        def stop():raise TimeoutError('artificial deadline')
        with self.assertRaises(TimeoutError):d.fingerprint(snapshot(),obs,stop,watch_observations=records)
        self.assertFalse(obs.stack);self.assertFalse(records[0]['completed']);self.assertEqual(records[0]['watch_calls'],1)
        self.assertEqual(obs.summary()['phases']['snapshot.validation.first.traversal_copy']['failed'],1)

    def test_isolated_timer_observation_not_a_cost_correction(self):
        ticks=iter((1,5,10,20));result=d.timer_overhead(2,clock=lambda:next(ticks))
        self.assertEqual(result['sum_ns'],14);self.assertEqual(result['samples'],2)
        self.assertNotIn('corrected_seconds',result)

    def test_prepare_bytecode_wrappers_preserve_full_output_and_watch_calls(self):
        catalog={'10':10,'2':1,'1':1};counts={'1':3,'2':3,'10':0};before=[];after=[]
        expected=d.c1.ORIGINALS[2](catalog,counts,lambda:before.append(None))
        obs=observed.Observation();actual=d._Cold(None,obs).prepare(catalog,counts,lambda:after.append(None))
        self.assertEqual(before,after);self.assertEqual(codec.encode_snapshot(actual),codec.encode_snapshot(expected))
        self.assertEqual(type(actual),codec.FrozenCatalog);self.assertEqual(type(actual.counts),MappingProxyType)


class ContextTests(inherited.ContextTests):
    def rebind(self):
        super().rebind()
        self.request['metadata']={'fingerprint_scheme':codec.SCHEME}
        self.contract['methods'].extend(io.describe(io.ROOT/p) for p in (
            'scripts/retailrocket_session_knn_snapshot_v30.py','scripts/retailrocket_session_knn_snapshot_adapter_v30.py',
            'scripts/retailrocket_session_knn_diagnostics_v35.py'))
        self.pool=d.WorkerContext(self.contract,self.root,io.ROOT)

    def test_invalid_contract_failure_poison_is_preserved(self):
        self.pool.contract.pop('dependencies');store,obs=self.store()
        with store.writer(),self.assertRaises(KeyError):self.load(store,obs)
        self.assertTrue(self.pool.poisoned);self.assertIsNone(self.pool.prepared)

    def test_detailed_cold_phases_keep_original_types_bytes_and_fifteen_live_checks(self):
        phases={};fingerprints=0;prepared=None
        originals=(d.c1.WorkerContext.load,d.c1.ORIGINALS[2],codec.fingerprint,codec._rows)
        for i in range(7):
            _,obs,prepared=self.cycle();summary=obs.summary()
            fingerprints+=summary['phases']['snapshot.fingerprint']['calls']
            for name,value in summary['phases'].items():phases[name]=phases.get(name,0)+value['calls']
            self.assertEqual(summary['phases']['snapshot.fingerprint']['calls'],3 if i==0 else 2)
        self.assertEqual(fingerprints,15);self.assertEqual(len(self.pool.watch_observations),15)
        self.assertEqual(phases['cold.buffer.acquire'],4)
        for name in ('cold.parse.config','cold.parse.model','cold.expected_fingerprint'):self.assertEqual(phases[name],1)
        self.assertEqual(phases['cold.canonical.compare'],4);self.assertEqual(phases['cold.canonical.expected'],2)
        self.assertEqual(phases['cold.buffer.view'],2);self.assertEqual(phases['cold.prepare.mapping_view'],2)
        self.assertEqual(phases['cold.prepare.frozen_catalog'],1)
        self.assertEqual(type(prepared),codec.FrozenCatalog);self.assertEqual(type(prepared.first),MappingProxyType)
        self.assertEqual(self.pool.expected_config,d.c1.canonical(self.config));self.assertEqual(self.pool.expected_model,d.c1.canonical(self.model))
        self.assertEqual(self.pool.expected_digest,codec.fingerprint(prepared))
        self.assertEqual(originals,(d.c1.WorkerContext.load,d.c1.ORIGINALS[2],codec.fingerprint,codec._rows))
        self.assertEqual(self.pool.completed_summary()['fingerprint_scheme'],codec.SCHEME)


if __name__=='__main__':unittest.main()
