"""V80 sealed artificial bundle admission. No real-data profile or arbitrary paths.

The caller supplies previously sealed SHA anchors (or the formal runner's env).
Recomputing a local manifest hash is never an admission authority by itself.
"""
from __future__ import annotations

import ast
import hashlib
import importlib.metadata
import json
import os
from pathlib import Path, PurePosixPath
import platform
import sqlite3
import sys

ROOT = Path(__file__).resolve().parents[1]
METHOD_SEAL = "reports/mainline/v80_tool_seal_20261118.json"
FIXTURE_SEAL = "reports/mainline/v80_fixture_seal_20261118.json"
PARENT_FIXTURE_SEAL = "reports/mainline/v77_fixture_seal_20261117.json"
PARENT_FIXTURE_SHA256 = "afa494940682ebd2d52c63ed50dbf8bb00914bb1762eb992b34df9f7f3996353"
CASE_CONTRACT = "docs/contracts/retailrocket_session_knn_cases_v80.json"
PARENT_CASE_CONTRACT = "docs/contracts/retailrocket_session_knn_cases_v77.json"
PARENT_CASE_SHA256 = "86eb3f5120f7cf7f37d788a6801bf2671d616a5c4ca700ffe9a4639e2f970363"
STAGE8_INPUT = "reports/stage8/retailrocket_build_v1_specification.json"
STAGE8_SHA256 = "67dfbf1e5d1a9e8ad0903bcb5c4f8043635b6356f521eda7ce1723b6441fc37c"
SOURCE_SEEDS = (
    "scripts/retailrocket_session_knn_bundle_v80.py",
    "scripts/retailrocket_session_knn_pipeline_v80.py",
    "scripts/retailrocket_session_knn_role_observer_v80.py",
    "scripts/run_retailrocket_session_knn_acceptance_v80.py",
    "scripts/seal_retailrocket_session_knn_preparation_v80.py",
    "scripts/retailrocket_session_knn_full_worker_v75.py",
    "scripts/retailrocket_session_knn_fixtures_v75.py",
    "tests/test_retailrocket_session_knn_full_v80.py",
    "tests/test_retailrocket_session_knn_full_worker_v80.py",
    "tests/test_retailrocket_session_knn_pipeline_v80.py",
)
DYNAMIC_SEEDS = (
    "scripts/retailrocket_session_knn_pipeline_v80.py",
    "scripts/run_retailrocket_session_knn_acceptance_v80.py",
    "tests/test_retailrocket_session_knn_full_v80.py",
    "tests/test_retailrocket_session_knn_full_worker_v80.py",
    "tests/test_retailrocket_session_knn_pipeline_v80.py",
)
PREPARATION_STATUS = "prepared_and_statically_sealed_awaiting_separate_window_authorization"
PROFILES = ("F-small", "F-long", "F-edge")
REQUIRED_STAGES = ("reconstruction", "queries", "global", "bootstrap")
MAX_FILES = 256
MAX_FILE_BYTES = 32 * 1024 * 1024
MAX_BUNDLE_BYTES = 128 * 1024 * 1024


class SourceAuthorityError(ValueError):
    """Unexpected admission/source failures cannot authorize a corrective rerun."""


def encoded(value):
    return (json.dumps(value, sort_keys=True, ensure_ascii=False,
                       separators=(",", ":"), allow_nan=False) + "\n").encode("utf-8")


def _object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise SourceAuthorityError("Duplicate JSON key: " + key)
        result[key] = value
    return result


def _decode_json(data):
    def invalid(value):
        raise SourceAuthorityError("Nonfinite JSON constant: " + value)
    return json.loads(data, object_pairs_hook=_object, parse_constant=invalid)


def read_json(path):
    return _decode_json(Path(path).read_text(encoding="utf-8"))


def _relative(name):
    if (type(name) is not str or not name or "\\" in name or ":" in name
            or PurePosixPath(name).is_absolute()
            or any(part in ("", ".", "..") for part in name.split("/"))):
        raise SourceAuthorityError("Unsafe relative path")
    return name


def safe_path(root, name):
    root = Path(root).resolve()
    path = root / _relative(name)
    resolved = path.resolve()
    if not resolved.is_relative_to(root):
        raise SourceAuthorityError("Path escaped sealed root")
    current = root
    for part in PurePosixPath(name).parts:
        current = current / part
        if current.is_symlink() or getattr(current, "is_junction", lambda: False)():
            raise SourceAuthorityError("Synthetic bundle aliases are not accepted")
    if os.path.normcase(str(path.absolute())) != os.path.normcase(str(resolved)):
        raise SourceAuthorityError("Path alias differs from sealed relative name")
    return path


