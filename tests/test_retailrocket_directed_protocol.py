"""Mutation guards and synthetic filesystem acceptance; no D1 model/oracle claim.

The production metadata is read-only. Every synthetic byte, partial freeze and
lock fixture stays below the ignored shop verification namespace.
"""
import contextlib
from copy import deepcopy
import io
import json
from pathlib import Path
import unittest
from unittest.mock import patch
import uuid

from scripts import freeze_retailrocket_directed_v1 as entry
from scripts.retailrocket_directed_protocol import validate


class ProtocolGuards(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.inputs = [entry.read(path) for path in entry.INPUTS]

    def test_accepted_contract_and_references_are_consistent(self):
        checks = validate(*deepcopy(self.inputs))
        self.assertEqual(len(checks), len(set(checks)))
        self.assertIn('required_full_queries', checks)
        self.assertIn('same_draw_recipe.seed', checks)
        self.assertIn('primary_source_urls', checks)

    def reject_mutation(self, input_number, keys, replacement):
        values = deepcopy(self.inputs)
        target = values[input_number]
        for key in keys[:-1]:
            target = target[key]
        target[keys[-1]] = replacement
        with self.assertRaises(ValueError):
            validate(*values)

    def test_missing_required_section_fails_closed(self):
        values = deepcopy(self.inputs)
        del values[0]['reserved_test']
        with self.assertRaises(ValueError):
            validate(*values)

    def test_nonfinite_tolerance_is_rejected(self):
        self.reject_mutation(0, ['evaluation', 'float_absolute_tolerance'], float('nan'))

    def test_reference_query_file_must_be_unique(self):
        values = deepcopy(self.inputs)
        duplicate = next(r for r in values[4]['files'] if r['path'].endswith('/queries.jsonl'))
        values[4]['files'].append(deepcopy(duplicate))
        with self.assertRaises(ValueError):
            validate(*values)

    def test_cold_reference_does_not_claim_zero_coverage_or_D1_metrics(self):
        text = self.inputs[0]['slices_and_diagnostics']['cold_reference']
        self.assertIn('coverage is not asserted zero', text)
        self.assertIn('not a prediction of D1', text)
        self.assertIs(self.inputs[0]['slices_and_diagnostics']['D1_metrics_known'], False)

    def test_missing_edge_keeps_independent_positive_P0_tiebreak(self):
        text = self.inputs[0]['ranking']['unknown_candidate']
        self.assertIn('independently look up the frozen P0 count', text)
        self.assertIn('positive P0 count', text)
        self.assertIn('must remain unchanged for tie/fill', text)

    def test_future_cost_scan_excludes_validation_test_item_decoding(self):
        text = self.inputs[0]['resources_and_next_entry']['train_only_preflight']
        self.assertIn('decode item arrays only for train baskets', text)
        self.assertIn('never validation/test item arrays or targets', text)


# Each mutation models a substantive change that would need a new protocol,
# rather than testing an arbitrary number of checks or a model implementation.
MUTATIONS = [
    ('train_validation_leakage', 0, ['comparison', 'fit_roles'], ['train', 'validation']),
    ('future_fit_cutoff', 0, ['comparison', 'fit_end_exclusive_utc'], '2015-08-25T00:00:00Z'),
    ('online_statistics_leakage', 0, ['comparison', 'statistics_update_during_evaluation'], True),
    ('test_role_leakage', 0, ['comparison', 'evaluation_roles'], ['validation', 'test']),
    ('multiple_candidate_search', 0, ['comparison', 'challenger_count'], 2),
    ('hyperparameter_search', 0, ['comparison', 'hyperparameter_search'], True),
    ('reference_refit', 0, ['comparison', 'reference_refits_or_rerankings'], 1),
    ('fit_id_changed', 0, ['reference_identity', 'C1_fit_id'], 'another-fit'),
    ('support_bytes_changed', 0, ['reference_identity', 'C1_support', 'sha256'], '0' * 64),
    ('source_data_changed', 0, ['fit', 'source'], 'replacement.csv'),
    ('cross_role_endpoint', 0, ['fit', 'both_endpoint_roles'], ['train', 'validation']),
    ('removed_basket_bridge', 0, ['fit', 'bridge_after_filtering'], True),
    ('original_index_gap', 0, ['fit', 'original_index_difference'], 2),
    ('noncausal_timestamps', 0, ['fit', 'strictly_later_timestamp'], False),
    ('cross_visitor_session', 0, ['fit', 'same_session_required'], False),
    ('invented_same_ms_order', 0, ['fit', 'within_basket_order'], True),
    ('labelled_query_only_fit', 0, ['fit', 'labelled_query_filter'], True),
    ('future_session_length_leakage', 0, ['fit', 'future_session_end_or_total_length_used'], True),
    ('occurrence_counts_replace_binary_sessions', 0, ['fit', 'repeat_within_session_counted_again'], True),
    ('self_edges_enabled', 0, ['fit', 'self_edges'], True),
    ('outgoing_row_normalization', 0, ['fit', 'row_sum_normalization'], True),
    ('shared_S_drops_singletons', 0, ['fit', 'shared_support'], 'Use outgoing-count keys only'),
    ('support_threshold_tuning', 0, ['fit', 'minimum_directed_support'], 2),
    ('neighbor_pruning', 0, ['fit', 'neighbor_top_L'], 100),
    ('session_cap', 0, ['fit', 'session_cap'], 100),
    ('history_cap', 0, ['fit', 'history_cap'], 10),
    ('last_basket_replaces_full_H', 0, ['history', 'set'], 'Current basket only'),
    ('lifetime_history', 0, ['history', 'visitor_lifetime_history'], True),
    ('current_basket_removed', 0, ['history', 'current_basket_included'], False),
    ('missing_join_silently_falls_back', 0, ['history', 'missing_or_empty_current_join'], 'Fallback and continue'),
    ('cold_candidate_removed', 0, ['ranking', 'catalog'], 'Only positive train items'),
    ('previously_seen_removed', 0, ['ranking', 'previously_seen_removed'], True),
    ('negative_sampled_candidates', 0, ['ranking', 'negative_sampling'], True),
    ('target_injected', 0, ['ranking', 'target_injection'], True),
    ('float_tie_replaces_exact_rational', 0, ['ranking', 'arithmetic'], 'float32 with tolerance'),
    ('P0_truncated_top10_fill', 0, ['ranking', 'partial_fallback'], 'Append P0 top10'),
    ('D1_missing_edge_zeroes_positive_P0_count', 0, ['ranking', 'unknown_candidate'], 'If D1 edge missing, P0 count is zero'),
    ('empty_catalog_dropped', 0, ['ranking', 'empty_catalog'], 'Drop query'),
    ('inner_join_denominator', 0, ['evaluation', 'missing_extra_duplicate_policy'], 'Inner join'),
    ('reachable_only_primary_denominator', 0, ['evaluation', 'primary_estimand'], 'mean over reachable targets only'),
    ('full_query_count_changed', 0, ['fixed_validation', 'queries'], 161211),
    ('full_target_denominator_changed', 0, ['fixed_validation', 'target_occurrences'], 161264),
    ('catalog_union_changed', 0, ['fixed_validation', 'candidate_union_items'], 198946),
    ('P0_second_primary', 0, ['evaluation', 'secondary_comparison'], 'D1-P0 confirmatory primary contrast'),
    ('P0_interval_enabled', 0, ['uncertainty', 'D1_P0_interval'], True),
    ('two_control_superiority', 0, ['uncertainty', 'multiple_comparison_policy'], 'Require both controls significantly beaten'),
    ('slice_inference_enabled', 0, ['uncertainty', 'secondary_or_slice_intervals'], True),
    ('old_C1_delta_reused', 0, ['uncertainty', 'audit_reuse'], 'Copy accepted C1-P0 deltas and interval'),
    ('iid_query_bootstrap', 0, ['uncertainty', 'method'], 'iid query bootstrap'),
    ('visitor_mean_estimand', 0, ['uncertainty', 'reduction'], 'Average visitor means'),
    ('bootstrap_draw_seed_changed', 0, ['uncertainty', 'seed'], 43),
    ('bootstrap_replicates_changed', 0, ['uncertainty', 'replicates'], 1000),
    ('cold_definition_changes_to_unreachable', 0, ['slices_and_diagnostics', 'shared_membership'], 'Cold = unreachable catalog target'),
    ('cold_coverage_claimed_zero', 0, ['slices_and_diagnostics', 'cold_reference'], 'All cold metrics and coverage are zero'),
    ('small_groups_removed', 0, ['slices_and_diagnostics', 'small_group_rule'], 'Drop groups below floor'),
    ('D1_performance_claimed_known', 0, ['slices_and_diagnostics', 'D1_metrics_known'], True),
    ('validation_exposure_erased', 0, ['evaluation', 'source_exposure'], 'Pristine unseen validation'),
    ('future_cost_decodes_validation_items', 0, ['resources_and_next_entry', 'train_only_preflight'], 'Decode all roles then filter'),
    ('raw_cost_bound_overclaim', 0, ['resources_and_next_entry', 'counts_to_reconcile'], 'Raw work bounded by twice C1 counts'),
    ('resource_limit_relaxed', 0, ['resources_and_next_entry', 'limits', 'maximum_process_RSS_bytes'], 16 * 1024**3),
    ('test_enabled', 0, ['reserved_test', 'D1_test_authorized'], True),
    ('old_gate_reused', 0, ['reserved_test', 'reuse_P0_or_C1_gate'], True),
    ('new_fit_claimed_this_round', 0, ['scope_this_round', 'real_D1_fits'], 1),
    ('boolean_not_integer_counter', 0, ['scope_this_round', 'new_P0_fits'], False),
    ('prior_test_was_consumed', 2, ['scope', 'reserved_test_ranked_queries'], 1),
    ('prior_fit_not_accepted', 4, ['status'], 'partial'),
    ('prior_acceptance_scope_disagrees', 5, ['scope', 'validation_queries'], 1),
    ('parent_window_changed', 1, ['time_roles', 'train'], ['2015-05-04T00:00:00Z', '2015-08-25T00:00:00Z']),
    ('parent_bootstrap_recipe_changed', 7, ['uncertainty', 'seed'], 43),
    ('source_not_primary_paper', 6, ['primary_sources', 0, 'url'], 'https://example.org/blog'),
    ('candidate_exposure_erased', 6, ['selection', 'validation_already_exposed'], False),
    ('EASE_estimate_claims_measured_cost', 6, ['dense_EASE_structural_estimate', 'kind'], 'measured_peak'),
]


def mutation_test(input_number, keys, replacement):
    def test(self):
        self.reject_mutation(input_number, keys, replacement)
    return test


for name, number, keys, replacement in MUTATIONS:
    setattr(ProtocolGuards, 'test_reject_' + name, mutation_test(number, keys, replacement))


class EntrySafety(unittest.TestCase):
    def setUp(self):
        base = entry.ROOT / entry.VERIFY / 'synthetic'
        base.mkdir(parents=True, exist_ok=True)
        # Inherit the shop ACL; Windows tempfile's private ACL can exclude the
        # restricted worker token even though the path stays inside shop.
        self.scratch = (base / ('metadata-' + uuid.uuid4().hex)).resolve()
        self.scratch.mkdir()
        self.assertTrue(self.scratch.is_relative_to(base.resolve()))
        self.root_patch = patch.object(entry, 'ROOT', self.scratch)
        self.root_patch.start()
        self.addCleanup(self.root_patch.stop)
        self.make_gates()

    def make_gates(self):
        for index, name in enumerate(entry.GATES):
            if index < 2:
                gate = {'status': ('locked_at_specification_freeze', 'locked_at_development_entry_freeze')[index],
                        'test_ranking_started': False, 'logical_tests_consumed': 0}
            else:
                gate = {'state': 'locked', 'C1_test_authorized': False, 'logical_test_runs_consumed_this_round': 0}
            entry.write_new(name, gate)

    def replace_json(self, relative, value):
        entry.within(relative).write_text(json.dumps(value), encoding='utf-8')

    def make_binary(self, relative, content=b'\xff\xfe\x00synthetic'):
        path = entry.within(relative)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content)
        return entry.descriptor(relative)

    def make_reference_bundle(self):
        payload = self.make_binary('raw/frozen.csv')
        dependency = self.make_binary('raw/external.jsonl')
        mutable = self.make_binary('README.md', b'archived index')
        mutable['live_role'] = 'mutable_context_snapshot'
        payload['live_role'] = 'frozen_research_source'
        manifest_path = 'archive/manifest.json'
        manifest = {'files': [payload, mutable], 'external_dependencies': [dependency]}
        entry.write_new(manifest_path, manifest)
        archive = self.make_binary('archive/release.zip', b'opaque synthetic archive bytes')
        entry.write_new(entry.RELEASE, {'status': 'C1_P0_research_handoff_evidence_archived_and_verified',
                                      'sources': manifest['files'], 'external_dependencies': manifest['external_dependencies'],
                                      'archive_manifest': entry.descriptor(manifest_path)})
        entry.write_new(entry.RELEASE_GUARD, {'receipt': entry.descriptor(entry.RELEASE),
                                            'archive': archive, 'manifest': entry.descriptor(manifest_path)})
        for guard in entry.REFERENCE_GUARDS:
            entry.write_new(guard, {'sources': [dependency], 'outputs': [payload]})
        self.replace_index = entry.within('README.md')
        self.replace_index.write_text('legitimate later live index', encoding='utf-8')
        return payload, dependency, archive, manifest_path

    def test_binary_hash_never_decodes_real_row_formats(self):
        for name in ('synthetic.csv', 'synthetic.jsonl'):
            record = self.make_binary(name)
            entry.check([record])
            with self.assertRaisesRegex(ValueError, 'Metadata JSON only'):
                entry.read(name)

    def test_unsafe_paths_rejected(self):
        for name in ('../outside.json', '/absolute.json', 'C:/outside.json', 'a\\b.json', 'a/./b', 'a//b'):
            with self.subTest(path=name), self.assertRaises(ValueError):
                entry.within(name)

    def test_write_new_refuses_overwrite(self):
        entry.write_new('result.json', {'accepted': True})
        with self.assertRaises(FileExistsError):
            entry.write_new('result.json', {'accepted': False})
        self.assertEqual(entry.read('result.json'), {'accepted': True})

    def test_boolean_logical_counter_is_not_zero(self):
        gate = entry.read(entry.GATES[0]); gate['logical_tests_consumed'] = False
        self.replace_json(entry.GATES[0], gate)
        with self.assertRaises(ValueError): entry.check_locked_scope()

    def test_future_validation_namespace_allowed_only_on_historical_verify(self):
        entry.within(entry.EXECUTION).mkdir(parents=True)
        entry.check_locked_scope(freeze_only=False)
        with self.assertRaises(ValueError): entry.check_locked_scope(freeze_only=True)

    def test_partial_freeze_is_preserved_and_refuses_replay(self):
        with patch.object(entry, 'consistency', side_effect=ValueError('synthetic fault')):
            with self.assertRaises(ValueError): entry.freeze()
        self.assertTrue(entry.within(entry.PRIVATE + '/started.json').is_file())
        self.assertEqual(entry.read(entry.PRIVATE + '/failure.json')['status'], 'partial_specification_preserved_no_replay')
        with self.assertRaises(FileExistsError): entry.freeze()
        with self.assertRaises(ValueError): entry.verify()

    def test_completed_reentry_only_verifies(self):
        entry.write_new(entry.PRIVATE + '/output_guard.json', {'synthetic': True})
        with patch.object(entry, 'verify', return_value={'verified': True}) as verify:
            self.assertEqual(entry.freeze(), {'verified': True})
            verify.assert_called_once_with()

    def test_collects_full_payload_dependencies_and_package_descriptors(self):
        payload, dependency, archive, manifest_path = self.make_reference_bundle()
        with patch.object(entry, 'NEW_SOURCES', []):
            records = entry.collect_sources()
        names = {r['path'] for r in records}
        for name in (payload['path'], dependency['path'], archive['path'], manifest_path, entry.RELEASE, entry.RELEASE_GUARD,
                     *entry.REFERENCE_GUARDS, *entry.GATES):
            self.assertIn(name, names)
        self.assertNotIn('README.md', names)

    def test_tampered_frozen_payload_fails_collection(self):
        payload, _, _, _ = self.make_reference_bundle()
        entry.within(payload['path']).write_bytes(b'tampered')
        with patch.object(entry, 'NEW_SOURCES', []), self.assertRaises(ValueError): entry.collect_sources()

    def test_tampered_external_dependency_fails_collection(self):
        _, dependency, _, _ = self.make_reference_bundle()
        entry.within(dependency['path']).write_bytes(b'tampered')
        with patch.object(entry, 'NEW_SOURCES', []), self.assertRaises(ValueError): entry.collect_sources()

    def test_tampered_archive_fails_collection(self):
        _, _, archive, _ = self.make_reference_bundle()
        entry.within(archive['path']).write_bytes(b'tampered')
        with patch.object(entry, 'NEW_SOURCES', []), self.assertRaises(ValueError): entry.collect_sources()

    def test_conflicting_old_guard_identity_fails_collection(self):
        self.make_reference_bundle()
        old_guard = entry.read(entry.REFERENCE_GUARDS[0]); old_guard['sources'][0]['sha256'] = '0' * 64
        self.replace_json(entry.REFERENCE_GUARDS[0], old_guard)
        with patch.object(entry, 'NEW_SOURCES', []), self.assertRaisesRegex(ValueError, 'Conflicting'):
            entry.collect_sources()

    def test_future_validation_verify_labels_scope_as_historical(self):
        gate = {'state': 'locked', 'D1_test_authorized': False, 'logical_test_runs_consumed_this_round': 0}
        historical = {'real_D1_fits': 0, 'specification_only': True}
        entry.write_new(entry.PRIVATE + '/initial_locked_scope.json', gate)
        entry.write_new(entry.ACCEPT, {'scope_at_freeze': historical})
        records = [entry.descriptor(p) for p in (entry.PRIVATE + '/initial_locked_scope.json', entry.ACCEPT)]
        entry.write_new(entry.PRIVATE + '/output_guard.json', {'sources': [], 'outputs': records})
        entry.within(entry.EXECUTION).mkdir(parents=True)
        with patch.object(entry, 'consistency', return_value=['synthetic_metadata_check']):
            result = entry.verify()
        self.assertEqual(result['scope_at_freeze'], historical)
        self.assertIs(result['current_D1_validation_namespace_exists'], True)
        self.assertIs(result['research_recomputed'], False)
        self.assertNotIn('real_D1_fits', result)

    def test_cli_has_no_model_validation_or_test_entry(self):
        with contextlib.redirect_stderr(io.StringIO()):
            for arg in ('--fit', '--run-validation', '--bootstrap', '--test', '--final-refit'):
                with self.subTest(arg=arg), self.assertRaises(SystemExit): entry.parser().parse_args([arg])
        self.assertTrue(entry.parser().parse_args(['--verify']).verify)


