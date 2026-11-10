"""Quiet entry checks, stopped log sealing, and explicit on-disk Python sources.

This module has no measurement entry point and permits no log-content exception.
"""
import ast
from contextlib import redirect_stderr, redirect_stdout
from datetime import datetime
import hashlib
from io import StringIO
import json
import math
from pathlib import Path, PurePosixPath

import psutil

from scripts import run_retailrocket_session_knn_sources_v25 as old


ROOT = Path(__file__).resolve().parents[1]
PRIORITY_SOURCE = 'scripts/retailrocket_session_knn_priority_v23.py'
# These modules supply functions/modules reached through clone globals, ORIGINALS,
# and module attributes. Callers must seal this explicit declaration with seeds.
DYNAMIC_TARGET_SEEDS = (
    'scripts/retailrocket_session_knn_checkpoint_v2.py',
    'scripts/retailrocket_session_knn_pair_v4.py',
    'scripts/retailrocket_session_knn_readback.py',
    'scripts/retailrocket_session_knn_readback_v2.py',
    'scripts/retailrocket_popularity_oracle.py',
    'scripts/retailrocket_session_knn_sql_v2.py',
    'scripts/retailrocket_session_knn_sql_v4.py',
    'scripts/run_retailrocket_session_knn_overlap_v22.py',
    PRIORITY_SOURCE,
    'scripts/retailrocket_session_knn_sources_v24.py',
    'scripts/retailrocket_session_knn_reuse_v27.py',
    'scripts/retailrocket_session_knn_compare_v28.py',
    'scripts/run_retailrocket_session_knn_compare_v28.py',
    'scripts/retailrocket_session_knn_snapshot_v30.py',
    'scripts/retailrocket_session_knn_snapshot_adapter_v30.py',
    'scripts/run_retailrocket_session_knn_compare_v31.py',
)
ACTIVE_LOG_NAMES = ('stdout_stderr.log', 'publisher.log')
PUBLISHER_OUTPUT_NAMES = (
    'audited_result.json', 'publisher/events.json', 'publisher/observation.json',
    'publisher/entry_span.json', 'publisher/telemetry_records.json',
)
POST_PUBLISHER_NAMES = (
    'supervisor_completion.json', 'tracked_process_identities.json',
    'pipeline_done.json', 'publisher_exit.json', *PUBLISHER_OUTPUT_NAMES,
)


def quiet_contract(function, *args, **kwargs):
    """Return (value, diagnostics) without leaking buffered parent audit output."""
    captured = StringIO()
    with redirect_stdout(captured), redirect_stderr(captured):
        value = function(*args, **kwargs)
    return value, captured.getvalue()


def _relative(name):
    if (type(name) is not str or not name or '\\' in name or ':' in name
            or '\x00' in name):
        raise ValueError('Canonical ROOT-relative path required')
    path = PurePosixPath(name)
    if path.is_absolute() or any(p in ('.', '..') for p in path.parts) or path.as_posix() != name:
        raise ValueError('Canonical ROOT-relative path required')
    return name


def _inside(root, name):
    root = Path(root).resolve()
    path = (root / _relative(name)).resolve()
    if not path.is_relative_to(root):
        raise ValueError('Project source/evidence escaped ROOT')
    return path


def _describe(path, root):
    path = Path(path)
    data = path.read_bytes()
    return dict(path=path.relative_to(Path(root).resolve()).as_posix(),
                bytes=len(data), sha256=hashlib.sha256(data).hexdigest())


def _index(records):
    result = {}
    for record in records:
        if (type(record) is not dict or set(record) != {'path', 'bytes', 'sha256'}
                or type(record['bytes']) is not int or record['bytes'] < 0
                or type(record['sha256']) is not str or len(record['sha256']) != 64
                or any(c not in '0123456789abcdef' for c in record['sha256'])):
            raise ValueError('Exact source descriptor required')
        name = _relative(record['path'])
        if name in result:
            raise ValueError('Duplicate source descriptor')
        result[name] = dict(record)
    return result


def _verify(records, root):
    for name, record in _index(records).items():
        if _describe(_inside(root, name), root) != record:
            raise ValueError('Direct source or sealed evidence bytes changed: ' + name)


def _manifest(folder, root, excluded=()):
    root = Path(root).resolve(); folder = Path(folder).resolve()
    if not folder.is_relative_to(root):
        raise ValueError('Window must be inside ROOT')
    excluded = set(excluded); records = []
    for path in sorted(folder.rglob('*')):
        if path.is_symlink():
            raise ValueError('Window symlinks are not a closed file inventory')
        if path.is_file() and path not in excluded:
            records.append(_describe(path, root))
    return records


def publisher_evidence(folder, *, root=ROOT):
    """Seal existing files except the two exact streams still owned by writers."""
    folder = Path(folder).resolve(); root = Path(root).resolve()
    excluded = tuple(folder / name for name in ACTIVE_LOG_NAMES)
    if any(not path.is_file() or path.is_symlink() for path in excluded):
        raise ValueError('Both active outer and publisher streams must exist')
    return _manifest(folder, root, excluded)