def describe(root, name):
    path = safe_path(root, name)
    before = path.stat()
    if not path.is_file():
        raise SourceAuthorityError("Bound file is missing")
    with path.open("rb") as stream:
        sha = hashlib.file_digest(stream, "sha256").hexdigest()
    after = path.stat()
    if (before.st_size, before.st_mtime_ns) != (after.st_size, after.st_mtime_ns):
        raise SourceAuthorityError("Source changed while checking identity")
    return {"path": name, "bytes": after.st_size, "sha256": sha}


def _anchor(value, env_name):
    value = value if value is not None else os.environ.get(env_name)
    if (type(value) is not str or len(value) != 64
            or any(c not in "0123456789abcdef" for c in value)):
        raise SourceAuthorityError("Previously sealed SHA anchor required: " + env_name)
    return value


def _sealed_document(name, sha):
    path = safe_path(ROOT, name)
    if not path.is_file():
        raise SourceAuthorityError("Sealed document is missing: " + name)
    with path.open("rb") as stream:
        data = stream.read(4 * 1024 * 1024 + 1)
    if len(data) > 4 * 1024 * 1024 or hashlib.sha256(data).hexdigest() != sha:
        raise SourceAuthorityError("Sealed document identity differs: " + name)
    return _decode_json(data)


def runtime_identity():
    return {"system": platform.system(), "implementation": platform.python_implementation(),
            "python": platform.python_version(), "byteorder": sys.byteorder,
            "numpy": importlib.metadata.version("numpy"),
            "psutil": importlib.metadata.version("psutil"),
            "sqlite_version": sqlite3.sqlite_version}


# New stdlib-only inventory adapted from frozen V34; it reads method text without
# importing its old experiment entries into the candidate process.
def _source_name(name, root):
    path = Path(name)
    if path.is_absolute():
        try:name = path.resolve().relative_to(root).as_posix()
        except ValueError as error:raise SourceAuthorityError('Source seed escaped ROOT') from error
    else:name = path.as_posix()
    name = _relative(name)
    if PurePosixPath(name).parts[0] not in ('scripts', 'tests') or not name.endswith('.py'):
        raise SourceAuthorityError('Explicit scripts/tests Python source seed required')
    path = safe_path(root, name)
    if not path.is_file():
        raise SourceAuthorityError('Missing direct project source: ' + name)
    return name

def source_inventory(seeds, *, dynamic_seeds=(), root=ROOT):
    """Resolve recursive project imports from current bytes, never sys.modules."""
    root = Path(root).resolve()
    pending = {_source_name(name, root) for name in (*seeds, *dynamic_seeds)}
    records = {}; parsed = {}; processed = set()

    def load(name):
        if name not in parsed:
            data = safe_path(root, name).read_bytes()
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
            raise SourceAuthorityError('Ambiguous project module source: ' + name)
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
            raise SourceAuthorityError('Missing direct project import: ' + name)
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
                    if node.level > len(package):raise SourceAuthorityError('Relative import escaped project package')
                    prefix = package[:len(package) - node.level + 1]
                    target = '.'.join(prefix + ([] if node.module is None else node.module.split('.')))
                else:target = node.module or ''
                source, is_package = module(target)
                if target.split('.')[0] in ('scripts', 'tests') and is_package:
                    if any(alias.name == '*' for alias in node.names):
                        raise SourceAuthorityError('Project star imports require an explicit source declaration')
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
                            raise SourceAuthorityError('Relative dynamic imports require an explicit resolved project module')
                        if target.startswith(('scripts.', 'tests.')):module(target)
                    elif not dynamic_seeds:
                        raise SourceAuthorityError('Nonliteral dynamic import requires explicit source seeds')
    result = [records[name] for name in sorted(records)]
    for record in result:
        if describe(root, record["path"]) != record:
            raise SourceAuthorityError("Method changed during closure inspection")
    return result


