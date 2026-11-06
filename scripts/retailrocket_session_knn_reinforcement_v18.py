"""Frozen V18 reinforcement and descriptive same-query/load observations."""
from collections import Counter, defaultdict
from datetime import datetime, timezone
import hashlib
import json
import math
from pathlib import Path
from statistics import mean, median
from threading import Event, Thread
from time import perf_counter

import psutil

from scripts.retailrocket_session_knn_cost_probe_v2 import _sha
from scripts.retailrocket_session_knn_gap_v7 import _historical
from scripts.retailrocket_session_knn_gap_v9 import _boundary
from scripts.retailrocket_session_knn_gap_v10 import _all_history
from scripts.retailrocket_session_knn_joint_cost_v5 import DIMENSIONS
from scripts.retailrocket_session_knn_refined_cost_v6 import _cell
from scripts.retailrocket_session_knn_cost_rollup_v17 import METRICS, normalize_repeat, summarize_costs


CELLS = ('1101/n4/v4', '1101/n5/v4')
PREFIX = b'k1-reinforcement-v18-20261106\x00'
HISTORY = ('V3', 'V6', 'V7', *('V'+str(v) for v in range(8, 17)))


def _quotas(spec):
    selection, measurement, telemetry = (spec[k] for k in ('selection', 'measurement', 'telemetry'))
    rows = spec['quotas']
    quotas = {row['cell']: row for row in rows}
    if (len(rows) != 2 or set(quotas) != set(CELLS)
            or selection['quota_by_cell'] != dict.fromkeys(CELLS, 4)
            or selection['anchor_quota_by_cell'] != dict.fromkeys(CELLS, 1)
            or (selection['planned_new_queries'], selection['planned_unique_queries']) != (8, 10)
            or selection['prefix_with_terminator'].encode('ascii') != PREFIX
            or (measurement['fresh_repeats'], measurement['queries_per_repeat'], measurement['expected_engineering_checks']) != (3, 10, 30)
            or telemetry['interval_seconds'] != .2 or telemetry['process_name_prefix'] != 'ollama'
            or any(type(row[k]) is not int or row[k] < 0 for row in rows for k in (
                'population', 'historical_exclusions', 'eligible', 'planned_new_queries', 'planned_anchor_queries'))
            or any(row['planned_new_queries'] != 4 or row['planned_anchor_queries'] != 1
                   or row['eligible'] < 4 or row['population'] != row['historical_exclusions'] + row['eligible'] for row in rows)):
        raise ValueError('V18 requires the frozen two cells, four new plus one anchor, and three instrumented repeats')
    return quotas


def _history(histories):
    if set(histories) != set(HISTORY):
        raise ValueError('All twelve frozen historical cohorts are required')
    groups = [histories[name]['probes'] for name in HISTORY]
    sizes = [64, 48, 34, *([8]*8), 10]
    identities = [{row['key_sha256'] for row in group} for group in groups]
    if ([len(group) for group in groups] != sizes or [len(group) for group in identities] != sizes
            or len(identities[0] & identities[1]) != 2
            or any(identities[i] & set.union(*identities[:i]) for i in range(2, len(identities)))
            or len(set.union(*identities)) != 218):
        raise ValueError('Historical cohort counts, overlaps or 218-key union differ')
    history, masks, fine = _all_history(*(histories[name] for name in ('V3', 'V6', 'V7', 'V8', 'V9')))
    for version in range(10, 17):
        recent = _historical(histories['V'+str(version)]['probes'])
        if recent.keys() & history.keys():
            raise ValueError('Later historical cohorts overlap')
        history.update(recent)
        fine.update(recent)
    return history, masks, fine