def _read(path):
    return json.loads(Path(path).read_text(encoding='utf-8'))


def _identity(value):
    return (type(value.get('pid')) is int and value['pid'] > 0
            and type(value.get('create_time')) in (int, float)
            and math.isfinite(value['create_time']) and value['create_time'] > 0)


def _stopped(folder, request, completion, exits):
    if (_read(folder / 'request.json') != request
            or _read(folder / 'supervisor_completion.json') != completion
            or set(exits) != {'worker', 'publisher'}):
        raise ValueError('Stopped window arguments differ from saved identities')
    old._check_window(request, completion)
    if _read(folder / 'pipeline_done.json') != dict(completed=True):
        raise ValueError('Pipeline is not complete')
    actual = {kind: old.child_exit(folder, request, kind) for kind in ('worker', 'publisher')}
    if actual != exits or any(not _identity(value) for value in actual.values()):
        raise ValueError('Exact normal child identities required')
    if (actual['worker']['ended_utc'] > actual['publisher']['started_utc']
            or datetime.fromisoformat(actual['publisher']['ended_utc'])
            > datetime.fromisoformat(completion['actual_exit_observed_utc'])):
        raise ValueError('Publisher/worker/supervisor exit order changed')
    tracked = _read(folder / 'tracked_process_identities.json')
    identities = tracked['identities']
    if (tracked.get('live_after_cleanup') != 0 or not identities
            or completion.get('tracked_processes') != len(identities)
            or any(not _identity(value) for value in identities)):
        raise ValueError('Complete stopped tracked identities required')
    pairs = [(value['pid'], value['create_time']) for value in identities]
    if len(set(pairs)) != len(pairs):
        raise ValueError('Duplicate tracked identity')
    pipeline = _read(folder / 'worker_identity.json')
    if not _identity(pipeline):
        raise ValueError('Original top-level pipeline identity required')
    for value in [pipeline, *actual.values()]:
        if (value['pid'], value['create_time']) not in pairs:
            raise ValueError('A writer identity is outside supervisor tracking')
    for pid, created in pairs:
        try:
            process = psutil.Process(pid)
            if process.is_running() and process.create_time() == created:
                raise ValueError('Original log-writing process is still alive')
        except psutil.NoSuchProcess:
            pass


def closed_log_manifest(folder, request, completion, exits, *, expected=None, root=ROOT):
    """First seal or exactly re-audit all files after the original writers stop."""
    root = Path(root).resolve(); folder = Path(folder).resolve()
    _stopped(folder, request, completion, exits)
    before = _manifest(folder, root)
    full = _index(before)
    active = [(folder / name).relative_to(root).as_posix() for name in ACTIVE_LOG_NAMES]
    if any(name not in full for name in active):
        raise ValueError('Both final active-log descriptors are required')
    result = _read(folder / 'audited_result.json')
    published = _index(result['evidence'])
    if any(name in published for name in active):
        raise ValueError('Publisher attempted to seal an active log stream')
    prefix = folder.relative_to(root).as_posix() + '/'
    if any(not name.startswith(prefix) or full.get(name) != record for name, record in published.items()):
        raise ValueError('Publisher-sealed file is missing or changed')
    _verify(list(published.values()), root)
    permitted = {prefix + name for name in POST_PUBLISHER_NAMES}
    if set(full) - set(published) - set(active) - permitted:
        raise ValueError('An undeclared post-publisher file appeared')
    expected_outputs = [prefix + name for name in PUBLISHER_OUTPUT_NAMES]
    outputs = _index(exits['publisher'].get('outputs', ()))
    if list(outputs) != expected_outputs or any(full.get(name) != record for name, record in outputs.items()):
        raise ValueError('All five exact publisher output seals are required')
    _verify(list(outputs.values()), root)
    if 'outputs' in exits['worker']:
        _verify(exits['worker']['outputs'], root)
    _stopped(folder, request, completion, exits)
    after = _manifest(folder, root)
    if after != before:
        raise ValueError('Window changed while final logs were being sealed')
    result = dict(status='v34_stopped_logs_and_complete_window_sealed',
                  active_log_exclusions=active,
                  final_logs=[record for record in after if record['path'].endswith('.log')],
                  window_evidence=after)
    if expected is not None and result != expected:
        raise ValueError('Post-seal file set or bytes changed')
    return result


def _source_name(name, root):
    path = Path(name)
    if path.is_absolute():
        try:name = path.resolve().relative_to(root).as_posix()
        except ValueError as error:raise ValueError('Source seed escaped ROOT') from error
    else:name = path.as_posix()
    name = _relative(name)
    if PurePosixPath(name).parts[0] not in ('scripts', 'tests') or not name.endswith('.py'):
        raise ValueError('Explicit scripts/tests Python source seed required')
    path = _inside(root, name)
    if not path.is_file():
        raise ValueError('Missing direct project source: ' + name)
    return name


