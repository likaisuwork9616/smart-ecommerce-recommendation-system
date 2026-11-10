"""Executed-vector evidence for the complete V39 core; never real-data tests.

The parent acceptance runner must execute this suite sequentially. Importing this
module does not execute tests. differential_evidence() refuses an unrun suite.
"""
from collections import Counter
from collections.abc import Mapping
import copy
import math
import pickle
import random
import sys
from types import MappingProxyType
import unittest

from scripts import retailrocket_session_knn_typed_v39 as core

EVIDENCE=dict(differential=[],reference=[],boundary=[],protocol=[])


def reset_evidence():
    for values in EVIDENCE.values():values.clear()


def differential_evidence():
    if not EVIDENCE['differential']:raise ValueError('No differential vectors have been executed')
    rows=copy.deepcopy(EVIDENCE)
    counts=Counter(row['outcome'] for row in rows['differential'])
    ids=[row['id'] for group in rows.values() for row in group]
    return dict(status='v39_executed_artificial_core_vectors',vector_count=sum(len(v) for v in rows.values()),
        differential_vector_count=len(rows['differential']),equal=counts['equal'],unequal=counts['unequal'],
        oracle_rejected=counts['oracle_rejected'],reference_rejection_vectors=len(rows['reference']),
        boundary_vectors=len(rows['boundary']),protocol_vectors=len(rows['protocol']),
        unique_vector_ids=len(set(ids)),vectors=rows,real_data_runs=0,
        interpretation='Counts describe actually executed vectors, not unittest wrapper counts. Runtime/callsite and unstable second-pass nonstring-key admission rejections are separate from oracle-equivalence claims. Public reference construction performs an extra unchanged canonical verification; the worker private path does not.')


class DifferentialCase(unittest.TestCase):
    def check_vector(self,case,value,reference_value=None):
        source=core.ORIGINAL_CANONICAL(reference_value)
        ref=core.build_reference(source)
        try:actual_bytes=core.ORIGINAL_CANONICAL(value)
        except (ValueError,TypeError,RecursionError,UnicodeError,OverflowError) as error:
            try:actual=core.compare_full(value,ref)
            except (ValueError,TypeError,RecursionError,UnicodeError,OverflowError,RuntimeError):actual=False
            self.assertIs(actual,False,case)
            EVIDENCE['differential'].append(dict(id=case,outcome='oracle_rejected',oracle_error=type(error).__name__,candidate_equal=False))
        else:
            expected=actual_bytes==source
            # Unexpected rejection of an oracle-valid value is a test failure,
            # never relabeled as a successful rejected vector.
            actual,stats=core.compare_with_stats(value,ref)
            self.assertIs(actual,expected,case)
            EVIDENCE['differential'].append(dict(id=case,outcome='equal' if expected else 'unequal',
                oracle_bytes=len(actual_bytes),source_bytes=len(source),candidate_equal=actual,visited_nodes=stats['nodes']))


class ScalarTests(DifferentialCase):
    def test_exact_scalar_and_string_vectors(self):
        values=[None,False,True,0,1,-1,10**120+9,-10**120,0.0,-0.0,1.0,-1.5,
            float.fromhex('0x0.0000000000001p-1022'),sys.float_info.max,sys.float_info.min,
            '', 'plain','"\\/',''.join(chr(i) for i in range(32)),'é','e\u0301','中文','😀']
        for index,value in enumerate(values):self.check_vector(f'scalar.equal.{index}',value,value)

    def test_type_and_encoding_inequality_vectors(self):
        pairs=[(True,1),(False,0),(1,1.0),(0,0.0),(0.0,-0.0),('1',1),
            ([],()),([1],(1,)),('é','e\u0301'),(None,False),(-1,1),(10**100+1,10**100+2)]
        for index,(left,right) in enumerate(pairs):self.check_vector(f'scalar.unequal.{index}',left,right)

    def test_mapping_order_and_dict_proxy_equivalence(self):
        values=[{}, {'z':1,'a':[True,2]}, {'中文':-1,'é':0.0,'e\u0301':-0.0}]
        for i,value in enumerate(values):
            self.check_vector(f'map.order.{i}',dict(reversed(list(value.items()))),value)
            self.check_vector(f'map.proxy.{i}',MappingProxyType(value),value)

    def test_unsupported_subclasses_and_invalid_values_are_not_equal(self):
        class I(int):pass
        class S(str):pass
        class L(list):pass
        class D(dict):pass
        values=[float('nan'),float('inf'),-float('inf'),object(),I(1),S('x'),L([1]),D(a=1),
            {'a':float('nan')},{1:'x'},{True:'x'},'\ud800','\udc00','\ud83d\ude00',{'\ud800':1}]
        for index,value in enumerate(values):self.check_vector(f'invalid.scalar.{index}',value)