def select_reinforcement_roster(path, histories, spec, watch=lambda: None):
    quotas = _quotas(spec)
    history, masks, fine = _history(histories)
    original = histories['V6']
    population = original['population']
    anchor_ids = {row['key_sha256'] for row in original['probes']}
    seen, counts, excluded = set(), Counter(), Counter()
    best, anchors = {cell: [] for cell in CELLS}, {cell: [] for cell in CELLS}
    digest = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for ordinal, line in enumerate(stream):
            watch()
            digest.update(line)
            row = json.loads(line)
            identity = row['key_sha256']
            if (row['original_ordinal'] != ordinal or _sha(row['key']) != identity or identity in seen
                    or any(type(row[k]) is not int or row[k] < 0 for k in DIMENSIONS)):
                raise ValueError('Invalid structural roster identity, ordinal or workload')
            seen.add(identity)
            parent = ''.join('1' if row[k] > 0 and row[k] >= population['p90_nearest_rank'][k] else '0' for k in DIMENSIONS)
            cell = _cell(row, parent, 'neighbor_vote_grid')
            if identity in history:
                if any(history[identity][k] != row[k] for k in ('key', 'history_sha256')):
                    raise ValueError('Historical identity differs from the roster')
                for group, label in ((masks, parent), (fine, cell)):
                    if identity in group and (group[identity]['original_ordinal'], group[identity]['cell']) != (ordinal, label):
                        raise ValueError('Historical ordinal or stratum changed')
            if cell not in quotas:
                continue
            counts[cell] += 1
            if identity in history:
                excluded[cell] += 1
                if identity in anchor_ids:
                    anchors[cell].append(dict(row, cell=cell, sample_role='anchor'))
                continue
            token = hashlib.sha256(PREFIX + bytes.fromhex(identity)).digest()
            best[cell].append((token, ordinal, dict(row, cell=cell, sample_role='new')))
            best[cell].sort(key=lambda value: value[:2])
            del best[cell][quotas[cell]['planned_new_queries']:]
        length = stream.tell()
    if (len(seen) != population['total_queries'] or length != population['roster_bytes']
            or digest.hexdigest() != population['roster_sha256'] or not history.keys() <= seen):
        raise ValueError('Incomplete or changed structural source')
    selected = []
    for cell, quota in quotas.items():
        if (counts[cell], excluded[cell], counts[cell]-excluded[cell], len(best[cell]), len(anchors[cell])) != (
                quota['population'], quota['historical_exclusions'], quota['eligible'], 4, 1):
            raise ValueError('Frozen population, exclusions, new quota or unique V6 anchor differs')
        selected.extend(row for _, _, row in best[cell])
        selected.extend(anchors[cell])
    return {'probes': sorted(selected, key=lambda row: row['original_ordinal']),
            'roster_sha256': digest.hexdigest(), 'new_keys': 8, 'anchor_keys': 2}


def audit_reinforcement_order(path, selection, histories, spec, watch=lambda: None):
    """Independently classify literal bands and fully sort every eligible list."""
    quotas = _quotas(spec)
    excluded = {row['key_sha256'] for name in HISTORY for row in histories[name]['probes']}
    old48 = {row['key_sha256'] for row in histories['V6']['probes']}
    population = histories['V6']['population']
    candidates, anchors = {cell: [] for cell in CELLS}, {cell: [] for cell in CELLS}
    counts, exclusions = Counter(), Counter()
    digest = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for ordinal, line in enumerate(stream):
            watch()
            digest.update(line)
            row = json.loads(line)
            parent = ''.join(str(int(0 < row[k] and population['p90_nearest_rank'][k] <= row[k])) for k in DIMENSIONS)
            neighbors, upper = row['eligible_neighbors'], row['vote_memberships_upper']
            if parent != '1101' or not 2000 <= upper <= 9999:
                continue
            if 500 <= neighbors <= 999:
                cell = CELLS[0]
            elif 1000 <= neighbors <= 4999:
                cell = CELLS[1]
            else:
                continue
            counts[cell] += 1
            identity = row['key_sha256']
            if identity in excluded:
                exclusions[cell] += 1
                if identity in old48:
                    anchors[cell].append(dict(row, cell=cell, sample_role='anchor'))
                continue
            token = hashlib.sha256(spec['selection']['prefix_with_terminator'].encode('ascii') + bytes.fromhex(identity)).hexdigest()
            candidates[cell].append((token, ordinal, dict(row, cell=cell, sample_role='new')))
    wanted = []
    for cell in CELLS:
        quota = quotas[cell]
        if (counts[cell], exclusions[cell], len(candidates[cell]), len(anchors[cell])) != (
                quota['population'], quota['historical_exclusions'], quota['eligible'], 1):
            raise ValueError('Independent eligibility or anchor inventory differs')
        wanted.extend(row for _, _, row in sorted(candidates[cell], key=lambda value: value[:2])[:4])
        wanted.extend(anchors[cell])
    expected = {'probes': sorted(wanted, key=lambda row: row['original_ordinal']),
                'roster_sha256': digest.hexdigest(), 'new_keys': 8, 'anchor_keys': 2}
    if expected != selection or digest.hexdigest() != population['roster_sha256']:
        raise ValueError('Independent V18 full sorting or anchor selection differs')


