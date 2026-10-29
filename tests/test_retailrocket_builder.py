"""Hand-counted boundaries, anonymous IDs, causal candidates and raw ZIP parity."""
import csv
import hashlib
import io
import json
from pathlib import Path
import sqlite3
import unittest
import uuid
import zipfile

from scripts import retailrocket_builder as b
from scripts import retailrocket_reference as r

ROOT=Path(__file__).resolve().parents[1]
POLICY=json.loads((ROOT/'docs/contracts/retailrocket_recommendation_v1.json').read_text(encoding='utf-8'))
W=b.bounds(POLICY)
START=dict((role,s) for role,s,e in W)
END=dict((role,e) for role,s,e in W)


def event(t=None,v='0',e='view',i='0',x=''):
    return [str(START['train']+10000000 if t is None else t),v,e,i,x]


class PolicyTests(unittest.TestCase):
    def test_zero_ids_are_valid(self):self.assertEqual(b.decode_event(event()),'')
    def test_leading_zero_id_is_not_coerced(self):self.assertNotEqual(b.decode_event(event(i='01')),'')
    def test_float_id_is_not_coerced(self):self.assertNotEqual(b.decode_event(event(v='1.0')),'')
    def test_non_ascii_digits_rejected(self):self.assertNotEqual(b.decode_event(event(i='１')),'')
    def test_whitespace_not_stripped(self):self.assertNotEqual(b.decode_event(event(i=' 1')),'')
    def test_missing_visitor_not_imputed(self):self.assertNotEqual(b.decode_event(event(v='')),'')
    def test_unknown_event_rejected(self):self.assertEqual(b.decode_event(event(e='click')),'unknown_event')
    def test_transaction_requires_id(self):self.assertNotEqual(b.decode_event(event(e='transaction')),'')
    def test_valid_transaction(self):self.assertEqual(b.decode_event(event(e='transaction',x='0')),'')
    def test_nontransaction_with_id_rejected(self):self.assertNotEqual(b.decode_event(event(x='2')),'')
    def test_timestamp_float_rejected(self):self.assertNotEqual(b.decode_event(['1.5','0','view','0','']),'')
    def test_timestamp_overflow_rejected(self):self.assertNotEqual(b.decode_event(event(t=2**63)),'')
    def test_start_inclusive(self):self.assertEqual(b.role_for(START['validation'],W),'validation')
    def test_end_exclusive(self):self.assertEqual(b.role_for(END['reserved_test'],W),'outside_v1')
    def test_training_end_is_validation(self):self.assertEqual(b.role_for(END['train'],W),'validation')
    def test_before_warmup_outside(self):self.assertEqual(b.role_for(START['warmup']-1,W),'outside_v1')
    def test_warmup_never_labelled(self):self.assertEqual(b.query_decision(START['warmup'], 'warmup',START['warmup']+1,'warmup',W)[-1],'warmup_context_only')
    def test_gap_exactly_30_minute_labelled(self):
        t=START['train']+10000000
        self.assertEqual(b.query_decision(t,'train',t+1800000,'train',W),(True,True,False,'labelled'))
    def test_gap_one_ms_over_has_no_continuation(self):
        t=START['train']+10000000
        self.assertEqual(b.query_decision(t,'train',t+1800001,'train',W)[-1],'no_observed_continuation')
    def test_no_observed_next_is_not_negative(self):
        self.assertEqual(b.query_decision(START['train'],'train',None,None,W)[-1],'no_observed_continuation')
    def test_maturity_equal_end_allowed(self):
        t=END['train']-1800000
        self.assertEqual(b.query_decision(t,'train',t+1,'train',W)[-1],'labelled')
    def test_one_ms_short_observation_censored(self):
        t=END['train']-1800000+1
        self.assertEqual(b.query_decision(t,'train',t+1,'train',W)[-1],'right_censored')
    def test_cross_role_at_horizon_not_labelled(self):
        t=END['train']-1800000
        self.assertEqual(b.query_decision(t,'train',END['train'],'validation',W),(True,True,True,'cross_role_target'))
    def test_conflicting_property_does_not_pick_file_order(self):self.assertEqual(b.property_state('available',['0','1']),('conflict',None))
    def test_exact_property_duplicates_collapse(self):self.assertEqual(b.property_state('available',['1','1']),('known','1'))
    def test_invalid_availability_unknown(self):self.assertEqual(b.property_state('available',['yes']),('invalid_value',None))
    def test_invalid_category_unknown(self):self.assertEqual(b.property_state('categoryid',['01']),('invalid_value',None))
    def test_source_hash_uses_all_five_raw_fields(self):
        self.assertNotEqual(hashlib.sha256(b.compact(event(e='transaction',x='1')).encode()).hexdigest(),hashlib.sha256(b.compact(event(e='transaction',x='2')).encode()).hexdigest())


