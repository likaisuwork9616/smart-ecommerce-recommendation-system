"""New literal synthetic sources and real tiny SQLite/checkpoint IO for V64.

Nothing runs on import. No production model, original fixed48 source, training,
bootstrap, live clock or resource collector is used. Expected K1 rows come from
the existing independent full-session oracle over the literal memberships.
"""
from copy import deepcopy
import csv
import hashlib
import json
from pathlib import Path
import sqlite3
from types import FunctionType, SimpleNamespace

from scripts import retailrocket_session_knn_checkpoint_v2 as checkpoint
from scripts.retailrocket_session_knn_checkpoint_cost_v5 import BudgetTimedStore
from scripts.retailrocket_session_knn_detailed_cost_v6 import DetailedTimedStore
from scripts import retailrocket_session_knn_pair_v4 as pair
from scripts import retailrocket_session_knn_readback as oracle
from scripts import retailrocket_session_knn_sql_v2 as index
from scripts import retailrocket_session_knn_sql_v4 as ranking


QUERY_FIELDS = ('visitorid', 'session_start_ms', 'query_ms', 'role', 'basket_index',
    'context_item_occurrences', 'next_view_ms', 'next_role', 'next_in_session',
    'mature', 'cross_role', 'status', 'candidate_count', 'target_items', 'target_count',
    'reachable_target_count', 'all_targets_reachable', 'visitor_seen_before_fit',
    'targets_seen_before_fit', 'train_view_events', 'train_activity_slice')
CATALOG_FIELDS = ('itemid', 'first_view_ms')
SESSIONS = {('1', 1): {'1', '2'}, ('2', 1): {'1', '3'},
            ('3', 1): {'2', '3'}, ('4', 1): {'4'}}
COUNTS = {'1': 8, '2': 7, '3': 6, '4': 5}
CATALOG = {'1': 1, '2': 2, '3': 3, '4': 4, '5': 5}
SUPPORT = {'1': 2, '2': 2, '3': 2, '4': 1}
FIT_IDS = {'P0': 'synthetic-p0', 'C1': 'synthetic-c1', 'D1': 'synthetic-d1'}


def clone(function, **overrides):
    result = FunctionType(function.__code__, dict(function.__globals__, **overrides),
                          function.__name__, function.__defaults__, function.__closure__)
    result.__kwdefaults__ = function.__kwdefaults__
    return result


def _csv(path, fields, rows):
    with Path(path).open('w', encoding='utf-8', newline='') as stream:
        writer = csv.DictWriter(stream, fieldnames=fields, lineterminator='\n')
        writer.writeheader()
        writer.writerows(rows)


def _jsonlines(path, rows):
    Path(path).write_bytes(b''.join(checkpoint.encoded(row) for row in rows))


