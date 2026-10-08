"""Setup for python-bugfix: copy a task's buggy module and its tests into the workspace."""

import argparse
import json
import shutil
import sys
from pathlib import Path

HERE = Path(__file__).parent


def main():
    parser = argparse.ArgumentParser(description="Set up a python-bugfix task")
    parser.add_argument("task_id")
    parser.add_argument("workspace")
    args = parser.parse_args()

    tasks = {t["id"]: t for t in json.loads((HERE / "dataset.json").read_text())}
    if args.task_id not in tasks:
        sys.exit(f"Unknown task {args.task_id}")
    workspace = Path(args.workspace)
    workspace.mkdir(parents=True, exist_ok=True)
    for source in (HERE / "tasks" / args.task_id).iterdir():
        shutil.copy(source, workspace / source.name)
        print(f"Created {source.name}")


if __name__ == "__main__":
    main()