class EndToEndTests(unittest.TestCase):
    def test_hand_counted_raw_zip_every_output_and_future_invariance(self):
        scratch=ROOT/'shop-mysql-runtime/verification/retailrocket-build-v1/synthetic'/uuid.uuid4().hex
        scratch.mkdir(parents=True)
        t=START['train']+10000000
        events=[event(t,i='10'),event(t,i='10'),event(t,i='2'),event(t+1,i='2'),event(t+1,i='99'),
                event(t+1800001,i='10'),event(t+3600002,i='10'),event(END['train']-1800000,v='1',i='10'),
                event(END['train'],v='1',i='2'),event(END['reserved_test'],v='2',i='7'),
                event(START['warmup']+1,v='3',i='5'),event(t-1,v='4',e='transaction',i='8',x='1')]
        properties=[ [str(t-1),'10','available','1'],[str(t),'2','available','0'],[str(t+1),'2','available','1'],
                    [str(t-1),'10','categoryid','1'],[str(t-1),'99','categoryid','99'],
                    [str(t-1),'99','available','0'],[str(t-1),'99','available','1'] ]
        package=scratch/'tiny.zip'
        with zipfile.ZipFile(package,'x') as z:
            for name,rows in [('events.csv',events),('item_properties_part1.csv',properties),('item_properties_part2.csv',[]),('category_tree.csv',[['1','']])]:
                f=io.StringIO(newline='');writer=csv.writer(f,lineterminator='\n');writer.writerow(POLICY['schemas'][name]);writer.writerows(rows);z.writestr(name,f.getvalue())
        with zipfile.ZipFile(package) as z:sha=hashlib.sha256(z.read('events.csv')).hexdigest()
        folder=scratch/'outputs';folder.mkdir()
        summary=b.build(package,POLICY,{'files':[{'name':'events.csv','sha256':sha}]},folder)
        accepted=r.verify(package,POLICY,{'files':[{'name':'events.csv','sha256':sha}]},folder,b.SCHEMAS)
        self.assertGreater(accepted['cells'],0)
        self.assertEqual(summary['row_decisions'],{'canonical':10,'duplicate':1,'excluded':1})
        def read(name):
            with (folder/name).open(encoding='utf-8',newline='') as f:return list(csv.DictReader(f))
        queries=read('queries.csv');first=next(q for q in queries if q['visitorid']=='0' and int(q['query_ms'])==t)
        self.assertEqual(first['target_items'],'["2","99"]')
        self.assertEqual(first['reachable_target_count'],'0') # first seen at q is not strictly before q
        self.assertEqual(first['candidate_count'],'1') # only warmup item 5
        self.assertEqual(first['all_targets_reachable'],'0')
        self.assertEqual(json.loads(read('baskets.csv')[0]['items']),['2','10'])
        diagnostics=read('view_property_diagnostics.csv')
        same_clock=next(x for x in diagnostics if x['itemid']=='2' and int(x['query_ms'])==t)
        self.assertEqual(same_clock['available_state'],'no_prior_version')
        conflict=next(x for x in diagnostics if x['itemid']=='99')
        self.assertEqual(conflict['available_state'],'conflict')
        self.assertEqual(conflict['category_tree_missing'],'1')
        self.assertTrue(any(x['cross_role']=='1' and x['status']=='cross_role_target' for x in read('boundary_ledger.csv')))
        self.assertTrue(all(int(q['next_view_ms'])>int(q['query_ms']) and q['next_role']==q['role'] for q in queries))
        # Change a source row outside v1: no qualified context, candidates or labels change.
        future=scratch/'future.zip'
        with zipfile.ZipFile(package) as z,zipfile.ZipFile(future,'x') as target:
            for name in z.namelist():
                data=z.read(name)
                if name=='events.csv':data+=(','.join(event(END['reserved_test']+1,v='9',i='123'))+'\n').encode()
                target.writestr(name,data)
        with zipfile.ZipFile(future) as z:future_sha=hashlib.sha256(z.read('events.csv')).hexdigest()
        second=scratch/'future_outputs';second.mkdir()
        b.build(future,POLICY,{'files':[{'name':'events.csv','sha256':future_sha}]},second)
        for name in ('baskets.csv','queries.csv','catalog.csv','view_property_diagnostics.csv'):
            self.assertEqual((folder/name).read_bytes(),(second/name).read_bytes(),name)
        with (folder/'queries.csv').open('a',encoding='utf-8') as f:f.write('corrupt\n')
        with self.assertRaisesRegex(ValueError,'extra CSV'):
            comparison=r.Compare(folder,b.SCHEMAS)
            try:
                for name in b.SCHEMAS:
                    expected_n=summary['files'][name]
                    for _ in range(expected_n):next(comparison.readers[name])
                comparison.finish()
            finally:comparison.close()

    def test_unexpected_header_stops_without_coercion(self):
        scratch=ROOT/'shop-mysql-runtime/verification/retailrocket-build-v1/synthetic'/uuid.uuid4().hex
        scratch.mkdir(parents=True);path=scratch/'bad.zip'
        with zipfile.ZipFile(path,'x') as z:z.writestr('events.csv','wrong,header\n')
        with zipfile.ZipFile(path) as z:
            with self.assertRaisesRegex(ValueError,'header'):list(b.stream_member(z,'events.csv',POLICY['schemas']['events.csv']))


if __name__=='__main__':unittest.main()
