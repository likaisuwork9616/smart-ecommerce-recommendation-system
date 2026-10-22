"""Synthetic provenance and complete source-derived RFM input roster checks."""
import copy
import csv
from pathlib import Path
import shutil
import unittest
from unittest.mock import patch
import uuid

from scripts import rfm_description_sources as sources
from tests.test_rfm_dataset_builder import add_order, build as synthetic_build, fixture, empty_tables
from tests import test_verify_rfm_description as prior_tests


def _write_json(path, payload):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(sources.artifacts.json_bytes(payload))


def make_fixture(root, tables=None):
    """Write only synthetic two-source CSVs and a typed accepted bundle.

    Callers patch ``metadata_snapshot`` with ``fixture_snapshot`` for the loading
    E2E path. Complete real metadata provenance is tested separately with the
    opaque prior-chain fixture, never bypassed by the production module.
    """
    root = Path(root)
    tables = copy.deepcopy(fixture() if tables is None else tables)
    dataset = synthetic_build(tables)
    frozen = {
        'format_version': 1, 'policy': sources.contract.policy(),
        'planned_schemas': sources.contract.schemas(),
        'source_headers': {name: list(columns) for name, columns in sources.PROJECTION.items()},
        'columns_read': copy.deepcopy(sources.base.COLUMNS),
    }
    _write_json(root / sources.contract.SPEC, frozen)
    descriptor = sources.base.descriptor(root / sources.contract.SPEC, root)
    build_spec = {'sources': [descriptor]}
    _write_json(root / sources.build.SPEC, build_spec)
    evaluation = {
        'format_version': 1, 'policy': sources.evaluation.method.policy(),
        'planned_outputs': sources.evaluation.method.planned_outputs(),
    }
    _write_json(root / sources.evaluation.SPEC, evaluation)
    for name, columns in sources.PROJECTION.items():
        path = root / sources.base.FILES[name]
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open('w', encoding='utf-8', newline='') as stream:
            writer = csv.DictWriter(stream, fieldnames=list(columns), lineterminator='\n')
            writer.writeheader()
            writer.writerows({key: row[key] for key in columns} for row in tables[name])
    sources.artifacts.write_bundle(dataset, frozen, build_spec['sources'], root / sources.build.PRIVATE)
    paths = [sources.contract.SPEC, sources.build.SPEC, sources.evaluation.SPEC,
             sources.base.FILES['orders'], sources.base.FILES['customers']]
    for number in range(30):
        relative = 'synthetic_public_sources/' + str(number) + '.bin'
        path = root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b'opaque synthetic source evidence\n')
        paths.append(relative)
    _write_json(root / '.runtime/synthetic_source_metadata.json', {
        'public_paths': paths,
        'rows': {'customers.csv': len(dataset['customers']), 'order_decisions.csv': len(dataset['orders'])},
    })
    return {'dataset': dataset, 'snapshot': fixture_snapshot(root),
            'evaluation_spec': evaluation, 'tables': tables}


def fixture_snapshot(root):
    root = Path(root)
    path = root / '.runtime/synthetic_source_metadata.json'
    metadata = sources.base.read_json(path)
    return {
        'format_version': 1,
        'public_sources': [sources.base.descriptor(root / relative, root) for relative in metadata['public_paths']],
        'private_inputs': [sources.base.descriptor(path, root)],
        'accepted_bundle': sources.artifacts.bundle_guard(root / sources.build.PRIVATE),
        'accepted_rows': metadata['rows'],
        'metadata_checks': {'synthetic_check_' + str(i): True for i in range(42)},
    }