def build_fixture(root):
    """Build 48 fresh artificial identities; never call a fit or old fixture."""
    root = Path(root)
    root.mkdir(parents=True, exist_ok=False)
    paths = {name: root / name for name in ('dataset', 'P0', 'C1', 'D1')}
    for folder in paths.values():
        folder.mkdir()
    primary = root / 'primary'
    primary.mkdir()
    database = root / 'model.sqlite'
    config = dict(synthetic_acceptance_only=True,
        schemas={'queries.csv': list(QUERY_FIELDS), 'catalog.csv': list(CATALOG_FIELDS)},
        train_window_ms=[0, 1000], validation_window_ms=[2_000_000, 10_000_000],
        control_fit_ids=deepcopy(FIT_IDS), fixed_validation={'queries': 48})
    model = dict(fit_audit={'fit_id': 'synthetic-k1'}, support=deepcopy(SUPPORT))
    query_rows, references, expected_payloads, ordinals, cohort = [], [], [], [], []
    controls = {name: [] for name in ('ranked_queries.csv', 'query_metrics.csv', 'query_slices.csv')}
    c1_rows, d1_rows = [], []
    db = sqlite3.connect(database)
    try:
        db.execute('CREATE TABLE m(v TEXT,s INTEGER,i TEXT,PRIMARY KEY(v,s,i))')
        db.execute('CREATE TABLE h(v TEXT,s INTEGER,t INTEGER,k INTEGER,role TEXT,items TEXT,n INTEGER,PRIMARY KEY(v,s,t),UNIQUE(v,s,k))')
        for (visitor, session), items in SESSIONS.items():
            db.executemany('INSERT INTO m VALUES(?,?,?)',
                           [(visitor, session, item) for item in sorted(items, key=int)])
        index.build_index(db)
        for ordinal in range(48):
            visitor, session, moment = str(1000+ordinal), 2000+ordinal, 3_000_000+ordinal*10_000
            history = (['1'], ['1', '2'], ['99'])[ordinal % 3]
            targets = (['2'], ['3', '5'], ['5'])[ordinal % 3]
            next_moment = moment+1000
            db.execute('INSERT INTO h VALUES(?,?,?,?,?,?,?)',
                (visitor, session, moment, 1, 'validation', oracle.dump(history), len(history)))
            db.execute('INSERT INTO h VALUES(?,?,?,?,?,?,?)',
                (visitor, session, next_moment, 2, 'validation', oracle.dump(targets), len(targets)))
            key = [visitor, session, moment]
            known = sum(item in SUPPORT for item in targets)
            slices = dict(visitor_history='new',
                current_basket='multiple' if len(history)>1 else 'single',
                target_basket='multiple' if len(targets)>1 else 'single', train_activity='0',
                target_model='all_positive' if known==len(targets) else 'all_zero' if not known else 'mixed')
            identity = dict(key=key, history=list(history),
                history_sha256=hashlib.sha256(oracle.dump(history).encode()).hexdigest(),
                targets=list(targets), candidate_count=5, reachable_targets=len(targets), slices=slices)
            predictions = dict(
                P0=dict(ids=['1', '2', '3', '4', '5'], candidate_count=5),
                C1=dict(fit_id=FIT_IDS['C1'], ids=['2', '3', '1', '4', '5'], candidate_count=5),
                D1=dict(fit_id=FIT_IDS['D1'], ids=['3', '2', '1', '4', '5'], candidate_count=5))
            predictions['K1'] = oracle.predict(SESSIONS, SUPPORT, model['fit_audit']['fit_id'],
                COUNTS, CATALOG, moment, history, (visitor, session), lambda: None)
            binary, precise = {}, {}
            for arm, prediction in predictions.items():
                binary[arm], decimals = oracle.terms(prediction['ids'], targets)
                precise[arm] = {name: str(value) for name, value in decimals.items()}
            delta = {'K1_minus_'+arm: {metric: binary['K1'][metric]-binary[arm][metric]
                     for metric in oracle.METRICS} for arm in ('C1', 'P0', 'D1')}
            expected = dict(identity, predictions=predictions, terms=binary, delta=delta)
            references.append(expected)
            expected_payloads.append(dict(expected=deepcopy(expected), precise=precise,
                delta_hex={arm: {name: value.hex() for name, value in values.items()}
                           for arm, values in delta.items()}))
            c1_rows.append(dict(identity,
                predictions={arm: deepcopy(predictions[arm]) for arm in ('P0', 'C1')},
                terms={arm: deepcopy(binary[arm]) for arm in ('P0', 'C1')}))
            d1_rows.append(dict(identity,
                predictions={arm: deepcopy(predictions[arm]) for arm in ('P0', 'C1', 'D1')},
                terms={arm: deepcopy(binary[arm]) for arm in ('P0', 'C1', 'D1')}))
            base = dict(visitorid=visitor, session_start_ms=str(session), query_ms=str(moment), role='validation')
            controls['ranked_queries.csv'].append(dict(base, fit_id=FIT_IDS['P0'],
                top10_items=oracle.dump(predictions['P0']['ids']),
                top10_scores=oracle.dump([COUNTS.get(item, 0) for item in predictions['P0']['ids']]),
                candidate_count='5'))
            metrics = dict(base, reachable_target_count=str(len(targets)), all_targets_reachable='1')
            for name, value in binary['P0'].items():
                metrics[name] = '' if value is None else str(value)
            controls['query_metrics.csv'].append(metrics)
            controls['query_slices.csv'].append(dict(base, **slices))
            query_rows.append(dict(base, basket_index='1', context_item_occurrences=str(len(history)),
                next_view_ms=str(next_moment), next_role='validation', next_in_session='1', mature='1',
                cross_role='0', status='labelled', candidate_count='5', target_items=oracle.dump(targets),
                target_count=str(len(targets)), reachable_target_count=str(len(targets)), all_targets_reachable='1',
                visitor_seen_before_fit='0', targets_seen_before_fit='unused', train_view_events='0', train_activity_slice='0'))
            original_ordinal = 100+ordinal*2
            ordinals.append(dict(key=key, original_ordinal=original_ordinal, subset_ordinal=ordinal))
            cohort.append(dict(original_ordinal=original_ordinal,
                key_sha256=hashlib.sha256(oracle.dump(key).encode()).hexdigest()))
        db.commit()
    finally:
        db.close()
    _csv(paths['dataset']/'queries.csv', QUERY_FIELDS, query_rows)
    _csv(paths['dataset']/'catalog.csv', CATALOG_FIELDS,
         [dict(itemid=item, first_view_ms=first) for item, first in CATALOG.items()])
    _csv(paths['P0']/'item_counts.csv', oracle.FIELDS['item_counts.csv'],
         [dict(itemid=item, count=count) for item, count in COUNTS.items()])
    for name, values in controls.items():
        _csv(paths['P0']/name, oracle.FIELDS[name], values)
    _jsonlines(paths['C1']/'queries.jsonl', c1_rows)
    _jsonlines(paths['D1']/'queries.jsonl', d1_rows)
    _jsonlines(primary/'queries.jsonl', references)
    (root/'configuration.json').write_bytes(checkpoint.encoded(config))
    (root/'model.json').write_bytes(checkpoint.encoded(model))
    names = [path.relative_to(root).as_posix() for path in root.rglob('*') if path.is_file()]
    binding = dict(sources=checkpoint.bind_sources(root, names), configuration=deepcopy(config),
                   method='v64_new_literal_synthetic_sources_only')
    return dict(root=root, paths=paths, config=config, primary=primary, database=database, model=model,
                ordinals=ordinals, cohort=cohort, binding=binding, expected_payloads=expected_payloads,
                expected_rows=references, literal_sessions=deepcopy(SESSIONS))


