"""Verify the local Olist environment without changing source notebooks or tables."""

import argparse
import importlib
from importlib.metadata import version
import json
from pathlib import Path
import sys
from urllib.parse import quote_plus


PROJECT_ROOT = Path(__file__).resolve().parents[1]
OUTPUT_DIR = PROJECT_ROOT / ".runtime" / "verification"
NOTEBOOK_DIR = PROJECT_ROOT / "notebooks"
VENV_PYTHON = PROJECT_ROOT / ".venv" / "Scripts" / "python.exe"
DEPENDENCIES = {
    "pandas": "pandas",
    "PyMySQL": "pymysql",
    "SQLAlchemy": "sqlalchemy",
    "cryptography": "cryptography",
    "matplotlib": "matplotlib.pyplot",
    "jupyter": "jupyter_core",
    "ipykernel": "ipykernel",
    "nbformat": "nbformat",
    "nbclient": "nbclient",
    "jupyter_client": "jupyter_client",
}
EXPECTED_ROWS = {
    "customers": 99441,
    "orders": 99441,
    "order_items": 112650,
    "order_payments": 103886,
    "order_reviews": 99224,
    "products": 32951,
    "sellers": 3095,
    "geolocation": 1000163,
    "product_category_name_translation": 71,
}


def safe_error(exc):
    """Record error types/codes only; connection errors can contain credentials."""
    result = {"error_type": type(exc).__name__}
    if exc.args and isinstance(exc.args[0], int):
        result["error_code"] = exc.args[0]
    return result


def verify_dependencies():
    results = {}
    for package, module in DEPENDENCIES.items():
        try:
            importlib.import_module(module)
            results[package] = {"ok": True, "version": version(package)}
        except Exception as exc:
            results[package] = {"ok": False, **safe_error(exc)}
    return results


def verify_database(config):
    import pymysql

    result = {"ok": False, "tables": {}}
    try:
        connection_config = dict(config)
        connection_config.setdefault("connect_timeout", 10)
        connection_config.setdefault("read_timeout", 120)
        with pymysql.connect(**connection_config) as connection:
            with connection.cursor() as cursor:
                cursor.execute("SELECT DATABASE()")
                result["database"] = cursor.fetchone()[0]
                for table, expected in EXPECTED_ROWS.items():
                    cursor.execute(f"SELECT COUNT(*) FROM `{table}`")
                    actual = cursor.fetchone()[0]
                    result["tables"][table] = {
                        "expected": expected,
                        "actual": actual,
                        "ok": actual == expected,
                    }
        result["ok"] = all(item["ok"] for item in result["tables"].values())
    except Exception as exc:
        result.update(safe_error(exc))
    return result


def save_notebook(notebook, destination, password):
    """Keep fresh outputs, omitting tracebacks and redacting any password text."""
    import nbformat

    secrets = {password, quote_plus(password)} if password else set()
    for cell in notebook.cells:
        if cell.cell_type != "code":
            continue
        cell.outputs = [out for out in cell.outputs if out.output_type != "error"]
        for output in cell.outputs:
            if "text" in output:
                for secret in secrets:
                    output.text = output.text.replace(secret, "[REDACTED]")
            for mime_type, value in output.get("data", {}).items():
                if mime_type.startswith("text/") and isinstance(value, str):
                    for secret in secrets:
                        value = value.replace(secret, "[REDACTED]")
                    output.data[mime_type] = value
    nbformat.write(notebook, destination)


def execute_notebooks(password):
    import nbformat
    from nbclient import NotebookClient
    from jupyter_client.kernelspec import KernelSpecManager

    result = {"ok": False, "kernel": ".venv", "notebooks": {}}
    try:
        kernel = KernelSpecManager().get_kernel_spec(".venv")
        if Path(kernel.argv[0]).resolve() != VENV_PYTHON.resolve():
            result["error_type"] = "KernelInterpreterMismatch"
            return result
    except Exception as exc:
        result.update(safe_error(exc))
        return result

    image_dir = OUTPUT_DIR / "images"
    image_dir.mkdir(parents=True, exist_ok=True)
    filenames = (
        "01_olist_data_overview.ipynb",
        "02_olist_sql_analysis.ipynb",
        "03_olist_business_analysis.ipynb",
    )
    for filename in filenames:
        notebook = None
        destination = OUTPUT_DIR / filename
        try:
            notebook = nbformat.read(NOTEBOOK_DIR / filename, as_version=4)
            for cell in notebook.cells:
                if cell.cell_type == "code":
                    cell.outputs = []
                    cell.execution_count = None

            if filename.startswith("03_"):
                original = 'IMAGE_DIR = PROJECT_ROOT / "reports" / "images"'
                replacement = f"IMAGE_DIR = Path({str(image_dir)!r})"
                replacements = 0
                for cell in notebook.cells:
                    if cell.cell_type == "code":
                        replacements += cell.source.count(original)
                        cell.source = cell.source.replace(original, replacement)
                if replacements != 1:
                    raise RuntimeError("Image output redirection could not be verified")

            notebook.metadata.kernelspec = {
                "name": ".venv",
                "display_name": kernel.display_name,
                "language": "python",
            }
            client = NotebookClient(notebook, timeout=600, kernel_name=".venv")
            client.execute(cwd=str(NOTEBOOK_DIR))
            result["notebooks"][filename] = {"ok": True}
        except Exception as exc:
            result["notebooks"][filename] = {"ok": False, **safe_error(exc)}
        finally:
            if notebook is not None:
                save_notebook(notebook, destination, password)

    result["ok"] = all(item["ok"] for item in result["notebooks"].values())
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--execute-notebooks",
        action="store_true",
        help="Execute copies with the project .venv kernel; save outputs under .runtime/verification.",
    )
    args = parser.parse_args()
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    report = {
        "python": {
            "ok": Path(sys.executable).resolve() == VENV_PYTHON.resolve(),
            "executable": sys.executable,
            "version": sys.version.split()[0],
        },
        "dependencies": verify_dependencies(),
        "database": {"ok": False, "status": "skipped"},
        "notebooks": {"status": "not_requested"},
    }
    dependencies_ok = all(item["ok"] for item in report["dependencies"].values())
    prerequisites_ok = report["python"]["ok"] and dependencies_ok
    config = None
    if prerequisites_ok:
        try:
            sys.path.insert(0, str(PROJECT_ROOT))
            from scripts.db_config import DB_CONFIG

            config = DB_CONFIG
            report["database"] = verify_database(config)
        except Exception as exc:
            report["database"] = {"ok": False, **safe_error(exc)}

    if args.execute_notebooks:
        if prerequisites_ok and report["database"]["ok"]:
            report["notebooks"] = execute_notebooks(str(config.get("password", "")))
        else:
            report["notebooks"] = {"ok": False, "status": "skipped_prerequisites_failed"}

    report["ok"] = prerequisites_ok and report["database"]["ok"]
    if args.execute_notebooks:
        report["ok"] = report["ok"] and report["notebooks"].get("ok", False)
    report_path = OUTPUT_DIR / "summary.json"
    report_path.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")

    for name in ("python", "dependencies", "database", "notebooks"):
        section = report[name]
        ok = dependencies_ok if name == "dependencies" else section.get("ok")
        status = "PASS" if ok else ("FAIL" if ok is False else "SKIP")
        print(f"{name}: {status}")
    print(f"Report: {report_path}")
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