def _selection_counts(probes):
    counts = Counter((p['cell'], p['sample_role']) for p in probes)
    if (len(probes) != 10 or len({p['key_sha256'] for p in probes}) != 10
            or [p['original_ordinal'] for p in probes] != sorted({p['original_ordinal'] for p in probes})
            or counts != Counter({(cell, role): 4 if role == 'new' else 1 for cell in CELLS for role in ('new', 'anchor')})):
        raise ValueError('Expected ten ordered identities: four new plus one old anchor per cell')


def sample_workload(probes, measured, predictions):
    _selection_counts(probes)
    groups = {cell: [] for cell in CELLS}
    for probe, row, prediction in zip(probes, measured['queries'], predictions, strict=True):
        n, upper = probe['eligible_neighbors'], probe['vote_memberships_upper']
        work = row['sql_workload']
        valid_band = 500 <= n <= 999 if probe['cell'] == CELLS[0] else 1000 <= n <= 4999
        votes = work['sql_vote_membership_rows_returned']
        if (not valid_band or not 2000 <= upper <= 9999 or not 500 <= votes <= upper
                or (n == 500 and votes != upper)
                or (row['original_ordinal'], row['key_sha256']) != (probe['original_ordinal'], probe['key_sha256'])
                or work['neighbor_pool_rows_hashed'] != n or work['sql_selected_rows_inserted'] != 500
                or work['sql_overlap_membership_matches'] != probe['posting_work']
                or work['causal_catalog_candidates'] != probe['causal_candidates']
                or not 0 <= work['exact_vote_additions'] <= votes):
            raise ValueError('Frozen V18 pool, capped workload or structural counts differ')
        groups[probe['cell']].append((probe, work, _boundary(probe, work, prediction)))
    result = {}
    for cell, rows in groups.items():
        n = [p['eligible_neighbors'] for p, _, _ in rows]
        bounds = [p['vote_memberships_upper'] for p, _, _ in rows]
        sums = {k: sum(work[k] for _, work, _ in rows) for k in (
            'neighbor_pool_rows_hashed', 'sql_selected_rows_inserted', 'sql_vote_membership_rows_returned', 'exact_vote_additions')}
        ties, excluded = sum(b[1] for _, _, b in rows), sum(b[2] for _, _, b in rows)
        result[cell] = dict(sums, new_queries=4, anchor_queries=1, eligible_neighbors_min=min(n), eligible_neighbors_max=max(n),
            vote_upper_min=min(bounds), vote_upper_max=max(bounds), vote_upper_sum=sum(bounds),
            vote_upper_slack=sum(bounds)-sums['sql_vote_membership_rows_returned'],
            under500_queries=0, exact500_queries=n.count(500), over500_queries=sum(value > 500 for value in n),
            boundary_queries=sum(b[0] for _, _, b in rows), boundary_ties_total=ties,
            boundary_ties_selected=ties-excluded, boundary_ties_excluded=excluded)
    return result