def generated(rng,depth):
    leaves=[None,False,True,-19,0,10**80+13,0.0,-0.0,1.25,'','é','e\u0301','😀','"\\\n']
    if not depth or rng.randrange(4)==0:return rng.choice(leaves)
    kind=rng.randrange(4);size=rng.randrange(5)
    if kind<2:
        values=[generated(rng,depth-1) for _ in range(size)]
        return values if kind==0 else tuple(values)
    result={f'{i}-'+rng.choice(('a','中','é','\n')):generated(rng,depth-1) for i in range(size)}
    return result if kind==2 else MappingProxyType(result)


class GeneratedTests(DifferentialCase):
    def test_reproducible_nested_equal_and_unequal_graphs(self):
        rng=random.Random(390138)
        for index in range(128):
            value=generated(rng,1+index%8)
            self.check_vector(f'generated.equal.{index}',value,value)
            self.check_vector(f'generated.unequal.{index}',{'original':value,'extra':index},value)


class ReferenceTests(unittest.TestCase):
    def test_malformed_tags_payloads_shapes_and_noncanonical_bytes(self):
        cases=[b'[]',b'null',b'false',b'["unknown"]',b'["none",true]',b'["bool","true"]',
            b'["bool",1]',b'["int","01"]',b'["int","-0"]',b'["int","+1"]',
            b'["float","nan"]',b'["float","inf"]',b'["float","0x1p0"]',
            b'["str",true]',b'["list",[true]]',b'["map",[["z",["none"]],["a",["none"]]]]',
            b'["map",[["a",["none"]],["a",["none"]]]]',b'["map",[["a"]]]',
            b' ["none"]',b'["none"]\n',b'["none",]',b'["str","\\u0061"]',
            b'["str","\\/"]',b'["str","\\u000a"]',b'["str","\\u001A"]',
            b'["str","\\ud800"]',b'["str","\xff"]',b'["list",[]]["none"]']
        for i,value in enumerate(cases):
            with self.subTest(index=i),self.assertRaises((ValueError,TypeError,UnicodeError,OverflowError)):
                core.build_reference(value)
            EVIDENCE['reference'].append(dict(id=f'reference.invalid.{i}',outcome='rejected',bytes=len(value)))
        for value in (bytearray(b'["none"]'),memoryview(b'["none"]'),'["none"]'):
            with self.assertRaises(ValueError):core.build_reference(value)

    def test_reference_is_tuple_only_nonserializable_and_factory_admitted(self):
        source=core.ORIGINAL_CANONICAL({'x':[None,True,-0.0]});ref=core.build_reference(source)
        self.assertIs(type(ref),core.Reference);self.assertFalse(hasattr(ref,'__dict__'))
        for field in ('root','source_bytes','scheme'):
            with self.subTest(field=field),self.assertRaises((AttributeError,TypeError)):
                object.__setattr__(ref,field,None)
        with self.assertRaises(TypeError):core.Reference()
        with self.assertRaises(TypeError):pickle.dumps(ref)
        source_description=ref.source_descriptor;source_description['bytes']=0
        self.assertEqual(ref.source_length,len(source))
        forged=tuple.__new__(core.Reference,tuple(ref))
        with self.assertRaises(ValueError):core.compare_full({'x':[None,True,-0.0]},forged)
        mixed=list(ref);mixed[0]='other-policy';mixed=tuple.__new__(core.Reference,mixed)
        with self.assertRaises(ValueError):core.compare_full({},mixed)
        pending=[ref.root]
        while pending:
            value=pending.pop()
            if type(value) is tuple:pending.extend(value)
            else:self.assertIn(type(value),(str,bool))
        EVIDENCE['reference'].append(dict(id='reference.immutable.factory',outcome='rejected_forgery_and_immutable'))

    def test_public_builder_rechecks_oracle_and_private_boundary_is_explicit(self):
        source=core.ORIGINAL_CANONICAL({'a':(1,True)})
        public=core.build_reference(source)
        self.assertEqual(public.provenance['authority'],'public_original_oracle_validation')
        before=core.capture_runtime();actual=core.ORIGINAL_CANONICAL({'a':(1,True)});after=core.capture_runtime()
        private=core._build_verified_reference(actual,runtime_before=before,runtime_after=after,
            oracle=core.ORIGINAL_CANONICAL,source_role='config')
        self.assertEqual(private.provenance['authority'],'trusted_sealed_adapter_success_attestation')
        self.assertTrue(core.compare_full({'a':(1,True)},private))
        for update in ({'runtime_after':dict(after,recursion_limit=after['recursion_limit']+1)},
                       {'oracle':lambda value:b''},{'source_role':'unverified'}):
            options=dict(runtime_before=before,runtime_after=after,oracle=core.ORIGINAL_CANONICAL,source_role='config');options.update(update)
            with self.assertRaises(ValueError):core._build_verified_reference(source,**options)
        EVIDENCE['boundary'].append(dict(id='provenance.public_and_trusted',outcome='two_explicit_authorities_verified'))

    def test_controlled_stale_admission_cannot_authorize_changed_slots(self):
        ref=core.build_reference(core.ORIGINAL_CANONICAL({'x':1}));lease=ref[7]
        alternatives=['other-scheme',('none',),b'["none"]',0,'0'*64,(),()]
        for index,replacement in enumerate(alternatives):
            fields=list(ref);fields[index]=replacement;forged=tuple.__new__(core.Reference,fields)
            # Simulate a stale registry entry at a reused id deterministically.
            # Do not depend on allocator address reuse or retain encoded caches.
            core._ADMITTED[id(forged)]=lease
            try:
                with self.subTest(slot=index),self.assertRaises(ValueError):core.compare_full({'x':1},forged)
            finally:core._ADMITTED.pop(id(forged),None)
        self.assertTrue(core.compare_full({'x':1},ref))
        EVIDENCE['reference'].append(dict(id='reference.stale_admission_changed_slots',outcome='rejected',slots_checked=7))