def _verify_methods(seal):
    if (seal.get("schema") != "v80_synthetic_tool_seal"
            or seal.get("status") != PREPARATION_STATUS
            or seal.get("formal_execution_authorized") is not False
            or seal.get("real_execution_enabled") is not False):
        raise SourceAuthorityError("Invalid synthetic tool seal")
    if seal.get("runtime") != runtime_identity():
        raise SourceAuthorityError("Runtime differs from sealed preparation")
    inputs = seal.get("preparation_inputs", [])
    if (len(inputs) != 1 or inputs[0].get("path") != STAGE8_INPUT
            or inputs[0].get("sha256") != STAGE8_SHA256):
        raise SourceAuthorityError("Required frozen preparation specification missing")
    for row in inputs:
        if describe(ROOT, row["path"]) != row:
            raise SourceAuthorityError("Frozen preparation input changed")
    methods = seal["methods"]
    if len({r["path"] for r in methods}) != len(methods):
        raise SourceAuthorityError("Duplicate method descriptor")
    if (seal.get("source_seeds") != list(SOURCE_SEEDS)
            or seal.get("dynamic_seeds") != list(DYNAMIC_SEEDS)):
        raise SourceAuthorityError("Required static and dynamic source seeds differ")
    for row in methods:
        name = _relative(row["path"])
        if not name.startswith(("scripts/", "tests/", "docs/contracts/")):
            raise SourceAuthorityError("Unexpected method root")
        if describe(ROOT, name) != row:
            raise SourceAuthorityError("Method source bytes differ: " + name)
    # Read the current import closure, never use sys.modules as source evidence.
    closure = source_inventory(SOURCE_SEEDS, dynamic_seeds=DYNAMIC_SEEDS, root=ROOT)
    supplied = {r["path"]: r for r in methods}
    current_case = describe(ROOT, CASE_CONTRACT)
    parent_case = describe(ROOT, PARENT_CASE_CONTRACT)
    if (parent_case["sha256"] != PARENT_CASE_SHA256
            or seal.get("case_contract") != current_case
            or seal.get("parent_case_contract") != parent_case):
        raise SourceAuthorityError("Case catalog does not preserve its original binding")
    exact = {r["path"]: r for r in (*closure, current_case, parent_case)}
    if supplied != exact:
        raise SourceAuthorityError("Missing, unexpected or changed direct method source")
    return len(methods)


def _count(value, name, maximum):
    if type(value) is not int or not 1 <= value <= maximum:
        raise SourceAuthorityError("Invalid exact integer: " + name)
    return value