def compare_repeats(folder, repeats):
    if len(repeats) != 3 or any(repeat['proof']['records'] != 10 for repeat in repeats):
        raise ValueError('Exactly three complete ten-query repeats are required')
    if any(repeat['proof'] != repeats[0]['proof'] or repeat['workload_by_cell'] != repeats[0]['workload_by_cell'] for repeat in repeats[1:]):
        raise ValueError('The three saved proofs or logical workloads differ')
    def frames(index):
        root = Path(folder)/f'repeat_{index}'/'verified_subset'
        for manifest in sorted((root/'chunks').glob('*.json')):
            payload = json.loads(manifest.read_bytes())['payload']['path']
            path = (root/payload).resolve()
            if not path.is_relative_to(root.resolve()):
                raise ValueError('Physical ledger path escapes the checkpoint')
            with path.open('rb') as stream:
                yield from stream
    count = total = 0
    digest = hashlib.sha256()
    for row0, row1, row2 in zip(*(frames(i) for i in range(3)), strict=True):
        if row0 != row1 or row0 != row2:
            raise ValueError('Corresponding physical frames differ across the three repeats')
        digest.update(row0)
        total += len(row0)
        count += 1
    proof = repeats[0]['proof']
    if (count, total, digest.hexdigest()) != (10, proof['actual_committed_bytes'], proof['actual_committed_payload_sha256']):
        raise ValueError('Physical frame count, bytes or concatenated digest differs')


def summarize_repeats(selection, repeats, spec):
    quotas = _quotas(spec)
    probes = selection['probes']
    _selection_counts(probes)
    if len(repeats) != 3 or selection['new_keys'] != 8 or selection['anchor_keys'] != 2:
        raise ValueError('V18 requires all three retained repeats and unchanged sample roles')
    roles = {p['key_sha256']: p['sample_role'] for p in probes}
    cell_by_key = {p['key_sha256']: p['cell'] for p in probes}
    normalized = [normalize_repeat('V18', i, probes, repeat['measured'], repeat['observations'], cell_by_key)
                  for i, repeat in enumerate(repeats)]
    rows = [row for repeat in normalized for row in repeat['rows']]
    result = summarize_costs({cell: q['population'] for cell, q in quotas.items()}, rows,
        [repeat['overheads'] for repeat in normalized], {'V18': {'queries': 10, 'repeats': 3}})
    for cell, summary in result['cells'].items():
        summary['new_queries'], summary['anchor_queries'] = 4, 1
        summary['roles'] = {}
        for role, size in (('new', 4), ('anchor', 1)):
            subset = [r for r in rows if r['cell'] == cell and roles[r['key_sha256']] == role]
            summary['roles'][role] = summarize_costs({cell: quotas[cell]['population']}, subset, [],
                {'V18': {'queries': size, 'repeats': 3}})['cells'][cell]
        grouped = defaultdict(list)
        for row in rows:
            if row['cell'] == cell:
                grouped[row['key_sha256']].append(row)
        largest = None
        for identity, observations in grouped.items():
            fastest = min(observations, key=lambda r: (r['seconds']['core'], r['repeat_index']))
            slowest = max(observations, key=lambda r: (r['seconds']['core'], -r['repeat_index']))
            delta = {metric: slowest['seconds'][metric]-fastest['seconds'][metric] for metric in METRICS}
            item = {'sample_role': roles[identity], 'fast_repeat': fastest['repeat_index'], 'slow_repeat': slowest['repeat_index'],
                    'fast_core_seconds': fastest['seconds']['core'], 'slow_core_seconds': slowest['seconds']['core'],
                    'delta_seconds': delta}
            if largest is None or delta['core'] > largest['delta_seconds']['core']:
                largest = item
        summary['max_same_query_range_decomposition'] = largest
    result['scope'].update(new_keys=8, anchor_keys=2, engineering_checks=30,
                          distinct_historically_verified_queries=226, distinct_comparable_queries=164,
                          globally_covered_cells=55, globally_uncovered_cells=0)
    result['interpretation']['reinforcement'] = 'Five different identities per target cell: four new plus one explicitly old anchor. All three fresh repeats are retained; historical V6 anchor timings remain separate machine windows, not paired optimization evidence.'
    return result


def _finite(value):
    return type(value) in (int, float) and math.isfinite(value) and value >= 0


def _describe(values, weights=None):
    values = list(values)
    if not values:
        return None
    average = mean(values) if weights is None else math.fsum(v*w for v, w in zip(values, weights, strict=True))/math.fsum(weights)
    return {'min': min(values), 'mean': average, 'max': max(values)}