class Trace:
    """The identical semantic observer is used by O and D, without clocks."""
    def __init__(self, fail_point=None, fail_at=1, error=None):
        self.fail_point, self.fail_at = fail_point, fail_at
        self.error = error if error is not None else RuntimeError('synthetic injected fault')
        self.events, self.connections, self._hits = [], [], {}
        self._flush_tick = 0
        self.sqlite = SimpleNamespace(connect=self.connect)

    def trip(self, point):
        self._hits[point] = self._hits.get(point, 0)+1
        if self.fail_point == point and self._hits[point] == self.fail_at:
            raise self.error

    def watch(self):
        self.events.append(('watch',))
        self.trip('watch')

    def fault(self, point):
        self.events.append(('fault', point))
        self.trip(point)

    def flush_clock(self):
        self._flush_tick += 1
        return self._flush_tick / 1_000_000

    def connect(self, *args, **kwargs):
        # Both arms receive the same fixture database; preserve the supplied URI.
        self.events.append(('connect', args, dict(kwargs)))
        result = RecordingConnection(sqlite3.connect(*args, **kwargs), self)
        self.connections.append(result)
        return result


def _kind(statement):
    if statement.startswith('SELECT membership.v,membership.s,COUNT(*)'):
        return 'overlap'
    if statement.startswith('SELECT chosen.r,membership.i'):
        return 'votes'
    return 'other'


class RecordingCursor:
    def __init__(self, cursor, owner, number, kind):
        self.cursor, self.owner, self.number, self.kind = cursor, owner, number, kind
        self.calls = 0

    def __iter__(self):
        return self

    def __next__(self):
        self.calls += 1
        self.owner.events.append(('next', self.number, self.kind, self.calls))
        self.owner.trip('next_'+self.kind)
        try:
            row = next(self.cursor)
        except StopIteration:
            self.owner.events.append(('eof', self.number, self.kind, self.calls))
            raise
        self.owner.events.append(('row', self.number, self.kind, row))
        return row

    def fetchone(self):
        self.owner.events.append(('fetchone', self.number, self.kind))
        row = self.cursor.fetchone()
        self.owner.events.append(('fetchone_row', self.number, self.kind, row))
        return row

    def fetchall(self):
        raise AssertionError('Synthetic trace rejects eager fetchall')

    def fetchmany(self, *args, **kwargs):
        raise AssertionError('Synthetic trace rejects fetchmany batching')


