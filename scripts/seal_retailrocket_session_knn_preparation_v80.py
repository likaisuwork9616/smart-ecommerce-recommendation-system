"""Build V80 preparation seals from saved bytes, without project imports.

With --write, create the two public receipts exclusively. This command does
not generate fixtures, load the suite, or issue formal-window authorization.
"""
from __future__ import annotations

import argparse
import ast
import hashlib
import json
import os
from pathlib import Path, PurePosixPath


ROOT = Path(__file__).resolve().parents[1]
BUNDLE = "scripts/retailrocket_session_knn_bundle_v80.py"
RUNNER = "scripts/run_retailrocket_session_knn_acceptance_v80.py"
PARENT_METHOD = "reports/mainline/v77_tool_seal_20261117.json"
PARENT_METHOD_SHA = "49668e4cd23a48759b4337eefd14dfb5c2b32e4204c3d0ed860f61abc22936e7"
PLAN = "reports/mainline/v79_role_exit_integration_proposal_20261117.json"
PLAN_SHA = "8045ddd0657b9a49166d3a68173d2c7c919cad82cfbc38fa51063a40ffd617ec"
DATE = "2026-11-18"


def _source(path):
    return ast.parse(path.read_bytes(), filename=str(path))


def _static_helpers(path, *, names, constants, namespace):
    """Read only the named file/AST helpers and literal constants."""
    tree = _source(path)
    selected = []
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.ClassDef)) and node.name in names:
            if node.decorator_list or any(isinstance(item, (ast.Import, ast.ImportFrom))
                                          for item in ast.walk(node)):
                raise ValueError("Static helper gained a decorator or import: " + node.name)
            selected.append(node)
        elif isinstance(node, ast.Assign) and len(node.targets) == 1:
            target = node.targets[0]
            if isinstance(target, ast.Name) and target.id in constants:
                namespace[target.id] = ast.literal_eval(node.value)
    if ({node.name for node in selected} != set(names)
            or len(selected) != len(names) or not set(constants).issubset(namespace)):
        raise ValueError("Required static source helpers differ")
    # Load only file/AST routines. Never execute the bundle or runner module body.
    fragment = ast.Module(body=selected, type_ignores=[])
    exec(compile(fragment, str(path), "exec"), namespace)
    return namespace


def _bundle_static():
    return _static_helpers(ROOT / BUNDLE, names={
        "SourceAuthorityError", "_object", "_decode_json", "read_json", "_relative",
        "safe_path", "describe", "_source_name", "source_inventory",
    }, constants={
        "SOURCE_SEEDS", "DYNAMIC_SEEDS", "METHOD_SEAL", "FIXTURE_SEAL", "CASE_CONTRACT",
        "PARENT_CASE_CONTRACT", "PARENT_CASE_SHA256", "PARENT_FIXTURE_SEAL",
        "PARENT_FIXTURE_SHA256", "STAGE8_INPUT", "STAGE8_SHA256", "PREPARATION_STATUS",
    }, namespace={"ROOT": ROOT, "Path": Path, "PurePosixPath": PurePosixPath,
                  "os": os, "ast": ast, "hashlib": hashlib, "json": json})


def _verify_bound(receipt, name, sha, static):
    descriptor = static["describe"](ROOT, name)
    if descriptor["sha256"] != sha:
        raise ValueError("Frozen source descriptor changed: " + name)
    value = static["read_json"](ROOT / name) if receipt else None
    if static["describe"](ROOT, name) != descriptor:
        raise ValueError("Frozen source changed while reading: " + name)
    return descriptor, value


def _verify_runtime_target(parent, static):
    target = parent["runtime"]
    if target != {"system": "Windows", "implementation": "CPython", "python": "3.12.10",
                  "byteorder": "little", "numpy": "2.5.4", "psutil": "7.2.2",
                  "sqlite_version": "3.49.1"}:
        raise ValueError("Unexpected saved V77 runtime target")

    paths = [".venv/pyvenv.cfg",
             ".venv/Lib/site-packages/numpy-2.5.4.dist-info/METADATA",
             ".venv/Lib/site-packages/psutil-7.2.2.dist-info/METADATA"]
    cfg = static["safe_path"](ROOT, paths[0]).read_text(encoding="utf-8")
    declarations = [value.strip() for line in cfg.splitlines()
                    for key, separator, value in (line.partition("="),)
                    if separator and key.strip() == "version"]
    if declarations != [target["python"]]:
        raise ValueError("Static venv Python declaration differs")
    for package, path in zip(("numpy", "psutil"), paths[1:], strict=True):
        metadata = static["safe_path"](ROOT, path).read_text(encoding="utf-8")
        headers = metadata.split("\n\n", 1)[0].splitlines()
        versions = [line.removeprefix("Version: ").strip() for line in headers
                    if line.startswith("Version: ")]
        if versions != [target[package]]:
            raise ValueError("Static package declaration differs: " + package)
    return target, [static["describe"](ROOT, name) for name in paths]