class TelemetrySampler:
    """One bounded background observer; never query or modify an inference service."""
    def __init__(self, interval_seconds=.2, process_name_prefix='ollama'):
        if interval_seconds != .2 or process_name_prefix != 'ollama':
            raise ValueError('V18 telemetry interval and executable-name scope are frozen')
        self.interval_seconds = interval_seconds
        self.process_name_prefix = process_name_prefix
        self.records = []
        self._stop = Event()
        self._ready = Event()
        self._thread = None
        self._error = None
        self._repeat = None

    def _process(self, process, known_name=None):
        result = {'pid': process.pid, 'create_time': None, 'name': known_name,
                  'cpu_user_seconds': None, 'cpu_system_seconds': None, 'rss_bytes': None, 'status': 'unavailable'}
        try:
            with process.oneshot():
                result['name'] = known_name if known_name is not None else process.name()
                result['create_time'] = process.create_time()
                times = process.cpu_times()
                result['cpu_user_seconds'] = times.user
                result['cpu_system_seconds'] = times.system
                result['rss_bytes'] = process.memory_info().rss
            result['status'] = 'observed'
        except (psutil.Error, OSError) as exc:
            result['status'] = type(exc).__name__
        return result

    def _capture(self, kind):
        started = perf_counter()
        cpu = psutil.cpu_percent(interval=None)
        memory = psutil.virtual_memory()
        disk_status = 'ok'
        try:
            disk = psutil.disk_io_counters()
            if disk is None:
                disk_status = 'unsupported'
            else:
                disk = dict(disk._asdict())
        except (psutil.Error, OSError, NotImplementedError) as exc:
            disk, disk_status = None, type(exc).__name__
        worker = self._process(psutil.Process())
        ollama, scan_status = [], 'ok'
        try:
            for process in psutil.process_iter(['pid', 'name']):
                name = process.info.get('name')
                if name is None:
                    scan_status = 'partially_unavailable_process_names'
                elif name.lower().startswith(self.process_name_prefix):
                    ollama.append(self._process(process, name))
        except (psutil.Error, OSError) as exc:
            scan_status = type(exc).__name__
        # Both CPU priming and all subsequent CPU observations run on this one
        # sampler thread, preserving psutil's per-thread interval baseline.
        self.records.append({'sequence': len(self.records), 'repeat_index': self._repeat, 'kind': kind,
            'monotonic_seconds': started, 'observed_utc': datetime.now(timezone.utc).isoformat(),
            'system_cpu_percent': None if not self.records else cpu,
            'logical_cpus': psutil.cpu_count() or 1,
            'memory': {'total_bytes': memory.total, 'available_bytes': memory.available,
                       'used_bytes': memory.used, 'percent': memory.percent},
            'disk_io': disk, 'disk_io_status': disk_status, 'worker': worker,
            'ollama': sorted(ollama, key=lambda p: p['pid']), 'ollama_scan_status': scan_status,
            'collector_seconds': perf_counter()-started})

    def _observe(self):
        try:
            self._capture('start')
            self._ready.set()
            while not self._stop.wait(self.interval_seconds):
                self._capture('periodic')
            self._capture('end')
        except BaseException as exc:
            self._error = exc
            self._ready.set()

    def start(self, repeat_index):
        if self._thread is not None or type(repeat_index) is not int or not 0 <= repeat_index < 3:
            raise ValueError('Sampler cannot be reused or assigned an unexpected repeat')
        self._repeat = repeat_index
        self._thread = Thread(target=self._observe, name='v18-readonly-telemetry', daemon=True)
        self._thread.start()
        if not self._ready.wait(5):
            self._stop.set()
            raise RuntimeError('Telemetry sampler did not acquire the initial observation')
        if self._error is not None:
            raise RuntimeError('Telemetry initial observation failed') from self._error
        return self

    def stop(self):
        if self._thread is None:
            raise ValueError('Telemetry sampler was not started')
        self._stop.set()
        self._thread.join(5)
        if self._thread.is_alive():
            raise RuntimeError('Telemetry sampler failed to stop before the next repeat')
        if self._error is not None:
            raise RuntimeError('Telemetry observation failed') from self._error
        summarize_telemetry(self.records, self._repeat, self.interval_seconds)
        return self.records


