"""V20 observational proxies over frozen V4 ranking and V6 checkpoint bytecode.

No SQL, fetch strategy, ranking, checkpoint operation or fault boundary changes.
Private per-query events retain raw clocks; public summaries contain aggregates.
"""
from collections import Counter
from types import FunctionType, SimpleNamespace
from time import perf_counter, perf_counter_ns, thread_time_ns, get_clock_info
from pathlib import Path
import json
import math

from scripts import retailrocket_session_knn_pair_v4 as pair
from scripts import retailrocket_session_knn_sql_v4 as v4
from scripts import retailrocket_session_knn_checkpoint_v2 as checkpoint
from scripts.retailrocket_session_knn_detailed_cost_v6 import DetailedTimedStore
from scripts.retailrocket_session_knn_cost_rollup_v17 import _stats


OVERLAP_SQL = (
    'SELECT membership.v,membership.s,COUNT(*),sizes.n '
    'FROM temp.k1_v4_history AS query '
    'CROSS JOIN main.m AS membership INDEXED BY k1_v2_posting '
    'ON membership.i=query.i '
    'LEFT JOIN main.k1_v2_sizes AS sizes '
    'ON sizes.v=membership.v AND sizes.s=membership.s '
    'GROUP BY membership.v,membership.s')
RANK_PHASES = ('history_and_temp_setup', 'sql_positive_overlaps', 'neighbor_pool_sha',
               'exact_neighbor_selection', 'sql_selected_votes_and_accumulation',
               'top_ten_and_zero_fill', 'prediction_output')
APPEND_PHASES = ('budget_check', 'guards_and_key', 'frame_encode', 'payload_open',
                 'payload_write', 'pending_and_trigger', 'nested_flush')


def clock_metadata():
    return {name: {field: getattr(get_clock_info(name), field) for field in
                  ('implementation', 'monotonic', 'adjustable', 'resolution')}
            for name in ('perf_counter', 'thread_time')}


def _clone(function, **globals_override):
    result = FunctionType(function.__code__, dict(function.__globals__, **globals_override),
                          function.__name__, function.__defaults__, function.__closure__)
    result.__kwdefaults__ = function.__kwdefaults__
    return result


def _stamp():
    return perf_counter_ns(), thread_time_ns()


def _span(start, end):
    wall, cpu = end[0]-start[0], end[1]-start[1]
    if wall < 0 or cpu < 0:
        raise ValueError('Diagnostic monotonic or thread CPU clock moved backwards')
    return {'wall_ns': wall, 'thread_cpu_ns': cpu, 'wall_minus_thread_cpu_ns': wall-cpu}


def _zero():
    return {'wall_ns': 0, 'thread_cpu_ns': 0, 'wall_minus_thread_cpu_ns': 0}


def _add(target, source):
    for name in target:
        target[name] += source[name]


class _ClockTap:
    """Keep the original float wall return; observe CPU at each existing clock call."""
    def __init__(self):
        self.samples = []

    def __call__(self):
        wall = perf_counter()
        cpu = thread_time_ns()
        self.samples.append({'wall_seconds': wall, 'thread_cpu_ns': cpu})
        return wall


class _OverlapCursor:
    def __init__(self, cursor, event):
        self.cursor, self.event = cursor, event

    def __iter__(self):
        return self

    def __next__(self):
        terminal = False
        start = _stamp()
        try:
            row = next(self.cursor)
        except StopIteration:
            terminal = True
            raise
        finally:
            duration = _span(start, _stamp())
            self.event['fetch_calls'] += 1
            _add(self.event['fetch'], duration)
            if terminal:
                self.event['eof_calls'] += 1
                self.event['terminal_fetch'] = duration
        self.event['returned_rows'] += 1
        self.event['intersection_sum'] += row[2]
        return row


class _ConnectionProxy:
    def __init__(self, connection, event):
        self.connection, self.event = connection, event

    def __getattr__(self, name):
        return getattr(self.connection, name)

    def execute(self, sql, *args, **kwargs):
        if sql != OVERLAP_SQL:
            return self.connection.execute(sql, *args, **kwargs)
        self.event['execute_calls'] += 1
        if self.event['execute_calls'] != 1:
            raise ValueError('One exact unchanged overlap statement is required per query')
        start = _stamp()
        try:
            cursor = self.connection.execute(sql, *args, **kwargs)
        finally:
            self.event['execute'] = _span(start, _stamp())
        return _OverlapCursor(cursor, self.event)


