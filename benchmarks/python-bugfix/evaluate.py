"""Grader for python-bugfix: run the task's tests; score = fraction passing; editing the tests scores 0.

Prints a JSON verdict and always exits 0 (read `passed` from the JSON).
"""

import argparse
import json
import subprocess
import sys
import tempfile
import xml.etree.ElementTree as ET
from pathlib import Path

HERE = Path(__file__).parent
TEST_TIMEOUT = 60


def grade(task: dict, workspace: Path) -> dict:
    test_file = task["test_file"]
    original = (HERE / "tasks" / task["id"] / test_file).read_text()
    submitted = workspace / test_file
    if not submitted.exists() or submitted.read_text() != original:
        return {"passed": False, "score": 0.0, "details": {"test_file_modified": True}}

    with tempfile.TemporaryDirectory() as tmp:
        report = Path(tmp) / "report.xml"
        cmd = [sys.executable, "-m", "pytest", test_file, "-q", "-p", "no:cacheprovider", f"--junitxml={report}"]
        try:
            proc = subprocess.run(cmd, cwd=workspace, capture_output=True, text=True, timeout=TEST_TIMEOUT)
        except subprocess.TimeoutExpired:
            return {"passed": False, "score": 0.0, "details": {"test_file_modified": False, "error": "tests timed out"}}
        cases = ET.parse(report).getroot().iter("testcase") if report.exists() else []
        bad = ("failure", "error", "skipped")
        results = {c.get("name"): not any(child.tag in bad for child in c) for c in cases}

    total, passed = len(results), sum(results.values())
    return {
        "passed": total > 0 and passed == total,
        "score": round(passed / total, 4) if total else 0.0,
        "details": {
            "test_file_modified": False,
            "tests_passed": passed,
            "tests_total": total,
            "failed_tests": [name for name, ok in results.items() if not ok],
            "pytest_output": proc.stdout[-3000:],
        },
    }


def main():
    parser = argparse.ArgumentParser(description="Grade a python-bugfix task")
    parser.add_argument("task_id")
    parser.add_argument("workspace")
    args = parser.parse_args()

    tasks = {t["id"]: t for t in json.loads((HERE / "dataset.json").read_text())}
    result = grade(tasks[args.task_id], Path(args.workspace))
    print(json.dumps({"task_id": args.task_id, **result}, indent=2))


if __name__ == "__main__":
    main()
