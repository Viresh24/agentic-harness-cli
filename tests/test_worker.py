import json
import signal
import subprocess
import sys
import time
from pathlib import Path

import pytest

from agentic_harness.models import RunStatus
from agentic_harness.store import RunStore
from agentic_harness.worker import fail_stale_runs


def _agent(tmp_path: Path, command: str) -> str:
    d = tmp_path / "agent"
    d.mkdir(exist_ok=True)
    (d / "harness-agent.yaml").write_text(f"adapter: command\ncommand: {json.dumps(command)}\n")
    return str(d)


def _start_worker(concurrency: int) -> subprocess.Popen:
    return subprocess.Popen(
        [sys.executable, "-m", "agentic_harness.cli", "worker", "--concurrency", str(concurrency)],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )


def _wait_until(condition, timeout: float = 120):
    deadline = time.time() + timeout
    while not condition():
        assert time.time() < deadline, "timed out"
        time.sleep(0.2)


@pytest.mark.docker
def test_worker_caps_concurrency_and_completes_all_runs(tmp_path):
    store = RunStore()
    agent = _agent(tmp_path, "sleep 2; echo 'Hello World' > hello.txt")
    run_ids = [store.create_run(agent, "bash-operations", ["bash-001"]).run_id for _ in range(4)]
    worker = _start_worker(concurrency=2)
    try:
        max_running = 0

        def all_done():
            nonlocal max_running
            runs = [store.get_run(r) for r in run_ids]
            max_running = max(max_running, sum(r.status == RunStatus.RUNNING for r in runs))
            return all(r.status == RunStatus.COMPLETED for r in runs)

        _wait_until(all_done)
    finally:
        worker.send_signal(signal.SIGTERM)
        worker.wait(timeout=60)
    assert max_running == 2  # ran in parallel, never above the cap
    assert all(store.get_task_results(r)[0].passed for r in run_ids)


@pytest.mark.docker
def test_first_sigterm_lets_running_run_finish(tmp_path):
    store = RunStore()
    run = store.create_run(_agent(tmp_path, "sleep 3; echo 'Hello World' > hello.txt"), "bash-operations", ["bash-001"])
    worker = _start_worker(concurrency=1)
    _wait_until(lambda: store.get_run(run.run_id).pid is not None)
    worker.send_signal(signal.SIGTERM)
    assert worker.wait(timeout=60) == 0
    assert store.get_run(run.run_id).status == RunStatus.COMPLETED


def test_fail_stale_runs_marks_dead_executors_failed():
    store = RunStore()
    dead = subprocess.Popen([sys.executable, "-c", "pass"])
    dead.wait()
    stale = store.create_run("/a", "/b", ["t1"], status=RunStatus.RUNNING)
    store.update_run(stale.run_id, pid=dead.pid)
    just_claimed = store.create_run("/a", "/b", ["t1"], status=RunStatus.RUNNING)  # pid not recorded yet
    fail_stale_runs(store)
    assert store.get_run(stale.run_id).status == RunStatus.FAILED
    assert store.get_run(just_claimed.run_id).status == RunStatus.RUNNING
