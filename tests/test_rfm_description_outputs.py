"""Synthetic whole-bundle, roster, typed readback and public-whitelist checks."""
import copy
import json
from pathlib import Path
import shutil
import unittest
from unittest.mock import patch
import uuid

from scripts import rfm_description_outputs as outputs
from scripts import rfm_description as core
from tests.test_rfm_description import all_states_dataset, dataset_for_prices, evaluation_spec


def loaded(dataset):
    return {'dataset': dataset, 'evaluation_spec': evaluation_spec(),
            'customer_ids': [r['customer_unique_id'] for r in dataset['customers']],
            'order_ids': [r['order_id'] for r in dataset['orders']],
            'window_order_ids': [r['order_id'] for r in dataset['orders'] if r['window_event_eligible']]}


def provenance():
    return {'execution_specification': {'path': 'reports/stage6/rfm_description_execution_specification.json',
                                        'bytes': 123, 'sha256': 'a' * 64},
            'source_bindings': [{'path': f'scripts/synthetic_source_{i:02d}.py',
                                 'bytes': i, 'sha256': 'b' * 64} for i in range(41)]}


class RFMDescriptionOutputTests(unittest.TestCase):
    def setUp(self):
        self.scratch = Path(__file__).resolve().parents[1] / '.runtime' / 'rfm_description_outputs_tests'
        self.scratch.mkdir(parents=True, exist_ok=True)
        self.temp = self.scratch / uuid.uuid4().hex
        self.temp.mkdir()
        self.addCleanup(self.cleanup)
        self.output = self.temp / 'bundle'
        self.data = loaded(all_states_dataset())
        self.description = core.describe_dataset(self.data['dataset'], self.data['evaluation_spec'],
                                                  expected_customer_ids=self.data['customer_ids'])
        self.provenance = provenance()

    def cleanup(self):
        target = self.temp.resolve()
        if not target.is_relative_to(self.scratch.resolve()) or target == self.scratch.resolve():
            raise ValueError('Synthetic cleanup escaped its private scratch directory')
        shutil.rmtree(target)

    def write(self):
        return outputs.write_outputs(self.data, self.description, self.provenance, self.output)

    def replace_data(self, dataset):
        self.data = loaded(dataset)
        self.description = core.describe_dataset(dataset, self.data['evaluation_spec'],
                                                  expected_customer_ids=self.data['customer_ids'])

    def resign_manifest(self, mutate=None):
        path = self.output / 'manifest.json'
        value = json.loads(path.read_text('utf-8'))
        value['private_bytes_sha'] = {name: outputs.typed._digest((self.output / name).read_bytes())
                                      for name in outputs.FILES[:3]}
        if mutate:
            mutate(value)
        path.write_bytes(outputs.typed.json_bytes(value))

    def test_complete_four_file_typed_readback_and_same_ids(self):
        result = self.write()
        restored = outputs.read_outputs(self.output, self.provenance)
        self.assertTrue(outputs.typed._same(restored['description'], self.description))
        self.assertEqual(len(restored['customer_roster']), 5)
        self.assertEqual(set(result['private_guard']), set(outputs.FILES))
        self.assertEqual(result['readback_acceptance']['roster_cells_compared'],
                         len(self.data['customer_ids']) * 3 + len(self.data['order_ids']) * 5)
        self.assertGreater(result['readback_acceptance']['binary64_values_compared'], 0)
        self.assertEqual(outputs.verify_outputs(self.output, self.data, self.description, self.provenance,
                                               result['private_guard']), result['readback_acceptance'])

    def test_rosters_have_ids_and_flags_only_no_individual_rfm(self):
        self.write()
        self.assertEqual((self.output / 'customer_roster.csv').read_text('utf-8').splitlines()[0],
                         'customer_unique_id,activity_state,eligible_for_numeric_description')
        self.assertEqual((self.output / 'order_roster.csv').read_text('utf-8').splitlines()[0],
                         'order_id,customer_unique_id,history_event_eligible,window_event_eligible,window_quarantine')
        self.assertNotIn('monetary_product_cents', (self.output / 'customer_roster.csv').read_text('utf-8'))

    def test_writer_does_not_call_core_or_mutate_inputs(self):
        before = copy.deepcopy((self.data, self.description, self.provenance))
        with patch.object(core, 'describe_dataset', side_effect=AssertionError('No statistics replay')):
            self.write()
        self.assertEqual(before, (self.data, self.description, self.provenance))

    def test_nullable_iqr_zero_and_zero_money_are_preserved(self):
        self.replace_data(dataset_for_prices([0, 0]))
        self.write()
        restored = outputs.read_outputs(self.output, self.provenance)['description']
        self.assertIsNone(restored['statistics_and_null_reasons']['raw']['monetary_product_cents']['Bowley_skewness'])
        self.assertIsNone(restored['outlier_flags_not_removed']['monetary_product_cents']['flag_count'])
        self.assertIsNone(restored['shape_and_tail_diagnostics']['M_ge_Q99']['share_of_total_M']['value'])

    def test_empty_reference_roundtrips_without_fake_values(self):
        self.replace_data(dataset_for_prices([]))
        result = self.write()
        restored = outputs.read_outputs(self.output, self.provenance)['description']
        self.assertEqual(restored['gate_status']['G1'], 'not_evaluable_empty_reference')
        self.assertEqual(result['readback_acceptance']['roster_cells_compared'], 0)
        self.assertIsNone(restored['statistics_and_null_reasons']['raw']['frequency_orders']['sum'])

    def test_large_exact_integer_and_float64_roundtrip(self):
        value = 2**53 + 1
        self.replace_data(dataset_for_prices([value, value + 1, value + 3]))
        self.write()
        restored = outputs.read_outputs(self.output, self.provenance)['description']
        raw = restored['statistics_and_null_reasons']['raw']['monetary_product_cents']
        self.assertIs(type(raw['min']), int)
        self.assertEqual(raw['min'], value)
        self.assertEqual(raw['sum'], 3 * value + 4)
        self.assertTrue(outputs.typed._same(restored, self.description))

    def test_missing_duplicate_or_shortened_independent_ids_rejected(self):
        for key in ('customer_ids', 'order_ids', 'window_order_ids'):
            for mutation in ('missing', 'duplicate'):
                original = copy.deepcopy(self.data[key])
                self.data[key] = original[:-1] if mutation == 'missing' else original + original[:1]
                with self.subTest(key=key, mutation=mutation), self.assertRaises(ValueError):
                    self.write()
                self.data[key] = original
        self.assertFalse(self.output.exists())

    def test_consistently_smaller_dataset_cannot_replace_independent_roster(self):
        self.data['dataset'] = dataset_for_prices([100])
        with self.assertRaises(ValueError):
            self.write()
        self.assertFalse(self.output.exists())

    def test_forged_routing_or_known_money_is_rejected_before_writes(self):
        mutations = (
            lambda d: d['routing_counts'].update(complete_active_n=99),
            lambda d: d['population_and_money_conservation'].update(complete_active_product_cents=1),
            lambda d: d['population_and_money_conservation']['money'].update(published_customer_product_cents=1),
            lambda d: d['statistics_and_null_reasons']['raw']['monetary_product_cents'].update(sum=1),
        )
        for mutate in mutations:
            description = copy.deepcopy(self.description)
            mutate(description)
            with self.assertRaises(ValueError):
                outputs.write_outputs(self.data, description, self.provenance, self.output)
        self.assertFalse(self.output.exists())

    def test_extra_nested_id_digest_or_scope_field_is_rejected(self):
        mutations = (
            lambda d: d.update(customer_ids=['private']),
            lambda d: d['statistics_and_null_reasons']['raw']['recency_seconds'].update(private_sha='a' * 64),
            lambda d: d['source_version'].update(customer_id='private'),
            lambda d: d['execution'].update(scores_assigned=True),
            lambda d: d['limitations'].append('private customer'),
        )
        for mutate in mutations:
            description = copy.deepcopy(self.description)
            mutate(description)
            with self.assertRaises(ValueError):
                outputs.write_outputs(self.data, description, self.provenance, self.output)

    def test_exact_json_numeric_types_are_required(self):
        for mutate in (
            lambda d: d.update(format_version=True),
            lambda d: d.update(eligible_n=1.0),
            lambda d: d['statistics_and_null_reasons']['raw']['frequency_orders'].update(sum=1.0),
            lambda d: d['statistics_and_null_reasons']['log1p_views']['frequency_orders'].update(min=float('nan')),
        ):
            value = copy.deepcopy(self.description)
            mutate(value)
            with self.assertRaises(ValueError):
                outputs.write_outputs(self.data, value, self.provenance, self.output)

    def test_private_or_duplicate_or_shortened_provenance_rejected(self):
        for mutate in (
            lambda p: p['source_bindings'].pop(),
            lambda p: p['source_bindings'].__setitem__(1, copy.deepcopy(p['source_bindings'][0])),
            lambda p: p['source_bindings'][0].update(path='.runtime/private.csv'),
            lambda p: p['source_bindings'][0].update(bytes=True),
            lambda p: p.update(private_digest='a' * 64),
        ):
            value = copy.deepcopy(self.provenance)
            mutate(value)
            with self.assertRaises(ValueError):
                outputs.write_outputs(self.data, self.description, value, self.output)

    def test_public_report_contains_only_whitelisted_aggregate_and_public_version(self):
        result = self.write()
        public = result['public_report']
        encoded = json.dumps(public, allow_nan=False)
        for row in self.data['dataset']['customers']:
            self.assertNotIn('"' + row['customer_unique_id'] + '"', encoded)
        for row in self.data['dataset']['orders']:
            self.assertNotIn('"' + row['order_id'] + '"', encoded)
        for value in result['private_guard'].values():
            self.assertNotIn(value['sha256'], encoded)
        self.assertTrue(outputs.typed._same(outputs.public_report(self.description, self.provenance,
                                                                 result['readback_acceptance']), public))

    def test_public_report_rejects_unvalidated_acceptance_payload(self):
        receipt = outputs._acceptance(self.description, *outputs._rosters(self.data))
        for mutate in (lambda r: r.update(private_sha='a' * 64),
                       lambda r: r.update(all_values_read_back=1),
                       lambda r: r['rows'].update({'customer_roster.csv': True}),
                       lambda r: r.update(aggregate_scalar_values_compared=1)):
            value = copy.deepcopy(receipt)
            mutate(value)
            with self.assertRaises(ValueError):
                outputs.public_report(self.description, self.provenance, value)

    def test_existing_empty_partial_or_complete_namespace_never_overwritten(self):
        self.output.mkdir()
        with self.assertRaises(ValueError):
            self.write()
        (self.output / 'manifest.json').write_bytes(b'partial')
        with self.assertRaises(ValueError):
            self.write()
        self.assertEqual((self.output / 'manifest.json').read_bytes(), b'partial')
        (self.output / 'manifest.json').unlink()
        self.output.rmdir()
        self.write()
        before = outputs.bundle_guard(self.output)
        with self.assertRaises(ValueError):
            self.write()
        self.assertEqual(before, outputs.bundle_guard(self.output))

    def test_failed_staging_readback_does_not_publish_bundle_or_report(self):
        with patch.object(outputs, 'read_outputs', side_effect=ValueError('synthetic failure')):
            with self.assertRaises(ValueError):
                self.write()
        self.assertFalse(self.output.exists())
        self.assertEqual(len(list(self.temp.glob('bundle.staging-*'))), 1)

    def test_verify_is_read_only_and_guard_detects_any_change(self):
        result = self.write()
        before = {name: (self.output / name).stat().st_mtime_ns for name in outputs.FILES}
        outputs.verify_outputs(self.output, self.data, self.description, self.provenance, result['private_guard'])
        self.assertEqual(before, {name: (self.output / name).stat().st_mtime_ns for name in outputs.FILES})
        (self.output / 'description.json').write_bytes((self.output / 'description.json').read_bytes() + b'\n')
        with self.assertRaises(ValueError):
            outputs.verify_outputs(self.output, self.data, self.description, self.provenance, result['private_guard'])

    def test_rehashed_description_change_fails_full_expected_readback(self):
        self.write()
        path = self.output / 'description.json'
        value = json.loads(path.read_text('utf-8'))
        value['statistics_and_null_reasons']['raw']['frequency_orders']['empirical_quantiles']['50'] = 2
        path.write_bytes(outputs.typed.json_bytes(value))
        self.resign_manifest()
        with self.assertRaises(ValueError):
            outputs.verify_outputs(self.output, self.data, self.description, self.provenance)

    def test_rehashed_roster_flag_and_bad_bool_are_rejected(self):
        self.write()
        path = self.output / 'customer_roster.csv'
        original = path.read_bytes()
        for replacement in (b'True', b'false'):
            path.write_bytes(original.replace(b'true', replacement))
            self.resign_manifest()
            with self.assertRaises(ValueError):
                outputs.verify_outputs(self.output, self.data, self.description, self.provenance)
        path.write_bytes(original)

    def test_provenance_version_and_noncanonical_manifest_rejected(self):
        self.write()
        altered = copy.deepcopy(self.provenance)
        altered['execution_specification']['sha256'] = 'c' * 64
        with self.assertRaises(ValueError):
            outputs.read_outputs(self.output, altered)
        path = self.output / 'manifest.json'
        for bad in (b'{"format_version":1,"format_version":1}', b'{"value":NaN}'):
            path.write_bytes(bad)
            with self.assertRaises(ValueError):
                outputs.read_outputs(self.output, self.provenance)

    def test_metadata_alias_and_extra_files_rejected(self):
        self.write()
        self.resign_manifest(lambda m: m['rows'].update({'customer_roster.csv': 5.0}))
        with self.assertRaises(ValueError):
            outputs.read_outputs(self.output, self.provenance)
        (self.output / 'unexpected').write_bytes(b'private')
        with self.assertRaises(ValueError):
            outputs.read_outputs(self.output, self.provenance)


if __name__ == '__main__':
    unittest.main()