class RFMSourceRosterTests(unittest.TestCase):
    def setUp(self):
        self.scratch = sources.ROOT / '.runtime' / 'stage6_description_source_tests'
        self.scratch.mkdir(parents=True, exist_ok=True)
        self.root = self.scratch / uuid.uuid4().hex
        self.root.mkdir()
        self.addCleanup(self.cleanup)

    def cleanup(self):
        target = self.root.resolve()
        if target == self.scratch.resolve() or not target.is_relative_to(self.scratch.resolve()):
            raise ValueError('Synthetic source cleanup escaped the private scratch directory')
        shutil.rmtree(target)

    def roster(self, tables):
        return sources.derive_roster({key: tables[key] for key in sources.PROJECTION})

    def load(self, case):
        with patch.object(sources, 'metadata_snapshot', side_effect=fixture_snapshot):
            return sources.read_inputs(self.root, case['snapshot'])

    def two_customers(self):
        tables = fixture()
        add_order(tables, 'o2', 'c2', 'u2')
        return tables

    def test_source_roster_includes_inactive_and_all_pre_T_orders_but_not_future(self):
        tables = fixture()
        add_order(tables, 'old', 'c2', 'u2', purchase='2017-08-01 00:00:00',
                  approval='', delivery='2017-08-02 00:00:00')
        add_order(tables, 'quarantine', 'c3', 'u3', delivery='')
        add_order(tables, 'cancelled', 'c4', 'u4', status='canceled', delivery='')
        add_order(tables, 'future', 'unmapped', 'future-uid', purchase='2018-09-01 00:00:00',
                  approval='', delivery='')
        tables['customers'] = [row for row in tables['customers'] if row['customer_id'] != 'unmapped']
        result = self.roster(tables)
        self.assertEqual(result['customer_ids'], ['u1', 'u2'])
        self.assertEqual(result['order_ids'], ['cancelled', 'o1', 'old', 'quarantine'])
        self.assertEqual(result['window_order_ids'], ['o1'])
        self.assertEqual(len(result['order_proofs']), 4)

    def test_missing_approval_is_nonblocking_clock_conflicts_quarantined_by_rule(self):
        tables = fixture()
        tables['orders'][0]['order_approved_at'] = ''
        add_order(tables, 'clock', 'c2', 'u2', approval='2018-08-11 00:00:00')
        add_order(tables, 'late', 'c3', 'u3', delivery='2018-09-01 00:00:00')
        result = self.roster(tables)
        self.assertEqual(result['customer_ids'], ['u1'])
        proof = {row['order_id']: row for row in result['order_proofs']}
        self.assertTrue(proof['o1']['history_event_eligible'])
        self.assertTrue(proof['o1']['approval_missing_or_invalid'])
        self.assertTrue(proof['clock']['window_quarantine'])
        self.assertFalse(proof['late']['window_quarantine'])

    def test_duplicates_empty_or_noncanonical_master_IDs_stop(self):
        for table, key in (('orders', 'order_id'), ('customers', 'customer_id')):
            for mutation in ('duplicate', 'empty', 'whitespace'):
                tables = fixture()
                if mutation == 'duplicate':
                    tables[table].append(copy.deepcopy(tables[table][0]))
                else:
                    tables[table][0][key] = '' if mutation == 'empty' else ' bad '
                with self.subTest(table=table, mutation=mutation), self.assertRaises(ValueError):
                    self.roster(tables)

    def test_every_unmapped_historical_order_stops_even_if_not_delivered(self):
        for status in ('delivered', 'canceled'):
            tables = fixture()
            tables['customers'] = []
            tables['orders'][0]['order_status'] = status
            with self.subTest(status=status), self.assertRaises(ValueError):
                self.roster(tables)

    def test_invalid_or_unlocatable_purchase_stops_and_raw_types_are_exact(self):
        for value in ('', 'not-a-clock', '2018-02-30 00:00:00', None, 1):
            tables = fixture()
            tables['orders'][0]['order_purchase_timestamp'] = value
            with self.subTest(value=value), self.assertRaises(ValueError):
                self.roster(tables)

    def test_canonical_UIDs_and_required_projection_fields_are_enforced(self):
        for value in ('', ' u1 ', None):
            tables = fixture()
            tables['customers'][0]['customer_unique_id'] = value
            with self.subTest(value=value), self.assertRaises(ValueError):
                self.roster(tables)
        tables = fixture()
        del tables['orders'][0]['order_status']
        with self.assertRaises(ValueError):
            self.roster(tables)

    def test_roster_is_order_independent_and_does_not_mutate_source_rows(self):
        tables = self.two_customers()
        before = copy.deepcopy(tables)
        expected = self.roster(tables)
        self.assertEqual(tables, before)
        tables['orders'].reverse()
        tables['customers'].reverse()
        self.assertEqual(expected, self.roster(tables))

    def test_success_parses_only_two_synthetic_sources_and_returns_six_fields(self):
        case = make_fixture(self.root, self.two_customers())
        before = {str(p): p.read_bytes() for p in self.root.rglob('*') if p.is_file()}
        blocked = AssertionError('No original builder or real descriptor is permitted')
        with patch.object(sources.build.builder, 'build_dataset', side_effect=blocked):
            result = self.load(case)
        self.assertEqual(set(result), {'dataset', 'evaluation_spec', 'customer_ids', 'order_ids', 'window_order_ids', 'snapshot'})
        self.assertEqual(result['customer_ids'], ['u1', 'u2'])
        self.assertEqual(result['dataset'], case['dataset'])
        self.assertEqual(before, {str(p): p.read_bytes() for p in self.root.rglob('*') if p.is_file()})

    def test_changed_snapshot_or_bool_type_stops_before_any_parser(self):
        case = make_fixture(self.root)
        for mutate in (lambda s: s['public_sources'].pop(), lambda s: s.update(format_version=True)):
            expected = copy.deepcopy(case['snapshot'])
            mutate(expected)
            with patch.object(sources, 'metadata_snapshot', side_effect=fixture_snapshot), \
                    patch.object(csv, 'DictReader', side_effect=AssertionError('Must stop before parser')):
                with self.assertRaisesRegex(ValueError, 'snapshot differs before parsing'):
                    sources.read_inputs(self.root, expected)

    def test_changed_raw_bytes_stop_before_bundle_or_source_parsing(self):
        case = make_fixture(self.root)
        path = self.root / sources.base.FILES['orders']
        path.write_bytes(path.read_bytes() + b'\n')
        with patch.object(sources.artifacts, 'read_bundle', side_effect=AssertionError('Must stop first')):
            with self.assertRaises(ValueError):
                self.load(case)

    def test_original_header_and_ragged_source_rows_are_rejected(self):
        case = make_fixture(self.root)
        path = self.root / sources.base.FILES['orders']
        original = path.read_bytes()
        for bad in (original.replace(b'order_status', b'wrong_status'), original + b'broken\n'):
            path.write_bytes(bad)
            case['snapshot'] = fixture_snapshot(self.root)
            with self.subTest(bad=bad[-20:]), self.assertRaises(ValueError):
                self.load(case)
        path.write_bytes(original)

    def test_coherently_reduced_dataset_cannot_replace_independent_full_source_roster(self):
        case = make_fixture(self.root, self.two_customers())
        reduced = synthetic_build(fixture())
        metadata_path = self.root / '.runtime/synthetic_source_metadata.json'
        metadata = sources.base.read_json(metadata_path)
        metadata['rows'] = {'customers.csv': 1, 'order_decisions.csv': 1}
        _write_json(metadata_path, metadata)
        case['snapshot'] = fixture_snapshot(self.root)
        with patch.object(sources.artifacts, 'read_bundle', return_value=reduced):
            with self.assertRaisesRegex(ValueError, 'customer IDs differ'):
                self.load(case)

    def test_same_ID_sets_cannot_hide_wrong_customer_mapping(self):
        case = make_fixture(self.root, self.two_customers())
        swapped = copy.deepcopy(case['tables'])
        swapped['customers'][0]['customer_unique_id'] = 'u2'
        swapped['customers'][1]['customer_unique_id'] = 'u1'
        dataset = synthetic_build(swapped)
        with patch.object(sources.artifacts, 'read_bundle', return_value=dataset):
            with self.assertRaisesRegex(ValueError, 'customer mappings differ'):
                self.load(case)

    def test_eligible_but_different_source_clock_is_not_accepted_as_same_ID_proof(self):
        case = make_fixture(self.root)
        changed = copy.deepcopy(case['tables'])
        changed['orders'][0]['order_delivered_customer_date'] = '2018-08-09 00:00:00'
        dataset = synthetic_build(changed)
        with patch.object(sources.artifacts, 'read_bundle', return_value=dataset):
            with self.assertRaisesRegex(ValueError, 'source proofs'):
                self.load(case)

    def test_private_row_types_and_duplicate_IDs_remain_strict(self):
        case = make_fixture(self.root)
        for mutate in (lambda d: d['customers'][0].update(frequency_orders=True),
                       lambda d: d['customers'].append(copy.deepcopy(d['customers'][0]))):
            dataset = copy.deepcopy(case['dataset'])
            mutate(dataset)
            with patch.object(sources.artifacts, 'read_bundle', return_value=dataset):
                with self.assertRaises(ValueError):
                    self.load(case)

    def test_input_bytes_changed_during_readback_stop_before_return(self):
        case = make_fixture(self.root)
        original = sources._source_projections
        def change_after_projection(root, headers):
            result = original(root, headers)
            path = root / sources.base.FILES['orders']
            path.write_bytes(path.read_bytes() + b'\n')
            return result
        with patch.object(sources, '_source_projections', side_effect=change_after_projection):
            with self.assertRaisesRegex(ValueError, 'changed during complete roster'):
                self.load(case)


