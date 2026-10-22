"""Synthetic hash-only Stage 6 evaluation-contract provenance acceptance."""
import copy
import csv
import json
from pathlib import Path
import shutil
import unittest
from unittest.mock import patch
import uuid

from scripts import freeze_rfm_evaluation_spec as entry
from tests.test_rfm_dataset_builder import add_order, build as synthetic_build, fixture


class RFMEvaluationSpecTests(unittest.TestCase):
    def setUp(self):
        self.scratch = entry.ROOT / '.runtime' / 'stage6_evaluation_spec_tests'
        self.scratch.mkdir(parents=True, exist_ok=True)
        self.root = self.scratch / uuid.uuid4().hex
        self.root.mkdir()
        self.addCleanup(self.cleanup)
        base, frozen, prior = entry.base, entry.dataset_contract, entry.prior
        self.tables = fixture()
        add_order(self.tables, 'old', 'old-customer', 'old-anonymous',
                  purchase='2017-08-01 00:00:00', approval='2017-08-02 00:00:00',
                  delivery='2017-08-10 00:00:00')
        add_order(self.tables, 'q', 'q-customer', 'q-anonymous', delivery='')
        self.synthetic = synthetic_build(self.tables)
        for path in (*base.FILES.values(), base.CODE, base.TEST, 'sql/03_business_analysis.sql',
                     frozen.CODE, frozen.TEST, *prior.IMPLEMENTATION,
                     entry.METHOD, entry.CODE, entry.TEST, 'requirements-lock.txt'):
            target = self.root / path
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(b'\xff opaque synthetic bytes; CSV/text decoding is prohibited\n')
        raw = [base.descriptor(self.root / path, self.root) for path in base.FILES.values()]
        self.write(base.EVENT, {'raw_sources': raw})
        self.event_sha = patch.object(base, 'EVENT_SHA', base.descriptor(self.root / base.EVENT, self.root)['sha256'])
        self.event_sha.start()
        self.addCleanup(self.event_sha.stop)
        inventory = {
            'format_version': 1, 'policy': base.policy(), 'columns_read': base.COLUMNS,
            'source_headers': copy.deepcopy(base.COLUMNS),
            'sources': [base.descriptor(self.root / base.EVENT, self.root), *raw,
                        *[base.descriptor(self.root / p, self.root) for p in
                          (base.CODE, base.TEST, 'sql/03_business_analysis.sql')]],
        }
        self.write(base.SPEC, inventory)
        self.write(base.OUTPUT, {'specification': base.descriptor(self.root / base.SPEC, self.root)})
        contract = {
            'format_version': 1, 'policy': frozen.policy(), 'planned_schemas': frozen.schemas(),
            'source_headers': inventory['source_headers'], 'columns_read': base.COLUMNS,
            'sources': [*inventory['sources'], *[base.descriptor(self.root / p, self.root) for p in
                        (base.SPEC, base.OUTPUT, frozen.CODE, frozen.TEST)]],
        }
        self.write(frozen.SPEC, contract)
        self.write(frozen.OUTPUT, {'specification': base.descriptor(self.root / frozen.SPEC, self.root),
                                   'policy': contract['policy'], 'results': frozen.audit_support(self.tables)})
        self.build_spec = {
            'format_version': 1, 'policy': prior.policy(),
            'dataset_contract': base.descriptor(self.root / frozen.SPEC, self.root),
            'sources': [*contract['sources'], *[base.descriptor(self.root / p, self.root) for p in
                        (frozen.SPEC, frozen.OUTPUT, *prior.IMPLEMENTATION)]],
        }
        self.write(prior.SPEC, self.build_spec)
        bundle = self.root / prior.PRIVATE
        bundle.mkdir(parents=True)
        for name in entry.artifacts.FILES[:2]:
            (bundle / name).write_bytes(b'\xff this is not parseable CSV\n')
        self.readback = {
            **{key: True for key in prior.ACCEPTANCE_FLAGS},
            'rows': {'customers.csv': 2, 'order_decisions.csv': 3}, 'cells_compared': 80,
        }
        self.summary = copy.deepcopy(self.synthetic['summary'])
        self.accepted_metadata()

    def cleanup(self):
        target = self.root.resolve()
        if target == self.scratch.resolve() or not target.is_relative_to(self.scratch.resolve()):
            raise ValueError('Synthetic cleanup escaped its private scratch directory')
        shutil.rmtree(target)

    def write(self, relative, payload):
        path = self.root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(entry.artifacts.json_bytes(payload))

    def accepted_metadata(self):
        base, prior = entry.base, entry.prior
        bundle = self.root / prior.PRIVATE
        csv_guard = {name: entry.artifacts._digest((bundle / name).read_bytes()) for name in entry.artifacts.FILES[:2]}
        manifest = {
            'specification_bytes_sha': self.build_spec['dataset_contract'],
            'source_bindings': self.build_spec['sources'],
            'schema': entry.dataset_contract.schemas(), 'rows': self.readback['rows'],
            'private_bytes_sha': csv_guard, 'population_and_state_counts': self.summary,
            'readback_acceptance': self.readback,
        }
        self.write(prior.PRIVATE + '/manifest.json', manifest)
        guard = {
            'format_version': 1, 'build_specification': base.descriptor(self.root / prior.SPEC, self.root),
            'dataset_contract': self.build_spec['dataset_contract'],
            'source_bindings': self.build_spec['sources'],
            'private_bundle_guard': entry.artifacts.bundle_guard(bundle),
            'readback_acceptance': self.readback,
        }
        self.write(prior.GUARD, guard)
        report = {'format_version': 1, 'specification': guard['build_specification'],
                  'policy': prior.policy(), 'status': 'retrospective_RFM_dataset_built_readback_accepted_no_segmentation',
                  'results': self.summary, 'acceptance': self.readback}
        self.write(prior.OUTPUT, report)
        independent = {
            'status': 'pass', 'production_code_imported': False,
            'reference_fingerprints_rechecked': True, 'frozen_raw_source_fingerprints_rechecked': True,
            'total_cell_comparisons': self.readback['cells_compared'],
            'datasets': {
                name: {
                    'rows': self.readback['rows'][name],
                    'typed_cell_comparisons': self.readback['rows'][name] * 16,
                    'binary64_comparisons': sum(row['recency_days'] is not None for row in self.synthetic['customers']) if name == 'customers.csv' else 0,
                    'nullable_cells': sum(value is None for row in self.synthetic['customers' if name == 'customers.csv' else 'orders'] for value in row.values()),
                } for name in entry.artifacts.FILES[:2]},
        }
        self.write(entry.COMPARISON, independent)
        money = self.summary['customer_money_conservation']
        self.write(entry.REFERENCE, {
            'customer_rows': self.readback['rows']['customers.csv'],
            'order_rows': self.readback['rows']['order_decisions.csv'],
            'eligible_history_orders': self.summary['history']['event_eligible_orders'],
            'eligible_window_orders': self.summary['window']['event_eligible_orders'],
            'frequency_sum': self.summary['window']['event_eligible_orders'],
            'activity_state_counts': {key: value for key, value in self.summary['customer_states'].items() if value},
            'null_recency_customers': sum(row['recency_seconds'] is None for row in self.synthetic['customers']),
            'null_monetary_customers': sum(row['monetary_product_cents'] is None for row in self.synthetic['customers']),
            'money_conservation': {'all_eligible_window_product_cents': money['eligible_window_product_cents_on_known_orders'],
                                   'known_customer_M_cents': money['published_customer_product_cents'],
                                   'masked_customer_known_eligible_product_cents': money['known_product_cents_masked_customer_subsets'],
                                   'holds': True},
            'history_clock_quarantine_orders': self.summary['history']['approval_conflict_orders'],
            'window_clock_quarantine_orders': self.summary['window']['approval_conflict_orders'],
            'window_all_quality_quarantine_orders': self.summary['window_quarantine']['orders'],
            'raw_source_bytes_unchanged': True, 'segmentation_training_dashboard': False,
            'source_rows': {'orders': self.summary['source']['orders'], 'customers': self.summary['source']['customer_master_rows'],
                            'order_items': self.summary['source']['order_item_rows'], 'order_payments': self.summary['source']['order_payment_rows']},
            'private_reference_sha': {'customers.reference.csv': csv_guard['customers.csv']['sha256'],
                                      'order_decisions.reference.csv': csv_guard['order_decisions.csv']['sha256']}})
        accepted = {
            'format_version': 1,
            'status': 'synthetic_real_readback_independent_same_ID_and_read_only_verification_passed',
            'build_report': base.descriptor(self.root / prior.OUTPUT, self.root),
            'specification': guard['build_specification'],
            'real_private_bundle': self.readback, 'independent_acceptance': independent,
            'scope': {'dataset_correctness_only': True, 'model_fits': 0, 'segmentation': False, 'dashboard': False,
                      'new_model_performance_conclusion': False, 'operational_as_of_accepted': False,
                      'refund_net_money_supported': False},
            'read_only_entry_verification': {'passed': True, 'command': 'scripts/build_rfm_dataset.py --verify',
                                              'source_binding_count': 20, 'rebuilt': False, 'wrote_files': False},
            'stage4': prior.policy()['stage4'], 'stage5': prior.policy()['stage5'],
        }
        self.write(entry.ACCEPTANCE, accepted)

    def freeze(self):
        return entry.run(self.root, specification_only=True)

    def audit(self):
        return entry.run(self.root, audit=True)

    def snapshot(self):
        return {str(path.relative_to(self.root)): path.read_bytes()
                for path in self.root.rglob('*') if path.is_file()}

    def test_requires_exactly_one_action(self):
        for flags in ({}, {'specification_only': True, 'audit': True}):
            with self.assertRaises(ValueError):
                entry.run(self.root, **flags)

    def test_complete_twenty_seven_bindings_and_frozen_methods(self):
        self.freeze()
        spec = entry.base.read_json(self.root / entry.SPEC)
        self.assertEqual(len(spec['sources']), 27)
        self.assertEqual(spec['policy'], entry.method.policy())
        self.assertEqual(spec['planned_outputs'], entry.method.planned_outputs())
        self.assertIn('requirements-lock.txt', [item['path'] for item in spec['sources']])
        self.assertFalse((self.root / entry.OUTPUT).exists())

    def test_no_csv_content_or_header_parser_builder_or_statistics(self):
        with patch.object(csv, 'reader', side_effect=AssertionError('CSV parsing prohibited')), \
                patch.object(entry.base, 'read_tables', side_effect=AssertionError('raw table read')), \
                patch.object(entry.prior, 'run', side_effect=AssertionError('prior entry replay')), \
                patch.object(entry.prior, 'verify_sources', side_effect=AssertionError('header verifier')), \
                patch.object(entry.artifacts, 'read_bundle', side_effect=AssertionError('individual RFM read')):
            self.freeze()
            self.audit()
        report = entry.base.read_json(self.root / entry.OUTPUT)
        self.assertIs(report['execution']['csv_content_parsed'], False)
        self.assertIs(report['execution']['csv_header_parsed'], False)
        self.assertEqual(report['execution']['model_fits'], 0)

    def test_audit_reuses_prior_counts_without_new_statistics(self):
        self.freeze()
        self.audit()
        report = entry.base.read_json(self.root / entry.OUTPUT)
        self.assertEqual(report['reused_accepted_population']['customer_rows'], 2)
        self.assertEqual(report['reused_accepted_population']['order_decision_rows'], 3)
        self.assertTrue(all(report['metadata_checks'].values()))
        self.assertIs(report['execution']['new_descriptive_statistics_computed'], False)
        self.assertIs(report['execution']['segments_assigned'], False)

    def test_public_report_omits_private_fingerprints(self):
        self.freeze()
        self.audit()
        report = (self.root / entry.OUTPUT).read_text('utf-8')
        guard = entry.base.read_json(self.root / entry.GUARD)
        for value in guard['private_bundle_guard'].values():
            self.assertNotIn(value['sha256'], report)
        self.assertNotIn('private_bundle_guard', report)
        self.assertNotIn('private_reference_sha', report)

    def test_identical_freeze_and_audit_are_immutable_noops(self):
        self.freeze()
        self.audit()
        before = self.snapshot()
        times = {path: path.stat().st_mtime_ns for path in self.root.rglob('*') if path.is_file()}
        self.freeze()
        self.audit()
        self.assertEqual(before, self.snapshot())
        self.assertEqual(times, {path: path.stat().st_mtime_ns for path in times})

    def test_changed_raw_bytes_stop_without_parsing(self):
        (self.root / next(iter(entry.base.FILES.values()))).write_bytes(b'changed source')
        with self.assertRaisesRegex(ValueError, 'raw CSV bytes'):
            self.freeze()
        self.assertFalse((self.root / entry.SPEC).exists())

    def test_shortened_eight_twelve_twenty_source_lists_stop(self):
        for path in (entry.base.SPEC, entry.dataset_contract.SPEC, entry.prior.SPEC):
            original = (self.root / path).read_bytes()
            spec = entry.base.read_json(self.root / path)
            spec['sources'].pop()
            self.write(path, spec)
            with self.subTest(path=path), self.assertRaises(ValueError):
                self.freeze()
            (self.root / path).write_bytes(original)

    def test_changed_frozen_method_and_lock_bytes_stop(self):
        self.freeze()
        for path in (entry.METHOD, 'requirements-lock.txt'):
            original = (self.root / path).read_bytes()
            (self.root / path).write_bytes(b'changed')
            with self.subTest(path=path), self.assertRaises(ValueError):
                self.audit()
            (self.root / path).write_bytes(original)

    def test_changed_private_csv_guard_manifest_or_reference_stops(self):
        self.freeze()
        for path in (entry.prior.PRIVATE + '/customers.csv', entry.prior.GUARD,
                     entry.prior.PRIVATE + '/manifest.json', entry.REFERENCE, entry.COMPARISON):
            original = (self.root / path).read_bytes()
            (self.root / path).write_bytes(b'changed')
            with self.subTest(path=path), self.assertRaises((ValueError, json.JSONDecodeError)):
                self.audit()
            (self.root / path).write_bytes(original)

    def test_changed_public_build_or_acceptance_stops(self):
        self.freeze()
        for path in (entry.prior.OUTPUT, entry.ACCEPTANCE):
            original = (self.root / path).read_bytes()
            data = entry.base.read_json(self.root / path)
            data['extra'] = True
            self.write(path, data)
            with self.subTest(path=path), self.assertRaises(ValueError):
                self.audit()
            (self.root / path).write_bytes(original)

    def test_shortened_new_specification_cannot_bypass_sources(self):
        self.freeze()
        spec = entry.base.read_json(self.root / entry.SPEC)
        spec['sources'].pop()
        self.write(entry.SPEC, spec)
        with self.assertRaisesRegex(ValueError, 'Complete evaluation'):
            self.audit()

    def test_guard_numeric_types_cannot_impersonate_integer(self):
        self.freeze()
        guard = entry.base.read_json(self.root / entry.GUARD)
        for value in (True, 1.0):
            guard['format_version'] = value
            self.write(entry.GUARD, guard)
            with self.subTest(value=value), self.assertRaisesRegex(ValueError, 'input guard'):
                self.audit()

    def test_prior_guard_numeric_types_rejected(self):
        original = entry.base.read_json(self.root / entry.prior.GUARD)
        for value in (True, 1.0):
            guard = copy.deepcopy(original)
            guard['format_version'] = value
            self.write(entry.prior.GUARD, guard)
            with self.subTest(value=value), self.assertRaises(ValueError):
                self.freeze()
        self.write(entry.prior.GUARD, original)

    def test_consistently_forged_metadata_row_bool_is_rejected(self):
        self.readback['rows']['customers.csv'] = True
        self.readback['cells_compared'] = 64
        self.accepted_metadata()
        with self.assertRaisesRegex(ValueError, 'row types'):
            self.freeze()

    def test_partial_spec_or_private_guard_is_not_regenerated(self):
        self.freeze()
        (self.root / entry.GUARD).unlink()
        with self.assertRaisesRegex(ValueError, 'Partial frozen'):
            self.freeze()
        self.assertFalse((self.root / entry.GUARD).exists())

    def test_changed_existing_spec_is_not_overwritten_or_refrozen(self):
        self.freeze()
        original = entry.base.read_json(self.root / entry.SPEC)
        original['policy']['unexpected'] = True
        self.write(entry.SPEC, original)
        bad = (self.root / entry.SPEC).read_bytes()
        with self.assertRaisesRegex(ValueError, 'Refusing changed frozen'):
            self.freeze()
        self.assertEqual((self.root / entry.SPEC).read_bytes(), bad)

    def test_unexpected_control_file_stops(self):
        control = self.root / entry.PRIVATE
        control.mkdir(parents=True)
        (control / 'foreign').write_bytes(b'preserve')
        with self.assertRaisesRegex(ValueError, 'Unexpected files'):
            self.freeze()
        self.assertEqual((control / 'foreign').read_bytes(), b'preserve')

    def test_audit_before_freeze_creates_nothing(self):
        before = self.snapshot()
        with self.assertRaises(FileNotFoundError):
            self.audit()
        self.assertEqual(before, self.snapshot())

    def test_changed_inputs_between_preflight_and_write_stop(self):
        original = entry._state
        calls = 0
        def changing(root):
            nonlocal calls
            result = original(root)
            calls += 1
            if calls == 1:
                (self.root / entry.METHOD).write_bytes(b'changed during preflight')
            return result
        with patch.object(entry, '_state', side_effect=changing):
            with self.assertRaisesRegex(ValueError, 'Inputs changed'):
                self.freeze()
        self.assertFalse((self.root / entry.SPEC).exists())
        self.assertFalse((self.root / entry.GUARD).exists())

    def test_strict_json_duplicate_key_and_nonfinite_stop(self):
        for bad in (b'{"format_version":1,"format_version":1}', b'{"value":NaN}'):
            original = (self.root / entry.COMPARISON).read_bytes()
            (self.root / entry.COMPARISON).write_bytes(bad)
            with self.subTest(bad=bad), self.assertRaises(ValueError):
                self.freeze()
            (self.root / entry.COMPARISON).write_bytes(original)

    def test_changed_audit_report_is_never_overwritten(self):
        self.freeze()
        self.audit()
        self.write(entry.OUTPUT, {'unrelated': True})
        with self.assertRaises(ValueError):
            self.audit()
        self.assertEqual(entry.base.read_json(self.root / entry.OUTPUT), {'unrelated': True})

    def test_semantically_equal_specification_or_guard_bytes_cannot_change(self):
        self.freeze()
        for relative in (entry.SPEC, entry.GUARD):
            original = (self.root / relative).read_bytes()
            (self.root / relative).write_bytes(original + b'\n')
            with self.subTest(relative=relative), self.assertRaises(ValueError):
                self.audit()
            (self.root / relative).write_bytes(original)

    def test_resigned_impossible_customer_state_population_is_rejected(self):
        self.summary['customer_states']['active_complete'] = 999
        self.accepted_metadata()
        with self.assertRaisesRegex(ValueError, 'state sum'):
            self.freeze()
        self.assertFalse((self.root / entry.SPEC).exists())

    def test_resigned_state_key_type_and_active_inactive_denominator_forgery_rejected(self):
        original = copy.deepcopy(self.summary)
        mutations = (
            lambda s: s['customer_states'].update({'active_complete': True}),
            lambda s: s['customer_states'].update({'extra_state': 0}),
            lambda s: s['window'].update({'active_customers': 999}),
            lambda s: s['window'].update({'zero_eligible_window_customers': 999}),
            lambda s: s['history'].update({'customer_universe': 999}),
        )
        for mutate in mutations:
            self.summary = copy.deepcopy(original)
            mutate(self.summary)
            self.accepted_metadata()
            with self.subTest(mutation=mutate), self.assertRaises(ValueError):
                self.freeze()

    def test_resigned_contract_support_summary_conflict_is_rejected(self):
        self.summary['history']['event_eligible_orders'] = 999
        self.accepted_metadata()
        with self.assertRaisesRegex(ValueError, 'frozen support'):
            self.freeze()

    def test_resigned_conservation_contradiction_is_rejected(self):
        self.summary['customer_money_conservation']['published_customer_product_cents'] += 1
        self.accepted_metadata()
        with self.assertRaisesRegex(ValueError, 'conservation equation'):
            self.freeze()

    def test_reference_frequency_population_null_or_money_contradictions_rejected(self):
        original = entry.base.read_json(self.root / entry.REFERENCE)
        mutations = (
            lambda r: r.update({'frequency_sum': 999}),
            lambda r: r.update({'customer_rows': 999}),
            lambda r: r.update({'null_recency_customers': 999}),
            lambda r: r.update({'null_monetary_customers': 999}),
            lambda r: r['money_conservation'].update({'known_customer_M_cents': 999}),
        )
        for mutate in mutations:
            reference = copy.deepcopy(original)
            mutate(reference)
            self.write(entry.REFERENCE, reference)
            with self.subTest(mutation=mutate), self.assertRaises(ValueError):
                self.freeze()

    def test_resigned_independent_per_file_rows_cells_binary64_types_rejected(self):
        original = entry.base.read_json(self.root / entry.COMPARISON)
        accepted_original = entry.base.read_json(self.root / entry.ACCEPTANCE)
        mutations = (
            lambda d: d['datasets']['customers.csv'].update({'rows': 999}),
            lambda d: d['datasets']['customers.csv'].update({'typed_cell_comparisons': 999}),
            lambda d: d['datasets']['customers.csv'].update({'binary64_comparisons': 999}),
            lambda d: d['datasets']['order_decisions.csv'].update({'binary64_comparisons': 0.0}),
            lambda d: d['datasets']['customers.csv'].update({'nullable_cells': 999}),
            lambda d: d.update({'total_cell_comparisons': 999}),
        )
        for mutate in mutations:
            independent = copy.deepcopy(original)
            mutate(independent)
            self.write(entry.COMPARISON, independent)
            accepted = copy.deepcopy(accepted_original)
            accepted['independent_acceptance'] = independent
            self.write(entry.ACCEPTANCE, accepted)
            with self.subTest(mutation=mutate), self.assertRaises(ValueError):
                self.freeze()

    def test_resigned_build_version_policy_or_status_changes_rejected(self):
        original = entry.base.read_json(self.root / entry.prior.OUTPUT)
        accepted_original = entry.base.read_json(self.root / entry.ACCEPTANCE)
        mutations = (
            lambda b: b.update({'format_version': True}),
            lambda b: b['policy'].update({'training': True}),
            lambda b: b.update({'status': 'unaccepted'}),
        )
        for mutate in mutations:
            build = copy.deepcopy(original)
            mutate(build)
            self.write(entry.prior.OUTPUT, build)
            accepted = copy.deepcopy(accepted_original)
            accepted['build_report'] = entry.base.descriptor(self.root / entry.prior.OUTPUT, self.root)
            self.write(entry.ACCEPTANCE, accepted)
            with self.subTest(mutation=mutate), self.assertRaises(ValueError):
                self.freeze()

    def test_acceptance_version_status_scope_read_only_and_stage_permissions_rejected(self):
        original = entry.base.read_json(self.root / entry.ACCEPTANCE)
        mutations = (
            lambda a: a.update({'format_version': 1.0}),
            lambda a: a.update({'status': 'unaccepted'}),
            lambda a: a['scope'].update({'model_fits': False}),
            lambda a: a['scope'].update({'operational_as_of_accepted': True}),
            lambda a: a['read_only_entry_verification'].update({'source_binding_count': 20.0}),
            lambda a: a['read_only_entry_verification'].update({'wrote_files': True}),
            lambda a: a['stage4'].update({'daily_budget': 0.2}),
            lambda a: a['stage5'].update({'status': 'accepted'}),
        )
        for mutate in mutations:
            accepted = copy.deepcopy(original)
            mutate(accepted)
            self.write(entry.ACCEPTANCE, accepted)
            with self.subTest(mutation=mutate), self.assertRaises(ValueError):
                self.freeze()

    def test_resigned_readback_extra_file_or_schema_keys_rejected(self):
        original = copy.deepcopy(self.readback)
        self.readback['rows']['extra.csv'] = 1
        self.readback['cells_compared'] = 96
        self.accepted_metadata()
        with self.assertRaisesRegex(ValueError, 'row keys'):
            self.freeze()
        self.readback = original
        self.readback['extra_acceptance'] = True
        self.accepted_metadata()
        with self.assertRaisesRegex(ValueError, 'readback schema'):
            self.freeze()


if __name__ == '__main__':
    unittest.main()