class RecordingConnection:
    def __init__(self, connection, trace):
        self.connection, self.trace = connection, trace
        self.closed, self.statements, self.cursors = False, [], []

    def execute(self, statement, *args, **kwargs):
        number = len(self.statements)
        self.statements.append((statement, args, dict(kwargs)))
        self.trace.events.append(('execute', number, statement, args, dict(kwargs)))
        kind = _kind(statement)
        self.trace.trip('execute_'+kind)
        result = RecordingCursor(self.connection.execute(statement, *args, **kwargs), self.trace, number, kind)
        self.cursors.append(result)
        return result

    def set_progress_handler(self, callback, steps):
        self.trace.events.append(('set_progress_handler', steps))
        self.connection.set_progress_handler(callback, steps)

    def close(self):
        self.trace.events.append(('close',))
        self.closed = True
        self.connection.close()


class FakeBudgetClock:
    def utc(self):
        return 1000.0

    def monotonic(self):
        return 50.0


class FakeProcesses:
    def identity(self):
        return dict(pid=123, create_time=950.0, boot_time=800.0)

    def is_alive(self, identity):
        return identity == self.identity()


def create_store(fixture, name, trace, *, chunk_queries=8, flush_clock=None):
    """Real original checkpoint writer, with only its timing reader injected."""
    reader = trace.flush_clock if flush_clock is None else flush_clock
    class SyntheticTimedStore(pair.TimedStore):
        flush_chunk = clone(pair.TimedStore.flush_chunk, perf_counter=reader)
    return SyntheticTimedStore.create(fixture['root']/name, fixture['binding'], 2000.0, 900.0,
        source_root=fixture['root'], expected_queries=48,
        required_stages=('reconstruction', 'queries'), chunk_queries=chunk_queries,
        clock=FakeBudgetClock(), process_api=FakeProcesses(), fault=trace.fault)


def detailed_store_class(clock):
    """Inject every legacy observation clock without changing production globals.

    The diamond deliberately places ClockedTimed after BudgetTimedStore, so its
    original flush_chunk's super() resolves to the cloned V4 timing method.
    Checkpoint budget/identity clocks remain separate explicit create() inputs.
    """
    class ClockedTimed(pair.TimedStore):
        flush_chunk = clone(pair.TimedStore.flush_chunk, perf_counter=clock)

    class ClockedBudget(BudgetTimedStore, ClockedTimed):
        _atomic = clone(BudgetTimedStore._atomic, perf_counter=clock)

    class ClockedDetailed(DetailedTimedStore, ClockedBudget):
        append_verified = clone(DetailedTimedStore.append_verified, perf_counter=clock)

    return ClockedDetailed


def seal_reconstruction(store, fixture):
    store.seal_stage('reconstruction', dict(kind='literal_synthetic_model',
                                          fit_audit=fixture['model']['fit_audit']))


def physical_payload_bytes(store):
    """Read actual committed payload files in manifest order, not re-encoding."""
    result = []
    for manifest_path in sorted((store.folder/'chunks').glob('*.json')):
        manifest = checkpoint.read(manifest_path)
        result.append((store.folder/manifest['payload']['path']).read_bytes())
    return b''.join(result)


class SyntheticPool:
    """Small uncached context collaborator; never loads a real model or sources."""
    def __init__(self, trace):
        self.trace, self.active, self.poisoned = trace, None, False
        self.calls, self.finishes, self.invalidations = [], 0, 0

    def load(self, paths, config, support, watch, **kwargs):
        self.trace.events.append(('pool.load',))
        self.trace.trip('pool_load')
        if config.get('synthetic_acceptance_only') is not True:
            raise ValueError('SyntheticPool only accepts explicitly artificial configuration')
        self.active = True
        self.calls.append(dict(paths=tuple(paths), model=deepcopy(kwargs.get('model'))))
        return pair.core.load_context(paths, config, support, watch)

    def prepare(self, catalog, counts, watch):
        self.trace.events.append(('pool.prepare',))
        self.trace.trip('pool_prepare')
        return ranking.prepare_catalog(catalog, counts, watch)

    def finish(self, observer, watch):
        self.trace.events.append(('pool.finish',))
        self.trace.trip('pool_finish')
        self.finishes += 1
        self.active = None

    def invalidate(self):
        self.trace.events.append(('pool.invalidate',))
        self.invalidations += 1
        self.active, self.poisoned = None, True