def _validate_catalog(catalog, parent, static):
    helpers = _static_helpers(ROOT / RUNNER, names={"validate_catalog"},
                              constants={"PARENT_CATALOG", "PARENT_CATALOG_SHA256"},
                              namespace={"ROOT": ROOT, "hashlib": hashlib, "json": json})
    facts = helpers["validate_catalog"](catalog)
    if catalog.get("real_execution_enabled") is not False:
        raise ValueError("Case catalog must remain synthetic only")
    if catalog.get("fixture_profiles") != parent.get("fixture_profiles"):
        raise ValueError("Original artificial profiles changed")
    for entry in catalog["modules"]:
        path = static["safe_path"](ROOT, entry["path"])
        tree = _source(path)
        module = ".".join(PurePosixPath(entry["path"]).with_suffix("").parts)
        declarations = [f"{module}.{cls.name}.{method.name}"
                        for cls in tree.body if isinstance(cls, ast.ClassDef)
                        for method in cls.body if isinstance(method, ast.FunctionDef)
                        and method.name.startswith("test_")]
        if sorted(declarations) != sorted(entry["required_test_ids"]):
            raise ValueError("V80 static test declarations differ from catalog: " + entry["path"])
    base = "tests/test_retailrocket_session_knn_full_"
    original = (ROOT / (base + "v77.py")).read_bytes().replace(b"v77", b"v80").replace(b"V77", b"V80")
    names = {"test_A09_sealed_database_and_source_integrity", "_missing_database_rejection"}

    def a09(data):
        return {method.name: ast.dump(method)
                for node in ast.parse(data).body if isinstance(node, ast.ClassDef)
                for method in node.body if isinstance(method, ast.FunctionDef) and method.name in names}

    original_a09 = a09(original)
    if set(original_a09) != names or a09((ROOT / (base + "v80.py")).read_bytes()) != original_a09:
        raise ValueError("The frozen A09 refusal and evidence assertions changed")
    return facts


def _check_original_fixtures(registry, static):
    fixtures = registry["fixtures"]
    expected_roster = registry["verified_source_descriptors"]
    expected_by_name = {row["path"]: row for row in expected_roster}
    if (tuple(item["fixture_id"] for item in fixtures) != ("F-small", "F-long", "F-edge")
            or len(expected_by_name) != len(expected_roster) or len(expected_roster) != 78):
        raise ValueError("Original fixture roster differs from 3 bundles / 78 files")
    actual = {}
    for record in fixtures:
        prefix = record["bundle_root"]
        path = static["safe_path"](ROOT, prefix)
        manifest = record["manifest"]
        if (prefix != "shop-mysql-runtime/v75/fixtures/" + record["fixture_id"]
                or manifest["path"] != prefix + "/manifest.json"
                or static["describe"](ROOT, manifest["path"]) != manifest):
            raise ValueError("Original fixture manifest differs")
        manifest_row = static["read_json"](ROOT / manifest["path"])
        names = sorted(entry.relative_to(path).as_posix() for entry in path.rglob("*")
                       if static["safe_path"](path, entry.relative_to(path).as_posix()).is_file())
        declared = [row["path"] for row in manifest_row["sources"]]
        if names != sorted(["manifest.json", *declared]) or len(declared) != record["files"]:
            raise ValueError("Original fixture manifest and directory rosters differ")
        for row in manifest_row["sources"]:
            key = prefix + "/" + row["path"]
            descriptor = static["describe"](ROOT, key)
            if (descriptor != expected_by_name.get(key) or descriptor["bytes"] != row["bytes"]
                    or descriptor["sha256"] != row["sha256"]):
                raise ValueError("Original fixture payload descriptor changed: " + key)
            if static["safe_path"](ROOT, key).stat().st_nlink != 1:
                raise ValueError("Original fixture contains a hardlink alias")
            actual[key] = descriptor
        if sum(actual[prefix + "/" + name]["bytes"] for name in declared) != record["bytes"]:
            raise ValueError("Original fixture bytes disagree with frozen aggregate")
    if actual != expected_by_name or sum(row["bytes"] for row in actual.values()) != 8043982:
        raise ValueError("Original fixture source count or size changed")


def _encoded(value):
    return (json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + "\n").encode("utf-8")


def _descriptor(name, data):
    return {"path": name, "bytes": len(data), "sha256": hashlib.sha256(data).hexdigest()}