def make_predictor(profile_rows):
    if not isinstance(profile_rows, list):
        raise ValueError('Diagnostic predictions require a private event list')
    def predict(db, support, fit_id, counts, catalog, time, history, current,
                watch=lambda: None, *, workload=None, timings=None):
        work = {} if workload is None else workload
        times = {} if timings is None else timings
        tap = _ClockTap()
        event = {'subset_ordinal': len(profile_rows), 'completed': False,
                 'execute_calls': 0, 'fetch_calls': 0, 'eof_calls': 0,
                 'returned_rows': 0, 'intersection_sum': 0,
                 'execute': _zero(), 'fetch': _zero(), 'terminal_fetch': None,
                 'clock_samples': tap.samples}
        original = _clone(v4.predict, perf_counter=tap)
        try:
            result = original(_ConnectionProxy(db, event), support, fit_id, counts, catalog,
                              time, history, current, watch, workload=work, timings=times)
            event['current_session_excluded'] = result['current_session_excluded']
            event['eligible_neighbors'] = result['eligible_neighbors']
            event['completed'] = True
            return result
        finally:
            profile_rows.append(event)
    return predict


def make_verifier(mode, profile_rows=None):
    """Return a verifier with a call-local SQL binding; never patch module globals."""
    if mode == 'R':
        if profile_rows is not None:
            raise ValueError('Reference mode has no extra diagnostic observers')
        return pair.verify_selected
    if mode != 'D':
        raise ValueError('Expected fixed reference R or diagnostic D mode')
    predictor = make_predictor(profile_rows)
    return _clone(pair.verify_selected, sql=SimpleNamespace(predict=predictor, prepare_catalog=v4.prepare_catalog))


class DiagnosticTimedStore(DetailedTimedStore):
    """Observe active appends; setup/tail retain the original V6 behavior and timers."""
    def __init__(self, *args, **kwargs):
        self.append_diagnostics = []
        self._active_append_diagnostic = None
        self._active_budget_diagnostic = None
        super().__init__(*args, **kwargs)

    def append_verified(self, ordinal, key, payload):
        wrapper_started = _stamp()
        if self._active_append_diagnostic is not None:
            raise ValueError('Nested append diagnostic context')
        tap = _ClockTap()
        event = {'subset_ordinal': ordinal, 'completed': False,
                 'clock_samples': tap.samples, 'budget_checks': []}
        self._active_append_diagnostic = event
        original = _clone(DetailedTimedStore.append_verified, perf_counter=tap)
        try:
            result = original(self, ordinal, key, payload)
            event['completed'] = True
            return result
        finally:
            self.append_diagnostics.append(event)
            self._active_append_diagnostic = None
            event['wrapper_total'] = _span(wrapper_started, _stamp())

    def check_budget(self, persist=False):
        parent = self._active_append_diagnostic
        if parent is None:
            return super().check_budget(persist=persist)
        if self._active_budget_diagnostic is not None:
            raise ValueError('Nested budget diagnostic context')
        context, ordinal, stage = self._budget_context
        event = {'context': context, 'subset_ordinal': ordinal, 'stage': stage,
                 'persist': persist, 'completed': False, 'reads': [], 'publications': []}
        def observed_read(path):
            if Path(path) != self.folder/'budget.json':
                raise ValueError('The frozen budget checker read an unexpected path')
            read_event = {'completed': False}
            event['reads'].append(read_event)
            start = _stamp()
            try:
                text = Path(path).read_text(encoding='utf-8')
            finally:
                read_event['read_text'] = _span(start, _stamp())
            read_event['text_characters'] = len(text)
            start = _stamp()
            try:
                value = json.loads(text, parse_constant=checkpoint._invalid_constant)
            finally:
                read_event['json_parse'] = _span(start, _stamp())
            read_event['completed'] = True
            return value
        original = _clone(checkpoint.CheckpointStore.check_budget, read=observed_read)
        self._active_budget_diagnostic = event
        start = _stamp()
        try:
            result = original(self, persist=persist)
            event['completed'] = True
            return result
        finally:
            event['total'] = _span(start, _stamp())
            parent['budget_checks'].append(event)
            self._active_budget_diagnostic = None

    def _atomic(self, name, value, replace=False):
        parent = self._active_budget_diagnostic
        if parent is None or name != 'budget.json':
            return super()._atomic(name, value, replace=replace)
        event = {'completed': False, 'context': self._budget_context[0], 'replace': replace}
        start = _stamp()
        try:
            result = super()._atomic(name, value, replace=replace)
            event['completed'] = True
            return result
        finally:
            event['total'] = _span(start, _stamp())
            parent['publications'].append(event)


