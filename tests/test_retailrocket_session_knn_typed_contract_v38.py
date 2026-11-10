"""Characterize the unchanged typed canonical oracle, not a comparator candidate."""
from collections import namedtuple
from copy import deepcopy
from decimal import Decimal
import json
from types import MappingProxyType
import unicodedata
import unittest

from scripts import retailrocket_session_knn_reuse_v27 as c1


class OriginalTypedCanonicalTests(unittest.TestCase):
    def test_exact_scalar_tags_do_not_alias_none_boolean_integer_or_string(self):
        cases=[(None,['none']),(False,['bool',False]),(True,['bool',True]),
            (0,['int','0']),(1,['int','1']),('0',['str','0']),('', ['str',''])]
        values=[]
        for value,expected in cases:
            with self.subTest(value=value):
                encoded=c1.canonical(value);self.assertIs(type(encoded),bytes)
                self.assertEqual(json.loads(encoded),expected);values.append(encoded)
        self.assertEqual(len(set(values)),len(cases))

    def test_nested_boolean_and_integer_values_remain_distinct(self):
        for left,right in ((False,0),(True,1)):
            with self.subTest(left=left):
                self.assertNotEqual(c1.canonical({'nested':[left]}),c1.canonical({'nested':[right]}))
                self.assertNotEqual(c1.canonical((left,)),c1.canonical((right,)))

    def test_arbitrary_precision_integer_decimal_digits_are_preserved(self):
        for value in (10**200+17,-(10**200+17),2**53+1):
            with self.subTest(value=value):
                self.assertEqual(json.loads(c1.canonical(value)),['int',str(value)])
                self.assertNotEqual(c1.canonical(value),c1.canonical(value+1))

    def test_finite_float_values_use_exact_binary64_hex(self):
        for value in (.1,1.0,-1.5,float.fromhex('0x0.0000000000001p-1022'),float.fromhex('0x1.fffffffffffffp+1023')):
            with self.subTest(value=value):
                self.assertEqual(json.loads(c1.canonical(value)),['float',value.hex()])
                self.assertEqual(float.fromhex(json.loads(c1.canonical(value))[1]).hex(),value.hex())
        self.assertNotEqual(c1.canonical(1.0),c1.canonical(1))

    def test_positive_and_negative_float_zero_remain_distinct(self):
        self.assertEqual(0.0,-0.0)
        self.assertEqual(c1.canonical(0.0),b'["float","0x0.0p+0"]')
        self.assertEqual(c1.canonical(-0.0),b'["float","-0x0.0p+0"]')
        self.assertNotEqual(c1.canonical(0.0),c1.canonical(-0.0))

    def test_list_and_tuple_tags_are_distinct_at_every_depth(self):
        for left,right in (([],()),([1,2],(1,2)),({'x':[1]},{'x':(1,)}),([('x',)],[['x']])):
            with self.subTest(left=left):self.assertNotEqual(c1.canonical(left),c1.canonical(right))

    def test_exact_dict_and_mappingproxy_share_map_semantics(self):
        value={'z':[1,{'value':None}],'a':('x',2)}
        proxy=MappingProxyType(value)
        self.assertEqual(c1.canonical(value),c1.canonical(proxy))
        self.assertEqual(c1.canonical({'nested':value}),c1.canonical({'nested':proxy}))
        self.assertEqual(json.loads(c1.canonical(proxy))[0],'map')

    def test_map_insertion_order_is_irrelevant_at_every_depth(self):
        left={'z':{'b':2,'a':1},'a':[{'y':False,'x':0}]}
        right={'a':[{'x':0,'y':False}],'z':{'a':1,'b':2}}
        self.assertEqual(c1.canonical(left),c1.canonical(right))
        self.assertEqual(c1.canonical(left),c1.canonical(MappingProxyType(right)))

    def test_sequence_order_duplicates_and_length_are_all_preserved(self):
        for container in (list,tuple):
            variants=[container(x) for x in ([1,2,1],[1,1,2],[1,2],[2,1],[])]
            with self.subTest(container=container.__name__):
                self.assertEqual(len({c1.canonical(x) for x in variants}),len(variants))
                typed=json.loads(c1.canonical(container([1,2,1])))
                self.assertEqual(typed[1],[['int','1'],['int','2'],['int','1']])

    def test_unicode_normalization_case_and_non_ascii_bytes_are_not_coalesced(self):
        composed='\u00e9';decomposed='e\u0301'
        self.assertEqual(unicodedata.normalize('NFC',composed),unicodedata.normalize('NFC',decomposed))
        self.assertNotEqual(c1.canonical(composed),c1.canonical(decomposed))
        self.assertNotEqual(c1.canonical({composed:1}),c1.canonical({decomposed:1}))
        self.assertNotEqual(c1.canonical('A'),c1.canonical('a'))
        self.assertNotEqual(c1.canonical('1'),c1.canonical('\uff11'))
        self.assertIn('雪😀'.encode('utf-8'),c1.canonical('雪😀'))
        self.assertNotIn(b'\\u',c1.canonical('雪😀'))

    def test_unsupported_value_types_are_rejected_including_nested_values(self):
        cases=[b'x',bytearray(b'x'),{1},frozenset({1}),range(2),complex(1,2),Decimal('1'),object()]
        for value in cases:
            for wrapped in (value,{'nested':[value]}):
                with self.subTest(type=type(value).__name__,nested=type(wrapped) is dict),self.assertRaisesRegex(ValueError,'Unsupported mutable or custom semantic value'):
                    c1.canonical(wrapped)

    def test_nonfinite_float_values_are_rejected_at_scalar_and_nested_positions(self):
        for value in (float('nan'),float('inf'),float('-inf')):
            for wrapped in (value,{'nested':(value,)}):
                with self.subTest(value=value,nested=type(wrapped) is dict),self.assertRaisesRegex(ValueError,'Nonfinite semantic value'):
                    c1.canonical(wrapped)

    def test_non_string_map_keys_are_rejected_including_nested_maps(self):
        for key in (0,True,None,1.0,('x',),b'x'):
            for value in ({key:'x'},{'nested':{key:'x'}}):
                with self.subTest(key=key,nested='nested' in value),self.assertRaisesRegex(ValueError,'Non-string semantic key'):
                    c1.canonical(value)

    def test_builtin_subclasses_are_not_accepted_as_exact_oracle_types(self):
        class Integer(int):pass
        class Float(float):pass
        class String(str):pass
        class List(list):pass
        class Tuple(tuple):pass
        class Dict(dict):pass
        Pair=namedtuple('Pair','left right')
        for value in (Integer(1),Float(1.0),String('x'),List([1]),Tuple((1,)),Dict(x=1),Pair(1,2)):
            with self.subTest(type=type(value).__name__),self.assertRaisesRegex(ValueError,'Unsupported mutable or custom semantic value'):
                c1.canonical(value)
        with self.assertRaisesRegex(ValueError,'Non-string semantic key'):c1.canonical({String('x'):1})

    def test_complete_support_and_unrelated_nested_metadata_are_part_of_identity(self):
        model={'support':{'1':2,'2':1},'fit_audit':{'fit_id':'A','schema':['itemid','count'],
            'provenance':{'source':'train','seed':13}},'unrelated':{'enabled':False,'value':None}}
        expected=c1.canonical(model);variants=[]
        changed=deepcopy(model);changed['support']['1']=3;variants.append(changed)
        changed=deepcopy(model);changed['support']['3']=0;variants.append(changed)
        changed=deepcopy(model);changed['fit_audit']['fit_id']='B';variants.append(changed)
        changed=deepcopy(model);changed['fit_audit']['provenance']['seed']=14;variants.append(changed)
        changed=deepcopy(model);changed['fit_audit']['schema']=tuple(changed['fit_audit']['schema']);variants.append(changed)
        changed=deepcopy(model);changed['unrelated']['enabled']=0;variants.append(changed)
        changed=deepcopy(model);changed['unrelated']['value']=False;variants.append(changed)
        for ordinal,changed in enumerate(variants):
            with self.subTest(ordinal=ordinal):self.assertNotEqual(c1.canonical(changed),expected)
        self.assertEqual(c1.canonical(model),expected)

    def test_map_key_sort_is_unicode_lexical_not_numeric_or_locale_order(self):
        keys=['雪','\u00e9','e\u0301','a','A','2','10']
        value={key:None for key in keys}
        typed=json.loads(c1.canonical(value))
        self.assertEqual([key for key,_ in typed[1]],['10','2','A','a','e\u0301','\u00e9','雪'])
        self.assertEqual(c1.canonical(value),c1.canonical({key:None for key in reversed(keys)}))

    def test_lone_surrogate_values_and_keys_fail_original_utf8_encoding(self):
        for value in ('\ud800','\udfff',{'nested':['\ud800']},{'\ud800':'value'}):
            with self.subTest(value=repr(value)),self.assertRaises(UnicodeEncodeError):c1.canonical(value)

    def test_cyclic_list_and_mapping_are_rejected_by_original_recursive_oracle(self):
        sequence=[];sequence.append(sequence)
        mapping={};mapping['self']=mapping
        for value in (sequence,mapping):
            with self.subTest(type=type(value).__name__),self.assertRaises(RecursionError):c1.canonical(value)

    def test_shared_acyclic_dict_and_list_subtrees_match_independent_deep_copies(self):
        shared_list=[1,{'leaf':('x',False)}]
        shared_dict={'values':shared_list,'tag':'shared'}
        aliased={'left':shared_dict,'right':shared_dict,'lists':[shared_list,shared_list]}
        copied={'left':deepcopy(shared_dict),'right':deepcopy(shared_dict),
            'lists':[deepcopy(shared_list),deepcopy(shared_list)]}
        self.assertIs(aliased['left'],aliased['right'])
        self.assertIs(aliased['left']['values'],aliased['lists'][0])
        self.assertIs(aliased['lists'][0],aliased['lists'][1])
        self.assertIsNot(copied['left'],copied['right'])
        self.assertIsNot(copied['left']['values'],copied['lists'][0])
        self.assertIsNot(copied['lists'][0],copied['lists'][1])
        self.assertEqual(c1.canonical(aliased),c1.canonical(copied))


if __name__=='__main__':unittest.main()