def gate_unlock_test(index):
    def test(self):
        path = entry.GATES[index]; gate = entry.read(path)
        gate['test_ranking_started' if index < 2 else 'C1_test_authorized'] = True
        self.replace_json(path, gate)
        with self.assertRaises(ValueError): entry.check_locked_scope()
    return test


def forbidden_test_namespace_test(relative):
    def test(self):
        self.make_binary(relative)
        with self.assertRaises(ValueError): entry.check_locked_scope(freeze_only=False)
    return test


def partial_artifact_test(relative):
    def test(self):
        self.make_binary(relative)
        with self.assertRaises(FileExistsError): entry.ensure_new()
    return test


for index in range(len(entry.GATES)):
    setattr(EntrySafety, 'test_reference_gate_' + str(index) + '_cannot_unlock', gate_unlock_test(index))
for index, name in enumerate(entry.ABSENT_TEST):
    setattr(EntrySafety, 'test_forbidden_test_namespace_' + str(index), forbidden_test_namespace_test(name))
for index, name in enumerate((entry.PRIVATE + '/partial.json', entry.SPEC, entry.ACCEPT, entry.VERIFY + '/tests.log')):
    setattr(EntrySafety, 'test_partial_artifact_' + str(index) + '_blocks_new_freeze', partial_artifact_test(name))


if __name__ == '__main__':
    unittest.main()
