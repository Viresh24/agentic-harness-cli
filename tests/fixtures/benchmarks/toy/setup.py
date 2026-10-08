"""Toy setup: creates the workspace, or exits with the task's configured failure code."""

import json
import sys
from pathlib import Path

workspace, task_id = Path(sys.argv[1]), sys.argv[2]
task = {t["key"]: t for t in json.loads(Path(__file__).with_name("dataset.json").read_text())}[task_id]
if task["setup_exit"]:
    print("setup exploded", file=sys.stderr)
    sys.exit(task["setup_exit"])
workspace.mkdir(parents=True, exist_ok=True)
print("ok")