class RFMSourceMetadataTests(unittest.TestCase):
    def setUp(self):
        self.fixture = prior_tests.RFMDescriptionVerificationTests()
        self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)
        self.fixture.verify()
        self.root = self.fixture.root

    def test_metadata_snapshot_binds_all_thirty_five_and_seven_private_inputs(self):
        result = sources.metadata_snapshot(self.root)
        self.assertEqual(len(result['public_sources']), 35)
        self.assertEqual(len(result['private_inputs']), 7)
        self.assertEqual(set(result['accepted_bundle']), set(sources.artifacts.FILES))
        self.assertEqual(len(result['metadata_checks']), 42)

    def test_metadata_only_never_calls_CSV_parser_builder_or_bundle_reader(self):
        blocked = AssertionError('No CSV or individual-value parsing')
        with patch.object(csv, 'reader', side_effect=blocked), \
                patch.object(csv, 'DictReader', side_effect=blocked), \
                patch.object(sources.base, 'read_tables', side_effect=blocked), \
                patch.object(sources.artifacts, 'read_bundle', side_effect=blocked), \
                patch.object(sources.build.builder, 'build_dataset', side_effect=blocked):
            result = sources.metadata_snapshot(self.root)
        self.assertEqual(result['format_version'], 1)

    def test_shortened_original_sources_cannot_be_rebound(self):
        path = self.root / sources.prior.SPEC
        payload = sources.base.read_json(path)
        payload['sources'].pop()
        path.write_bytes(sources.artifacts.json_bytes(payload))
        with self.assertRaises(ValueError):
            sources.metadata_snapshot(self.root)

    def test_changed_prior_guard_receipt_or_private_bundle_is_rejected(self):
        for relative in (sources.prior.GUARD, sources.prior.RECEIPT,
                         sources.build.PRIVATE + '/customers.csv'):
            path = self.root / relative
            original = path.read_bytes()
            path.write_bytes(original + b'\n')
            with self.subTest(relative=relative), self.assertRaises(ValueError):
                sources.metadata_snapshot(self.root)
            path.write_bytes(original)


if __name__ == '__main__':
    unittest.main()
