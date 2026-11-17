"""Bounded V77 artificial acceptance; sealed preparation is mandatory.

One formal window, fail-fast, no corrective rerun. Unexpected whole-window
timeout is terminal. Child test output stays in ignored storage.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import time
import traceback
import unittest

ROOT = Path(__file__).resolve().parents[1]
PRIVATE = ROOT / "shop-mysql-runtime" / "v77" / "formal"
TEST_MODULES = (
    "tests.test_retailrocket_session_knn_full_v77",
    "tests.test_retailrocket_session_knn_full_worker_v77",
    "tests.test_retailrocket_session_knn_pipeline_v77",
)
CASE_CATALOG = ROOT / "docs/contracts/retailrocket_session_knn_cases_v77.json"
PARENT_CATALOG = "docs/contracts/retailrocket_session_knn_cases_v75.json"
PARENT_CATALOG_SHA256 = "a8a3c80186bc2af3a53db1f93e4136b32996566d196b6c84b1dc64328b880330"
LIMIT_SECONDS = 900


def save(path, value):
    path = Path(path)
    data = (json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2,
                       allow_nan=False) + "\n").encode("utf-8")
    with path.open("xb") as stream:
        stream.write(data); stream.flush(); os.fsync(stream.fileno())


def flatten(suite):
    for item in suite:
        if isinstance(item, unittest.TestSuite):
            yield from flatten(item)
        else:
            yield item


def validate_catalog(catalog):
    """Bind the new module names to all original methods, cases and families."""
    if catalog.get("schema") != "v77_required_synthetic_cases":
        raise ValueError("Sealed required-case catalog is missing")
    parent_bytes = (ROOT / PARENT_CATALOG).read_bytes()
    parent_descriptor = {"path": PARENT_CATALOG, "bytes": len(parent_bytes),
                         "sha256": hashlib.sha256(parent_bytes).hexdigest()}
    if (parent_descriptor["sha256"] != PARENT_CATALOG_SHA256
            or catalog.get("parent_case_contract") != parent_descriptor):
        raise ValueError("The original V75 case contract changed or is unbound")
    parent = json.loads(parent_bytes)
    mapping = [{"original": name, "proposed": name.replace("_v75.", "_v77.", 1)}
               for name in parent["required_test_ids"]]
    expected_tests = [row["proposed"] for row in mapping]
    if (len(mapping) != 34 or len(set(expected_tests)) != 34
            or catalog.get("method_id_mapping") != mapping
            or catalog.get("required_test_ids") != expected_tests):
        raise ValueError("All 34 original methods require a one-to-one version mapping")
    cases = parent["required_case_ids"]
    if (len(cases) != 196 or len(set(cases)) != 196
            or catalog.get("required_case_ids") != cases):
        raise ValueError("All 196 original case IDs must be preserved in order")
    families = catalog.get("families", [])
    if len(families) != 24 or len(parent["families"]) != 24:
        raise ValueError("All 24 original case families must be preserved")
    for current, original in zip(families, parent["families"], strict=True):
        if (current.get("id") != original["id"]
                or current.get("required_case_ids") != original["required_case_ids"]
                or current.get("required_test_ids") != [
                    name.replace("_v75.", "_v77.", 1) for name in original["required_test_ids"]]):
            raise ValueError("Original family membership must be preserved")
    modules = catalog.get("modules", [])
    if len(modules) != 3 or len(parent["modules"]) != 3:
        raise ValueError("All three original test modules must be mapped")
    for current, original in zip(modules, parent["modules"], strict=True):
        if (current.get("path") != original["path"].replace("_v75.py", "_v77.py")
                or current.get("required_case_ids") != original["required_case_ids"]
                or current.get("required_test_ids") != [
                    name.replace("_v75.", "_v77.", 1) for name in original["required_test_ids"]]):
            raise ValueError("Original module case and method membership must be preserved")
    return {"parent_case_contract": parent_descriptor, "mapped_methods": 34,
            "preserved_case_ids": 196, "preserved_families": 24}


class EvidenceResult(unittest.TextTestResult):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.outcomes = []
        self.subcases = []
        self.current_subcases = []
        self.seen_case_ids = set()
        self.source_authority_errors = []
        self.unexpected_timeout_errors = []
        self.error_details = []

    def startTest(self, test):
        self.current_subcases = []
        super().startTest(test)

    def addSuccess(self, test):
        super().addSuccess(test)
        self.outcomes.append({"id": test.id(), "status": "passed"})

    def _record_error(self, test, error):
        self.error_details.append({"id": test.id(), "type": error[0].__name__, "message": str(error[1])})
        if issubclass(error[0], (TimeoutError, subprocess.TimeoutExpired)) or error[0].__name__ == "BudgetExceeded":
            self.unexpected_timeout_errors.append(test.id())

    def addFailure(self, test, error):
        self._record_error(test, error)
        super().addFailure(test, error)
        self.outcomes.append({"id": test.id(), "status": "failed"})
        self.stop()

    def addError(self, test, error):
        self._record_error(test, error)
        from scripts.retailrocket_session_knn_bundle_v77 import SourceAuthorityError
        if issubclass(error[0], SourceAuthorityError):
            self.source_authority_errors.append(test.id())
        super().addError(test, error)
        self.outcomes.append({"id": test.id(), "status": "error"})
        self.stop()

    def addSkip(self, test, reason):
        super().addSkip(test, reason)
        self.outcomes.append({"id": test.id(), "status": "skipped", "reason": reason})
        self.stop()

    def addExpectedFailure(self, test, error):
        # Negative cases must assert their expected refusal, not suppress a test.
        super().addExpectedFailure(test, error)
        self.outcomes.append({"id": test.id(), "status": "expected_failure_incomplete"})
        self.stop()

    def addUnexpectedSuccess(self, test):
        super().addUnexpectedSuccess(test)
        self.outcomes.append({"id": test.id(), "status": "unexpected_success"})
        self.stop()

    def addSubTest(self, test, subtest, error):
        if error is not None:
            self._record_error(subtest, error)
        super().addSubTest(test, subtest, error)
        from scripts.retailrocket_session_knn_bundle_v77 import SourceAuthorityError
        if error is not None and issubclass(error[0], SourceAuthorityError):
            self.source_authority_errors.append(subtest.id())
        case_id = subtest.params.get("case_id")
        status = "passed" if error is None else "failed"
        if type(case_id) is not str or not case_id or case_id in self.seen_case_ids:
            status = "missing_or_duplicate_case_id"
        self.seen_case_ids.add(case_id)
        self.subcases.append({"id": subtest.id(), "parent": test.id(),
                              "case_id": case_id, "status": status})
        if error is not None or status != "passed":
            self.outcomes.append({"id": test.id(), "status": "failed_subcase"})
            self.stop()


def suite_process(folder):
    save(folder / "suite_started.json", {"status": "formal_slot_consumed"})
    if time.monotonic() >= float(os.environ["V77_FORMAL_DEADLINE_MONOTONIC"]):
        raise TimeoutError("Formal deadline expired before suite admission")
    from scripts import retailrocket_session_knn_bundle_v77 as bundle
    try:
        for fixture_id in bundle.PROFILES:
            bundle.admit(fixture_id)
    except Exception as error:
        save(folder / "suite_exception.json", {"source_authority_error": True,
             "type": type(error).__name__, "message": str(error)})
        raise
    catalog = json.loads(CASE_CATALOG.read_text(encoding="utf-8"))
    catalog_identity = validate_catalog(catalog)
    loader = unittest.TestLoader()
    suite = loader.loadTestsFromNames(TEST_MODULES)
    tests = list(flatten(suite))
    ids = [test.id() for test in tests]
    if loader.errors or len(ids) != len(set(ids)):
        raise ValueError("Missing, duplicated or unloadable sealed tests")
    families = {match.group(0) for name in ids for match in re.finditer(r"A(?:0[1-9]|1[0-9]|2[0-4])", name)}
    if families != {f"A{i:02d}" for i in range(1, 25)}:
        raise ValueError("All 24 sealed case families must be present before execution")
    if set(ids) != set(catalog["required_test_ids"]):
        raise ValueError("Loaded tests differ from the sealed required-test roster")
    runner = unittest.TextTestRunner(verbosity=2, resultclass=EvidenceResult, failfast=True)
    result = runner.run(suite)
    completed = {row["id"] for row in result.outcomes}
    missing = [name for name in ids if name not in completed]
    required_cases = set(catalog["required_case_ids"])
    passed_cases = {row["case_id"] for row in result.subcases if row["status"] == "passed"}
    missing_cases = sorted(required_cases - passed_cases)
    unlisted_cases = sorted(str(x) for x in result.seen_case_ids - required_cases)
    passed = (not missing_cases and not unlisted_cases and result.wasSuccessful() and not result.skipped and not result.expectedFailures
              and not missing and all(row["status"] == "passed" for row in result.outcomes)
              and all(row["status"] == "passed" for row in result.subcases))
    report = {"schema": "v77_formal_suite_result", "passed": passed,
              "catalog_identity": catalog_identity,
              "test_ids": ids, "tests_run": result.testsRun,
              "outcomes": result.outcomes, "subcases": result.subcases,
              "source_authority_errors": result.source_authority_errors,
              "unexpected_timeout_errors": result.unexpected_timeout_errors,
              "error_details": result.error_details,
              "missing_test_ids": missing, "missing_required_case_ids": missing_cases,
              "unlisted_case_ids": unlisted_cases, "failures": len(result.failures),
              "errors": len(result.errors), "skips": len(result.skipped),
              "new_real_measurements": 0, "real_full_acceptance": False,
              "scope": "synthetic_only", "T_plan": None}
    save(folder / "suite_result.json", report)
    return 0 if passed else 1


def observe_tree(process, tracked):
    if process.poll() is not None:
        return
    import psutil
    try:
        parent = psutil.Process(process.pid)
        nodes = [parent, *parent.children(recursive=True)]
    except psutil.NoSuchProcess:
        return
    for node in nodes:
        try: tracked[(node.pid, node.create_time())] = node.create_time()
        except psutil.NoSuchProcess: pass


def alive_tracked(tracked):
    import psutil
    alive = []
    for pid, created in tracked:
        try:
            process = psutil.Process(pid)
            if process.create_time() == created and process.is_running():
                alive.append(process)
        except psutil.NoSuchProcess: pass
    return alive


def stop_tree(process, tracked):
    import psutil
    observe_tree(process, tracked)
    nodes = alive_tracked(tracked)
    recorded = [{"pid": item.pid, "create_time": item.create_time()} for item in nodes]
    for item in reversed(nodes):
        try: item.terminate()
        except psutil.NoSuchProcess: pass
    _, alive = psutil.wait_procs(nodes, timeout=3)
    for item in alive:
        try: item.kill()
        except psutil.NoSuchProcess: pass
    if process.poll() is None:
        try: process.wait(timeout=3)
        except subprocess.TimeoutExpired:
            process.kill(); process.wait(timeout=3)
    if alive_tracked(tracked):
        raise RuntimeError("Observed synthetic children did not stop")
    return recorded


def formal(window, method_sha, fixture_sha):
    from scripts import retailrocket_session_knn_bundle_v77 as bundle
    if window != 1:
        raise ValueError("Only the single sealed V77 formal window is permitted")
    PRIVATE.mkdir(parents=True, exist_ok=True)
    folder = PRIVATE / "window1"
    folder.mkdir(exist_ok=False)  # A crashed/failed attempt cannot reset its slot.
    started = time.monotonic()
    deadline = started + LIMIT_SECONDS
    env = dict(os.environ, V77_METHOD_SEAL_SHA256=method_sha,
               V77_FIXTURE_SEAL_SHA256=fixture_sha,
               V77_FORMAL_DEADLINE_MONOTONIC=str(deadline))
    request = {"window": window, "method_seal_sha256": method_sha,
               "fixture_seal_sha256": fixture_sha, "success_limit_seconds": LIMIT_SECONDS,
               "started_utc": datetime.now(timezone.utc).isoformat(), "scope": "synthetic_only"}
    save(folder / "request.json", request)
    status = "failed"; timed_out = False; authority_error = False; exception = None
    process = None; stopped = []; tracked = {}
    try:
        # This validation is inside the one formal window.
        for fixture_id in bundle.PROFILES:
            bundle.admit(fixture_id, fixture_seal_sha256=fixture_sha, method_seal_sha256=method_sha)
        if time.monotonic() >= deadline:
            timed_out = True
            raise TimeoutError("Formal admission exceeded the success deadline")
        with (folder / "stdout.log").open("xb") as out, (folder / "stderr.log").open("xb") as err:
            process = subprocess.Popen([sys.executable, "-B", "-m", "scripts.run_retailrocket_session_knn_acceptance_v77",
                                        "--suite", str(folder)], cwd=ROOT, env=env,
                                       stdout=out, stderr=err)
            while process.poll() is None:
                observe_tree(process, tracked)
                if time.monotonic() >= deadline:
                    timed_out = True; stopped = stop_tree(process, tracked); break
                time.sleep(0.1)
        if process.returncode == 0 and not timed_out and not alive_tracked(tracked) and (folder / "suite_result.json").is_file():
            suite = json.loads((folder / "suite_result.json").read_text(encoding="utf-8"))
            if suite["passed"] and time.monotonic() < deadline:
                status = "passed"
    except Exception as error:
        exception = {"type": type(error).__name__, "message": str(error)}
        authority_error = process is None
        if process is not None and process.poll() is None:
            stopped = stop_tree(process, tracked)
    if process is not None and status != "passed" and alive_tracked(tracked):
        stopped.extend(stop_tree(process, tracked))
    if (folder / "suite_exception.json").exists():
        child_error = json.loads((folder / "suite_exception.json").read_text(encoding="utf-8"))
        authority_error = bool(child_error.get("source_authority_error"))
        timed_out = timed_out or bool(child_error.get("unexpected_timeout"))
        exception = child_error
    elapsed = time.monotonic() - started
    if timed_out or elapsed >= LIMIT_SECONDS:
        timed_out = True; status = "incomplete_timeout"
    summary = dict(request, schema="v77_bounded_synthetic_acceptance", status=status,
                   elapsed_seconds=elapsed, unexpected_timeout=timed_out,
                   source_authority_error=authority_error, exception=exception,
                   stopped_child_identities=stopped,
                   observed_child_identities=[{"pid": pid, "create_time": created} for pid, created in tracked],
                   unobserved_descendants_guaranteed_absent=False, real_full_acceptance=False,
                   new_real_measurements=0, T_plan=None,
                   usage="synthetic_acceptance_deadline_only_not_performance")
    if (folder / "suite_result.json").exists():
        summary["suite"] = json.loads((folder / "suite_result.json").read_text(encoding="utf-8"))
        if summary["suite"].get("source_authority_errors"):
            summary["source_authority_error"] = True
        if summary["suite"].get("unexpected_timeout_errors"):
            summary["unexpected_timeout"] = True
            summary["status"] = status = "incomplete_timeout"
    save(folder / "result.json", summary)
    # If saving itself crosses the success deadline, preserve that evidence and
    # emit a separate veto. The public collector must honor the veto.
    if status == "passed" and time.monotonic() >= deadline:
        save(folder / "deadline_veto.json", {"status": "incomplete_timeout",
             "elapsed_seconds_including_receipt": time.monotonic() - started})
        status = "incomplete_timeout"
    print(json.dumps({"status": status, "window": window,
                      "private_result": str(folder / "result.json")}, ensure_ascii=False))
    return 0 if status == "passed" else 1


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--window", type=int, choices=(1,))
    parser.add_argument("--method-sha")
    parser.add_argument("--fixture-sha")
    parser.add_argument("--suite", type=Path, help=argparse.SUPPRESS)
    args = parser.parse_args()
    if args.suite:
        folder = args.suite.resolve()
        if folder.parent != PRIVATE.resolve() or folder.name != "window1":
            parser.error("Internal suite requires its formal request namespace")
        request = json.loads((folder / "request.json").read_text(encoding="utf-8"))
        for key, env in [("method_seal_sha256", "V77_METHOD_SEAL_SHA256"),
                         ("fixture_seal_sha256", "V77_FIXTURE_SEAL_SHA256")]:
            if request[key] != os.environ.get(env):
                parser.error("Internal suite must inherit its sealed request")
        try: return suite_process(folder)
        except Exception as error:
            if not (folder / "suite_exception.json").exists():
                save(folder / "suite_exception.json", {"source_authority_error": False,
                     "unexpected_timeout": isinstance(error, (TimeoutError, subprocess.TimeoutExpired)),
                     "type": type(error).__name__, "message": str(error)})
            traceback.print_exc(); return 2
    if args.window != 1 or not args.method_sha or not args.fixture_sha:
        parser.error("Single sealed --window 1 and both SHA anchors required")
    return formal(args.window, args.method_sha, args.fixture_sha)


if __name__ == "__main__":
    raise SystemExit(main())