def _validate_process(process, *, ollama=False):
    fields = {'pid', 'create_time', 'name', 'cpu_user_seconds', 'cpu_system_seconds', 'rss_bytes', 'status'}
    if (set(process) != fields or type(process['pid']) is not int or process['pid'] <= 0
            or type(process['status']) is not str or not process['status']
            or any(process[k] is not None and not _finite(process[k]) for k in (
                'create_time', 'cpu_user_seconds', 'cpu_system_seconds', 'rss_bytes'))
            or process['name'] is not None and type(process['name']) is not str):
        raise ValueError('Invalid process observation or unavailable-field status')
    if process['status'] == 'observed' and (not process['name'] or any(process[k] is None for k in (
            'create_time', 'cpu_user_seconds', 'cpu_system_seconds', 'rss_bytes'))):
        raise ValueError('Observed process lacks required identity or counters')
    if ollama and (process['name'] is None or not process['name'].lower().startswith('ollama')):
        raise ValueError('Out-of-scope process observation')


def _process_summary(records, field):
    snapshots = [[row['worker']] if field == 'worker' else row['ollama'] for row in records]
    observed_ids, rss, rates, durations = set(), [], [], []
    unavailable = discontinuous = partial_intervals = 0
    for snapshot in snapshots:
        good = [p for p in snapshot if p['status'] == 'observed']
        unavailable += len(snapshot)-len(good)
        observed_ids.update((p['pid'], p['create_time']) for p in good)
        if good:
            rss.append(sum(p['rss_bytes'] for p in good))
    for i in range(1, len(records)):
        dt = records[i]['monotonic_seconds']-records[i-1]['monotonic_seconds']
        before = {(p['pid'], p['create_time']): p for p in snapshots[i-1] if p['status'] == 'observed'}
        after = {(p['pid'], p['create_time']): p for p in snapshots[i] if p['status'] == 'observed'}
        common = before.keys() & after.keys()
        discontinuous += len(before.keys() ^ after.keys())
        deltas = []
        for key in common:
            delta = sum(after[key][k]-before[key][k] for k in ('cpu_user_seconds', 'cpu_system_seconds'))
            if any(after[key][k] < before[key][k] for k in ('cpu_user_seconds', 'cpu_system_seconds')):
                discontinuous += 1
            else:
                deltas.append(delta)
        if deltas:
            rates.append(100*sum(deltas)/dt)
            durations.append(dt)
            partial_intervals += int(len(deltas) != len(before) or len(deltas) != len(after)
                                     or any(p['status'] != 'observed' for p in snapshots[i-1]+snapshots[i]))
    return {'status': 'observed' if observed_ids else 'not_observed_or_unavailable',
            'observed_processes': len(observed_ids), 'cpu_core_percent': _describe(rates, durations) if rates else None,
            'rss_bytes': _describe(rss), 'valid_cpu_intervals': len(rates),
            'valid_cpu_duration_seconds': sum(durations), 'unavailable_observations': unavailable,
            'discontinuous_cpu_intervals': discontinuous, 'partial_cpu_intervals': partial_intervals}


