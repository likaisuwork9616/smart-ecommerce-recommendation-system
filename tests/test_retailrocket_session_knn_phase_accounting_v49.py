"""Pure numeric interval tests; no context, query, model decoder or worker."""
from copy import deepcopy
from math import fsum
import unittest

from scripts.retailrocket_session_knn_phase_accounting_v49 import partition
from scripts.retailrocket_session_knn_sources_v24 import summarize_events


def fixture():
    events = []

    def add(phase, start, end, parent=None, **metadata):
        event = dict(id=len(events), parent=parent, phase=phase, start_ns=round(start * 1e9),
                     end_ns=round(end * 1e9), completed=True, error_type=None, metadata=metadata)
        events.append(event)
        return event['id']

    def source(start, end, parent):
        check = add('checkpoint.check_sources', start, end, parent)
        verify = add('binding.verify_sources', start + .1, end - .1, check)
        add('binding.descriptor', start + .2, end - .2, verify,
            identity='synthetic-only', descriptor=dict(path='synthetic', bytes=1, sha256='0' * 64))

    def snapshot(start, end, parent):
        snap = add('snapshot.fingerprint', start, end, parent)
        width = end - start
        cursor = start
        for name, fraction in (('validation', .4), ('json', .2), ('utf8', .1),
                               ('release', .05), ('sha256', .1), ('release', .05)):
            stop = cursor + width * fraction
            add('snapshot.' + name, cursor, stop, snap)
            cursor = stop

    root = add('run.total', 0, 100)
    create = add('checkpoint.create', 0, 5, root)
    source(.5, 3.5, create)
    writer = add('checkpoint.writer_lifetime', 5, 85, root)
    acquire = add('checkpoint.writer_acquire', 5, 11, writer)
    source(6, 10, acquire)
    verifier = add('verifier.total', 11, 81, writer)
    setup = add('verifier.setup_envelope', 11, 53, verifier)
    load = add('context.load_context', 12, 52, setup)
    add('cache.identity', 12, 14, load)
    cold = add('cache.cold_build', 14, 44, load)
    add('cache.original_load_context', 24, 30, cold)
    add('cache.original_prepare_catalog', 30, 34, cold)
    snapshot(38, 43, cold)
    pre = add('cache.pre_use_digest', 44, 48, load)
    snapshot(44, 48, pre)
    proof = dict(build=dict(start_ns=15_000_000_000, end_ns=23_000_000_000, roots=2, completed=True), checks=[
        dict(root='config', start_ns=34_200_000_000, end_ns=35_200_000_000, completed=True, equal=True),
        dict(root='model', start_ns=35_200_000_000, end_ns=36_200_000_000, completed=True, equal=True)])
    add('cache.use', 49, 49, load, typed_reference=proof)
    add('context.prepare_catalog', 52, 53, setup)
    add('verifier.seal_consistent', 53, 54, verifier)
    guard = add('cache.final_guard', 72, 80, verifier)
    snapshot(73, 79, guard)
    add('run.ledger_proof', 86, 88, root)
    add('run.output_write', 89, 90, root)
    primary = dict(verification_seconds=8.0, append_excluding_commit_seconds=1.0, all_commit_seconds=3.0)
    accounting = dict(costs=dict(entry_seconds=99.75, primary_seconds=12.0, rank_seconds=7.0, **primary),
                      entry_exclusive_seconds=dict(tail_without_commit_seconds=2.0),
                      primary_parts_seconds=primary,
                      rank_stages_seconds=dict(sql_positive_overlaps=2.0, sql_selected_votes_and_accumulation=2.0,
                          neighbor_pool_sha=1.0, exact_neighbor_selection=.5, history_and_temp_setup=.2,
                          prediction_output=.5, top_ten_and_zero_fill=.3),
                      rank_unpartitioned_seconds=.5, verification_outside_rank_seconds=1.0)
    return events, accounting


def event(events, phase):
    return next(row for row in events if row['phase'] == phase)