class TraversalTests(unittest.TestCase):
    def test_ordinary_mismatch_never_skips_invalid_extra_live_tails(self):
        vectors=[([False,object()],[True]),([1,float('nan')],[0]),
            ({'a':9,'z':object()},{'a':0}),({'a':[9],'extra':['\ud800']},{'a':[0]}),
            ((False,{'bad':float('inf')}),(True,))]
        for i,(live,reference) in enumerate(vectors):
            ref=core.build_reference(core.ORIGINAL_CANONICAL(reference))
            with self.assertRaises((ValueError,UnicodeError,TypeError)):
                core.ORIGINAL_CANONICAL(live)
            with self.subTest(index=i),self.assertRaises((ValueError,UnicodeError,TypeError)):
                core.compare_full(live,ref)
            EVIDENCE['differential'].append(dict(id=f'tail.invalid.{i}',outcome='oracle_rejected',candidate_equal=False))

    def test_shared_acyclic_aliases_are_each_fully_traversed(self):
        shared=[1,{'x':True}];live=[shared,shared,{'again':shared}]
        ref=core.build_reference(core.ORIGINAL_CANONICAL(live));equal,stats=core.compare_with_stats(live,ref)
        self.assertTrue(equal);self.assertEqual(stats['nodes'],ref.statistics()['nodes'])
        self.assertEqual(stats['sequence_items'],9)
        EVIDENCE['differential'].append(dict(id='alias.DAG.repeat',outcome='equal',visited_nodes=stats['nodes']))

    def test_active_ancestry_rejects_cycles_and_recovers_after_failure(self):
        cycle=[];cycle.append(cycle);mapping={};mapping['x']=mapping
        backing={};proxy=MappingProxyType(backing);backing['x']=proxy
        child=[];mixed=(child,);child.append(mixed)
        ref=core.build_reference(core.ORIGINAL_CANONICAL(None))
        for i,value in enumerate((cycle,mapping,proxy,mixed)):
            with self.assertRaises((ValueError,RecursionError)):core.ORIGINAL_CANONICAL(value)
            with self.subTest(index=i),self.assertRaises((ValueError,RecursionError)):core.compare_full(value,ref)
            self.assertTrue(core.compare_full(None,ref))
            EVIDENCE['differential'].append(dict(id=f'cycle.{i}',outcome='oracle_rejected',candidate_equal=False))

    def test_proxy_protocol_exact_all_keyscan_sorted_then_getitem(self):
        class Trace(Mapping):
            def __init__(self,values):self.values=values;self.trace=[]
            def __iter__(self):self.trace.append(('iter',));return iter(self.values)
            def __len__(self):self.trace.append(('len',));return len(self.values)
            def __getitem__(self,key):self.trace.append(('get',key));return self.values[key]
            def items(self):raise AssertionError('items() is not the original protocol')
        for index,values in enumerate(({'z':[1,True],'a':0},{'z':1,'a':2})):
            trace=Trace(values);live=MappingProxyType(trace);source=core.ORIGINAL_CANONICAL(live);expected=list(trace.trace)
            ref=core.build_reference(source);trace.trace.clear()
            self.assertTrue(core.compare_full(live,ref));self.assertEqual(trace.trace,expected)
            self.assertEqual([x for x in trace.trace if x[0]=='get'],[('get','a'),('get','z')])
            EVIDENCE['protocol'].append(dict(id=f'proxy.trace.{index}',outcome='exact_original_protocol',events=trace.trace))
        trace=Trace({'a':1,2:3});proxy=MappingProxyType(trace)
        with self.assertRaises(ValueError):core.ORIGINAL_CANONICAL(proxy)
        expected=list(trace.trace);trace.trace.clear();ref=core.build_reference(core.ORIGINAL_CANONICAL(None))
        with self.assertRaises(ValueError):core.compare_full(proxy,ref)
        self.assertEqual(trace.trace,expected)
        EVIDENCE['protocol'].append(dict(id='proxy.nonstring.shortcircuit',outcome='exact_original_protocol',events=trace.trace))

    def test_proxy_reentry_is_rejected_without_leaking_busy_state(self):
        ref=core.build_reference(core.ORIGINAL_CANONICAL({'x':1}))
        class Reentrant(Mapping):
            def __iter__(self):return iter(('x',))
            def __len__(self):return 1
            def __getitem__(self,key):return core.compare_full({'x':1},ref)
        with self.assertRaises((RuntimeError,ValueError)):core.compare_full(MappingProxyType(Reentrant()),ref)
        self.assertTrue(core.compare_full({'x':1},ref))
        EVIDENCE['protocol'].append(dict(id='proxy.reentry',outcome='rejected_and_busy_released'))

    def test_dynamic_second_pass_string_payload_matches_original_json(self):
        class LieStr(str):
            def __new__(cls,value,answer):
                instance=super().__new__(cls,value);instance.answer=answer;return instance
            def __eq__(self,other):return self.answer
            __hash__=str.__hash__
            def __str__(self):return 'not-the-Unicode-payload'
            def encode(self,*args,**kwargs):return b'a'
        class Dynamic(Mapping):
            def __init__(self,key):self.key=key;self.iterations=0;self.trace=[]
            def __iter__(self):
                self.iterations+=1;self.trace.append(('iter',self.iterations))
                return iter(('a',)) if self.iterations==1 else iter((self.key,))
            def __len__(self):self.trace.append(('len',));return 1
            def __getitem__(self,key):self.trace.append(('get',str.__str__(key)));return 1
            def items(self):raise AssertionError('Unexpected mapping protocol')
        source=core.ORIGINAL_CANONICAL({'a':1});ref=core.build_reference(source)
        for i,(payload,answer,expected_equal) in enumerate((('b',True,False),('a',False,True))):
            oracle_map=Dynamic(LieStr(payload,answer));actual_bytes=core.ORIGINAL_CANONICAL(MappingProxyType(oracle_map))
            compared_map=Dynamic(LieStr(payload,answer));result=core.compare_full(MappingProxyType(compared_map),ref)
            self.assertIs(result,actual_bytes==source);self.assertIs(result,expected_equal)
            self.assertEqual(compared_map.trace,oracle_map.trace)
            EVIDENCE['protocol'].append(dict(id=f'proxy.dynamic_unicode.{i}',outcome='exact_original_payload_and_protocol',
                expected_equal=expected_equal,events=compared_map.trace))

    def test_caught_nested_comparison_still_invalidates_outer_and_resets(self):
        ref=core.build_reference(core.ORIGINAL_CANONICAL({'x':1}));attempts=[]
        class Catching(Mapping):
            def __iter__(self):return iter(('x',))
            def __len__(self):return 1
            def __getitem__(self,key):
                if not attempts:
                    attempts.append(True)
                    try:core.compare_full({'x':1},ref)
                    except (RuntimeError,ValueError):pass
                return 1
        with self.assertRaises(RuntimeError):core.compare_full(MappingProxyType(Catching()),ref)
        self.assertEqual(attempts,[True]);self.assertTrue(core.compare_full({'x':1},ref))
        EVIDENCE['protocol'].append(dict(id='proxy.caught_reentry',outcome='outer_rejected_and_busy_released'))

    def test_dynamic_second_pass_nonstr_is_explicit_admission_not_oracle_rejection(self):
        class Dynamic(Mapping):
            def __init__(self,key):self.key=key;self.iterations=0
            def __iter__(self):
                self.iterations+=1
                return iter(('a',)) if self.iterations==1 else iter((self.key,))
            def __len__(self):return 1
            def __getitem__(self,key):return 1
        source=core.ORIGINAL_CANONICAL({'a':1});ref=core.build_reference(source)
        for i,key in enumerate((None,1,True)):
            oracle=core.ORIGINAL_CANONICAL(MappingProxyType(Dynamic(key)))
            self.assertNotEqual(oracle,source)
            with self.subTest(key=key),self.assertRaises(TypeError):
                core.compare_full(MappingProxyType(Dynamic(key)),ref)
            EVIDENCE['boundary'].append(dict(id=f'proxy.dynamic_nonstr_admission.{i}',
                outcome='oracle_valid_unequal_but_dynamic_key_admission_rejected',oracle_bytes=len(oracle),candidate_error='TypeError'))


