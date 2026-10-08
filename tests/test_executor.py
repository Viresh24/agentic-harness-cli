import json
import subprocess
import sys
import time
from pathlib import Path

import pytest

from agentic_harness.executor import execute_run
from agentic_harness.models import ErrorPhase, RunStatus, TaskStatus
from agentic_harness.store import RunStore

pytestmark = pytest.mark.docker

TOY = Path(__file__).parent / "fixtures" / "benchmarks" / "toy"


def _agent(tmp_path: Path, command: str) -> str:
    d = tmp_path / "agent"
    d.mkdir(exist_ok=True)
    (d / "harness-agent.yaml").write_text(f"adapter: command\ncommand: {json.dumps(command)}\n")
    return str(d)


def _run(agent: str, benchmark: str, task_ids: list[str], **config):
    store = RunStore()
    run = store.create_run(agent, benchmark, task_ids, config=config)
    return store, execute_run(run.run_id, store), store.get_task_results(run.run_id)


def test_execute_run_bash_pass_and_fail(tmp_path):
    store, run, results = _run(
        _agent(tmp_path, "echo 'Hello World' > hello.txt"), "bash-operations", ["bash-001", "bash-002"]
    )
    assert [r.status for r in results] == [TaskStatus.PASSED, TaskStatus.FAILED]
    assert all(r.started_at and r.finished_at and r.agent_exit_status == "Submitted" for r in results)
    assert run.status == RunStatus.COMPLETED and run.pid and run.finished_at
    task_dir = store.artifacts_dir(run.run_id, "bash-001")
    assert json.loads((task_dir / "result.json").read_text())["status"] == "passed"
    assert (task_dir / "prompt.txt").read_text().startswith("Create a file named 'hello.txt'")


def test_execute_run_python_task_passes(tmp_path):
    _, _, results = _run(
        _agent(tmp_path, "printf 'def add():\\n    return 4\\n' > solution.py"), "python-tasks", ["py-001"]
    )
    assert results[0].status == TaskStatus.PASSED


def test_setup_failure_is_error_and_agent_not_run(tmp_path):
    store, run, results = _run(_agent(tmp_path, "true"), str(TOY), ["toy-badsetup", "toy-ok"])
    assert (results[0].status, results[0].error_phase) == (TaskStatus.ERROR, ErrorPhase.SETUP)
    assert "setup exploded" in results[0].error
    assert not (store.artifacts_dir(run.run_id, "toy-badsetup") / "agent.log").exists()
    assert results[1].status == TaskStatus.PASSED  # one task's failure doesn't stop the run


def test_agent_timeout_still_evaluates_and_cleans_container(tmp_path):
    agent = _agent(tmp_path, "echo 'Hello World' > hello.txt; sleep 30")
    _, run, results = _run(agent, "bash-operations", ["bash-001"], task_timeout=3)
    assert (results[0].agent_exit_status, results[0].status) == ("Timeout", TaskStatus.PASSED)
    leftover = subprocess.run(
        ["docker", "ps", "-aq", "--filter", f"label=agentic-harness={run.run_id}-bash-001"],
        capture_output=True,
        text=True,
    )
    assert leftover.stdout.split() == []


def test_infra_error_marks_task_error_not_run_failed(tmp_path):
    bench = tmp_path / "bad-image"
    bench.mkdir()
    (bench / "dataset.json").write_text(
        json.dumps([{"key": "toy-ok", "question": "q", "image": "agentic-harness-does-not-exist:nope"}])
    )
    manifest = (
        (TOY / "harness.yaml")
        .read_text()
        .replace('"setup.py"', f'"{TOY}/setup.py"')
        .replace('"check.py"', f'"{TOY}/check.py"')
    )
    (bench / "harness.yaml").write_text(manifest)
    _, run, results = _run(_agent(tmp_path, "true"), str(bench), ["toy-ok"])
    assert (results[0].status, results[0].error_phase) == (TaskStatus.ERROR, ErrorPhase.SANDBOX)
    assert run.status == RunStatus.COMPLETED


def test_unloadable_benchmark_marks_run_failed(tmp_path):
    store = RunStore()
    run = store.create_run(_agent(tmp_path, "true"), str(tmp_path / "missing-benchmark"), ["t1"])
    with pytest.raises(Exception):
        execute_run(run.run_id, store)
    failed = store.get_run(run.run_id)
    assert failed.status == RunStatus.FAILED and "missing-benchmark" in failed.error


def test_sigterm_marks_run_failed_and_cleans_container(tmp_path, harness_home):
    store = RunStore()
    run = store.create_run(_agent(tmp_path, "sleep 60"), "bash-operations", ["bash-001"])
    proc = subprocess.Popen([sys.executable, "-m", "agentic_harness.executor", run.run_id], stderr=subprocess.DEVNULL)
    label = f"label=agentic-harness={run.run_id}-bash-001"
    deadline = time.time() + 60
    while not subprocess.run(["docker", "ps", "-q", "--filter", label], capture_output=True, text=True).stdout.strip():
        assert time.time() < deadline and proc.poll() is None, "agent container never started"
        time.sleep(0.5)
    proc.terminate()
    proc.wait(timeout=60)
    failed = store.get_run(run.run_id)
    assert (failed.status, failed.error) == (RunStatus.FAILED, "interrupted")
    assert (
        subprocess.run(["docker", "ps", "-aq", "--filter", label], capture_output=True, text=True).stdout.split() == []
    )
