"""Synthetic G2 source provenance, full independent IDs and existing G1 readback."""
import copy
import csv
from pathlib import Path
import shutil
import unittest
from unittest.mock import patch
import uuid

from scripts import rfm_rule_candidate_sources as sources
from scripts import rfm_description as description_core
from tests import test_rfm_description_sources as description_tests
from tests import test_verify_rfm_rule_candidate as implementation_tests
from tests.test_prepare_rfm_description import five_states
from tests.test_rfm_dataset_builder import fixture, add_order, build


def _write(root, relative, value):
    path = Path(root) / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(sources.artifacts.json_bytes(value))


def make_fixture(root, tables=None):
    """Full synthetic original sources, RFM bundle and completed G1 four files.

    For the future loader E2E, patch this module's ``metadata_snapshot`` with
    ``fixture_snapshot`` and the original description source metadata function
    with ``description_tests.fixture_snapshot``. Actual CSV/typed readers and
    the complete independent ID/G1 readback code remain unmocked.
    """
    root = Path(root)
    case = description_tests.make_fixture(root, five_states() if tables is None else tables)
    entry = sources.description_entry
    public_paths = [item['path'] for item in case['snapshot']['public_sources']]
    for relative in entry.IMPLEMENTATION:
        path = root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b'synthetic previous G1 implementation\n')
        public_paths.append(relative)
    g1_sources = [sources.base.descriptor(root / p, root) for p in public_paths]
    _write(root, entry.SPEC, {'format_version': 1, 'sources': g1_sources})
    _write(root, entry.PREFLIGHT, {'synthetic': 'G1 preflight'})
    _write(root, entry.INPUT_GUARD, {'input_snapshot': case['snapshot']})
    data = {'dataset': case['dataset'], 'evaluation_spec': case['evaluation_spec'],
            'customer_ids': [r['customer_unique_id'] for r in case['dataset']['customers']],
            'order_ids': [r['order_id'] for r in case['dataset']['orders']],
            'window_order_ids': [r['order_id'] for r in case['dataset']['orders'] if r['window_event_eligible']]}
    description = description_core.describe_dataset(data['dataset'], data['evaluation_spec'],
                                                    expected_customer_ids=data['customer_ids'])
    provenance = {'execution_specification': sources.base.descriptor(root / entry.SPEC, root),
                  'source_bindings': g1_sources}
    written = sources.description_outputs.write_outputs(data, description, provenance, root / entry.DATASET)
    _write(root, entry.PUBLIC, written['public_report'])
    _write(root, entry.OUTPUT_GUARD, {
        'format_version': 1, 'specification': provenance['execution_specification'],
        'input_guard': sources.base.descriptor(root / entry.INPUT_GUARD, root),
        'private_bundle_guard': written['private_guard'],
        'public_report': sources.base.descriptor(root / entry.PUBLIC, root),
        'readback_acceptance': written['readback_acceptance'],
    })
    _write(root, sources.prior.ACCEPTANCE, {'synthetic': 'G1 accepted', 'gates': description['gate_status']})
    public_paths.extend((entry.SPEC, entry.PREFLIGHT, entry.PUBLIC, sources.prior.ACCEPTANCE))
    for relative in sources.prior.IMPLEMENTATION:
        path = root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b'synthetic G2 implementation\n')
        public_paths.append(relative)
    for relative in (sources.prior.SPEC, sources.prior.OUTPUT, sources.prior.GUARD):
        _write(root, relative, {'synthetic': relative})
    log = root / sources.prior.LOG
    log.parent.mkdir(parents=True, exist_ok=True)
    log.write_bytes(b'synthetic accepted G2 implementation tests\n')
    public_paths.extend((sources.prior.SPEC, sources.prior.OUTPUT))
    _write(root, '.runtime/synthetic_G2_source_metadata.json', {'public_paths': public_paths})
    case.update(data=data, description=description, g1_written=written)
    case['snapshot'] = fixture_snapshot(root)
    return case


