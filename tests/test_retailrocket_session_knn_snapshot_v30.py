"""C1-S1 complete schema, exact preimage and adversarial live-content tests."""
from dataclasses import replace
import hashlib
from types import MappingProxyType
import unittest

from scripts import retailrocket_session_knn_snapshot_v30 as codec
from scripts.retailrocket_session_knn_sql_v2 import FrozenCatalog
from scripts.retailrocket_session_knn_sources_v24 import Observation


def snapshot(first=None,counts=None,times=(1,1,10),fallback=('2','1','10')):
    return FrozenCatalog(MappingProxyType({'2':1,'1':1,'10':10} if first is None else first),
        MappingProxyType({'2':3,'1':2,'10':0} if counts is None else counts),times,fallback)


class SnapshotSchemaTests(unittest.TestCase):
    def test_exact_FrozenCatalog_mappingproxy_tuple_types(self):
        original=snapshot()
        class Other(FrozenCatalog):pass
        for value in (None,{},Other(original.first,original.counts,original.first_times,original.fallback),
                replace(original,first=dict(original.first)),replace(original,counts=dict(original.counts)),
                replace(original,first_times=list(original.first_times)),replace(original,fallback=list(original.fallback))):
            with self.subTest(value=type(value).__name__),self.assertRaises(ValueError):codec.fingerprint(value)

    def test_all_four_fields_present_and_field_order(self):
        value=snapshot();object.__delattr__(value,'fallback')
        with self.assertRaises(ValueError):codec.fingerprint(value)
        expected=codec.PREFIX+b'[["first",[["1",1],["10",10],["2",1]]],["counts",[["1",2],["10",0],["2",3]]],["first_times",[1,1,10]],["fallback",["2","1","10"]]]'
        self.assertEqual(codec.encode_snapshot(snapshot()),expected)
        self.assertEqual(codec.fingerprint(snapshot()),hashlib.sha256(expected).hexdigest())

    def test_canonical_ASCII_numeric_string_IDs(self):
        for item in ('','01','-1','+1','１','١','1.0',' 1','1\n',1,True):
            for value in (snapshot(first={item:1}),snapshot(counts={item:1}),snapshot(fallback=(item,))):
                with self.subTest(item=item),self.assertRaises(ValueError):codec.fingerprint(value)

    def test_bool_float_int_not_aliased(self):
        for value in (True,False,1.0,float('nan'),float('inf'),'1'):
            for state in (snapshot(first={'1':value}),snapshot(counts={'1':value}),snapshot(times=(value,))):
                with self.subTest(value=value),self.assertRaises(ValueError):codec.fingerprint(state)

    def test_nonnegative_counts_and_timestamps(self):
        for state in (snapshot(first={'1':-1}),snapshot(counts={'1':-1}),snapshot(times=(-1,))):
            with self.assertRaises(ValueError):codec.fingerprint(state)
        zero=snapshot(first={'0':0},counts={'0':0},times=(0,),fallback=('0',))
        self.assertEqual(codec.encode_snapshot(zero),codec.PREFIX+b'[["first",[["0",0]]],["counts",[["0",0]]],["first_times",[0]],["fallback",["0"]]]')

    def test_large_integers_not_float_rounded(self):
        large=10**100+37;value=snapshot(first={'1':large},counts={'1':large+1},times=(large,),fallback=('1',))
        data=codec.encode_snapshot(value)
        self.assertIn(str(large).encode(),data);self.assertIn(str(large+1).encode(),data)
        self.assertNotIn(b'e+',data);self.assertNotEqual(codec.fingerprint(value),codec.fingerprint(replace(value,first_times=(large+1,))))

    def test_map_insertion_order_equivalence(self):
        a=snapshot();b=snapshot(first=dict(reversed(list(a.first.items()))),counts=dict(reversed(list(a.counts.items()))))
        self.assertEqual(codec.encode_snapshot(a),codec.encode_snapshot(b))
        self.assertEqual(codec.fingerprint(a),codec.fingerprint(b))

    def test_tuple_order_duplicates_and_empty_snapshot(self):
        original=snapshot()
        self.assertNotEqual(codec.fingerprint(original),codec.fingerprint(replace(original,first_times=(1,10))))
        self.assertNotEqual(codec.fingerprint(original),codec.fingerprint(replace(original,first_times=(10,1,1))))
        empty=snapshot(first={},counts={},times=(),fallback=())
        self.assertEqual(codec.encode_snapshot(empty),codec.PREFIX+b'[["first",[]],["counts",[]],["first_times",[]],["fallback",[]]]')