def admit(fixture_id, *, fixture_seal_sha256=None, method_seal_sha256=None):
    """Admit only a registered sealed fixture; validate paths before data reads."""
    if fixture_id not in PROFILES or type(fixture_id) is not str:
        raise SourceAuthorityError("Only registered artificial fixture IDs are accepted")
    fsha = _anchor(fixture_seal_sha256, "V80_FIXTURE_SEAL_SHA256")
    msha = _anchor(method_seal_sha256, "V80_METHOD_SEAL_SHA256")
    registry = _sealed_document(FIXTURE_SEAL, fsha)
    method = _sealed_document(METHOD_SEAL, msha)
    if (registry.get("schema") != "v80_artificial_fixture_registry"
            or registry.get("method_seal_sha256") != msha
            or registry.get("formal_execution_authorized") is not False
            or registry.get("real_execution_enabled") is not False):
        raise SourceAuthorityError("Artificial registry does not bind the tool seal")
    parent_descriptor = describe(ROOT, PARENT_FIXTURE_SEAL)
    if (parent_descriptor["sha256"] != PARENT_FIXTURE_SHA256
            or registry.get("parent_fixture_registry") != parent_descriptor):
        raise SourceAuthorityError("Original fixture registry identity differs")
    parent = _sealed_document(PARENT_FIXTURE_SEAL, PARENT_FIXTURE_SHA256)
    if (registry.get("fixtures") != parent["fixtures"]
            or registry.get("verified_source_descriptors") != parent["verified_source_descriptors"]):
        raise SourceAuthorityError("Artificial registry changed original golden or input descriptors")
    records = registry["fixtures"]
    if len({row["fixture_id"] for row in records}) != len(records):
        raise SourceAuthorityError("Duplicate registered fixture ID")
    matches = [row for row in records if row["fixture_id"] == fixture_id]
    if len(matches) != 1:
        raise SourceAuthorityError("Fixture was not sealed for this acceptance")
    record = matches[0]
    root_name = _relative(record["bundle_root"])
    prefix = "shop-mysql-runtime/v75/fixtures/" + fixture_id
    if root_name != prefix:
        raise SourceAuthorityError("Fixture root outside registered artificial namespace")
    bundle_root = safe_path(ROOT, root_name)
    mdesc = record["manifest"]
    if mdesc["path"] != root_name + "/manifest.json":
        raise SourceAuthorityError("Unexpected manifest location")
    if describe(ROOT, mdesc["path"]) != mdesc or mdesc["bytes"] > 1024 * 1024:
        raise SourceAuthorityError("Fixture manifest differs from presealed registry")
    manifest = read_json(safe_path(ROOT, mdesc["path"]))
    if (manifest.get("schema") != "v75_artificial_bundle"
            or manifest.get("profile") != "synthetic_only"
            or manifest.get("fixture_id") != fixture_id
            or manifest.get("generator") != "scripts/retailrocket_session_knn_fixtures_v75.py"
            or manifest.get("oracle") != "scripts/retailrocket_session_knn_readback.py"):
        raise SourceAuthorityError("Fixture authority/profile differs")
    n = _count(manifest.get("expected_queries"), "queries", 129)
    visitors = _count(manifest.get("expected_visitors"), "visitors", n)
    if type(manifest.get("bootstrap_replicates")) is not int or manifest["bootstrap_replicates"] != 2000:
        raise SourceAuthorityError("Original 2000 artificial draws required")
    if fixture_id == "F-long" and (n, visitors) != (129, 3):
        raise SourceAuthorityError("Long fixture must keep its 129/3 frozen shape")
    config = manifest["configuration"]
    if (config.get("synthetic_acceptance_only") is not True
            or type(config["fixed_validation"]["queries"]) is not int
            or config["fixed_validation"]["queries"] != n
            or type(config["fixed_validation"]["visitors"]) is not int
            or config["fixed_validation"]["visitors"] != visitors):
        raise SourceAuthorityError("Configuration count/profile differs from sealed manifest")
    if set(manifest["paths"]) != {"dataset", "P0", "C1", "D1"}:
        raise SourceAuthorityError("Four explicit source roles required")
    folders = dict(manifest["paths"], primary=manifest["primary"])
    if len(set(folders.values())) != 5:
        raise SourceAuthorityError("Source roles must use distinct folders")
    for name in folders.values():
        safe_path(bundle_root, name)
    gold = manifest["golden_records"]
    reference = manifest["reference"]
    safe_path(bundle_root, gold); safe_path(bundle_root, reference)
    sources = manifest["sources"]
    if not 1 <= len(sources) <= MAX_FILES or len({r["path"] for r in sources}) != len(sources):
        raise SourceAuthorityError("Invalid source roster")
    total = 0
    for row in sources:
        name = _relative(row["path"]); path = safe_path(bundle_root, name)
        if type(row["bytes"]) is not int or not 0 <= row["bytes"] <= MAX_FILE_BYTES:
            raise SourceAuthorityError("Artificial file size outside sealed preparation limits")
        total += row["bytes"]
        role = row["role"]
        if role in folders:
            if not name.startswith(folders[role] + "/"):
                raise SourceAuthorityError("File is outside its declared source role")
        elif role == "golden":
            if name != gold: raise SourceAuthorityError("Unexpected golden artifact")
        elif role == "reference":
            if name != reference: raise SourceAuthorityError("Unexpected reference artifact")
        elif role == "configuration":
            if name != "configuration.json": raise SourceAuthorityError("Unexpected configuration artifact")
        else:
            raise SourceAuthorityError("Unknown artificial source role")
        if path.exists() and path.stat().st_nlink > 1:
            raise SourceAuthorityError("Hardlinked artificial files are not accepted")
    if total > MAX_BUNDLE_BYTES:
        raise SourceAuthorityError("Artificial bundle exceeds preparation size limit")
    names = {r["path"] for r in sources}
    actual = set()
    for path in bundle_root.rglob("*"):
        rel = path.relative_to(bundle_root).as_posix()
        safe_path(bundle_root, rel)
        if path.is_file() and rel != "manifest.json": actual.add(rel)
    if actual != names or gold not in names or reference not in names:
        raise SourceAuthorityError("Artificial file roster is incomplete or has extra files")
    _verify_methods(method)
    for row in sources:
        expected = {k: row[k] for k in ("path", "bytes", "sha256")}
        if describe(bundle_root, row["path"]) != expected:
            raise SourceAuthorityError("Artificial input bytes differ from presealed source")
    if "configuration.json" in names and read_json(bundle_root / "configuration.json") != config:
        raise SourceAuthorityError("Configuration file differs from manifest")
    binding = {"profile": "synthetic_only", "fixture_id": fixture_id,
               "expected_queries": n, "expected_visitors": visitors,
               "bootstrap_replicates": 2000, "configuration": config,
               "sources": [{k: r[k] for k in ("path", "bytes", "sha256")} for r in sources],
               "method_seal_sha256": msha, "fixture_seal_sha256": fsha}
    return {"manifest": manifest, "binding": binding, "config": config,
            "bundle_root": bundle_root, "primary": bundle_root / manifest["primary"],
            "paths": {k: bundle_root / v for k, v in manifest["paths"].items()},
            "admission": {"fixture_id": fixture_id, "fixture_seal_sha256": fsha,
                          "method_seal_sha256": msha}}


def recheck(admitted):
    """Repeat all source checks at the original CP and two publisher positions."""
    checked = admit(**admitted["admission"])
    for field in ("manifest", "binding", "config", "bundle_root", "primary", "paths"):
        if checked[field] != admitted[field]:
            raise SourceAuthorityError("Admitted request/context changed: " + field)
    return len(checked["binding"]["sources"])
