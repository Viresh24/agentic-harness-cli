import subprocess
import sys

import pytest

from agentic_harness.models import ErrorPhase, RunStatus, TaskResult, TaskStatus
from agentic_harness.store import RunStore


def test_create_and_get_run(harness_home):
    store = RunStore()
    run = store.create_run("/abs/agent", "/abs/bench", ["t1", "t2"], config={"task_timeout": 5})
    assert len(run.run_id) == 8
    assert store.get_run(run.run_id) == run
    assert (run.status, run.task_ids, run.config) == (RunStatus.QUEUED, ["t1", "t2"], {"task_timeout": 5})
    results = store.get_task_results(run.run_id)
    assert [(r.task_id, r.status) for r in results] == [("t1", TaskStatus.PENDING), ("t2", TaskStatus.PENDING)]
    assert (harness_home / "harness.db").is_file()


def test_save_task_result_upserts():
    store = RunStore()
    run = store.create_run("a", "b", ["t1", "t2"])
    store.save_task_result(run.run_id, TaskResult("t1", TaskStatus.RUNNING, started_at=1.0))
    final = TaskResult(
        task_id="t1",
        status=TaskStatus.ERROR,
        error="boom",
        error_phase=ErrorPhase.SETUP,
        duration=2.5,
        agent_exit_status="Timeout",
        started_at=1.0,
        finished_at=3.5,
        details={"nested": {"a": [1, 2]}},
    )
    store.save_task_result(run.run_id, final)
    assert store.get_task_results(run.run_id) == [final, TaskResult("t2")]


def test_update_run():
    store = RunStore()
    run = store.create_run("a", "b", ["t1"])
    store.update_run(run.run_id, status=RunStatus.RUNNING, pid=4242, started_at=10.0)
    got = store.get_run(run.run_id)
    assert (got.status, got.pid, got.started_at, got.task_ids) == (RunStatus.RUNNING, 4242, 10.0, ["t1"])
    with pytest.raises(TypeError):
        store.update_run(run.run_id, not_a_field=1)


def test_store_shared_across_instances(harness_home):
    run = RunStore(harness_home).create_run("a", "b", ["t1"])
    other = RunStore(harness_home)
    other.save_task_result(run.run_id, TaskResult("t1", TaskStatus.PASSED, passed=True, score=1.0))
    assert RunStore(harness_home).get_task_results(run.run_id)[0].passed is True


def test_get_run_missing_returns_none():
    assert RunStore().get_run("nope") is None


def test_artifacts_dir_layout(harness_home):
    store = RunStore()
    assert store.artifacts_dir("abc12345") == harness_home / "abc12345"
    task_dir = store.artifacts_dir("abc12345", "bash-001")
    assert task_dir == harness_home / "abc12345" / "tasks" / "bash-001" and task_dir.is_dir()


def test_claim_next_run_is_fifo_and_once():
    store = RunStore()
    first, second = store.create_run("a", "b", ["t1"]), store.create_run("a", "b", ["t1"])
    assert store.claim_next_run().run_id == first.run_id
    claimed = store.claim_next_run()
    assert claimed.run_id == second.run_id and claimed.status == RunStatus.RUNNING
    assert store.claim_next_run() is None


def test_claim_never_hands_out_a_run_twice_across_processes(harness_home):
    store = RunStore()
    queued = {store.create_run("a", "b", ["t1"]).run_id for _ in range(30)}
    claimer = (
        "from agentic_harness.store import RunStore\n"
        "s = RunStore()\n"
        "while (r := s.claim_next_run()):\n"
        "    print(r.run_id)\n"
    )
    procs = [subprocess.Popen([sys.executable, "-c", claimer], stdout=subprocess.PIPE, text=True) for _ in range(3)]
    claimed = [line for p in procs for line in p.communicate(timeout=60)[0].split()]
    assert sorted(claimed) == sorted(queued)  # every run claimed exactly once


def test_list_runs_filters_and_orders_newest_first():
    store = RunStore()
    old, new = store.create_run("a", "b", ["t1"]), store.create_run("a", "b", ["t1"])
    store.update_run(old.run_id, status=RunStatus.COMPLETED)
    assert [r.run_id for r in store.list_runs()] == [new.run_id, old.run_id]
    assert [r.run_id for r in store.list_runs([RunStatus.QUEUED, RunStatus.RUNNING])] == [new.run_id]


def test_create_run_with_status_skips_the_queue():
    store = RunStore()
    store.create_run("a", "b", ["t1"], status=RunStatus.RUNNING)
    assert store.claim_next_run() is None
