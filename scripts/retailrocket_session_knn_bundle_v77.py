"""V77 sealed artificial bundle admission. No real-data profile or arbitrary paths.

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
METHOD_SEAL = "reports/mainline/v77_tool_seal_20261117.json"
FIXTURE_SEAL = "reports/mainline/v77_fixture_seal_20261117.json"
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


def read_json(path):
    def invalid(value):
        raise SourceAuthorityError("Nonfinite JSON constant: " + value)
    return json.loads(Path(path).read_text(encoding="utf-8"),
                      object_pairs_hook=_object, parse_constant=invalid)


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
    candidates = [name]  # One approved V77 tool/registry identity, no revision fallback.
    for candidate in candidates:
        if not safe_path(ROOT, candidate).is_file():
            continue
        desc = describe(ROOT, candidate)
        if desc["sha256"] == sha and desc["bytes"] <= 4 * 1024 * 1024:
            return read_json(safe_path(ROOT, candidate))
    raise SourceAuthorityError("Sealed registry identity differs")


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
    if seal.get("schema") != "v77_synthetic_tool_seal" or seal.get("real_execution_enabled") is not False:
        raise SourceAuthorityError("Invalid synthetic tool seal")
    if seal.get("runtime") != runtime_identity():
        raise SourceAuthorityError("Runtime differs from sealed preparation")
    inputs = seal.get("preparation_inputs", [])
    if {r["path"] for r in inputs} != {"reports/stage8/retailrocket_build_v1_specification.json"}:
        raise SourceAuthorityError("Required frozen preparation specification missing")
    for row in inputs:
        if describe(ROOT, row["path"]) != row:
            raise SourceAuthorityError("Frozen preparation input changed")
    methods = seal["methods"]
    if len({r["path"] for r in methods}) != len(methods):
        raise SourceAuthorityError("Duplicate method descriptor")
    for row in methods:
        name = _relative(row["path"])
        if not name.startswith(("scripts/", "tests/", "docs/contracts/")):
            raise SourceAuthorityError("Unexpected method root")
        if describe(ROOT, name) != row:
            raise SourceAuthorityError("Method source bytes differ: " + name)
    # Read the current import closure, never use sys.modules as source evidence.
    closure = source_inventory(seal["source_seeds"],
                                      dynamic_seeds=seal.get("dynamic_seeds", ()), root=ROOT)
    supplied = {r["path"]: r for r in methods}
    if any(supplied.get(row["path"]) != row for row in closure):
        raise SourceAuthorityError("Missing or changed direct method source")
    return len(methods)


def _count(value, name, maximum):
    if type(value) is not int or not 1 <= value <= maximum:
        raise SourceAuthorityError("Invalid exact integer: " + name)
    return value


def admit(fixture_id, *, fixture_seal_sha256=None, method_seal_sha256=None):
    """Admit only a registered sealed fixture; validate paths before data reads."""
    if fixture_id not in PROFILES or type(fixture_id) is not str:
        raise SourceAuthorityError("Only registered artificial fixture IDs are accepted")
    fsha = _anchor(fixture_seal_sha256, "V77_FIXTURE_SEAL_SHA256")
    msha = _anchor(method_seal_sha256, "V77_METHOD_SEAL_SHA256")
    registry = _sealed_document(FIXTURE_SEAL, fsha)
    method = _sealed_document(METHOD_SEAL, msha)
    if (registry.get("schema") != "v77_artificial_fixture_registry"
            or registry.get("method_seal_sha256") != msha
            or registry.get("real_execution_enabled") is not False):
        raise SourceAuthorityError("Artificial registry does not bind the tool seal")
    records = registry["fixtures"]
    if len({row["fixture_id"] for row in records}) != len(records):
        raise SourceAuthorityError("Duplicate registered fixture ID")
    matches = [row for row in records if row["fixture_id"] == fixture_id]
    if len(matches) != 1:
        raise SourceAuthorityError("Fixture was not sealed for this acceptance")
    record = matches[0]
    root_name = _relative(record["bundle_root"])
    prefix = "shop-mysql-runtime/v75/fixtures/" + fixture_id
    if root_name != prefix and not root_name.startswith(prefix + "/"):
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