def _approved_at_original_callsite(value):
    before=core.capture_runtime();source=core.ORIGINAL_CANONICAL(value);after=core.capture_runtime()
    return core._build_verified_reference(source,runtime_before=before,runtime_after=after,
        oracle=core.ORIGINAL_CANONICAL,source_role='model')


class BoundaryTests(unittest.TestCase):
    def test_last_proxy_read_permanent_runtime_change_cannot_return_equal(self):
        limit=sys.getrecursionlimit();deep=None
        for _ in range(120):deep=[deep]
        source={'a':1,'z':deep};ref=core.build_reference(core.ORIGINAL_CANONICAL(source));lowered=[]
        class LowerAtLastRead(Mapping):
            def __iter__(self):return iter(('a','z'))
            def __len__(self):return 2
            def __getitem__(self,key):
                if key=='z':
                    budget=max(80,core.capture_runtime()['frame_depth']+32)
                    lowered.append(budget);sys.setrecursionlimit(budget)
                return source[key]
        try:
            with self.assertRaises(RecursionError):core.ORIGINAL_CANONICAL(MappingProxyType(LowerAtLastRead()))
        finally:sys.setrecursionlimit(limit)
        try:
            with self.assertRaises(ValueError):core.compare_with_stats(MappingProxyType(LowerAtLastRead()),ref)
        finally:sys.setrecursionlimit(limit)
        self.assertTrue(core.compare_full(source,ref))
        EVIDENCE['boundary'].append(dict(id='runtime.permanent_last_proxy_mutation',
            outcome='actual_original_and_candidate_reject_runtime_mutation',restored_after_failure=True,lowered_limits=lowered))

    def test_current_runtime_and_attested_callsite_are_checked(self):
        ref=_approved_at_original_callsite(1)
        runtime=core.capture_runtime();self.assertTrue(core.compare_full(1,ref,runtime=runtime))
        with self.assertRaises(ValueError):core.compare_full(1,ref,runtime=dict(runtime,frame_depth=runtime['frame_depth']+1))
        limit=sys.getrecursionlimit()
        try:
            sys.setrecursionlimit(limit+73)
            with self.assertRaises(ValueError):core.compare_full(1,ref)
        finally:sys.setrecursionlimit(limit)
        self.assertTrue(core.compare_full(1,ref))
        EVIDENCE['boundary'].append(dict(id='runtime.recursion_and_callsite',outcome='policy_eligibility_rejection_not_oracle_equivalence'))

    def test_integer_limit_change_and_large_decimal_conversion(self):
        if not hasattr(sys,'set_int_max_str_digits'):self.fail('This frozen runtime requires the integer digit-limit API')
        limit=sys.get_int_max_str_digits()
        try:
            sys.set_int_max_str_digits(0);value=10**5000+7
            ref=_approved_at_original_callsite(value);self.assertTrue(core.compare_full(value,ref))
            sys.set_int_max_str_digits(4300)
            with self.assertRaises(ValueError):core.ORIGINAL_CANONICAL(value)
            with self.assertRaises(ValueError):core.compare_full(value,ref)
            EVIDENCE['boundary'].append(dict(id='runtime.integer_digits',outcome='oracle_and_policy_reject_changed_limit',decimal_digits=5001))
        finally:sys.set_int_max_str_digits(limit)

    def test_near_limit_worker_approval_and_public_deep_bytes_rejection(self):
        original_limit=sys.getrecursionlimit();approved=0;last_depth=None
        try:
            sys.setrecursionlimit(500);value=None
            for depth in range(501):
                try:ref=_approved_at_original_callsite(value)
                except RecursionError:
                    last_depth=depth;break
                # This is an actual oracle success at the recorded worker callsite;
                # iterative grammar/comparison must not introduce a lower cutoff.
                self.assertTrue(core.compare_full(value,ref));approved+=1
                EVIDENCE['boundary'].append(dict(id=f'runtime.approved_depth.{depth}',
                    outcome='original_oracle_success_equal',approved_depth=depth,
                    approved_callsite=ref.provenance['observed_source_callstack_depth']))
                value=[value]
            self.assertIsNotNone(last_depth);self.assertGreater(approved,50)
            deep=b'["list",['*501+b'["none"]'+b']]'*501
            with self.assertRaises(RecursionError):core.build_reference(deep)
            EVIDENCE['boundary'].append(dict(id='runtime.actual_near_limit',outcome='all_actual_worker_oracle_approvals_equal',
                approved_vectors=approved,first_oracle_rejected_depth=last_depth,manual_deep_public_reference_rejected=True))
        finally:sys.setrecursionlimit(original_limit)


