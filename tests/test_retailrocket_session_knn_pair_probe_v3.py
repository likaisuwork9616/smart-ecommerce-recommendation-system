"""Synthetic full-EOF frozen subset pairing and private checkpoint cost tests."""
from copy import deepcopy
from datetime import datetime, timedelta, timezone
import csv
import hashlib
import json
from pathlib import Path
import sqlite3
import unittest

from scripts import retailrocket_session_knn_pair_probe_v3 as pair
from scripts import retailrocket_session_knn_checkpoint_v2 as cp
from scripts import retailrocket_session_knn_io as synthetic
from scripts import retailrocket_session_knn_readback as v1
from scripts import retailrocket_session_knn_sql_v2 as sql
from tests.test_retailrocket_session_knn_validation import make_fixture


class PairedProbeTests(unittest.TestCase):
    def setUp(self):
        self.root, self.paths, self.config = make_fixture()
        self.primary = self.root / 'paired_original_primary'
        self.primary.mkdir()
        synthetic.build(self.primary, self.paths, self.config)
        self.database = self.root / 'sealed_model.sqlite'
        db = sqlite3.connect(self.database)
        try:
            _, support, audit = v1.reconstruct(db, self.primary, self.paths['dataset'],
                                               self.paths['C1'], self.config, lambda: None)
            sql.build_index(db)
            db.commit()
        finally:
            db.close()
        self.model = {'fit_audit': audit, 'support': support}
        self.original_rows = list(v1.rows(self.primary / 'queries.jsonl'))
        self.folder = self.root / 'paired_engineering'
        self.folder.mkdir()
        self.probes = [{'key': self.original_rows[index]['key']} for index in (6, 0, 3)]
        self.freeze()

    def freeze(self):
        (self.folder / 'frozen_probes.json').write_text(json.dumps({
            'population': {'total_queries': 7, 'complete': True}, 'probes': self.probes}), encoding='utf-8')

    def extract(self):
        return pair.extract_samples(self.folder, self.primary, self.paths, self.config, self.probes)

    def measure(self, extracted, watch=lambda: None):
        return pair.measure_paired(self.folder, extracted, self.database, self.model,
            (datetime.now(timezone.utc) + timedelta(minutes=10)).isoformat(), 600, watch)

    def rewrite_json(self, path, values):
        path.write_text(''.join(json.dumps(row) + '\n' for row in values), encoding='utf-8')

    def test_full_eof_subset_ordinals_and_complete_four_arm_checkpoint(self):
        before = hashlib.sha256(self.database.read_bytes()).hexdigest()
        extracted = self.extract()
        self.assertEqual([row['original_ordinal'] for row in extracted['ordinals']], [0, 3, 6])
        self.assertEqual(extracted['selected_queries'], 3)
        self.assertEqual(extracted['config']['fixed_validation']['queries'], 3)
        self.assertEqual(self.config['fixed_validation']['queries'], 7)
        self.assertEqual(set(extracted['scan_counts'].values()), {7})
        self.assertEqual(len(extracted['scan_counts']), 7)
        selected = list(v1.rows(Path(extracted['sample_primary']) / 'queries.jsonl'))
        self.assertEqual(selected, [self.original_rows[index] for index in (0, 3, 6)])
        result = self.measure(extracted)
        self.assertEqual(result['verified_subset_queries'], 3)
        self.assertEqual(result['checkpoint_records'], 3)
        self.assertEqual(result['checkpoint_chunks'], 1)
        self.assertEqual([row['original_ordinal'] for row in result['queries']], [0, 3, 6])
        self.assertTrue(all(row['verification_seconds'] > 0 for row in result['queries']))
        self.assertTrue(all(row['checkpoint_append_seconds'] > 0 for row in result['queries']))
        self.assertFalse(result['formal_acceptance'])
        self.assertFalse(result['full_validation_accepted'])
        self.assertFalse(result['global_or_bootstrap_executed'])
        checkpoint = Path(result['checkpoint_folder'])
        self.assertTrue((checkpoint / 'stages/reconstruction.json').exists())
        self.assertTrue((checkpoint / 'stages/queries.json').exists())
        self.assertFalse((checkpoint / 'candidate.json').exists())
        self.assertFalse((checkpoint / 'acceptance.json').exists())
        self.assertEqual(hashlib.sha256(self.database.read_bytes()).hexdigest(), before)
        self.assertTrue(result['database_copy_seconds'] > 0)
        self.assertEqual(result['database_copy_bytes'], self.database.stat().st_size)
        self.assertEqual(result['temp_store'], 'MEMORY')
        self.assertEqual(cp.read(checkpoint.parent / 'paired_measurement.json'), result)

    def test_unfrozen_or_changed_probe_roster_is_rejected_before_extraction(self):
        path = self.folder / 'frozen_probes.json'
        path.unlink()
        with self.assertRaisesRegex(ValueError, 'Frozen probe roster'):
            self.extract()
        self.assertFalse((self.folder / 'paired_samples').exists())
        self.freeze()
        changed = deepcopy(self.probes)
        changed[0]['key'][0] = '9999'
        with self.assertRaises(ValueError):
            pair.extract_samples(self.folder, self.primary, self.paths, self.config, changed)
        self.assertFalse((self.folder / 'paired_samples').exists())

    def test_duplicate_probe_keys_are_rejected(self):
        self.probes = [self.probes[0], self.probes[0]]
        self.freeze()
        with self.assertRaisesRegex(ValueError, 'Duplicate frozen'):
            self.extract()

    def test_every_json_control_full_eof_count_is_required(self):
        for arm, base in [('K1', self.primary), ('C1', self.paths['C1']), ('D1', self.paths['D1'])]:
            with self.subTest(arm=arm):
                path = base / 'queries.jsonl'
                original = path.read_bytes()
                values = list(v1.rows(path))
                self.rewrite_json(path, values[:-1])
                folder = self.root / ('missing_' + arm)
                folder.mkdir()
                (folder / 'frozen_probes.json').write_bytes((self.folder / 'frozen_probes.json').read_bytes())
                with self.assertRaisesRegex(ValueError, 'EOF count differs'):
                    pair.extract_samples(folder, self.primary, self.paths, self.config, self.probes)
                path.write_bytes(original)

    def test_extra_control_and_selected_ordinal_key_mismatch_are_rejected(self):
        path = self.primary / 'queries.jsonl'
        original = path.read_bytes()
        values = list(v1.rows(path))
        extra = deepcopy(values[-1]); extra['key'] = ['999999', 900000000, 900000001]
        self.rewrite_json(path, [*values, extra])
        with self.assertRaisesRegex(ValueError, 'EOF count differs'):
            self.extract()
        path.write_bytes(original)

    def test_selected_key_at_wrong_ordinal_is_rejected(self):
        path = self.paths['D1'] / 'queries.jsonl'
        values = list(v1.rows(path))
        values[0]['key'][2] += 1
        self.rewrite_json(path, values)
        with self.assertRaises(ValueError):
            self.extract()

    def test_p0_csv_eof_count_is_required(self):
        path = self.paths['P0'] / 'query_metrics.csv'
        with path.open(encoding='utf-8', newline='') as stream:
            reader = csv.DictReader(stream); headers = reader.fieldnames; values = list(reader)
        with path.open('w', encoding='utf-8', newline='') as stream:
            writer = csv.DictWriter(stream, fieldnames=headers); writer.writeheader(); writer.writerows(values[:-1])
        with self.assertRaisesRegex(ValueError, 'P0 original paired stream EOF'):
            self.extract()

    def test_selected_metric_and_nested_neighbor_corruption_fail_semantic_pairing(self):
        for fault in ('metric', 'neighbor'):
            with self.subTest(fault=fault):
                path = self.primary / 'queries.jsonl'
                original = path.read_bytes()
                values = list(v1.rows(path))
                if fault == 'metric':
                    values[0]['terms']['K1']['ndcg'] += .1
                else:
                    values[0]['predictions']['K1']['selected_neighbors'][0]['union'] += 1
                self.rewrite_json(path, values)
                folder = self.root / ('corrupt_' + fault)
                folder.mkdir()
                (folder / 'frozen_probes.json').write_bytes((self.folder / 'frozen_probes.json').read_bytes())
                extracted = pair.extract_samples(folder, self.primary, self.paths, self.config, self.probes)
                with self.assertRaises(ValueError):
                    pair.measure_paired(folder, extracted, self.database, self.model,
                        (datetime.now(timezone.utc) + timedelta(minutes=10)).isoformat(), 600)
                self.assertFalse(list(Path(extracted['sample_root']).rglob('candidate.json')))
                self.assertFalse(list(Path(extracted['sample_root']).rglob('acceptance.json')))
                path.write_bytes(original)

    def test_subset_tamper_after_extract_is_rejected_before_measurement(self):
        extracted = self.extract()
        path = Path(extracted['sample_primary']) / 'queries.jsonl'
        path.write_bytes(path.read_bytes().replace(b'"history"', b'"histoRy"', 1))
        with self.assertRaises(ValueError):
            self.measure(extracted)
        self.assertFalse((Path(extracted['sample_root']) / 'measurement').exists())

    def test_source_database_with_journal_is_rejected(self):
        extracted = self.extract()
        Path(str(self.database) + '-wal').touch()
        with self.assertRaisesRegex(ValueError, 'Unsealed source database journal'):
            self.measure(extracted)

    def test_expired_deadline_or_watch_abort_never_publishes_acceptance(self):
        extracted = self.extract()
        with self.assertRaises(TimeoutError):
            pair.measure_paired(self.folder, extracted, self.database, self.model,
                (datetime.now(timezone.utc) - timedelta(seconds=1)).isoformat(), 60)
        def abort():
            raise RuntimeError('synthetic external stop')
        with self.assertRaisesRegex(RuntimeError, 'synthetic external stop'):
            self.measure(extracted, abort)
        self.assertFalse((Path(extracted['sample_root']) / 'measurement').exists())

    def test_nonvalidation_target_is_not_json_decoded(self):
        # The fixture already puts poison target/items in forbidden roles.
        extracted = self.extract()
        self.assertEqual(extracted['original_validation_queries'], 7)
        self.assertEqual(self.measure(extracted)['verified_subset_queries'], 3)


if __name__ == '__main__':
    unittest.main()
