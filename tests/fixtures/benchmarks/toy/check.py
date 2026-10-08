"""Toy grader: prints a passing JSON verdict, or a non-JSON traceback while still exiting 0."""

import json
import sys
from pathlib import Path

task_id = sys.argv[2]
task = {t["key"]: t for t in json.loads(Path(__file__).with_name("dataset.json").read_text())}[task_id]
if task["check"] == "traceback":
    print("Traceback (most recent call last):\n  RuntimeError: grader crashed")
else:
    print(json.dumps({"task_id": task_id, "passed": True}))
