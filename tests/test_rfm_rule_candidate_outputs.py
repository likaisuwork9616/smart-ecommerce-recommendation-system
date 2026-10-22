"""Synthetic complete G2 output, independent semantics and tamper checks."""
import copy
import json
from pathlib import Path
import shutil
import unittest
from unittest.mock import patch
import uuid

from scripts import rfm_rule_candidate_outputs as outputs
from scripts import rfm_rule_candidate as core
from tests.test_rfm_description_outputs import loaded
from tests.test_rfm_description import all_states_dataset, dataset_for_prices
from tests.test_rfm_rule_candidate import balanced_dataset, synthetic_dataset


def loaded_g2(dataset):
    return {**loaded(dataset), 'g1_accepted': True}


def result_for(data):
    return core.evaluate_rule_candidate(data['dataset'], data['evaluation_spec'],
                                        expected_customer_ids=data['customer_ids'], g1_accepted=True)


def provenance():
    return {'execution_specification': {'path': 'reports/stage6/rfm_rule_candidate_execution_specification.json',
                                        'bytes': 123, 'sha256': 'a' * 64},
            'source_bindings': [{'path': f'scripts/synthetic_source_{i:02d}.py',
                                 'bytes': i, 'sha256': 'b' * 64} for i in range(57)]}