def fixture_snapshot(root):
    root = Path(root)
    entry = sources.description_entry
    old_snapshot = description_tests.fixture_snapshot(root)
    guard = sources.base.read_json(root / entry.OUTPUT_GUARD)
    metadata = sources.base.read_json(root / '.runtime/synthetic_G2_source_metadata.json')
    inherited = {
        'prepared_input_guard': sources.base.descriptor(root / entry.INPUT_GUARD, root),
        'completed_output_guard': sources.base.descriptor(root / entry.OUTPUT_GUARD, root),
        'prepared_state': {'input_snapshot': old_snapshot}, 'completed_guard': guard,
    }
    return {
        'format_version': 1,
        'public_sources': [sources.base.descriptor(root / p, root) for p in metadata['public_paths']],
        'private_inputs': {'implementation_input_guard': sources.base.descriptor(root / sources.prior.GUARD, root),
                           'implementation_test_log': sources.base.descriptor(root / sources.prior.LOG, root),
                           'prior_G0_G1_provenance': inherited},
        'accepted_rows': old_snapshot['accepted_rows'], 'metadata_checks': old_snapshot['metadata_checks'],
        'description_input_snapshot': old_snapshot,
        'G1_readback_acceptance': guard['readback_acceptance'],
    }


class G2InputLoadTests(unittest.TestCase):
    def setUp(self):
        self.scratch = sources.ROOT / '.runtime' / 'stage6_G2_source_load_tests'
        self.scratch.mkdir(parents=True, exist_ok=True)
        self.root = self.scratch / uuid.uuid4().hex
        self.root.mkdir()
        self.addCleanup(self.cleanup)

    def cleanup(self):
        target, parent = self.root.resolve(), self.scratch.resolve()
        if target == parent or not target.is_relative_to(parent):
            raise ValueError('Synthetic cleanup escaped its private directory')
        shutil.rmtree(target)

    def load(self, case):
        with patch.object(sources, 'metadata_snapshot', side_effect=fixture_snapshot), \
                patch.object(sources.description_sources, 'metadata_snapshot',
                             side_effect=description_tests.fixture_snapshot):
            return sources.read_inputs(self.root, case['snapshot'])

    def snapshot(self):
        return {str(p.relative_to(self.root)): p.read_bytes()
                for p in self.root.rglob('*') if p.is_file()}

    def test_full_five_state_universe_and_G1_readback_returned_without_replay_or_write(self):
        case = make_fixture(self.root)
        before = self.snapshot()
        blocked = AssertionError('No G1 replay, new RFM builder or prior dispatcher')
        with patch.object(description_core, 'describe_dataset', side_effect=blocked), \
                patch.object(sources.description_entry, 'execute_prepared', side_effect=blocked), \
                patch.object(sources.description_entry, 'verify_completed', side_effect=blocked), \
                patch.object(sources.description_sources.build.builder, 'build_dataset', side_effect=blocked):
            data = self.load(case)
        self.assertEqual(set(data), {'dataset', 'evaluation_spec', 'customer_ids', 'order_ids',
                                   'window_order_ids', 'snapshot', 'g1_accepted', 'g1_readback_acceptance'})
        self.assertEqual(data['dataset'], case['dataset'])
        self.assertEqual(data['customer_ids'], ['u1', 'u2', 'u3', 'u4', 'u5'])
        self.assertEqual(set(r['activity_state'] for r in data['dataset']['customers']),
                         {'active_complete', 'inactive_complete', 'active_with_quarantine',
                          'active_money_unknown', 'inactive_with_quarantine'})
        self.assertTrue(data['g1_accepted'])
        self.assertEqual(data['g1_readback_acceptance'], case['g1_written']['readback_acceptance'])
        self.assertIn('outside-cancelled', data['order_ids'])
        self.assertIn('outside-quarantine', data['order_ids'])
        self.assertNotIn('future', data['order_ids'])
        self.assertEqual(before, self.snapshot())

    def test_RFM_bundle_loaded_only_once_and_existing_G1_verified_with_same_data(self):
        case = make_fixture(self.root)
        original = sources.artifacts.read_bundle
        with patch.object(sources.artifacts, 'read_bundle', wraps=original) as reader, \
                patch.object(sources.description_outputs, 'verify_outputs',
                             wraps=sources.description_outputs.verify_outputs) as verify:
            data = self.load(case)
        self.assertEqual(reader.call_count, 1)
        self.assertEqual(verify.call_count, 1)
        self.assertIs(verify.call_args.args[1]['dataset'], data['dataset'])

    def test_snapshot_or_strict_type_mismatch_stops_before_parser(self):
        case = make_fixture(self.root)
        for mutation in (lambda s: s.update(format_version=True), lambda s: s['public_sources'].pop()):
            expected = copy.deepcopy(case['snapshot'])
            mutation(expected)
            with patch.object(sources, 'metadata_snapshot', side_effect=fixture_snapshot), \
                    patch.object(sources.description_sources, 'read_inputs', side_effect=AssertionError('Too early')):
                with self.subTest(mutation=mutation), self.assertRaisesRegex(ValueError, 'before parsing'):
                    sources.read_inputs(self.root, expected)

    def test_changed_original_source_bytes_stop_before_any_reader(self):
        case = make_fixture(self.root)
        path = self.root / sources.description_sources.base.FILES['orders']
        path.write_bytes(path.read_bytes() + b'\n')
        with patch.object(csv, 'DictReader', side_effect=AssertionError('Must stop before parse')):
            with self.assertRaisesRegex(ValueError, 'before parsing'):
                self.load(case)

    def test_coherent_missing_customer_bundle_cannot_replace_independent_source_IDs(self):
        tables = fixture()
        add_order(tables, 'o2', 'c2', 'u2')
        case = make_fixture(self.root, tables)
        reduced = build(fixture())
        metadata_path = self.root / '.runtime/synthetic_source_metadata.json'
        metadata = sources.base.read_json(metadata_path)
        metadata['rows'] = {'customers.csv': 1, 'order_decisions.csv': 1}
        _write(self.root, '.runtime/synthetic_source_metadata.json', metadata)
        case['snapshot'] = fixture_snapshot(self.root)
        with patch.object(sources.artifacts, 'read_bundle', return_value=reduced):
            with self.assertRaisesRegex(ValueError, 'customer IDs differ'):
                self.load(case)

    def test_same_ID_counts_cannot_hide_customer_mapping_swaps(self):
        tables = fixture()
        add_order(tables, 'o2', 'c2', 'u2')
        case = make_fixture(self.root, tables)
        swapped = copy.deepcopy(tables)
        swapped['customers'][0]['customer_unique_id'] = 'u2'
        swapped['customers'][1]['customer_unique_id'] = 'u1'
        fake_dataset = build(swapped)
        with patch.object(sources.artifacts, 'read_bundle', return_value=fake_dataset):
            with self.assertRaisesRegex(ValueError, 'event decisions or customer mappings'):
                self.load(case)

    def test_duplicate_original_ID_or_unmapped_historical_order_stops(self):
        for mutation in ('duplicate', 'unmapped'):
            with self.subTest(mutation=mutation):
                case = make_fixture(self.root / mutation)
                target = self.root / mutation
                path = target / sources.description_sources.base.FILES['orders']
                original = path.read_text('utf-8')
                if mutation == 'duplicate':
                    path.write_text(original + original.splitlines()[1] + '\n', encoding='utf-8', newline='')
                else:
                    rows = original.splitlines()
                    cells = rows[1].split(',')
                    customer_pos = rows[0].split(',').index('customer_id')
                    cells[customer_pos] = 'unmapped'
                    rows[1] = ','.join(cells)
                    path.write_text('\n'.join(rows) + '\n', encoding='utf-8', newline='')
                expected = fixture_snapshot(target)
                with patch.object(sources, 'metadata_snapshot', side_effect=fixture_snapshot), \
                        patch.object(sources.description_sources, 'metadata_snapshot',
                                     side_effect=description_tests.fixture_snapshot):
                    with self.assertRaises(ValueError):
                        sources.read_inputs(target, expected)

    def test_changed_G1_private_file_stops_before_full_readback(self):
        case = make_fixture(self.root)
        path = self.root / sources.description_entry.DATASET / 'customer_roster.csv'
        path.write_bytes(path.read_bytes() + b'\n')
        # Snapshot hashes remain the old successful guard, so parser proceeds
        # only to the G1 bytes guard and cannot accept an altered roster.
        with self.assertRaisesRegex(ValueError, 'private output guard'):
            self.load(case)

    def test_changed_G1_aggregate_cannot_be_blessed_by_refreshing_public_source_hash(self):
        case = make_fixture(self.root)
        public_path = self.root / sources.description_entry.PUBLIC
        public = sources.base.read_json(public_path)
        public['description']['routing_counts']['population_n'] += 1
        _write(self.root, sources.description_entry.PUBLIC, public)
        case['snapshot'] = fixture_snapshot(self.root)
        with self.assertRaises(ValueError):
            self.load(case)

    def test_changed_G1_acceptance_receipt_is_rejected(self):
        case = make_fixture(self.root)
        case['snapshot']['G1_readback_acceptance']['roster_cells_compared'] += 1
        # Return this coherently typed but wrong expected receipt as both before
        # and after metadata, so the full G1 readback must detect the mismatch.
        with patch.object(sources, 'metadata_snapshot', return_value=case['snapshot']), \
                patch.object(sources.description_sources, 'metadata_snapshot',
                             side_effect=description_tests.fixture_snapshot):
            with self.assertRaisesRegex(ValueError, 'full readback'):
                sources.read_inputs(self.root, case['snapshot'])

    def test_source_mutation_during_G1_readback_is_detected_after_verification(self):
        case = make_fixture(self.root)
        original = sources.description_outputs.verify_outputs
        def mutate(*args, **kwargs):
            receipt = original(*args, **kwargs)
            log = self.root / sources.prior.LOG
            log.write_bytes(log.read_bytes() + b'changed\n')
            return receipt
        with patch.object(sources.description_outputs, 'verify_outputs', side_effect=mutate):
            with self.assertRaisesRegex(ValueError, 'changed during'):
                self.load(case)