def build_preparation():
    static = _bundle_static()
    describe = static["describe"]
    method_descriptor, parent_method = _verify_bound(True, PARENT_METHOD, PARENT_METHOD_SHA, static)
    registry_descriptor, parent_registry = _verify_bound(
        True, static["PARENT_FIXTURE_SEAL"], static["PARENT_FIXTURE_SHA256"], static)
    plan_descriptor, _ = _verify_bound(False, PLAN, PLAN_SHA, static)
    parent_case_descriptor, parent_case = _verify_bound(
        True, static["PARENT_CASE_CONTRACT"], static["PARENT_CASE_SHA256"], static)
    stage8, _ = _verify_bound(False, static["STAGE8_INPUT"], static["STAGE8_SHA256"], static)
    if parent_registry["method_seal_sha256"] != method_descriptor["sha256"]:
        raise ValueError("Original fixture seal does not bind the saved tool seal")
    for row in (*parent_method["methods"], *parent_method["preparation_inputs"]):
        if describe(ROOT, row["path"]) != row:
            raise ValueError("Original frozen preparation bytes changed: " + row["path"])
    runtime, runtime_declarations = _verify_runtime_target(parent_method, static)
    case_path = static["CASE_CONTRACT"]
    case = describe(ROOT, case_path)
    catalog = static["read_json"](static["safe_path"](ROOT, case_path))
    catalogs = _validate_catalog(catalog, parent_case, static)
    if describe(ROOT, case_path) != case:
        raise ValueError("Case contract changed during preparation")
    methods = static["source_inventory"](static["SOURCE_SEEDS"], dynamic_seeds=static["DYNAMIC_SEEDS"])
    _check_original_fixtures(parent_registry, static)
    if (static["safe_path"](ROOT, "shop-mysql-runtime/v80/formal_authorization.json").exists()
            or static["safe_path"](ROOT, "shop-mysql-runtime/v80/formal/window1").exists()):
        raise ValueError("Preparation requires the original unused formal slot and no authorization receipt")
    method_receipt = {
        "schema": "v80_synthetic_tool_seal",
        "date": DATE,
        "status": static["PREPARATION_STATUS"],
        "formal_execution_authorized": False,
        "real_execution_enabled": False,
        "runtime": runtime,
        "runtime_provenance": {
            "saved_target": method_descriptor,
            "checked_text_declarations": runtime_declarations,
            "observed_current_runtime": False,
        },
        "source_seeds": list(static["SOURCE_SEEDS"]),
        "dynamic_seeds": list(static["DYNAMIC_SEEDS"]),
        "methods": sorted([*methods, case, parent_case_descriptor], key=lambda row: row["path"]),
        "preparation_inputs": [stage8],
        "parent_plan": plan_descriptor,
        "case_contract": case,
        "parent_case_contract": parent_case_descriptor,
        "required_test_methods": catalogs["mapped_methods"],
        "required_subcases": catalogs["preserved_case_ids"],
        "case_families": catalogs["preserved_families"],
        "limits": {"maximum_formal_windows": 1, "automatic_correction_windows": 0,
                   "success_deadline_seconds": 900, "work_child_watchdog_seconds_max": 120,
                   "retry_allowed": False, "preparation_checkpoint_minutes": 120,
                   "real_full_T_plan": None},
        "static_checks": {"source_closure_python_files": len(methods),
                          "ordered_catalog_ids_verified": True,
                          "methods_families_and_modules_verified": True,
                          "A09_refusal_and_evidence_AST_preserved": True,
                          "V77_methods_and_preparation_descriptors_rechecked": (
                              len(parent_method["methods"]) + len(parent_method["preparation_inputs"]))},
        "scope": {"new_fixture_generation": 0, "suite_imports": 0, "tests_executed": 0,
                  "formal_windows_started": 0, "live_process_api_probes": 0,
                  "real_measurements": 0, "real_data_reruns": 0},
    }
    method_name = static["METHOD_SEAL"]
    method_data = _encoded(method_receipt)
    fixture_receipt = {
        "schema": "v80_artificial_fixture_registry",
        "date": DATE,
        "status": "original_V75_inputs_bound_to_V80_before_separate_window_authorization",
        "method_seal_sha256": _descriptor(method_name, method_data)["sha256"],
        "formal_execution_authorized": False,
        "real_execution_enabled": False,
        "parent_fixture_registry": registry_descriptor,
        "fixtures": parent_registry["fixtures"],
        "verified_source_descriptors": parent_registry["verified_source_descriptors"],
        "preservation": parent_registry["preservation"],
    }
    return {method_name: method_data, static["FIXTURE_SEAL"]: _encoded(fixture_receipt)}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--write", action="store_true", help="exclusively save both public receipts")
    args = parser.parse_args()
    receipts = build_preparation()
    if args.write:
        if any((ROOT / name).exists() or (ROOT / name).is_symlink() for name in receipts):
            raise ValueError("Preparation receipts already exist")
        for name, data in receipts.items():
            with (ROOT / name).open("xb") as stream:
                stream.write(data)
                stream.flush()
                os.fsync(stream.fileno())
        for name, data in receipts.items():
            if (ROOT / name).read_bytes() != data:
                raise ValueError("Preparation receipt changed while saving")
    print(json.dumps({"written": args.write,
                      "receipts": [_descriptor(name, data) for name, data in receipts.items()]}))


if __name__ == "__main__":
    main()