def _seconds(wall, cpu_ns):
    if type(wall) not in (int, float) or not math.isfinite(wall) or wall < 0 or type(cpu_ns) is not int or cpu_ns < 0:
        raise ValueError('Invalid elapsed wall or thread CPU observation')
    cpu = cpu_ns / 1e9
    return {'wall_seconds': wall, 'thread_cpu_seconds': cpu, 'wall_minus_thread_cpu_seconds': wall-cpu}


def _raw_span(value):
    if (set(value) != {'wall_ns', 'thread_cpu_ns', 'wall_minus_thread_cpu_ns'}
            or any(type(v) is not int for v in value.values())
            or min(value['wall_ns'], value['thread_cpu_ns']) < 0
            or value['wall_minus_thread_cpu_ns'] != value['wall_ns']-value['thread_cpu_ns']):
        raise ValueError('Invalid raw clock span; signed wall-minus-CPU must be retained')
    return _seconds(value['wall_ns']/1e9, value['thread_cpu_ns'])


def _close(left, right):
    return math.isclose(left, right, rel_tol=1e-10, abs_tol=1e-12)


def _sum_spans(parts):
    return {key: math.fsum(part[key] for part in parts) for key in
            ('wall_seconds', 'thread_cpu_seconds', 'wall_minus_thread_cpu_seconds')}


def _residual(total, parts):
    used = _sum_spans(parts)
    cpu_ns = round(total['thread_cpu_seconds']*1e9)-sum(round(part['thread_cpu_seconds']*1e9) for part in parts)
    wall = total['wall_seconds']-used['wall_seconds']
    if wall < 0 or cpu_ns < 0:
        raise ValueError('Diagnostic child intervals exceed their enclosing clocks')
    # Do not clamp signed wall-minus-thread-CPU, including clock quantization.
    return _seconds(wall, cpu_ns)


def _clock_parts(samples, phases, expected_walls, *, final=False):
    required = len(phases)+1+int(final)
    if len(samples) != required:
        raise ValueError('The frozen bytecode did not produce its expected clock boundaries')
    for sample in samples:
        if (set(sample) != {'wall_seconds', 'thread_cpu_ns'}
                or type(sample['wall_seconds']) not in (int, float) or not math.isfinite(sample['wall_seconds'])
                or type(sample['thread_cpu_ns']) is not int or sample['thread_cpu_ns'] < 0):
            raise ValueError('Invalid original clock-tap observation')
    result = {}
    names = (*phases, 'unpartitioned') if final else phases
    for index, name in enumerate(names):
        first, last = samples[index], samples[index+1]
        wall = last['wall_seconds']-first['wall_seconds']
        if name in expected_walls and not _close(wall, expected_walls[name]):
            raise ValueError('Clock tap does not reconstruct the original V4/V6 wall phase')
        result[name] = _seconds(wall, last['thread_cpu_ns']-first['thread_cpu_ns'])
    return result


