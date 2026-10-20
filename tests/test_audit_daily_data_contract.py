from pathlib import Path
import tempfile
import unittest

import pandas as pd

from scripts import audit_daily_data_contract as audit


class DailyDataContractTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(dir=Path(__file__).resolve().parents[1] / '.runtime')
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)

    def test_strict_json_rejects_duplicate_keys_and_nan(self):
        for value in ('{"a":1,"a":2}', '{"a":NaN}', '{"a":Infinity}'):
            with self.subTest(value=value):
                path = self.root / 'bad.json'
                path.write_text(value, encoding='utf8')
                with self.assertRaises(ValueError):
                    audit.read_json(path)

    def test_immutable_report_is_byte_stable_and_rejects_replacement(self):
        path = self.root / 'out.json'
        audit.immutable_write(path, {'status': 'pending_data'})
        original = path.read_bytes()
        audit.immutable_write(path, {'status': 'pending_data'})
        self.assertEqual(path.read_bytes(), original)
        with self.assertRaises(ValueError):
            audit.immutable_write(path, {'status': 'passed'})
        self.assertEqual(path.read_bytes(), original)
        with self.assertRaises(ValueError):
            audit.immutable_write(self.root / 'nan.json', {'bad': float('nan')})

    def test_guard_detects_changed_source_and_duplicate_path(self):
        path = self.root / 'source.txt'
        path.write_text('frozen', encoding='utf8')
        item = audit.descriptor(path, self.root)
        self.assertEqual(audit.verify_sources([item], self.root), 1)
        with self.assertRaises(ValueError):
            audit.verify_sources([item, item], self.root)
        path.write_text('changed', encoding='utf8')
        with self.assertRaises(ValueError):
            audit.verify_sources([item], self.root)

    def raw(self):
        return pd.DataFrame({'order_id': ['a', 'b', 'c', 'd'],
                             'order_purchase_timestamp': ['2018-02-01 01:00:00'] * 4,
                             'order_approved_at': ['2018-02-01 01:00:00', '2018-02-02 00:00:00',
                                                   None, 'invalid']})

    def test_day_boundaries_missing_invalid_and_reversed_are_separate(self):
        raw = self.raw()
        raw.loc[0, 'order_purchase_timestamp'] = '2018-02-01 02:00:00'
        selected, quality = audit.day_roster(raw, '2018-02-01')
        self.assertEqual(selected['order_id'].tolist(), ['a'])
        self.assertEqual(quality['order_approved_at'], {'missing': 1, 'invalid_nonmissing': 1})
        self.assertEqual(quality['approval_before_purchase'], 1)

    def test_raw_duplicate_and_missing_order_ids_rejected(self):
        for value in ('a', None):
            raw = self.raw()
            raw.loc[1, 'order_id'] = value
            with self.assertRaises(ValueError):
                audit.day_roster(raw, '2018-02-01')

    def fixtures(self):
        roster = pd.DataFrame({'order_id': ['a', 'b', 'c'],
                               'prediction_time': pd.to_datetime(['2018-02-01 01:00:00'] * 3)})
        ledger = pd.DataFrame({'order_id': ['a', 'b'], 'prediction_time': ['2018-02-01 01:00:00'] * 2,
                               'fold': ['2018-02'] * 2, 'model_version': ['2018-02'] * 2,
                               'role': ['evaluation'] * 2, 'candidate': ['base'] * 2,
                               'seed': [11] * 2, 'colsample_bytree': [0.8] * 2})
        schema = {'versions': ['base08'], 'seeds': [11],
                  'version_source': {'base08': {'candidate': 'base', 'colsample_bytree': 0.8}}}
        selected = {'day': '2018-02-01', 'full_day_rows': 2}
        return roster, ledger, schema, selected

    def test_roster_verification_tracks_raw_gap_without_reading_scores(self):
        runs, missing = audit.verify_roster_runs(*self.fixtures())
        self.assertEqual(len(runs), 1)
        self.assertEqual(runs[0]['raw_export_rows_without_frozen_score'], 1)
        self.assertEqual(missing['order_id'].tolist(), ['c'])

    def test_bad_run_identity_time_metadata_or_denominator_rejected(self):
        for column, value in [('order_id', 'a'), ('order_id', 'unknown'),
                              ('prediction_time', '2018-02-01 02:00:00'),
                              ('candidate', 'other'), ('seed', 29), ('colsample_bytree', 1.0)]:
            with self.subTest(column=column, value=value):
                roster, ledger, schema, selected = self.fixtures()
                ledger.loc[1, column] = value
                with self.assertRaises(ValueError):
                    audit.verify_roster_runs(roster, ledger, schema, selected)

    def test_same_length_different_research_roster_between_runs_rejected(self):
        roster, ledger, schema, selected = self.fixtures()
        other = ledger.copy()
        other['seed'] = 29
        other.loc[1, 'order_id'] = 'c'
        schema['seeds'] = [11, 29]
        with self.assertRaises(ValueError):
            audit.verify_roster_runs(roster, pd.concat([ledger, other]), schema, selected)


if __name__ == '__main__':
    unittest.main()