def summarize_telemetry(records, repeat_index, interval_seconds=.2):
    """Repeat-level context only; unavailable metrics stay unavailable, without interpolation."""
    if interval_seconds != .2 or type(repeat_index) is not int or not 0 <= repeat_index < 3 or len(records) < 3:
        raise ValueError('V18 requires bracketing observations and at least two CPU intervals')
    if (records[0]['kind'] != 'start' or records[-1]['kind'] != 'end'
            or any(row['kind'] != 'periodic' for row in records[1:-1])
            or records[0]['system_cpu_percent'] is not None):
        raise ValueError('Telemetry start/end markers or first CPU interval differ')
    gaps, cpu, available, acquisition = [], [], [], []
    previous_utc = None
    for i, row in enumerate(records):
        observed = datetime.fromisoformat(row['observed_utc'])
        if (row['sequence'] != i or row['repeat_index'] != repeat_index
                or not _finite(row['monotonic_seconds']) or not _finite(row['collector_seconds'])
                or observed.utcoffset() is None or previous_utc is not None and observed < previous_utc
                or type(row['logical_cpus']) is not int or row['logical_cpus'] <= 0
                or row['logical_cpus'] != records[0]['logical_cpus']):
            raise ValueError('Invalid telemetry identity, timestamp or collector duration')
        previous_utc = observed
        if i:
            gap = row['monotonic_seconds']-records[i-1]['monotonic_seconds']
            if gap <= 0 or not _finite(row['system_cpu_percent']) or row['system_cpu_percent'] > 100:
                raise ValueError('Telemetry clock or required CPU interval differs')
            gaps.append(gap)
            cpu.append(row['system_cpu_percent'])
        memory = row['memory']
        if (set(memory) != {'total_bytes', 'available_bytes', 'used_bytes', 'percent'}
                or any(not _finite(v) for v in memory.values()) or memory['total_bytes'] <= 0
                or max(memory['available_bytes'], memory['used_bytes']) > memory['total_bytes'] or memory['percent'] > 100):
            raise ValueError('Required memory observations are incomplete or invalid')
        available.append(memory['available_bytes'])
        acquisition.append(row['collector_seconds'])
        _validate_process(row['worker'])
        if type(row['ollama_scan_status']) is not str or not row['ollama_scan_status']:
            raise ValueError('Missing process-discovery status')
        if len({p['pid'] for p in row['ollama']}) != len(row['ollama']):
            raise ValueError('Duplicate process identity within a snapshot')
        for process in row['ollama']:
            _validate_process(process, ollama=True)
        if row['disk_io'] is not None and (not row['disk_io'] or any(not _finite(v) for v in row['disk_io'].values())):
            raise ValueError('Invalid optional disk counters')
    disk_totals, disk_intervals, disk_missing = {}, 0, 0
    for before, after in zip(records, records[1:]):
        first, last = before['disk_io'], after['disk_io']
        if first is None or last is None or set(first) != set(last) or any(last[k] < first[k] for k in first):
            disk_missing += 1
            continue
        disk_intervals += 1
        for key in first:
            disk_totals[key] = disk_totals.get(key, 0) + last[key]-first[key]
    return {'repeat_index': repeat_index, 'samples': len(records), 'duration_seconds': sum(gaps),
            'nominal_interval_seconds': interval_seconds, 'system_cpu_percent': _describe(cpu, gaps),
            'available_memory_bytes': _describe(available), 'collector_seconds': _describe(acquisition),
            'total_collector_seconds': sum(acquisition),
            'disk_io_delta': disk_totals if disk_intervals else None,
            'disk_valid_intervals': disk_intervals, 'disk_unavailable_or_reset_intervals': disk_missing,
            'disk_status_counts': dict(Counter(row.get('disk_io_status', 'ok' if row['disk_io'] is not None else 'unavailable') for row in records)),
            'worker': _process_summary(records, 'worker'), 'ollama': _process_summary(records, 'ollama'),
            'ollama_scan_status_counts': dict(Counter(row['ollama_scan_status'] for row in records)),
            'coverage': {'max_gap_seconds': max(gaps), 'intervals': len(gaps),
                         'missing_periodic_intervals': sum(max(0, math.floor(gap/interval_seconds+.5)-1) for gap in gaps)},
            'interpretation': 'Whole-verifier context only. System CPU is interval utilization across logical CPUs including this benchmark; process cpu_core_percent is relative to one logical CPU and may exceed 100. The first CPU observation is excluded. Cumulative disk deltas cover only adjacent valid samples. PID/create_time changes, unavailable processes and counter resets are never bridged or filled with zero. Nominal 200ms polling includes acquisition and scheduling gaps; missing-periodic counts estimate skipped nominal slots. No per-query interpolation, process-specific slowdown causality, Ollama token speed or optimization claim follows. Observer work remains part of this measured environment.'}
