"""Exercise publication gates using invented counts and synthetic receipts only."""
from copy import deepcopy
import json
from pathlib import Path
import tempfile
import unittest

from scripts import summarize_k1_august_readback_v1 as public


H = '1' * 64
ROSTER = '2' * 64
C1_SRC = 'shop-mysql-runtime/retailrocket_cooccurrence_paired_v1/queries.jsonl'


def save(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value), encoding='utf-8')
    return public.load(path)[1]


def fake_fold(n):
    arms, hits = {}, {}
    for arm in public.ARMS:
        k = min(n, 1) if arm == 'K1' else 0
        hits[arm] = k
        arms[arm] = dict(queries=n, visitors=min(n, 1), recommended_unique_items=k, candidate_union_items=n,
                         metrics={m: k/n if n else None for m in public.MEASURES})
    contrasts = {'K1_minus_' + a: {'delta_metrics': dict(arms['K1']['metrics'])} for a in ('C1', 'P0', 'D1')}
    return ({'queries': n, 'visitors': min(n, 1), 'arms': arms, 'comparisons': contrasts},
            {'queries': n, 'hits': hits, 'K1_vs_C1': dict(both=0, k1_only=min(n, 1), c1_only=0, neither=max(0, n-1))})


class PublicationTests(unittest.TestCase):
    def setUp(self):
        work = tempfile.TemporaryDirectory()
        self.addCleanup(work.cleanup)
        self.root = Path(work.name)
        self.out = self.root / 'private'
        self.out.mkdir()
        n = 4
        keys = dict(queries=n, visitors=1, target_occurrences=5, reachable_target_occurrences=4,
                    all_targets_reachable_queries=3)
        train = dict(train_sessions=3, distinct_session_item_memberships=5)
        fit = dict(train, fit_id=H)
        config = dict(fixed_validation=dict(keys, support_floor_queries=50), train_cost_audit=train, train_window_ms=[0, 10],
                      validation_window_ms=[10, 20])
        primary = ['K1/' + name for name in ('queries.jsonl', 'fit_audit.json', 'sessions.jsonl',
                                             'postings.jsonl', 'train_sessions.jsonl')]
        external = ['data/baskets.csv', 'data/catalog.csv', 'C1/train_sessions.jsonl',
                    'C1/support.csv', 'P0/item_counts.csv', C1_SRC]
        bindings = lambda paths: [dict(path=p, sha256=H, bytes=100) for p in paths]
        direct = [dict(r, role=role) for r, role in zip(bindings([*external, 'C1/bootstrap.jsonl']),
                                                       ('dataset', 'dataset', 'C1', 'C1', 'P0', 'C1', 'C1'), strict=True)]
        spec_hash = save(self.root / 'spec.json', dict(configuration=config, direct_input_bindings=direct))
        specification = dict(path='spec.json', sha256=spec_hash, bytes=(self.root / 'spec.json').stat().st_size)
        frozen_primary = bindings([*primary, 'K1/aggregate.json', 'K1/bootstrap.jsonl'])
        attempt = dict(specification=specification, preservation=dict(execution_artifacts=frozen_primary),
                       primary_fit_audit_unaccepted=fit)
        attempt_hash = save(self.root / public.ATTEMPT, attempt)
        gate = dict(status='passed', primary_sha256={Path(r['path']).name: H for r in frozen_primary},
                    entry_spec_sha256=spec_hash, attempt_sha256=attempt_hash, prepared={'reserved_test': 'locked'},
                    preserved_files=len(frozen_primary), engine_sha256=H)
        before = save(self.path('sources_before'), gate)
        save(self.path('sources_after'), dict(gate, elapsed_seconds=10))
        identity = dict(status='passed', queries=n, queries_sha256=H, roster_sha256=ROSTER)
        coh = save(self.path('cohort'), dict({**identity, **keys}, paired_streams_eof=True, test_ranked_queries=0))
        source = {path: H for path in [*primary[1:], *external[:-1]]}
        pred = save(self.path('predictions'), dict(identity, query_eof_verified=True, fit_audit=fit, source_sha256=source))
        sql = dict(status='passed', queries_scanned=n, queries_sha256=H, queries_sql_checked=n,
                   ordinals_zero_based=list(range(n)), test_ranked_queries=0, fit_audit=fit,
                   index_counts=dict(train_sessions=3, session_item_memberships=5),
                   source_gate_sha256=before, verified_predictions_sha256=H, database_sha256=H)
        save(self.path('sql_witness'), sql)
        ag, hits = {}, {}
        for key, count in [('main', n), ('conditional', 3)]:
            ag[key], hits[key] = fake_fold(count)
        ag['slices'], hits['slices'] = {}, {}
        for field, groups in public.GROUPS.items():
            ag['slices'][field], hits['slices'][field] = {}, {}
            for idx, group in enumerate(groups):
                fold, h = fake_fold(n if idx == 0 else 0)
                ag['slices'][field][group] = dict(fold, support='descriptive_only' if fold['queries'] else 'empty')
                hits['slices'][field][group] = h
        ag.update(roster_sha256=ROSTER, uncertainty=dict(replicates=2000, visitors=1, mean_delta=0.25,
                                                         interval=[0.1, 0.4], reason=None), support_floor_queries=50)
        ag['diagnostics'] = {k: {'0': n} for k in ('history_size', 'unknown_seeds', 'eligible_neighbors',
                             'current_session_excluded', 'selected_neighbor_count', 'boundary_ties_excluded',
                             'positive_candidates', 'zero_fill_slots')}
        ag['diagnostics']['fallback_reason'] = {'positive_evidence': n}
        ag['fallback_cold_cross_tabs'] = {'[false,true,true,"all_positive"]': n}
        retained = {primary[0], primary[1], 'K1/aggregate.json', 'K1/bootstrap.jsonl',
                    'data/catalog.csv', 'P0/item_counts.csv', 'C1/support.csv', 'C1/bootstrap.jsonl'}
        inputs = [r for r in [*frozen_primary, *direct] if r['path'] in retained]
        save(self.path('aggregate'), dict(identity, aggregate=ag, paired_hits=hits,
                                          prerequisite_sha256={'k1_cohort.json': coh, 'k1_predictions.json': pred},
                                          bootstrap_replicates=2000, inputs=[specification, *inputs]))
        slot = dict(baseline='C1', role='2015-08 exposed development validation', roster_sha256=ROSTER,
                    counts=dict(queries=n, c1_hits=0, recency_hits=2, gained=2, lost=0), net_extra_hit_queries=2,
                    source_sha256={C1_SRC: H}, metrics={'c1': dict(ndcg=0., hit_rate=0., mrr=0.),
                                                       'recency': dict(ndcg=0.5, hit_rate=0.5, mrr=0.4)})
        save(self.root / public.SLOT, slot)
        for stage in public.CORE:
            self.resource(stage)

    def path(self, stage):
        return self.out / ('k1_' + stage + '.json')

    def resource(self, stage, status='passed'):
        save(self.out / ('resource_' + stage + '.json'), dict(
            stage=stage, status=status, started_utc='2026-11-19T06:00:00+00:00', ended_utc='2026-11-19T06:01:00+00:00',
            deadline_utc='2026-11-19T09:00:00+00:00', samples=2, sampled_peak_tree_rss_bytes=100,
            sampled_peak_run_disk_bytes=100))

    def test_no_dense_core_is_complete_and_ignores_row_data(self):
        raw, _ = public.load(self.path('aggregate'))
        raw['unrequested_private_rows'] = ['private payload']
        save(self.path('aggregate'), raw)
        summary = public.summarize(self.out, self.root)
        self.assertEqual(summary['verification']['dense_cross_check']['status'], 'not_run')
        self.assertEqual(summary['results']['recency_slot_reference']['net_hit_queries_K1_minus_recency'], -1)
        self.assertNotIn('private payload', json.dumps(summary))
        self.assertEqual(summary['results']['primary_ndcg_K1_minus_C1']['replicates'], 2000)

    def test_optional_dense_needs_exit_or_explicit_partial_status(self):
        (self.out / 'dense.started').touch()
        with self.assertRaises(FileNotFoundError):
            public.summarize(self.out, self.root)
        self.resource('dense', 'incomplete')
        save(self.out / 'k1_dense.progress.json', dict(queries=2))
        summary = public.summarize(self.out, self.root)
        self.assertEqual(summary['verification']['dense_cross_check']['last_reported_queries'], 2)
        self.resource('dense')
        complete = dict(status='passed', queries=4, queries_sha256=H, roster_sha256=ROSTER, fit_id=H,
                        train_sessions=3, train_memberships=5, session_query_comparisons=12, catalog_size=9,
                        catalog_query_comparisons=36, membership_intersections_checked=20,
                        causal_candidate_scores_checked=30, vote_memberships_scanned=20,
                        voting_modes={'dense_uint32': 4}, query_eof_verified=True, test_ranked_queries=0)
        save(self.path('dense'), complete)
        summary = public.summarize(self.out, self.root)
        self.assertEqual(summary['verification']['dense_cross_check']['status'], 'passed')
        complete['membership_intersections_checked'] -= 1
        save(self.path('dense'), complete)
        with self.assertRaisesRegex(ValueError, 'dense full coverage'):
            public.summarize(self.out, self.root)

    def test_rejects_evidence_substitutions_and_missing_exit(self):
        cases = [
            (self.path('cohort'), 'roster_sha256', H), (self.path('cohort'), 'paired_streams_eof', False),
            (self.path('predictions'), 'status', 'engineering_prefix_only'),
            (self.path('sql_witness'), 'queries_sql_checked', 3),
            (self.path('aggregate'), 'bootstrap_replicates', 1999),
            (self.path('aggregate'), 'inputs', []),
            (self.path('sources_after'), 'attempt_sha256', ROSTER),
            (self.out / 'resource_predictions.json', 'status', 'incomplete'),
            (self.root / public.SLOT, 'roster_sha256', H),
        ]
        for path, field, value in cases:
            old, _ = public.load(path)
            changed = deepcopy(old)
            changed[field] = value
            save(path, changed)
            with self.subTest(field=field), self.assertRaises(ValueError):
                public.summarize(self.out, self.root)
            save(path, old)


if __name__ == '__main__':
    unittest.main()
