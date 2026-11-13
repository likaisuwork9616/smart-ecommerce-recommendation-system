"""Test offline paired accounting without invoking any benchmark."""
from contextlib import redirect_stderr
from copy import deepcopy
import hashlib
from io import StringIO
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from scripts import analyze_retailrocket_session_knn_phases_v49 as analysis


def rows():
    result = {}
    for item in analysis.v47.cold.SCHEDULE:
        parts = dict(reference_build=1.0, context_load=10.0, other=3.0, signed_entry_bridge=-0.1)
        result[item['label']] = dict(entry_seconds=sum(parts.values()), parts_seconds=parts,
            snapshot_parts_seconds={role: dict(validation=0.2, other=0.1) for role in ('cold', 'pre_use', 'final')},
            primary_parts_seconds=dict(verification=1.0, append=0.1, commit=0.05),
            rank_parts_seconds=dict(sql=0.5, remaining=0.5))
    return result


class OfflineSummaryTests(unittest.TestCase):
    def test_signed_pairs_keep_offsets_regressions_and_exclude_warmups(self):
        runs = rows()
        extras = (2, -3, 0, 4, -1, 1)
        for index, extra in enumerate(extras, 1):
            row = runs[f'pair_{index}_C']
            row['parts_seconds']['reference_build'] -= 0.5
            row['parts_seconds']['context_load'] += extra + 0.5
            row['entry_seconds'] = sum(row['parts_seconds'].values())
        runs['warm_C']['parts_seconds']['other'] += 1000
        runs['warm_C']['entry_seconds'] += 1000
        value = analysis.summarize_pairs(runs, analysis.v47.cold.SCHEDULE)
        self.assertEqual(value['slower_pairs'], [1, 4, 6])
        self.assertAlmostEqual(value['formal']['entry_extra_seconds']['sum'], 3)
        self.assertAlmostEqual(value['formal']['nonreference_extra_seconds']['sum'], 6)
        self.assertAlmostEqual(value['formal']['parts_extra_seconds']['reference_build']['sum'], -3)
        self.assertAlmostEqual(value['slower_pairs_only']['entry_extra_seconds']['sum'], 7)
        self.assertEqual(value['warmups']['C'], runs['warm_C'])
        self.assertEqual(value['pairs'][0]['largest_positive_nonreference_parts'][0]['part'], 'context_load')

    def test_no_regressions_is_explicit_and_ties_are_not_slowdowns(self):
        value = analysis.summarize_pairs(rows(), analysis.v47.cold.SCHEDULE)
        self.assertEqual(value['slower_pairs'], [])
        self.assertIsNone(value['slower_pairs_only'])

    def test_rejects_changed_schedule_missing_rows_keys_and_nonconservation(self):
        schedule = deepcopy(analysis.v47.cold.SCHEDULE)
        schedule.reverse()
        with self.assertRaisesRegex(ValueError, 'original schedule'):
            analysis.summarize_pairs(rows(), schedule)
        runs = rows()
        del runs['warm_C']
        with self.assertRaisesRegex(ValueError, 'All 14'):
            analysis.summarize_pairs(runs, analysis.v47.cold.SCHEDULE)
        runs = rows()
        runs['pair_1_C']['parts_seconds']['unaccounted'] = 1
        with self.assertRaisesRegex(ValueError, 'keys differ'):
            analysis.summarize_pairs(runs, analysis.v47.cold.SCHEDULE)
        runs = rows()
        runs['pair_1_C']['entry_seconds'] += 1
        with self.assertRaisesRegex(ValueError, 'conserve'):
            analysis.summarize_pairs(runs, analysis.v47.cold.SCHEDULE)

    def test_sealed_event_reader_rejects_changed_or_unlisted_bytes(self):
        with TemporaryDirectory(prefix='knn-v49-reader-', dir=analysis.v48.PRIVATE) as folder:
            path = Path(folder) / 'events.json'
            data = b'[]\n'
            path.write_bytes(data)
            key = path.relative_to(analysis.ROOT).as_posix()
            record = dict(path=key, bytes=len(data), sha256=hashlib.sha256(data).hexdigest())
            self.assertEqual(analysis.sealed_json(path, {key: record}), ([], record))
            with self.assertRaisesRegex(ValueError, 'outside'):
                analysis.sealed_json(path, {})
            path.write_bytes(b'{}\n')
            with self.assertRaisesRegex(ValueError, 'bytes differ'):
                analysis.sealed_json(path, {key: record})

    def test_cli_has_no_measure_mode(self):
        with patch('sys.argv', ['analysis', '--measure']), redirect_stderr(StringIO()), \
                patch.object(analysis.v48.entry, 'exclusive') as entry:
            with self.assertRaises(SystemExit) as error:
                analysis.main()
            self.assertEqual(error.exception.code, 2)
            entry.assert_not_called()


if __name__ == '__main__':
    unittest.main()
