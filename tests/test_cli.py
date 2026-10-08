import json
import re
import sqlite3
import subprocess
import sys
import time
from pathlib import Path

import pytest
from click.testing import CliRunner

from agentic_harness.cli import cli
from agentic_harness.models import RunStatus
from agentic_harness.store import RunStore

SCRIPTED = str(Path(__file__).parent / "fixtures" / "agents" / "scripted")


def _invoke(*args: str):
    return CliRunner().invoke(cli, list(args))


def _run_count(harness_home: Path) -> int:
    db = harness_home / "harness.db"
    return sqlite3.connect(db).execute("SELECT COUNT(*) FROM runs").fetchone()[0] if db.exists() else 0


def test_run_unknown_task_id(harness_home):
    result = _invoke("run", "--agent", SCRIPTED, "--benchmark", "bash-operations", "--task_ids", "bash-999")
    assert result.exit_code == 1
    assert "bash-999" in result.output and "bash-001" in result.output
    assert _run_count(harness_home) == 0


def test_run_unknown_benchmark(harness_home):
    result = _invoke("run", "--agent", SCRIPTED, "--benchmark", "nope")
    assert result.exit_code == 1 and "python-tasks" in result.output
    assert _run_count(harness_home) == 0


def test_run_unknown_agent():
    result = _invoke("run", "--agent", "agents/nope", "--benchmark", "bash-operations")
    assert result.exit_code == 1 and "harness-agent.yaml" in result.output


@pytest.mark.docker
def test_run_wait_then_status_and_results():
    result = _invoke(
        "run", "--agent", SCRIPTED, "--benchmark", "bash-operations", "--task_ids", "bash-001, bash-002", "--wait"
    )
    assert result.exit_code == 0, result.output
    run_id = re.search(r"Run ID: (\w+)", result.output).group(1)
    assert "bash-001  passed" in result.output and "Accuracy:" in result.output

    status = _invoke("status", "--run_id", run_id).output
    assert "completed" in status and "2/2" in status
    assert "bash-001  passed" in status and "bash-002  failed" in status

    data = json.loads(_invoke("results", "--run_id", run_id).stdout)
    assert (data["summary"]["passed"], data["summary"]["accuracy"]) == (1, 0.5)
    assert "bash-002" in _invoke("results", "--run_id", run_id, "--format", "table").output
    assert "1/2 (50.0%)" in _invoke("results", "--run_id", run_id, "--format", "summary").output


@pytest.mark.docker
def test_run_detached_completes():
    result = _invoke("run", "--agent", SCRIPTED, "--benchmark", "bash-operations", "--task_ids", "bash-001")
    assert result.exit_code == 0 and "Benchmark run submitted" in result.output
    run_id = re.search(r"Run ID: (\w+)", result.output).group(1)
    store, deadline = RunStore(), time.time() + 120
    while store.get_run(run_id).status != RunStatus.COMPLETED:
        assert time.time() < deadline, (store.artifacts_dir(run_id) / "executor.log").read_text()
        time.sleep(0.5)
    assert store.get_task_results(run_id)[0].passed is True


def test_status_reports_stale_when_executor_dead():
    store = RunStore()
    run = store.create_run("/a", "/b", ["t1"])
    dead = subprocess.Popen([sys.executable, "-c", "pass"])
    dead.wait()
    store.update_run(run.run_id, status=RunStatus.RUNNING, pid=dead.pid)
    assert "stale" in _invoke("status", "--run_id", run.run_id).output


def test_results_partial_warns_on_stderr_and_keeps_json_clean():
    run = RunStore().create_run("/a", "/b", ["t1"])
    result = _invoke("results", "--run_id", run.run_id)
    assert json.loads(result.stdout)["summary"]["pending"] == 1
    assert "partial" in result.stderr


@pytest.mark.parametrize(("command",), [("status",), ("results",)])
def test_unknown_run(command):
    result = _invoke(command, "--run_id", "nope")
    assert result.exit_code == 1 and "Run nope not found" in result.output