def diagnostic_rows(measured, observations, diagnostics):
    """Independently validate raw events; return private per-query decompositions."""
    rows = measured['queries']
    if (not 1 <= len(rows) <= 64 or measured['committed_prefix_rows'] != 0
            or measured['verified_subset_queries'] != len(rows)
            or [row['subset_ordinal'] for row in rows] != list(range(len(rows)))
            or set(diagnostics) != {'sql', 'append'}
            or len(diagnostics['sql']) != len(rows) or len(diagnostics['append']) != len(rows)):
        raise ValueError('Complete contiguous diagnostic events for every fresh query are required')
    restored = DetailedTimedStore.__new__(DetailedTimedStore)
    restored.append_events = observations['append_events']
    restored.budget_events = observations['budget_events']
    restored.commit_events = measured['chunk_commits']
    if restored.detailed_cost_summary(measured) != observations['detail']:
        raise ValueError('Saved V6 append accounting differs from the raw original events')
    result = []
    for index, (row, sql_event, append_event, original_append) in enumerate(zip(
            rows, diagnostics['sql'], diagnostics['append'], observations['append_events'], strict=True)):
        if (any(event['subset_ordinal'] != index or event['completed'] is not True for event in (sql_event, append_event))
                or sql_event['execute_calls'] != 1 or sql_event['eof_calls'] != 1
                or sql_event['fetch_calls'] != sql_event['returned_rows']+1
                or sql_event['returned_rows'] != row['sql_workload']['sql_overlap_groups_returned']
                or sql_event['intersection_sum'] != row['sql_workload']['sql_overlap_membership_matches']
                or sql_event['eligible_neighbors'] != row['sql_workload']['neighbor_pool_rows_hashed']
                or sql_event['current_session_excluded'] not in (0, 1)
                or sql_event['returned_rows'] != sql_event['eligible_neighbors']+sql_event['current_session_excluded']):
            raise ValueError('Incomplete overlap cursor, row counts or original workload differs')
        rank_phases = _clock_parts(sql_event['clock_samples'], RANK_PHASES, row['rank_stages_seconds'])
        positive = rank_phases['sql_positive_overlaps']
        execute, fetch, terminal = (_raw_span(sql_event[key]) for key in ('execute', 'fetch', 'terminal_fetch'))
        _residual(fetch, [terminal])
        sql_parts = {'execute': execute, 'fetch_including_eof': fetch,
                     'python_watch_proxy_other': _residual(positive, [execute, fetch])}
        append_phases = _clock_parts(append_event['clock_samples'], APPEND_PHASES,
                                    original_append['parts_seconds'], final=True)
        tap_total = _sum_spans(list(append_phases.values()))
        if (not _close(tap_total['wall_seconds'], original_append['seconds'])
                or not _close(append_phases['unpartitioned']['wall_seconds'], original_append['unpartitioned_seconds'])):
            raise ValueError('Append wall phases do not conserve the unchanged V6 enclosing event')
        wrapper_total = _raw_span(append_event['wrapper_total'])
        wrapper_other = _residual(wrapper_total, [tap_total])
        outer_wall = row['checkpoint_append_seconds']-wrapper_total['wall_seconds']
        if outer_wall < 0:
            raise ValueError('Diagnostic append wrapper exceeds its original V4 wall timer')
        direct_checks, nested_checks, all_checks = [], [], []
        direct_read, direct_parse, direct_publish, direct_other = [], [], [], []
        publication_contexts = Counter()
        for check in append_event['budget_checks']:
            if (check['completed'] is not True or check['subset_ordinal'] != index
                    or check['context'] not in ('query_append', 'chunk_commit') or check['stage'] is not None
                    or type(check['persist']) is not bool or len(check['reads']) != 1):
                raise ValueError('Invalid budget-check diagnostic context')
            reading = check['reads'][0]
            if reading['completed'] is not True or type(reading['text_characters']) is not int or reading['text_characters'] <= 0:
                raise ValueError('Incomplete budget UTF-8 read or JSON parse')
            total = _raw_span(check['total'])
            read_time, parse_time = _raw_span(reading['read_text']), _raw_span(reading['json_parse'])
            publishes = []
            for publication in check['publications']:
                if publication['completed'] is not True or publication['context'] != check['context'] or publication['replace'] is not True:
                    raise ValueError('Budget publication changed its original context')
                publishes.append(_raw_span(publication['total']))
                publication_contexts[publication['context']] += 1
            remaining = _residual(total, [read_time, parse_time, *publishes])
            all_checks.append(total)
            if check['context'] == 'query_append':
                direct_checks.append(total); direct_read.append(read_time); direct_parse.append(parse_time)
                direct_publish.extend(publishes); direct_other.append(remaining)
            else:
                nested_checks.append(total)
        if len(direct_checks) != 1:
            raise ValueError('Exactly one direct original check_budget call is required per append')
        direct = _sum_spans(direct_checks)
        _residual(append_phases['nested_flush'], nested_checks)
        append_budget_parts = {'read_text_utf8': _sum_spans(direct_read), 'json_parse': _sum_spans(direct_parse),
                               'budget_publication_with_observer': _sum_spans(direct_publish),
                               'deadline_accounting_proxy_other': _sum_spans(direct_other),
                               'writer_context_and_observer_other': _residual(append_phases['budget_check'], [direct])}
        budget_events = [event for event in observations['budget_events']
                         if event['subset_ordinal'] == index and event['context'] in ('query_append', 'chunk_commit')]
        if publication_contexts != Counter(event['context'] for event in budget_events):
            raise ValueError('Diagnostic publications differ from original V5 budget contexts')
        original_direct = sum(event['seconds'] for event in budget_events if event['context'] == 'query_append')
        if _sum_spans(direct_publish)['wall_seconds'] < original_direct:
            raise ValueError('Original budget publication exceeds its observed wrapper')
        result.append({'subset_ordinal': index, 'sql_positive_overlap_total': positive, 'sql_parts': sql_parts,
                       'terminal_fetch_included': terminal,
                       'sql_counts': {key: sql_event[key] for key in ('execute_calls', 'fetch_calls', 'eof_calls',
                           'returned_rows', 'intersection_sum', 'eligible_neighbors', 'current_session_excluded')},
                       'rank_phases': rank_phases, 'append_total': tap_total, 'append_phases': append_phases,
                       'append_wrapper_total': wrapper_total, 'append_wrapper_observer_other': wrapper_other,
                       'append_original_outer_wall_seconds': row['checkpoint_append_seconds'],
                       'append_outer_unobserved_wall_seconds': outer_wall,
                       'append_budget_check_parts': append_budget_parts,
                       'all_append_budget_checks': _sum_spans(all_checks),
                       'direct_budget_publications': publication_contexts['query_append'],
                       'nested_commit_budget_publications': publication_contexts['chunk_commit'],
                       'original_direct_budget_seconds': original_direct})
    return result


