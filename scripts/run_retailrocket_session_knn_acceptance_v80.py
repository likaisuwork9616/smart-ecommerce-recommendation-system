"""Bounded V80 artificial acceptance; sealed preparation is mandatory.

One formal window requires separate authorization bound to the two preparation
seals. Child test output stays in ignored storage.
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
PRIVATE = ROOT / "shop-mysql-runtime" / "v80" / "formal"
AUTHORIZATION = "shop-mysql-runtime/v80/formal_authorization.json"
AUTHORIZATION_ENV = "V80_FORMAL_AUTHORIZATION_SHA256"
REQUEST_SCHEMA = "v80_formal_window_request"
AUTHORIZATION_SCHEMA = "v80_formal_window_authorization"
TEST_MODULES = (
    "tests.test_retailrocket_session_knn_full_v80",
    "tests.test_retailrocket_session_knn_full_worker_v80",
    "tests.test_retailrocket_session_knn_pipeline_v80",
)
CASE_CATALOG = ROOT / "docs/contracts/retailrocket_session_knn_cases_v80.json"
PARENT_CATALOG = "docs/contracts/retailrocket_session_knn_cases_v77.json"
PARENT_CATALOG_SHA256 = "86eb3f5120f7cf7f37d788a6801bf2671d616a5c4ca700ffe9a4639e2f970363"
LIMIT_SECONDS = 900
WORK_CHILD_LIMIT = 120


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
    if catalog.get("schema") != "v80_required_synthetic_cases":
        raise ValueError("Sealed required-case catalog is missing")
    parent_bytes = (ROOT / PARENT_CATALOG).read_bytes()
    parent_descriptor = {"path": PARENT_CATALOG, "bytes": len(parent_bytes),
                         "sha256": hashlib.sha256(parent_bytes).hexdigest()}
    if (parent_descriptor["sha256"] != PARENT_CATALOG_SHA256
            or catalog.get("parent_case_contract") != parent_descriptor):
        raise ValueError("The original V77 case contract changed or is unbound")
    parent = json.loads(parent_bytes)
    mapping = [{"original": name, "proposed": name.replace("_v77.", "_v80.", 1)}
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
                    name.replace("_v77.", "_v80.", 1) for name in original["required_test_ids"]]):
            raise ValueError("Original family membership must be preserved")
    modules = catalog.get("modules", [])
    if len(modules) != 3 or len(parent["modules"]) != 3:
        raise ValueError("All three original test modules must be mapped")
    for current, original in zip(modules, parent["modules"], strict=True):
        if (current.get("path") != original["path"].replace("_v77.py", "_v80.py")
                or current.get("required_case_ids") != original["required_case_ids"]
                or current.get("required_test_ids") != [
                    name.replace("_v77.", "_v80.", 1) for name in original["required_test_ids"]]):
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
        from scripts.retailrocket_session_knn_bundle_v80 import SourceAuthorityError
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
        from scripts.retailrocket_session_knn_bundle_v80 import SourceAuthorityError
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


def _authorize(window, method_sha, fixture_sha, authorization_sha):
    """Verify independent authorization before consuming the unique slot."""
    from scripts import retailrocket_session_knn_bundle_v80 as bundle

    if type(window) is not int or window != 1:
        raise ValueError("Only the single sealed V80 formal window is permitted")
    anchors = {
        "method_seal_sha256": method_sha,
        "fixture_seal_sha256": fixture_sha,
        "authorization_sha256": authorization_sha,
    }
    for label, value in anchors.items():
        if type(value) is not str or re.fullmatch(r"[0-9a-f]{64}", value) is None:
            raise ValueError("Explicit presealed SHA-256 required: " + label)
    expected = {
        "schema": AUTHORIZATION_SCHEMA,
        "confirmation": "separate_user_confirmation_after_seal",
        "window": window,
        "method_seal_sha256": method_sha,
        "fixture_seal_sha256": fixture_sha,
        "success_limit_seconds": LIMIT_SECONDS,
        "work_child_limit_seconds": WORK_CHILD_LIMIT,
        "scope": "synthetic_only",
        "retry_allowed": False,
    }
    authority = bundle._sealed_document(AUTHORIZATION, authorization_sha)
    if bundle.encoded(authority) != bundle.encoded(expected):
        raise ValueError("Separate authorization does not bind the sealed V80 window")
    return anchors


def _authoritative_request(folder, *, inherited):
    from scripts import retailrocket_session_knn_bundle_v80 as bundle

    expected = bundle.safe_path(ROOT, "shop-mysql-runtime/v80/formal/window1")
    if Path(folder).absolute() != expected or not expected.is_dir():
        raise ValueError("The unique formal slot is required")
    request = bundle.read_json(bundle.safe_path(expected, "request.json"))
    if (request.get("schema") != REQUEST_SCHEMA
            or request.get("scope") != "synthetic_only"
            or type(request.get("success_limit_seconds")) is not int
            or request["success_limit_seconds"] != LIMIT_SECONDS
            or type(request.get("work_child_limit_seconds")) is not int
            or request["work_child_limit_seconds"] != WORK_CHILD_LIMIT):
        raise ValueError("Malformed formal request")
    _authorize(request["window"], request["method_seal_sha256"],
               request["fixture_seal_sha256"], request["authorization_sha256"])
    deadline = request.get("deadline_monotonic")
    if type(deadline) is not float or not 0 < deadline < float("inf"):
        raise ValueError("A finite formal deadline is required")
    if inherited:
        environment = {
            "V80_METHOD_SEAL_SHA256": request["method_seal_sha256"],
            "V80_FIXTURE_SEAL_SHA256": request["fixture_seal_sha256"],
            AUTHORIZATION_ENV: request["authorization_sha256"],
            "V80_FORMAL_DEADLINE_MONOTONIC": str(deadline),
        }
        if any(os.environ.get(name) != value for name, value in environment.items()):
            raise ValueError("Internal suite must inherit the authorized formal request")
    return request


def suite_process(folder):
    request = _authoritative_request(folder, inherited=True)
    save(folder / "suite_started.json", {"status": "formal_slot_consumed"})
    if time.monotonic() >= request["deadline_monotonic"]:
        raise TimeoutError("Formal deadline expired before suite admission")
    from scripts import retailrocket_session_knn_bundle_v80 as bundle
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
    completed_run_evidence = []
    delivery_error = None
    if passed:
        from scripts import retailrocket_session_knn_pipeline_v80 as pipeline

        try:
            evidence = pipeline._capture_formal_deliveries()
            if type(evidence) is not list or not evidence:
                raise ValueError("Successful runs require saved delivery evidence")
            completed_run_evidence = evidence
        except Exception as error:
            delivery_error = {"type": type(error).__name__, "message": str(error)}
            passed = False
    report = {"schema": "v80_formal_suite_result", "passed": passed,
              "request": bundle.describe(folder, "request.json"),
              "catalog_identity": catalog_identity,
              "test_ids": ids, "tests_run": result.testsRun,
              "outcomes": result.outcomes, "subcases": result.subcases,
              "completed_run_evidence": completed_run_evidence, "delivery_error": delivery_error,
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


def _complete_suite(folder, suite):
    from scripts import retailrocket_session_knn_bundle_v80 as bundle

    catalog = bundle.read_json(CASE_CATALOG)
    catalog_identity = validate_catalog(catalog)
    if (suite.get("schema") != "v80_formal_suite_result"
            or suite.get("passed") is not True
            or suite.get("request") != bundle.describe(folder, "request.json")
            or suite.get("catalog_identity") != catalog_identity
            or suite.get("scope") != "synthetic_only"
            or suite.get("real_full_acceptance") is not False
            or suite.get("delivery_error") is not None
            or type(suite.get("tests_run")) is not int or suite["tests_run"] != 34):
        return False
    for name in ("source_authority_errors", "unexpected_timeout_errors", "error_details",
                 "missing_test_ids", "missing_required_case_ids", "unlisted_case_ids"):
        if suite.get(name) != []:
            return False
    for name in ("failures", "errors", "skips"):
        if type(suite.get(name)) is not int or suite[name] != 0:
            return False
    test_ids = catalog["required_test_ids"]
    case_ids = catalog["required_case_ids"]
    loaded = suite.get("test_ids", [])
    outcomes = suite.get("outcomes", [])
    subcases = suite.get("subcases", [])
    if not all(type(rows) is list for rows in (loaded, outcomes, subcases)):
        return False
    if (len(loaded) != 34 or sorted(loaded) != sorted(test_ids)
            or sorted(row["id"] for row in outcomes if row.get("status") == "passed") != sorted(test_ids)
            or len(outcomes) != 34 or len(subcases) != 196):
        return False
    parents_by_case = {}
    for family in catalog["families"]:
        methods = set(family["required_test_ids"])
        for case in family["required_case_ids"]:
            parents_by_case.setdefault(case, set()).update(methods)
    observed = [row["case_id"] for row in subcases if row.get("status") == "passed"
                and row.get("parent") in parents_by_case.get(row.get("case_id"), ())]
    evidence = suite.get("completed_run_evidence")
    if sorted(observed) != sorted(case_ids) or type(evidence) is not list or not evidence:
        return False

    from scripts import retailrocket_session_knn_pipeline_v80 as pipeline

    pipeline._check_formal_deliveries(evidence)
    return True


def observe_tree(process, tracked):
    if process.poll() is not None:
        return
    import psutil
    try:
        parent = psutil.Process(process.pid)
        nodes = [parent, *parent.children(recursive=True)]
    except psutil.NoSuchProcess:
        return
    snapshot = {}
    for node in nodes:
        try:
            created = node.create_time()
            snapshot[(node.pid, created)] = created
        except psutil.NoSuchProcess:
            pass
    # On Windows both polls check the original Popen handle. Accept this
    # best-effort tree snapshot only while that launcher is still nonsignaled.
    if process.poll() is None:
        tracked.update(snapshot)


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


def formal(window, method_sha, fixture_sha, authorization_sha):
    from scripts import retailrocket_session_knn_bundle_v80 as bundle

    anchors = _authorize(window, method_sha, fixture_sha, authorization_sha)
    folder = bundle.safe_path(ROOT, "shop-mysql-runtime/v80/formal/window1")
    started = time.monotonic()
    folder.parent.mkdir(parents=True, exist_ok=True)
    folder.mkdir(exist_ok=False)  # A crashed/failed attempt cannot reset its slot.
    deadline = started + LIMIT_SECONDS
    env = dict(os.environ, V80_METHOD_SEAL_SHA256=method_sha,
               V80_FIXTURE_SEAL_SHA256=fixture_sha,
               V80_FORMAL_DEADLINE_MONOTONIC=str(deadline))
    env[AUTHORIZATION_ENV] = authorization_sha
    request = {"schema": REQUEST_SCHEMA, "window": window, **anchors,
               "success_limit_seconds": LIMIT_SECONDS, "work_child_limit_seconds": WORK_CHILD_LIMIT,
               "deadline_monotonic": deadline,
               "started_utc": datetime.now(timezone.utc).isoformat(), "scope": "synthetic_only"}
    save(folder / "request.json", request)
    status = "failed"; timed_out = False; authority_error = False; exception = None
    process = None; stopped = []; tracked = {}
    suite = None
    suite_descriptor = None
    terminal_stop_verified = False
    try:
        # This validation is inside the one formal window.
        for fixture_id in bundle.PROFILES:
            bundle.admit(fixture_id, fixture_seal_sha256=fixture_sha, method_seal_sha256=method_sha)
        if time.monotonic() >= deadline:
            timed_out = True
            raise TimeoutError("Formal admission exceeded the success deadline")
        with (folder / "stdout.log").open("xb") as out, (folder / "stderr.log").open("xb") as err:
            process = subprocess.Popen([sys.executable, "-B", "-m", "scripts.run_retailrocket_session_knn_acceptance_v80",
                                        "--suite", str(folder)], cwd=ROOT, env=env,
                                       stdout=out, stderr=err)
            while process.poll() is None:
                observe_tree(process, tracked)
                if time.monotonic() >= deadline:
                    timed_out = True; stopped = stop_tree(process, tracked); break
                time.sleep(0.1)
        if type(process.returncode) is int and process.returncode == 0 and not timed_out:
            terminal_stop_verified = not alive_tracked(tracked)
            if terminal_stop_verified and (folder / "suite_result.json").exists():
                suite_descriptor = bundle.describe(folder, "suite_result.json")
                suite = bundle.read_json(bundle.safe_path(folder, "suite_result.json"))
            if (suite is not None and _complete_suite(folder, suite)
                    and bundle.describe(folder, "suite_result.json") == suite_descriptor
                    and _authoritative_request(folder, inherited=False) == request
                    and time.monotonic() < deadline):
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
    summary = dict(request, schema="v80_bounded_synthetic_acceptance", status=status,
                   request=bundle.describe(folder, "request.json"),
                   suite_launcher_exit_code=None if process is None else process.returncode,
                   observed_suite_tree_stopped=terminal_stop_verified,
                   elapsed_seconds=elapsed, unexpected_timeout=timed_out,
                   source_authority_error=authority_error, exception=exception,
                   stopped_child_identities=stopped,
                   observed_child_identities=[{"pid": pid, "create_time": created} for pid, created in tracked],
                   unobserved_descendants_guaranteed_absent=False, real_full_acceptance=False,
                   new_real_measurements=0, T_plan=None,
                   usage="synthetic_acceptance_deadline_only_not_performance")
    if suite is None and (folder / "suite_result.json").exists():
        suite_descriptor = bundle.describe(folder, "suite_result.json")
        suite = bundle.read_json(bundle.safe_path(folder, "suite_result.json"))
    if suite is not None:
        summary["suite"] = suite
        summary["suite_result"] = suite_descriptor
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
    return 0 if status == "passed" else 1


def validate_formal_result(folder, *, entry_exit_code):
    """Accept saved evidence only with the actual formal entry exit status."""
    from scripts import retailrocket_session_knn_bundle_v80 as bundle

    if type(entry_exit_code) is not int or entry_exit_code != 0:
        raise ValueError("Actual successful formal entry exit is required")
    folder = Path(folder).absolute()
    request = _authoritative_request(folder, inherited=False)
    veto = bundle.safe_path(folder, "deadline_veto.json")
    if veto.exists():
        raise ValueError("Formal deadline veto takes precedence")
    summary_path = bundle.safe_path(folder, "result.json")
    suite_path = bundle.safe_path(folder, "suite_result.json")
    summary = bundle.read_json(summary_path)
    suite = bundle.read_json(suite_path)
    elapsed = summary.get("elapsed_seconds")
    if (summary.get("schema") != "v80_bounded_synthetic_acceptance"
            or summary.get("status") != "passed"
            or summary.get("unexpected_timeout") is not False
            or summary.get("source_authority_error") is not False
            or summary.get("real_full_acceptance") is not False
            or summary.get("observed_suite_tree_stopped") is not True
            or type(summary.get("suite_launcher_exit_code")) is not int
            or summary["suite_launcher_exit_code"] != 0
            or type(elapsed) not in (int, float) or not 0 <= elapsed < LIMIT_SECONDS
            or summary.get("request") != bundle.describe(folder, "request.json")
            or summary.get("suite_result") != bundle.describe(folder, "suite_result.json")
            or summary.get("suite") != suite
            or any(summary.get(name) != request[name] for name in (
                "window", "scope", "method_seal_sha256", "fixture_seal_sha256",
                "authorization_sha256", "deadline_monotonic"))
            or (folder / "suite_exception.json").exists()
            or not _complete_suite(folder, suite)
            or veto.exists()):
        raise ValueError("Formal result is missing, incomplete, inconsistent or vetoed")
    return summary


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--window", type=int, choices=(1,))
    parser.add_argument("--method-sha")
    parser.add_argument("--fixture-sha")
    parser.add_argument("--authorization-sha")
    parser.add_argument("--suite", type=Path, help=argparse.SUPPRESS)
    args = parser.parse_args()
    if args.suite:
        folder = args.suite
        if folder != PRIVATE / "window1":
            parser.error("Internal suite requires its formal request namespace")
        # Reject direct entry before creating any diagnostic file.
        _authoritative_request(folder, inherited=True)
        try: return suite_process(folder)
        except Exception as error:
            if not (folder / "suite_exception.json").exists():
                save(folder / "suite_exception.json", {"source_authority_error": False,
                     "unexpected_timeout": isinstance(error, (TimeoutError, subprocess.TimeoutExpired)),
                     "type": type(error).__name__, "message": str(error)})
            traceback.print_exc(); return 2
    if args.window != 1 or not args.method_sha or not args.fixture_sha or not args.authorization_sha:
        parser.error("Single --window 1, both seal anchors and separate authorization anchor required")
    return formal(args.window, args.method_sha, args.fixture_sha, args.authorization_sha)


if __name__ == "__main__":
    raise SystemExit(main())