class G2InputMetadataTests(unittest.TestCase):
    def setUp(self):
        self.previous = implementation_tests.RFMRuleCandidateVerificationTests()
        self.previous.setUp()
        self.addCleanup(self.previous.doCleanups)
        self.root = self.previous.root
        self.original_prepared = self.previous.synthetic_prepared
        def prepared(root):
            state = self.original_prepared(root)
            state[1]['input_snapshot'] = {
                'accepted_rows': {'customers.csv': 2, 'order_decisions.csv': 3},
                'opaque_prior_snapshot': True,
            }
            return state
        self.patch = patch.object(sources.description_entry, 'verify_prepared', side_effect=prepared)
        self.patch.start()
        self.addCleanup(self.patch.stop)
        self.previous.verify()

    def test_metadata_binds_complete_fifty_one_sources_and_private_receipts(self):
        snapshot = sources.metadata_snapshot(self.root)
        self.assertEqual(set(snapshot), {'format_version', 'public_sources', 'private_inputs', 'accepted_rows',
                                        'metadata_checks', 'description_input_snapshot', 'G1_readback_acceptance'})
        self.assertEqual(len(snapshot['public_sources']), 51)
        self.assertEqual(len({r['path'] for r in snapshot['public_sources']}), 51)
        self.assertEqual(snapshot['accepted_rows'], {'customers.csv': 2, 'order_decisions.csv': 3})
        self.assertEqual(set(snapshot['private_inputs']), {'implementation_input_guard', 'implementation_test_log',
                                                        'prior_G0_G1_provenance'})

    def test_opaque_metadata_cannot_parse_CSV_replay_prior_tests_or_read_individual_values(self):
        blocked = AssertionError('Only JSON metadata and binary hashes permitted')
        with patch.object(csv, 'reader', side_effect=blocked), patch.object(csv, 'DictReader', side_effect=blocked), \
                patch.object(sources.prior, 'run', side_effect=blocked), \
                patch.object(sources.prior, '_run_suites', side_effect=blocked), \
                patch.object(sources.description_sources, 'read_inputs', side_effect=blocked), \
                patch.object(sources.description_outputs, 'read_outputs', side_effect=blocked), \
                patch.object(description_core, 'describe_dataset', side_effect=blocked):
            sources.metadata_snapshot(self.root)

    def test_missing_or_changed_implementation_guard_or_log_is_rejected(self):
        for relative in (sources.prior.GUARD, sources.prior.LOG):
            path = self.root / relative
            original = path.read_bytes()
            path.write_bytes(original + b'\n')
            with self.subTest(relative=relative), self.assertRaises(ValueError):
                sources.metadata_snapshot(self.root)
            path.write_bytes(original)
        path = self.root / sources.prior.LOG
        path.unlink()
        with self.assertRaises((ValueError, FileNotFoundError)):
            sources.metadata_snapshot(self.root)

    def test_completed_description_bytes_and_G1_acceptance_are_required(self):
        path = self.root / sources.description_entry.DATASET / sources.description_outputs.FILES[0]
        path.write_bytes(path.read_bytes() + b'\n')
        with self.assertRaises(ValueError):
            sources.metadata_snapshot(self.root)

    def test_sources_changing_between_metadata_snapshots_are_rejected(self):
        original = sources.prior._prior_snapshot
        calls = []
        def changed(root):
            value = original(root)
            if calls:
                value['metadata_checks']['changed_after_check'] = True
            calls.append(value)
            return value
        with patch.object(sources.prior, '_prior_snapshot', side_effect=changed):
            with self.assertRaisesRegex(ValueError, 'changed during'):
                sources.metadata_snapshot(self.root)

    def test_no_source_or_provenance_file_is_written(self):
        before = self.previous.snapshot()
        sources.metadata_snapshot(self.root)
        self.assertEqual(before, self.previous.snapshot())


if __name__ == '__main__':
    unittest.main()