CASE_TO_TESTS={
    'reference_only_from_source_bytes_of_successful_early_complete_comparisons':('ReferenceTests.test_public_builder_rechecks_oracle_and_private_boundary_is_explicit',),
    'reference_tree_exact_grammar_recursively_immutable_no_live_or_parsed_alias':('ReferenceTests.test_malformed_tags_payloads_shapes_and_noncanonical_bytes','ReferenceTests.test_reference_is_tuple_only_nonserializable_and_factory_admitted'),
    'reference_tamper_or_mixed_source_policy_rejected_without_fallback':('ReferenceTests.test_reference_is_tuple_only_nonserializable_and_factory_admitted','ReferenceTests.test_controlled_stale_admission_cannot_authorize_changed_slots'),
    'exact_types_none_bool_int_float_str_and_bool_int_int_float_separation':('ScalarTests.test_exact_scalar_and_string_vectors','ScalarTests.test_type_and_encoding_inequality_vectors'),
    'finite_float_hex_subnormal_extremes_and_positive_negative_zero':('ScalarTests.test_exact_scalar_and_string_vectors','ScalarTests.test_type_and_encoding_inequality_vectors'),
    'arbitrary_precision_integer_decimal_conversion_and_current_interpreter_limits':('BoundaryTests.test_integer_limit_change_and_large_decimal_conversion',),
    'unicode_exact_codepoints_no_normalization_and_utf8_rejection_domain':('ScalarTests.test_exact_scalar_and_string_vectors','ScalarTests.test_unsupported_subclasses_and_invalid_values_are_not_equal'),
    'list_tuple_tag_order_lengths_and_duplicate_elements_all_covered':('GeneratedTests.test_reproducible_nested_equal_and_unequal_graphs','TraversalTests.test_shared_acyclic_aliases_are_each_fully_traversed'),
    'dict_proxy_equivalence_sorted_exact_string_keyset_and_values':('ScalarTests.test_mapping_order_and_dict_proxy_equivalence','TraversalTests.test_proxy_protocol_exact_all_keyscan_sorted_then_getitem','TraversalTests.test_dynamic_second_pass_string_payload_matches_original_json'),
    'every_nested_config_support_audit_and_unrelated_field_covered':('GeneratedTests.test_reproducible_nested_equal_and_unequal_graphs',),
    'no_identity_len_digest_only_equality_or_shallow_mappingproxy_shortcut':('TraversalTests.test_proxy_protocol_exact_all_keyscan_sorted_then_getitem','TraversalTests.test_shared_acyclic_aliases_are_each_fully_traversed'),
    'unsupported_custom_subclass_nonstr_keys_and_nonfinite_rejected':('ScalarTests.test_unsupported_subclasses_and_invalid_values_are_not_equal',),
    'selected_root_fully_validated_even_after_an_earlier_value_mismatch':('TraversalTests.test_ordinary_mismatch_never_skips_invalid_extra_live_tails',),
    'cycles_depth_limits_unencodable_strings_and_late_invalid_tail_fail_closed':('TraversalTests.test_active_ancestry_rejects_cycles_and_recovers_after_failure','BoundaryTests.test_near_limit_worker_approval_and_public_deep_bytes_rejection','BoundaryTests.test_last_proxy_read_permanent_runtime_change_cannot_return_equal'),
    'watch_and_observer_entry_exit_mutations_and_comparison_reentry_policy_explicit':('TraversalTests.test_proxy_reentry_is_rejected_without_leaking_busy_state','TraversalTests.test_caught_nested_comparison_still_invalidates_outer_and_resets'),
}
