"""Synthetic calendar/scoring rules and freeze tamper tests; no transaction data."""
from copy import deepcopy
from datetime import timedelta
import json
from pathlib import Path
import unittest
from unittest.mock import patch
import uuid

from scripts import freeze_uci_rfm_contract as c


class ContractTests(unittest.TestCase):
    def setUp(self):
        self.policy = c.read_json(c.ROOT/c.POLICY)

    def scratch(self):
        path = c.within(c.ROOT,'shop-mysql-runtime/verification/uci-rfm-contract-v1/synthetic/'+uuid.uuid4().hex)
        path.mkdir(parents=True)
        (path/'reports/stage6').mkdir(parents=True)
        return path

    def saved_fixture(self):
        root = self.scratch()
        p = root/c.POLICY
        p.parent.mkdir(parents=True)
        c.write_new(p,self.policy)
        sources = [c.descriptor(root,c.POLICY)]
        spec = {'sources':sources,'policy_file':sources[0]}
        acceptance = {'status':'frozen_contract_verified_no_dataset_execution',
                      'policy_checks':c.validate_policy(self.policy),
                      'execution_scope':self.policy['execution_scope_this_turn']}
        c.write_bundle(root,spec,acceptance,'synthetic fixture, not a real run\n')
        return root

    def reject(self, mutate):
        mutate(self.policy)
        with self.assertRaises(ValueError):
            c.validate_policy(self.policy)

    def test_current_policy_consistent(self):
        checks = c.validate_policy(self.policy)
        self.assertEqual(len(checks),len(set(checks)))

    def test_start_included_cutoff_excluded(self):
        for w in self.policy['windows']:
            self.assertTrue(c.in_window(w['start_inclusive'],w))
            self.assertFalse(c.in_window(w['cutoff_exclusive'],w))

    def test_boundary_belongs_to_second_window_only(self):
        boundary = '2010-12-01 00:00:00'
        self.assertFalse(c.in_window(boundary,self.policy['windows'][0]))
        self.assertTrue(c.in_window(boundary,self.policy['windows'][1]))

    def test_one_second_neighbors(self):
        for w in self.policy['windows']:
            before = (c.timestamp(w['start_inclusive'])-timedelta(seconds=1)).strftime('%Y-%m-%d %H:%M:%S')
            last = (c.timestamp(w['cutoff_exclusive'])-timedelta(seconds=1)).strftime('%Y-%m-%d %H:%M:%S')
            self.assertFalse(c.in_window(before,w))
            self.assertTrue(c.in_window(last,w))

    def test_incomplete_december_tail_outside_both(self):
        for w in self.policy['windows']:
            self.assertFalse(c.in_window('2011-12-09 12:50:00',w))

    def test_calendar_shift_rejected(self):
        self.reject(lambda p:p['windows'][1].update(start_inclusive='2010-06-01 00:00:00'))

    def test_false_365_length_rejected(self):
        self.reject(lambda p:p['windows'][1].update(days=366))

    def test_future_dependent_processing_rejected(self):
        self.reject(lambda p:p['processing_order'].__setitem__(1,'group_all_file_invoice_headers'))

    def test_global_header_grouping_rejected(self):
        self.reject(lambda p:p['processing_order'].__setitem__(3,'classify_invoice_headers_using_all_years'))

    def test_unseen_claim_rejected(self):
        self.reject(lambda p:p['prior_exposure'].update(pristine_holdout_available=True))

    def test_probe_role_rejected(self):
        self.reject(lambda p:p['prior_exposure'].update(exploratory_june_cutoff_selected_for_this_study=True))

    def test_cent_rounding_rejected(self):
        self.reject(lambda p:p['money'].update(integer_units_per_GBP=100))

    def test_net_revenue_claim_rejected(self):
        self.reject(lambda p:p['money'].update(net_revenue_supported=True))

    def test_quarantine_not_zero_rejected(self):
        self.reject(lambda p:p['universe_and_rfm'].update(window_quarantine='R_null_F_0_M_0'))

    def test_future_refund_netting_rejected(self):
        self.reject(lambda p:p['invoice_policy'].update(refund_matching='net_all_future_C_invoices'))

    def test_missing_identity_imputation_rejected(self):
        self.reject(lambda p:p['source'].update(missing_customer='shared_unknown_customer'))

    def test_sensitivity_missing_arm_rejected(self):
        self.reject(lambda p:p['arms'].pop())

    def test_reference_from_T2_rejected(self):
        self.reject(lambda p:p['evaluation'].update(reference='T2_active_complete'))

    def test_model_execution_claim_rejected(self):
        self.reject(lambda p:p['execution_scope_this_turn'].update(models_fitted=1))

    def test_hand_calculated_nearest_rank_cutpoints(self):
        self.assertEqual(c.reference_cutpoints(list(range(1,11))),[2,4,6,8])

    def test_equal_value_stays_lower_bin_and_R_direction(self):
        for axis,expected in [('F',1),('M',1),('R',5)]:
            self.assertEqual(c.score(2,[2,4,6,8],axis),expected)
        self.assertEqual(c.score(3,[2,4,6,8],'F'),2)

    def test_ties_not_split(self):
        values = [1]*8+[10]*2
        cuts = c.reference_cutpoints(values)
        self.assertEqual(cuts,[1])
        self.assertEqual([c.score(v,cuts,'F') for v in values],[1]*8+[2]*2)

    def test_constant_axis_one_level(self):
        self.assertEqual(c.reference_cutpoints([7]*12),[])
        self.assertEqual(c.score(999,[],'F'),1)
        self.assertEqual(c.score(0,[],'R'),1)

    def test_maximum_cutpoint_removed(self):
        self.assertEqual(c.reference_cutpoints([1,2,2,2,2]),[1])

    def test_permutation_does_not_change_thresholds(self):
        self.assertEqual(c.reference_cutpoints([2,9,1,8,3,4,8]),c.reference_cutpoints([8,4,3,8,1,9,2]))

    def test_future_scoring_cannot_refit_cutpoints(self):
        cuts = c.reference_cutpoints(list(range(1,11)))
        before = cuts[:]
        self.assertEqual(c.score(100000,cuts,'M'),5)
        self.assertEqual(c.score(0,cuts,'R'),5)
        self.assertEqual(cuts,before)

    def test_integer_money_precision_preserved_in_scoring(self):
        self.assertEqual(c.reference_cutpoints([1,2,3,4,5]),[1,2,3,4])
        self.assertEqual(c.score(3,[1,2,3,4],'M'),3)

    def test_empty_or_float_cutpoint_inputs_rejected(self):
        for values in ([],[0.1],[-1],[True]):
            with self.assertRaises(ValueError):
                c.reference_cutpoints(values)

    def test_small_group_floor_and_ceiling(self):
        self.assertEqual(c.minimum_support(0),50)
        self.assertEqual(c.minimum_support(4999),50)
        self.assertEqual(c.minimum_support(5001),51)

    def test_source_mutation_detected(self):
        root = self.scratch()
        (root/'source.txt').write_text('original',encoding='utf-8')
        sources = [c.descriptor(root,'source.txt')]
        (root/'source.txt').write_text('changed',encoding='utf-8')
        with self.assertRaises(ValueError):
            c.verify_descriptors(root,sources)

    def test_duplicate_source_path_rejected(self):
        root = self.scratch()
        (root/'source.txt').write_text('x',encoding='utf-8')
        d = c.descriptor(root,'source.txt')
        with self.assertRaises(ValueError):
            c.verify_descriptors(root,[d,d])

    def test_outside_shop_path_rejected(self):
        with self.assertRaises(ValueError):
            c.within(c.ROOT,'../not_in_shop')

    def test_saved_bundle_verifies_without_reexecution(self):
        root = self.saved_fixture()
        with patch.object(c,'collect_sources',side_effect=AssertionError('must not rerun intake collection')):
            result = c.freeze(root)
        self.assertFalse(result['tests_rerun'])
        self.assertFalse(result['transaction_rows_recomputed'])

    def test_saved_report_tamper_rejected(self):
        root = self.saved_fixture()
        p = root/c.REPORT
        p.write_text(p.read_text(encoding='utf-8')+' ',encoding='utf-8')
        with self.assertRaises(ValueError):
            c.verify(root)

    def test_saved_policy_tamper_rejected(self):
        root = self.saved_fixture()
        p = root/c.POLICY
        p.write_text(p.read_text(encoding='utf-8')+' ',encoding='utf-8')
        with self.assertRaises(ValueError):
            c.verify(root)

    def test_no_overwrite_existing_bundle(self):
        root = self.saved_fixture()
        before = (root/c.SPEC).read_bytes()
        with self.assertRaises(FileExistsError):
            c.write_bundle(root,{}, {},'changed')
        self.assertEqual((root/c.SPEC).read_bytes(),before)

    def test_partial_namespace_not_refrozen(self):
        root = self.scratch()
        (root/c.PRIVATE).mkdir(parents=True)
        with self.assertRaises(FileNotFoundError):
            c.freeze(root)
        self.assertFalse((root/c.SPEC).exists())

    def test_failed_write_keeps_evidence_and_cannot_replay(self):
        root = self.scratch()
        original = c.write_new
        def fail_guard(path,value):
            if Path(path).name == 'output_guard.json':
                raise OSError('synthetic guard failure')
            original(path,value)
        with patch.object(c,'write_new',side_effect=fail_guard):
            with self.assertRaises(OSError):
                c.write_bundle(root,{'sources':[]},{},'fixture')
        self.assertTrue((root/c.PRIVATE/'failure.json').exists())
        self.assertTrue((root/c.SPEC).exists())
        with self.assertRaises(FileNotFoundError):
            c.freeze(root)


if __name__ == '__main__':
    unittest.main()
