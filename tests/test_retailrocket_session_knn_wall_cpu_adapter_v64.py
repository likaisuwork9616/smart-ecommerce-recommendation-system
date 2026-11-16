"""Pure fake-reader/session guards; no real clock, model, SQL or entry execution."""
from copy import deepcopy
import hashlib
import unittest
from unittest.mock import patch

from scripts import retailrocket_session_knn_wall_cpu_adapter_v64 as adapter
from scripts.retailrocket_session_knn_wall_cpu_v63 import BoundaryError, BoundaryRecorder


def identities():
    ordinals = [dict(original_ordinal=2*i+1, key=[str(100+i), 1000+i, 2000+i])
                for i in range(48)]
    cohort = [dict(original_ordinal=row['original_ordinal'],
        key_sha256=hashlib.sha256(adapter.pair.dump(row['key']).encode()).hexdigest())
        for row in ordinals]
    return cohort, ordinals


def configuration():
    return {'fixed_validation': {'queries': 48}}


def completed_result(cohort):
    return dict(committed_prefix_rows=0, verified_subset_queries=48,
                queries=[dict(subset_ordinal=i, **row) for i, row in enumerate(cohort)])


def fake_recorder():
    calls = dict(wall=0, cpu=0, thread=0)

    def wall():
        value = 1_000_000 + calls['wall']*10
        calls['wall'] += 1
        return value

    def cpu():
        value = 1_000_000 + calls['cpu']*30
        calls['cpu'] += 1
        return value

    def thread():
        calls['thread'] += 1
        return 7

    return BoundaryRecorder(recording_id='synthetic-adapter', wall_clock=wall,
                            cpu_clock=cpu, thread_identity=thread), calls


def diagnostic_session():
    cohort, ordinals = identities()
    recorder, calls = fake_recorder()
    return adapter.BoundarySession('D', cohort, recorder=recorder), recorder, calls, ordinals


def fill_successful_trace(session, *, include_tail=True):
    # Original pair calls: setup 3, then 2 + 5 per query, finally tail 2.
    for _ in range(3):
        session.pair_tick()
    for _ in range(48):
        for _ in range(2):
            session.pair_tick()
        for _ in range(8):
            session.rank_tick()
        for _ in range(5):
            session.pair_tick()
    if include_tail:
        session.pair_tick()
        session.pair_tick()


class RaisingObserver:
    """Fail before the original verifier begins; no actual entry/SQL is run."""
    def __init__(self, error):
        self.error = error
        self.phases = []

    def span(self, phase):
        self.phases.append(phase)
        owner = self

        class Scope:
            def __enter__(self):
                raise owner.error

            def __exit__(self, *args):
                raise AssertionError('A failed __enter__ must not call __exit__')

        return Scope()