def summarize_diagnostics(measured, observations, diagnostics):
    """Public repeat aggregate; private raw rows stay outside the published report."""
    rows = diagnostic_rows(measured, observations, diagnostics)
    def aggregate(values):
        return {clock: _stats(value[clock] for value in values) for clock in
                ('wall_seconds', 'thread_cpu_seconds', 'wall_minus_thread_cpu_seconds')}
    def grouped(name):
        keys = rows[0][name]
        if any(set(row[name]) != set(keys) for row in rows):
            raise ValueError('Diagnostic component sets differ')
        return {key: aggregate([row[name][key] for row in rows]) for key in keys}
    return {'kind': 'v20_observed_overlap_and_append_diagnostics', 'queries': len(rows), 'clock_metadata': clock_metadata(),
            'sql_counts': {key: sum(row['sql_counts'][key] for row in rows) for key in rows[0]['sql_counts']},
            'sql_positive_overlap_total': aggregate([row['sql_positive_overlap_total'] for row in rows]),
            'sql_parts': grouped('sql_parts'),
            'terminal_fetch_included': aggregate([row['terminal_fetch_included'] for row in rows]),
            'rank_phases': grouped('rank_phases'), 'append_total': aggregate([row['append_total'] for row in rows]),
            'append_wrapper_total': aggregate([row['append_wrapper_total'] for row in rows]),
            'append_wrapper_observer_other': aggregate([row['append_wrapper_observer_other'] for row in rows]),
            'append_original_outer_wall_seconds': _stats(row['append_original_outer_wall_seconds'] for row in rows),
            'append_outer_unobserved_wall_seconds': _stats(row['append_outer_unobserved_wall_seconds'] for row in rows),
            'append_outer_unobserved_thread_cpu_seconds': None,
            'append_phases': grouped('append_phases'), 'append_budget_check_parts': grouped('append_budget_check_parts'),
            'direct_budget_publications': sum(row['direct_budget_publications'] for row in rows),
            'nested_commit_budget_publications': sum(row['nested_commit_budget_publications'] for row in rows),
            'interpretation': 'Diagnostic observers retain frozen SQL, lazy row iteration, checkpoint operations and original wall timers. '
                'Execute and fetch include SQLite stepping and Python DB-API tuple conversion; their wall residual includes Python validation, '
                'pool construction, watch, proxy bookkeeping and clock overhead, not pure Python conversion. Terminal EOF fetch is included in fetch totals. '
                'Append budget read_text includes UTF-8 decoding; JSON parsing preserves the original nonfinite rejection. '
                'Deadline/accounting and writer/context residuals include observer dispatch. Budget publication wrappers include the original V5 observer; '
                'original direct budget and nested commits keep their original cost allocation. Thread CPU excludes other threads including telemetry, '
                'but clock quantization can make it exceed wall in short spans. Signed wall-minus-thread-CPU is retained without clamping; it is not I/O wait '
                'or proof of OS, cache, disk or Ollama causation. FunctionType namespace allocation, per-cursor event bookkeeping and clock reads remain '
                'observed instrumentation overhead; reference/diagnostic differences are descriptive and provide no deterministic correction. '
                'Component totals conserve their own enclosing spans and must not be added across nested levels.'}