class RFMRuleCandidateOutputTests(unittest.TestCase):
    def setUp(self):
        self.scratch = Path(__file__).resolve().parents[1] / '.runtime' / 'rfm_rule_candidate_outputs_tests'
        self.scratch.mkdir(parents=True, exist_ok=True)
        self.temp = self.scratch / uuid.uuid4().hex
        self.temp.mkdir()
        self.addCleanup(self.cleanup)
        self.output = self.temp / 'bundle'
        self.data = loaded_g2(all_states_dataset())
        self.result = result_for(self.data)
        self.provenance = provenance()

    def cleanup(self):
        target, parent = self.temp.resolve(), self.scratch.resolve()
        if target == parent or not target.is_relative_to(parent):
            raise ValueError('Synthetic cleanup escaped its private scratch directory')
        shutil.rmtree(target)

    def replace(self, dataset):
        self.data = loaded_g2(dataset)
        self.result = result_for(self.data)

    def write(self):
        return outputs.write_outputs(self.data, self.result, self.provenance, self.output)

    def verify(self, guard=None):
        return outputs.verify_outputs(self.output, self.data, self.result, self.provenance, guard)

    def resign_manifest(self, mutation=None):
        path = self.output / 'manifest.json'
        manifest = json.loads(path.read_text('utf-8'))
        manifest['private_bytes_sha'] = {name: outputs.typed._digest((self.output / name).read_bytes())
                                         for name in outputs.FILES[:3]}
        if mutation:
            mutation(manifest)
        path.write_bytes(outputs.typed.json_bytes(manifest))

    def mutate_csv(self, filename, schema, mutation):
        path = self.output / filename
        rows = outputs.typed._read_csv(path, schema)
        mutation(rows)
        path.write_bytes(outputs.typed._csv_bytes(rows, schema))
        self.resign_manifest()

    def test_four_file_roundtrip_complete_rosters_and_all_values(self):
        result = self.write()
        restored = outputs.read_outputs(self.output, self.provenance)
        self.assertEqual(set(outputs.FILES), {p.name for p in self.output.iterdir()})
        for key in ('aggregate', 'assignments_by_id'):
            self.assertTrue(outputs.typed._same(restored[key], self.result[key]))
        acceptance = result['readback_acceptance']
        self.assertEqual(acceptance['roster_cells_compared'], len(self.data['customer_ids']) * 9 + len(self.data['order_ids']) * 11)
        self.assertEqual(acceptance['binary64_values_compared'], 0)
        self.assertTrue(acceptance['independent_source_cutpoints_and_assignments'])
        self.assertEqual(result['public_report']['delivery'], {
            'private_assignment_roster_written': True, 'private_bundle_files': 4,
            'G2_core_reexecuted_for_readback': False})
        self.assertEqual(self.verify(result['private_guard']), acceptance)

    def test_full_five_states_withheld_assignments_null_and_no_raw_rfm(self):
        self.write()
        restored = outputs.read_outputs(self.output, self.provenance)
        self.assertEqual(len(restored['customer_roster']), 5)
        for row in restored['customer_roster']:
            for prefix in ('r', 'f', 'm'):
                for suffix in ('numeric_bin', 'ordinal'):
                    self.assertEqual(row[prefix + '_' + suffix] is None, not row['eligible_for_rule_candidate'])
        header = (self.output / 'customer_roster.csv').read_text('utf-8').splitlines()[0]
        self.assertEqual(len(header.split(',')), 9)
        for axis in outputs.AXES:
            self.assertNotIn(axis, header)
        self.assertEqual(len((self.output / 'order_roster.csv').read_text('utf-8').splitlines()[0].split(',')), 11)

    def test_writer_and_readback_do_not_reexecute_core_or_mutate_inputs(self):
        before = copy.deepcopy((self.data, self.result, self.provenance))
        blocked = AssertionError('No G2 or G1 core replay')
        with patch.object(core, 'evaluate_rule_candidate', side_effect=blocked), \
                patch.object(core, '_partition', side_effect=blocked), \
                patch.object(outputs.description, 'describe_dataset', side_effect=blocked):
            self.write()
            self.verify()
        self.assertEqual(before, (self.data, self.result, self.provenance))

    def test_ineligible_candidate_is_completed_diagnostic_with_active_assignments(self):
        self.replace(synthetic_dataset([(i, 1, i * 100) for i in range(1, 6)]))
        written = self.write()
        self.assertEqual(written['public_report']['aggregate']['gate_status']['G2'], 'ineligible')
        self.assertEqual(written['readback_acceptance']['assigned_active_customers'], 5)
        self.assertNotIn('passed', written['public_report']['status'])

    def test_passed_candidate_and_small_cells_retain_cell_limits(self):
        self.replace(synthetic_dataset([(r, f, m * 100) for r in range(1, 6)
                                      for f in range(1, 6) for m in range(5) for _ in range(4)]))
        written = self.write()
        aggregate = written['public_report']['aggregate']
        self.assertEqual(aggregate['gate_status']['G2'], 'passed')
        self.assertEqual(aggregate['observed_joint_cells_n'], 125)
        self.assertTrue(all(cell['support_flag'] == 'insufficient_group_support' for cell in aggregate['neutral_joint_cell_counts']))

    def test_empty_reference_roundtrip_without_fake_assignments_or_cuts(self):
        self.replace(dataset_for_prices([]))
        written = self.write()
        restored = outputs.read_outputs(self.output, self.provenance)
        self.assertEqual(restored['assignments_by_id'], {})
        self.assertEqual(restored['aggregate']['gate_status']['G2'], 'not_evaluable_empty_reference')
        self.assertEqual(written['readback_acceptance']['roster_cells_compared'], 0)
        forged = copy.deepcopy(restored['aggregate'])
        forged['neutral_joint_cell_counts'] = [{'ordinals': [1, 1, 1], 'n': 1, 'support_flag': 'insufficient_group_support'}]
        with self.assertRaises(ValueError):
            outputs.public_report(forged, self.provenance, written['readback_acceptance'])

    def test_exact_large_integer_cuts_and_valid_zero_money_roundtrip(self):
        self.replace(synthetic_dataset([(i + 1, 1, value) for i, value in enumerate([0, 2**53 + 1, 2**53 + 2, 2**53 + 3, 2**53 + 4])]))
        self.write()
        aggregate = outputs.read_outputs(self.output, self.provenance)['aggregate']
        self.assertEqual(aggregate['axes']['monetary_product_cents']['cut_values'], [0, 2**53 + 1, 2**53 + 2, 2**53 + 3])
        self.assertTrue(all(type(v) is int for v in aggregate['axes']['monetary_product_cents']['cut_values']))

    def test_missing_or_duplicate_independent_rosters_rejected_before_write(self):
        for key in ('customer_ids', 'order_ids', 'window_order_ids'):
            for duplicate in (False, True):
                original = self.data[key]
                self.data[key] = original + original[:1] if duplicate else original[:-1]
                with self.subTest(key=key, duplicate=duplicate), self.assertRaises(ValueError):
                    self.write()
                self.data[key] = original
        self.assertFalse(self.output.exists())

    def test_g1_not_accepted_and_non_bool_flag_rejected(self):
        for value in (None, False, 1, 'true'):
            self.data['g1_accepted'] = value
            with self.subTest(value=value), self.assertRaises(ValueError):
                self.write()
        self.assertFalse(self.output.exists())

    def test_source_rfm_state_and_money_conservation_are_validated(self):
        self.data['dataset']['customers'][0]['monetary_product_cents'] = 987
        with self.assertRaises(ValueError):
            self.write()

    def test_changed_cut_with_same_bin_counts_is_independently_rejected(self):
        self.replace(balanced_dataset())
        self.result['aggregate']['axes']['monetary_product_cents']['cut_values'][0] += 1
        with self.assertRaises(ValueError):
            self.write()
        self.assertFalse(self.output.exists())

    def test_same_group_sizes_but_swapped_ids_are_independently_rejected(self):
        self.replace(balanced_dataset())
        assignments = self.result['assignments_by_id']
        ids = sorted(assignments)
        assignments[ids[0]], assignments[ids[-1]] = assignments[ids[-1]], assignments[ids[0]]
        with self.assertRaises(ValueError):
            self.write()

    def test_missing_active_assignment_or_added_inactive_assignment_rejected(self):
        original = copy.deepcopy(self.result)
        uid = next(iter(self.result['assignments_by_id']))
        del self.result['assignments_by_id'][uid]
        with self.assertRaises(ValueError): self.write()
        self.result = original
        inactive = next(row['customer_unique_id'] for row in self.data['dataset']['customers'] if not row['rfm_usable'])
        self.result['assignments_by_id'][inactive] = copy.deepcopy(self.result['assignments_by_id'][uid])
        with self.assertRaises(ValueError): self.write()

    def test_aggregate_nested_ID_digest_and_scope_injections_rejected(self):
        for mutate in (lambda agg: agg.update(customer_id='private-id'),
                       lambda agg: agg['limitations'].append('private-digest'),
                       lambda agg: agg['failed_checks'].append({'axis': 'private-id', 'check': 'private-digest'}),
                       lambda agg: agg['execution'].update(model_fits=1),
                       lambda agg: agg['gate_status'].update(G3='passed'),
                       lambda agg: agg['reproducibility'].update(customer_id='private-id')):
            original = copy.deepcopy(self.result)
            mutate(self.result['aggregate'])
            with self.assertRaises(ValueError): self.write()
            self.result = original

    def test_exact_types_not_bool_integer_or_float_replacements(self):
        for path, value in ((('support_floor',), 100.0), (('reference_n',), True),
                            (('axes', 'frequency_orders', 'effective_levels'), True)):
            original = copy.deepcopy(self.result)
            pointer = self.result['aggregate']
            for key in path[:-1]: pointer = pointer[key]
            pointer[path[-1]] = value
            with self.assertRaises(ValueError): self.write()
            self.result = original

    def test_entire_namespace_must_be_absent_and_no_overwrite(self):
        written = self.write()
        before = {p.name: p.read_bytes() for p in self.output.iterdir()}
        with self.assertRaises(ValueError): self.write()
        self.assertEqual(before, {p.name: p.read_bytes() for p in self.output.iterdir()})
        self.assertEqual(self.verify(written['private_guard']), written['readback_acceptance'])

    def test_empty_existing_namespace_partial_and_extra_files_rejected(self):
        self.output.mkdir()
        with self.assertRaises(ValueError): self.write()
        with self.assertRaises(ValueError): outputs.read_outputs(self.output, self.provenance)
        self.output.rmdir()
        self.write()
        (self.output / 'extra.json').write_text('{}', encoding='utf-8')
        with self.assertRaises(ValueError): self.verify()

    def test_guard_rejects_output_byte_mutation(self):
        written = self.write()
        with (self.output / 'candidate.json').open('ab') as stream: stream.write(b' ')
        with self.assertRaises(ValueError): self.verify(written['private_guard'])

    def test_noncanonical_json_and_csv_rejected_even_after_digest_update(self):
        self.write()
        p = self.output / 'candidate.json'
        original = p.read_bytes()
        p.write_bytes(original + b' ')
        self.resign_manifest()
        with self.assertRaises(ValueError): self.verify()
        p.write_bytes(original)
        p = self.output / 'customer_roster.csv'
        p.write_bytes(p.read_bytes().replace(b'true', b'True'))
        self.resign_manifest()
        with self.assertRaises(ValueError): self.verify()

    def test_reordered_duplicate_or_missing_customer_rows_rejected(self):
        self.write()
        p = self.output / 'customer_roster.csv'
        original = p.read_bytes()
        for mutation in (lambda rows: rows.reverse(), lambda rows: rows.append(copy.deepcopy(rows[0])), lambda rows: rows.pop()):
            p.write_bytes(original)
            self.mutate_csv('customer_roster.csv', outputs.CUSTOMER_SCHEMA, mutation)
            with self.assertRaises(ValueError): self.verify()

    def test_nonactive_assignment_injection_rejected_after_manifest_resigned(self):
        self.write()
        def inject(rows):
            row = next(row for row in rows if not row['eligible_for_rule_candidate'])
            row['r_numeric_bin'] = row['r_ordinal'] = 1
        self.mutate_csv('customer_roster.csv', outputs.CUSTOMER_SCHEMA, inject)
        with self.assertRaises(ValueError): self.verify()

    def test_each_order_proof_field_is_compared_against_loaded_source(self):
        self.write()
        p = self.output / 'order_roster.csv'
        original = p.read_bytes()
        for key in ('customer_unique_id', 'purchase_at', 'approval_at', 'delivery_at', 'in_window',
                    'primary_exclusion_reason', 'approval_missing_or_invalid'):
            p.write_bytes(original)
            def mutate(rows):
                row = rows[0]
                if key in ('in_window', 'approval_missing_or_invalid'): row[key] = not row[key]
                elif key == 'customer_unique_id': row[key] = 'other-source-id'
                elif key == 'primary_exclusion_reason': row[key] = 'status_not_delivered'
                else: row[key] = '2018-01-01 00:00:01'
            self.mutate_csv('order_roster.csv', outputs.ORDER_SCHEMA, mutate)
            with self.subTest(key=key), self.assertRaises(ValueError): self.verify()

    def test_synchronized_candidate_and_manifest_forgery_rejected_by_source(self):
        self.replace(balanced_dataset())
        self.write()
        forged = copy.deepcopy(self.result)
        forged['aggregate']['axes']['monetary_product_cents']['raw_cut_values'][0] += 1
        forged['aggregate']['axes']['monetary_product_cents']['cut_values'][0] += 1
        (self.output / 'candidate.json').write_bytes(outputs.typed.json_bytes(forged['aggregate']))
        self.resign_manifest()
        with self.assertRaises(ValueError):
            outputs.verify_outputs(self.output, self.data, forged, self.provenance)

    def test_public_report_contains_no_individual_ids_rfm_or_private_digests(self):
        written = self.write()
        public = json.dumps(written['public_report'], sort_keys=True)
        for uid in self.data['customer_ids']: self.assertNotIn('"' + uid + '"', public)
        for oid in self.data['order_ids']: self.assertNotIn('"' + oid + '"', public)
        for value in written['private_guard'].values(): self.assertNotIn(value['sha256'], public)
        self.assertNotIn('assignments_by_id', public)
        self.assertNotIn('private_bytes_sha', public)

    def test_public_provenance_private_paths_duplicates_and_receipt_types_rejected(self):
        written = self.write()
        for path in ('.runtime/private.json', 'models/private.json', '../escape.py'):
            p = copy.deepcopy(self.provenance)
            p['source_bindings'][0]['path'] = path
            with self.assertRaises(ValueError): outputs.public_report(self.result['aggregate'], p, written['readback_acceptance'])
        p = copy.deepcopy(self.provenance)
        p['source_bindings'].append(p['source_bindings'][0])
        with self.assertRaises(ValueError): outputs.public_report(self.result['aggregate'], p, written['readback_acceptance'])
        for key, value in (('all_values_read_back', 1), ('roster_cells_compared', True), ('independent_source_cutpoints_and_assignments', False)):
            acceptance = copy.deepcopy(written['readback_acceptance'])
            acceptance[key] = value
            with self.assertRaises(ValueError): outputs.public_report(self.result['aggregate'], self.provenance, acceptance)

    def test_staging_is_retained_on_readback_failure_without_publishing(self):
        with patch.object(outputs, 'verify_outputs', side_effect=ValueError('synthetic readback failure')):
            with self.assertRaises(ValueError): self.write()
        self.assertFalse(self.output.exists())
        self.assertEqual(len(list(self.temp.glob('bundle.staging-*'))), 1)

    def test_directory_and_file_symlinks_are_rejected(self):
        self.write()
        with patch.object(Path, 'is_symlink', return_value=True):
            with self.assertRaises(ValueError): outputs.bundle_guard(self.output)


if __name__ == '__main__':
    unittest.main()