def source_inventory(seeds, *, dynamic_seeds=(), root=ROOT):
    """Resolve recursive project imports from current bytes, never sys.modules."""
    root = Path(root).resolve()
    pending = {_source_name(name, root) for name in (*seeds, *dynamic_seeds, PRIORITY_SOURCE)}
    records = {}; parsed = {}; processed = set()

    def load(name):
        if name not in parsed:
            data = _inside(root, name).read_bytes()
            records[name] = dict(path=name, bytes=len(data), sha256=hashlib.sha256(data).hexdigest())
            parsed[name] = ast.parse(data, filename=name)
        return parsed[name]

    def module(name, required=True):
        parts = name.split('.')
        if not parts or parts[0] not in ('scripts', 'tests'):
            return None, False
        base = root.joinpath(*parts)
        candidates = [path for path in (base.with_suffix('.py'), base / '__init__.py') if path.is_file()]
        if len(candidates) > 1:
            raise ValueError('Ambiguous project module source: ' + name)
        if candidates:
            path = candidates[0];relative = _source_name(path, root)
            pending.add(relative)
            for i in range(1, len(parts)):
                parent = root.joinpath(*parts[:i]) / '__init__.py'
                if parent.is_file():pending.add(_source_name(parent, root))
            return relative, path.name == '__init__.py'
        if base.is_dir():
            return None, True  # PEP420 namespace; its imported children are explicit.
        if required:
            raise ValueError('Missing direct project import: ' + name)
        return None, False

    def exports(name):
        if name is None:return set()
        names = set()
        for node in load(name).body:
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):names.add(node.name)
            elif isinstance(node, (ast.Import, ast.ImportFrom)):
                names.update(alias.asname or alias.name.split('.')[0] for alias in node.names)
            elif isinstance(node, (ast.Assign, ast.AnnAssign)):
                targets = node.targets if isinstance(node, ast.Assign) else [node.target]
                for target in targets:
                    names.update(value.id for value in ast.walk(target) if isinstance(value, ast.Name))
        return names

    while pending:
        name = min(pending);pending.remove(name)
        if name in processed:continue
        tree = load(name);processed.add(name)
        parts = list(PurePosixPath(name).with_suffix('').parts)
        package = parts[:-1]
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:module(alias.name)
            elif isinstance(node, ast.ImportFrom):
                if node.level:
                    if node.level > len(package):raise ValueError('Relative import escaped project package')
                    prefix = package[:len(package) - node.level + 1]
                    target = '.'.join(prefix + ([] if node.module is None else node.module.split('.')))
                else:target = node.module or ''
                source, is_package = module(target)
                if target.split('.')[0] in ('scripts', 'tests') and is_package:
                    if any(alias.name == '*' for alias in node.names):
                        raise ValueError('Project star imports require an explicit source declaration')
                    known = exports(source)
                    for alias in node.names:
                        if alias.name != '*' and alias.name not in known:
                            module(target + '.' + alias.name)
            elif isinstance(node, ast.Call):
                dynamic = (isinstance(node.func, ast.Name) and node.func.id == '__import__'
                           or isinstance(node.func, ast.Attribute) and node.func.attr == 'import_module')
                if dynamic:
                    if node.args and isinstance(node.args[0], ast.Constant) and type(node.args[0].value) is str:
                        target = node.args[0].value
                        if target.startswith('.'):
                            raise ValueError('Relative dynamic imports require an explicit resolved project module')
                        if target.startswith(('scripts.', 'tests.')):module(target)
                    elif not dynamic_seeds:
                        raise ValueError('Nonliteral dynamic import requires explicit source seeds')
    result = [records[name] for name in sorted(records)]
    _verify(result, root)
    return result


def merge_methods(existing, direct):
    """Append direct methods while preserving every exact existing descriptor."""
    merged = _index(existing)
    for name, record in _index(direct).items():
        if name in merged and merged[name] != record:
            raise ValueError('Conflicting original/direct method descriptor: ' + name)
        merged[name] = record
    return [merged[name] for name in sorted(merged)]


def require_direct_sources(methods, inventory, *, root=ROOT):
    """Require every direct method in the complete bound source inventory.

    ``methods`` is the required direct-method roster; ``inventory`` is the full
    request source binding and may also contain large datasets. Only the method
    bytes are reread here; the original full-data source passes remain separate.
    """
    required = _index(methods);bound = _index(inventory)
    if PRIORITY_SOURCE not in required:
        raise ValueError('priority_v23 must be a direct project source')
    if any(bound.get(name) != record for name, record in required.items()):
        raise ValueError('A required direct project source is missing or conflicting')
    _verify(list(required.values()), root)
    return [required[name] for name in sorted(required)]