class BoundaryAdapterGuardTests(unittest.TestCase):
    def test_original_code_objects_required_for_predictor_verifier_and_entry(self):
        fake = lambda *args, **kwargs: None
        session, _, _, _ = diagnostic_session()
        with self.assertRaises(BoundaryError):
            adapter.bind_predictor(fake, lambda: 0.)
        with self.assertRaises(BoundaryError):
            adapter.bind_predictor(adapter.sql.predict, None)
        with self.assertRaises(BoundaryError):
            adapter.make_verifier(None, None, 'synthetic', {}, session=session, pair_function=fake)
        with self.assertRaises(BoundaryError):
            adapter.bind_entry(session=session, entry_function=fake)
        self.assertFalse(session.started)

    def test_bound_entry_rejects_wrong_route_and_real_typed_policy_before_any_clock(self):
        session, recorder, calls, _ = diagnostic_session()
        runner = adapter.bind_entry(session=session)

        class Pool:
            def __init__(self):
                self.invalidations = 0

            def invalidate(self):
                self.invalidations += 1

        pool = Pool()
        with self.assertRaises(BoundaryError):
            runner(None, {}, 'synthetic', 'R', None, pool=pool)
        self.assertEqual(pool.invalidations, 0)
        # S1 is valid, so the unchanged V39 require_policy must reject the
        # missing typed policy before forwarding to any original entry body.
        request = {'metadata': {'fingerprint_scheme': adapter.typed.s1.SCHEME}}
        with self.assertRaisesRegex(ValueError, 'Exact late typed source-reference policy'):
            runner(None, request, 'synthetic', 'C', None, pool=pool)
        self.assertEqual(pool.invalidations, 1)
        self.assertFalse(session.started)
        self.assertIsNone(session.report)
        self.assertEqual(recorder.boundaries, ())
        self.assertEqual(calls, dict(wall=0, cpu=0, thread=0))

    def test_begin_rejects_count_bool_float_and_identity_type_aliases(self):
        mutations = (
            lambda c, o: c['fixed_validation'].update(queries=48.0),
            lambda c, o: c['fixed_validation'].update(queries=True),
            lambda c, o: o[0].update(original_ordinal=True),
            lambda c, o: o[0].update(original_ordinal=1.0),
            lambda c, o: o.pop(),
        )
        for mutate in mutations:
            session, recorder, calls, ordinals = diagnostic_session()
            config = configuration()
            mutate(config, ordinals)
            with self.subTest(mutation=mutate), self.assertRaises((BoundaryError, ValueError)):
                session.begin(config, ordinals)
            self.assertFalse(session.started)
            self.assertEqual(recorder.boundaries, ())
            self.assertEqual(calls, dict(wall=0, cpu=0, thread=0))

    def test_begin_rejects_changed_key_original_ordinal_and_cohort_order(self):
        mutations = (
            lambda o: o[0]['key'].__setitem__(0, '999'),
            lambda o: o[0].update(original_ordinal=999),
            lambda o: o.reverse(),
        )
        for mutate in mutations:
            session, _, _, ordinals = diagnostic_session()
            mutate(ordinals)
            with self.subTest(mutation=mutate), self.assertRaises(BoundaryError):
                session.begin(configuration(), ordinals)
            self.assertFalse(session.started)

    def test_successful_725_fake_ticks_yield_exact_completed_shape_once(self):
        session, recorder, calls, ordinals = diagnostic_session()
        session.begin(configuration(), ordinals)
        fill_successful_trace(session)
        result = session.finish(completed=True, result=completed_result(session.cohort))
        self.assertTrue(result['completed'])
        self.assertEqual(result['diagnostics']['layout']['observed_marker_count'], 725)
        self.assertEqual(len(result['diagnostics']['analysis']['spans']), 578)
        self.assertEqual(len(recorder.boundaries), 725)
        self.assertEqual(calls, dict(wall=1450, cpu=725, thread=1450))
        before = dict(calls)
        with self.assertRaises(BoundaryError):
            session.begin(configuration(), ordinals)
        with self.assertRaises(BoundaryError):
            session.pair_tick()
        with self.assertRaises(BoundaryError):
            session.finish(completed=True, result=completed_result(session.cohort))
        self.assertEqual(calls, before)

    def test_tick_requires_active_session_and_exact_pair_rank_order(self):
        session, recorder, calls, ordinals = diagnostic_session()
        with self.assertRaises(BoundaryError):
            session.pair_tick()
        session.begin(configuration(), ordinals)
        with self.assertRaises(BoundaryError):
            session.rank_tick()
        self.assertEqual(calls, dict(wall=0, cpu=0, thread=0))
        # setup + query_start + rank_start; next point must be ranking_start.
        for _ in range(5):
            session.pair_tick()
        before = dict(calls)
        with self.assertRaises(BoundaryError):
            session.pair_tick()
        self.assertEqual(len(recorder.boundaries), 5)
        self.assertEqual(calls, before)

    def test_missing_tail_cannot_publish_complete_or_invent_boundaries(self):
        session, recorder, calls, ordinals = diagnostic_session()
        session.begin(configuration(), ordinals)
        fill_successful_trace(session, include_tail=False)
        before = dict(calls)
        with self.assertRaises(ValueError):
            session.finish(completed=True, result=completed_result(session.cohort))
        self.assertIsNone(session.report)
        self.assertEqual(len(recorder.boundaries), 723)
        self.assertEqual(calls, before)
        report = session.finish(completed=False, error=RuntimeError('synthetic tail fault'))
        self.assertFalse(report['completed'])
        self.assertIsNone(report['diagnostics']['analysis'])
        self.assertEqual(report['diagnostics']['layout']['spans'], [])
        self.assertEqual(len(recorder.boundaries), 723)

    def test_finish_rejects_boolean_float_counts_and_result_ordinal_aliases(self):
        mutations = (
            lambda r: r.update(committed_prefix_rows=False),
            lambda r: r.update(committed_prefix_rows=0.0),
            lambda r: r.update(verified_subset_queries=48.0),
            lambda r: r.update(verified_subset_queries=True),
            lambda r: r['queries'][0].update(original_ordinal=True),
            lambda r: r['queries'][0].update(original_ordinal=1.0),
            lambda r: r['queries'][0].update(subset_ordinal=False),
            lambda r: r['queries'][0].update(subset_ordinal=0.0),
        )
        for mutate in mutations:
            cohort, ordinals = identities()
            session = adapter.BoundarySession('O', cohort, legacy_clock=lambda: 1.)
            session.begin(configuration(), ordinals)
            result = completed_result(cohort)
            mutate(result)
            with self.subTest(mutation=mutate), self.assertRaises((BoundaryError, ValueError)):
                session.finish(completed=True, result=result)
            self.assertIsNone(session.report)

    def test_finish_rejects_missing_or_changed_output_identities_and_nonfresh_prefix(self):
        mutations = (
            lambda r: r['queries'].pop(),
            lambda r: r['queries'][0].update(key_sha256='0'*64),
            lambda r: r['queries'].reverse(),
            lambda r: r.update(committed_prefix_rows=1),
        )
        for mutate in mutations:
            cohort, ordinals = identities()
            session = adapter.BoundarySession('O', cohort, legacy_clock=lambda: 1.)
            session.begin(configuration(), ordinals)
            result = completed_result(cohort)
            mutate(result)
            with self.subTest(mutation=mutate), self.assertRaises((BoundaryError, ValueError)):
                session.finish(completed=True, result=result)
            self.assertIsNone(session.report)

    def test_incomplete_prefix_preserves_error_and_blocks_reuse_without_extra_reads(self):
        session, recorder, calls, ordinals = diagnostic_session()
        session.begin(configuration(), ordinals)
        for _ in range(4):
            session.pair_tick()
        error = LookupError('synthetic body fault')
        before = dict(calls)
        result = session.finish(completed=False, error=error)
        self.assertEqual(result['error_type'], 'LookupError')
        self.assertEqual(result['diagnostics']['layout']['status'], 'incomplete')
        self.assertEqual(result['diagnostics']['layout']['observed_marker_count'], 4)
        self.assertIsNone(result['diagnostics']['analysis'])
        self.assertEqual(len(recorder.boundaries), 4)
        with self.assertRaises(BoundaryError):
            session.begin(configuration(), ordinals)
        with self.assertRaises(BoundaryError):
            session.pair_tick()
        self.assertEqual(calls, before)

    def test_original_mode_uses_only_legacy_clock_and_has_no_diagnostic_state(self):
        cohort, ordinals = identities()
        values, calls = iter((1., 2., 3.)), []

        def legacy():
            calls.append('legacy')
            return next(values)

        session = adapter.BoundarySession('O', cohort, legacy_clock=legacy)
        session.begin(configuration(), ordinals)
        self.assertEqual((session.pair_tick(), session.rank_tick(), session.pair_tick()), (1., 2., 3.))
        self.assertEqual(calls, ['legacy']*3)
        self.assertIsNone(session.recorder)
        self.assertIsNone(session._markers)
        self.assertIsNone(session._expected)
        result = session.finish(completed=True, result=completed_result(cohort))
        self.assertIsNone(result['diagnostics'])

    def test_mode_requires_fresh_recorder_or_legacy_reader_without_mix(self):
        cohort, _ = identities()
        recorder, calls = fake_recorder()
        for mode, kwargs in (('D', {}), ('D', {'recorder': recorder, 'legacy_clock': lambda: 1.}),
                             ('O', {}), ('O', {'recorder': recorder, 'legacy_clock': lambda: 1.}),
                             ('other', {})):
            with self.subTest(mode=mode, kwargs=kwargs), self.assertRaises(BoundaryError):
                adapter.BoundarySession(mode, cohort, **kwargs)
        self.assertEqual(calls, dict(wall=0, cpu=0, thread=0))
        recorder.capture('already-used')
        with self.assertRaises(BoundaryError):
            adapter.BoundarySession('D', cohort, recorder=recorder)

    def test_verifier_preserves_original_exception_if_failure_recording_also_raises(self):
        session, recorder, calls, ordinals = diagnostic_session()
        original = LookupError('synthetic observer entry fault')
        observer = RaisingObserver(original)
        verifier = adapter.make_verifier(observer, object(), 'synthetic', {}, session=session)
        with patch.object(session, 'finish', side_effect=RuntimeError('secondary diagnostic failure')):
            with self.assertRaises(LookupError) as caught:
                verifier(None, None, configuration(), None, None, None, ordinals)
        self.assertIs(caught.exception, original)
        self.assertEqual(session.secondary_error_type, 'RuntimeError')
        self.assertEqual(observer.phases, ['verifier.total'])
        self.assertEqual(recorder.boundaries, ())
        self.assertEqual(calls, dict(wall=0, cpu=0, thread=0))

    def test_verifier_early_original_exception_yields_empty_incomplete_report(self):
        session, recorder, _, ordinals = diagnostic_session()
        original = RuntimeError('synthetic observer failure')
        observer = RaisingObserver(original)
        verifier = adapter.make_verifier(observer, object(), 'synthetic', {}, session=session)
        with self.assertRaises(RuntimeError) as caught:
            verifier(None, None, configuration(), None, None, None, ordinals)
        self.assertIs(caught.exception, original)
        self.assertFalse(session.report['completed'])
        self.assertEqual(session.report['error_type'], 'RuntimeError')
        self.assertEqual(session.report['diagnostics']['layout']['observed_marker_count'], 0)
        self.assertEqual(recorder.boundaries, ())

    def test_constructor_copies_cohort_and_finish_completion_must_be_bool(self):
        cohort, ordinals = identities()
        original = deepcopy(cohort)
        session = adapter.BoundarySession('O', cohort, legacy_clock=lambda: 1.)
        cohort[0]['original_ordinal'] = 999
        self.assertEqual(session.cohort, original)
        session.begin(configuration(), ordinals)
        for completed in (1, 0, 1.0, None):
            with self.subTest(completed=completed), self.assertRaises(BoundaryError):
                session.finish(completed=completed, result=completed_result(original))
        self.assertIsNone(session.report)


if __name__ == '__main__':
    unittest.main()