class PartitionTests(unittest.TestCase):
    def test_nested_tree_conserves_entry_and_keeps_child_details_separate(self):
        events, accounting = fixture()
        result = partition(events, accounting, summarize_events(events))
        parts = result['parts_seconds']
        expected = dict(reference_build=8, late_config=1, late_model=1, cold_other=5, original_load=6,
            prepare_catalog=4, snapshot_cold=5, snapshot_pre_use=4, snapshot_final=6, identity=2,
            final_guard_other=2, source_verification=7, checkpoint_other=8, primary=12,
            tail_without_commit=2, verifier_other=6, setup_other=6, ledger_proof=2, output_write=1,
            run_other=12, signed_entry_bridge=-.25)
        self.assertEqual(parts, expected)
        self.assertEqual(fsum(parts.values()), 99.75)
        self.assertEqual(result['nonreference_seconds'], 91.75)
        self.assertEqual(result['snapshot_parts_seconds']['cold']['validation'], 2)
        self.assertEqual(result['snapshot_parts_seconds']['cold']['release'], .5)
        self.assertEqual(fsum(result['primary_parts_seconds'].values()), 12)
        self.assertEqual(fsum(result['rank_parts_seconds'].values()), 8)
        self.assertLessEqual(result['max_reconciliation_residual_seconds'], 1e-8)

    def test_signed_bridge_may_be_negative_zero_or_positive(self):
        for total in (99.75, 100, 100.25):
            events, accounting = fixture()
            accounting['costs']['entry_seconds'] = total
            with self.subTest(total=total):
                parts = partition(events, accounting)['parts_seconds']
                self.assertEqual(parts['signed_entry_bridge'], total - 100)
                self.assertEqual(fsum(parts.values()), total)

    def test_changed_summary_and_invalid_tree_are_rejected(self):
        events, accounting = fixture()
        summary = summarize_events(events)
        summary['root_wall_ns'] += 1
        with self.assertRaisesRegex(ValueError, 'Saved diagnostic differs'):
            partition(events, accounting, summary)
        event(events, 'cache.original_load_context')['end_ns'] = 31_000_000_000
        with self.assertRaisesRegex(ValueError, 'Sibling observations overlap'):
            partition(events, accounting)

    def test_passive_reference_overlap_with_child_or_cold_boundary_is_rejected(self):
        for start, end, message in ((23, 25, 'overlaps an observed cold child'),
                                     (13, 20, 'outside cold build'), (14, 45, 'outside cold build')):
            events, accounting = fixture()
            build = event(events, 'cache.use')['metadata']['typed_reference']['build']
            build.update(start_ns=start * 10**9, end_ns=end * 10**9)
            with self.subTest(start=start, end=end), self.assertRaisesRegex(ValueError, message):
                partition(events, accounting)

    def test_passive_late_overlap_order_and_original_boundary_are_rejected(self):
        for field, value, message in (('start_ns', 35_000_000_000, 'overlap or change order'),
                                      ('end_ns', 39_000_000_000, 'overlaps an observed cold child')):
            events, accounting = fixture()
            checks = event(events, 'cache.use')['metadata']['typed_reference']['checks']
            checks[1][field] = value
            with self.subTest(field=field), self.assertRaisesRegex(ValueError, message):
                partition(events, accounting)
        events, accounting = fixture()
        build = event(events, 'cache.use')['metadata']['typed_reference']['build']
        build.update(start_ns=36_300_000_000, end_ns=37_000_000_000)
        with self.assertRaisesRegex(ValueError, 'overlap or change order'):
            partition(events, accounting)

    def test_primary_and_tail_keep_seal_once_and_reject_impossible_subtraction(self):
        events, accounting = fixture()
        result = partition(events, accounting)['parts_seconds']
        self.assertNotIn('verifier.seal_consistent', result)
        self.assertEqual(result['primary'] + result['tail_without_commit'] + result['verifier_other'], 20)
        for tail, message in ((.5, 'must contain the original seal'), (9, 'Parts exceed enclosing interval')):
            changed = deepcopy(accounting)
            changed['entry_exclusive_seconds']['tail_without_commit_seconds'] = tail
            with self.subTest(tail=tail), self.assertRaisesRegex(ValueError, message):
                partition(events, changed)
        changed = deepcopy(accounting)
        changed['primary_parts_seconds']['verification_seconds'] += 1
        with self.assertRaisesRegex(ValueError, 'Primary subpart differs'):
            partition(events, changed)

    def test_unknown_phase_parent_and_nonfinite_cost_are_rejected(self):
        events, accounting = fixture()
        event(events, 'cache.identity')['phase'] = 'unobserved.new.phase'
        with self.assertRaisesRegex(ValueError, 'Unexpected cold-entry phase'):
            partition(events, accounting)
        for value in (float('nan'), float('inf'), -1, True):
            events, accounting = fixture()
            accounting['costs']['entry_seconds'] = value
            with self.subTest(value=value), self.assertRaisesRegex(ValueError, 'Finite nonnegative'):
                partition(events, accounting)

    def test_rank_details_are_nested_under_verification_and_reject_mismatch(self):
        events, accounting = fixture()
        result = partition(events, accounting)
        self.assertEqual(fsum(result['rank_parts_seconds'].values()),
                         result['primary_parts_seconds']['verification_seconds'])
        for field, message in (('rank_unpartitioned_seconds', 'Rank stages do not conserve'),
                               ('verification_outside_rank_seconds', 'outside-rank parts do not conserve')):
            changed = deepcopy(accounting)
            changed[field] += .1
            with self.subTest(field=field), self.assertRaisesRegex(ValueError, message):
                partition(events, changed)


if __name__ == '__main__':
    unittest.main()