class SnapshotMutationTests(unittest.TestCase):
    def test_changed_first_key_or_value(self):
        original=snapshot()
        for value in ({'1':1,'2':1,'10':11},{'1':1,'3':1,'10':10}):
            self.assertNotEqual(codec.fingerprint(original),codec.fingerprint(replace(original,first=MappingProxyType(value))))

    def test_changed_count_key_or_value(self):
        original=snapshot()
        for value in ({'1':3,'2':3,'10':0},{'1':2,'3':3,'10':0}):
            self.assertNotEqual(codec.fingerprint(original),codec.fingerprint(replace(original,counts=MappingProxyType(value))))

    def test_changed_first_times_value_or_order(self):
        original=snapshot()
        for values in ((1,2,10),(10,1,1)):
            self.assertNotEqual(codec.fingerprint(original),codec.fingerprint(replace(original,first_times=values)))

    def test_changed_fallback_value_or_order(self):
        original=snapshot()
        for values in (('2','1','11'),('1','2','10')):
            self.assertNotEqual(codec.fingerprint(original),codec.fingerprint(replace(original,fallback=values)))

    def test_scheme_prefix_and_event_version_mismatch(self):
        value=snapshot();data=codec.encode_snapshot(value)
        self.assertTrue(data.startswith(codec.PREFIX))
        self.assertNotEqual(codec.fingerprint(value),hashlib.sha256(data[len(codec.PREFIX):]).hexdigest())
        self.assertNotEqual(codec.fingerprint(value),hashlib.sha256(b'wrong\n'+data[len(codec.PREFIX):]).hexdigest())
        obs=Observation();codec.fingerprint(value,obs)
        self.assertTrue(all(e['metadata']['scheme']==codec.SCHEME for e in obs.events))

    def test_cached_encoded_bytes_cannot_hide_live_mutation(self):
        value=snapshot();saved=codec.encode_snapshot(value);first=codec.fingerprint(value)
        object.__setattr__(value,'fallback',('1','2','10'))
        self.assertEqual(saved,codec.encode_snapshot(snapshot()))
        self.assertNotEqual(first,codec.fingerprint(value))

    def test_truncation_or_omitted_tail_rejected(self):
        value=snapshot()
        for changed in (replace(value,first=MappingProxyType({'1':1,'2':1})),replace(value,counts=MappingProxyType({'1':2,'2':3})),
                replace(value,first_times=value.first_times[:-1]),replace(value,fallback=value.fallback[:-1])):
            self.assertNotEqual(codec.fingerprint(value),codec.fingerprint(changed))
        data=codec.encode_snapshot(value)
        self.assertNotEqual(codec.fingerprint(value),hashlib.sha256(data[:-1]).hexdigest())

    def test_no_sorting_sequences_to_hide_tampering(self):
        value=snapshot(times=(10,1,1),fallback=('10','2','1'))
        data=codec.encode_snapshot(value)
        self.assertIn(b'["first_times",[10,1,1]]',data);self.assertIn(b'["fallback",["10","2","1"]]',data)
        self.assertNotEqual(codec.fingerprint(value),codec.fingerprint(replace(value,first_times=(1,1,10))))

    def test_separate_validation_JSON_UTF8_SHA_release_timers(self):
        obs=Observation();codec.fingerprint(snapshot(),obs)
        summary=obs.summary();phases=summary['phases']
        for phase in ('snapshot.validation','snapshot.json','snapshot.utf8','snapshot.sha256'):
            self.assertEqual(phases[phase]['calls'],1);self.assertEqual(phases[phase]['completed'],1)
        self.assertEqual(phases['snapshot.release']['calls'],2)
        self.assertEqual(sum(x['exclusive_wall_ns'] for x in phases.values()),summary['root_wall_ns'])

    def test_watch_failure_keeps_failed_observation(self):
        obs=Observation()
        def watch():raise TimeoutError('artificial stop')
        with self.assertRaises(TimeoutError):codec.fingerprint(snapshot(),obs,watch)
        self.assertFalse(obs.stack);self.assertEqual(obs.summary()['phases']['snapshot.validation']['failed'],1)


if __name__=='__main__':unittest.main()
