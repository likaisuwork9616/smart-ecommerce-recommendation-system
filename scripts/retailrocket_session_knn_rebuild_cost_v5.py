"""Measure a fresh independent K1 model reconstruction from frozen sources."""
from datetime import datetime, timezone
import hashlib
from pathlib import Path
import sqlite3
from time import perf_counter, process_time

from scripts import retailrocket_session_knn_readback as oracle
from scripts import retailrocket_session_knn_sql_v4 as sql
from scripts import retailrocket_session_knn_sources_v4 as sources
from scripts.retailrocket_session_knn_checkpoint_v2 import atomic_json, encoded


class _Phases:
    def __init__(self, folder, watch):
        self.folder = folder
        self.force = getattr(watch, 'force', watch)
        self.name = None
        self.results = {}

    def start(self, name):
        if self.name == name:
            return
        self.end()
        self.name = name
        self.wall, self.cpu = perf_counter(), process_time()
        atomic_json(self.folder / (name + '_started.json'), {'phase': name, 'completed': False,
                    'utc': datetime.now(timezone.utc).isoformat()})
        self.force()

    def end(self, error=None):
        if self.name is None:
            return
        info = {'phase': self.name, 'completed': error is None, 'error_type': error,
                'wall_seconds': perf_counter() - self.wall, 'cpu_seconds': process_time() - self.cpu}
        atomic_json(self.folder / (self.name + '_receipt.json'), info)
        self.results[self.name] = info
        self.name = None


# Frozen SQL statements are timing boundaries only. The connection always runs
# the original statement and parameters. No SQL trace expands millions of rows.
_BOUNDARIES = {
    'CREATE INDEX posting ON m(i,v,s)': 'original_posting_index_and_commit',
    'SELECT v,s,i FROM m ORDER BY v,s,i': 'session_map_from_train_memberships',
    'SELECT i,COUNT(*) FROM m GROUP BY i': 'support_and_session_file_check',
    'SELECT v,s FROM m WHERE i=? ORDER BY CAST(v AS INTEGER),s': 'posting_file_check',
    "SELECT v,s,COUNT(*),SUM(n) FROM h WHERE role='train' GROUP BY v,s ORDER BY v,s": 'both_lineage_files_check',
    "SELECT COUNT(*),COALESCE(SUM(n),0) FROM h WHERE role='train'": 'fit_audit_and_fixed_counts_check',
}


class _ObservedDatabase:
    def __init__(self, db, phases):
        self.db = db
        self.phases = phases
        self.executemany = db.executemany
        self.commit = db.commit

    def execute(self, statement, *parameters):
        name = _BOUNDARIES.get(statement)
        if name is not None and self.phases.name != name:
            self.phases.start(name)
        return self.db.execute(statement, *parameters)


def _direct_bindings(primary, paths, records, root):
    original = {row['path']: row for row in records}
    if len(original) != len(records):
        raise ValueError('Duplicate original source descriptor')
    inputs = [paths['dataset'] / 'baskets.csv', paths['C1'] / 'support.csv',
              paths['C1'] / 'train_sessions.jsonl', primary / 'sessions.jsonl',
              primary / 'postings.jsonl', primary / 'train_sessions.jsonl', primary / 'fit_audit.json']
    names = [path.resolve().relative_to(root).as_posix() for path in inputs]
    if len(set(names)) != len(inputs) or not set(names).issubset(original):
        raise ValueError('Incomplete original reconstruction source roster')
    return [original[name] for name in names]


def run_rebuild_cost(folder, primary, paths, config, expected_sources, source_root, watch):
    """Use the frozen V1 reconstruct and V4/V2 build_index in a new namespace.

    Supply the independently pinned original source descriptors and the same
    ThrottledWatch used by the outer deadline/resource supervisor. The outer
    runner also checks the full source and method inventory before and after.
    """
    started = perf_counter()
    folder, primary, root = (Path(p).resolve() for p in (folder, primary, source_root))
    paths = {name: Path(paths[name]).resolve() for name in ('dataset', 'C1')}
    if any(folder.is_relative_to(path) for path in (primary, *paths.values())):
        raise ValueError('Reconstruction output would modify an input namespace')
    required = _direct_bindings(primary, paths, expected_sources, root)
    folder.mkdir(parents=True, exist_ok=False)
    phase_folder = folder / 'phases'
    phase_folder.mkdir()
    phases = _Phases(phase_folder, watch)
    db_path = folder / 'independent.sqlite'
    db = None
    try:
        phases.start('initial_direct_source_hash')
        for record in required:
            sources._check_file(root, record, watch)
        atomic_json(folder / 'source_binding.json', {'sources': required,
            'configuration_sha256': hashlib.sha256(encoded(config)).hexdigest(),
            'scope': 'full_independent_model_reconstruction_only'})

        database_started = perf_counter()
        phases.start('setup_new_database')
        with db_path.open('xb'):
            pass
        db = sqlite3.connect(db_path)
        db.set_progress_handler(lambda: (watch() or 0), 10000)
        pragmas = {p: db.execute('PRAGMA ' + p).fetchone()[0]
                   for p in ('temp_store', 'journal_mode', 'synchronous', 'page_size')}

        phases.start('create_relations_and_ingest_baskets')
        reconstruct_started = perf_counter()
        sessions, support, audit = oracle.reconstruct(_ObservedDatabase(db, phases), primary,
            paths['dataset'], paths['C1'], config, watch)
        reconstruct_seconds = perf_counter() - reconstruct_started
        del sessions

        phases.start('derived_posting_index_and_sizes')
        index_started = perf_counter()
        index = sql.build_index(db, watch)
        index_seconds = perf_counter() - index_started
        oracle.exact(index, {'train_sessions': audit['train_sessions'],
                             'session_item_memberships': audit['distinct_session_item_memberships']})
        phases.start('commit_integrity_check_and_close')
        db.commit()
        if list(db.execute('PRAGMA integrity_check')) != [('ok',)]:
            raise ValueError('Reconstructed SQLite failed integrity_check')
        db.close()
        db = None
        if any(Path(str(db_path) + suffix).exists() for suffix in ('-wal', '-shm', '-journal')):
            raise ValueError('Reconstructed database has an unsealed SQLite journal')
        database_seconds = perf_counter() - database_started

        phases.start('final_direct_source_hash')
        for record in required:
            sources._check_file(root, record, watch)
        phases.start('hash_and_seal_closed_database')
        database_record = sources._descriptor(db_path, folder, watch)
        model = {'fit_audit': audit, 'support': support, 'model_method': 'raw_baskets_SQL_DISTINCT_membership_v2'}
        phases.force()
        atomic_json(folder / 'reconstruction.json', {'receipt': model, 'artifacts': [database_record],
            'status': 'independent_model_reconstructed_and_source_files_checked',
            'source_binding': sources._descriptor(folder / 'source_binding.json', folder, watch)})
        seal_record = sources._descriptor(folder / 'reconstruction.json', folder, watch)
        phases.force()
        phases.end()
        result = {'kind': 'fresh_independent_model_reconstruction_cost_only',
                  'database': database_record, 'reconstruction': seal_record, 'fit_audit': audit,
                  'derived_index_counts': index, 'sqlite_pragmas': pragmas,
                  'direct_source_files_verified_each_pass': len(required),
                  'direct_source_bytes_verified_each_pass': sum(r['bytes'] for r in required),
                  'canonical_reconstruct_wall_seconds': reconstruct_seconds,
                  'canonical_build_index_wall_seconds': index_seconds,
                  'new_database_setup_to_close_wall_seconds': database_seconds,
                  'total_wall_seconds_before_result_publication': perf_counter() - started,
                  'phases': phases.results, 'formal_query_acceptance': False, 'validation_queries_ranked': 0,
                  'bootstrap_draws': 0, 'reserved_test': 'locked', 'full_readback_started': False,
                  'new_primary_fits': 0, 'T_plan': None}
        phases.force()
        atomic_json(folder / 'rebuild_cost.json', result)
        return result
    except BaseException as error:
        phases.end(type(error).__name__)
        atomic_json(folder / 'failure.json', {'status': 'partial_rebuild_cost_evidence',
                    'error_type': type(error).__name__, 'full_readback_started': False,
                    'reserved_test': 'locked', 'T_plan': None})
        raise
    finally:
        if db is not None:
            db.close()
