"""Executor: runs a stored run's tasks (setup → agent → evaluate) and records the results."""

import argparse
import json
import os
import shutil
import signal
import threading
import time

from agentic_harness.agents import Agent, load_agent
from agentic_harness.benchmarks import Benchmark, BenchmarkError, load_benchmark
from agentic_harness.models import ErrorPhase, RunRecord, RunStatus, Task, TaskResult, TaskStatus
from agentic_harness.sandbox import Sandbox, SandboxError, ensure_docker
from agentic_harness.store import RunStore

DEFAULT_TASK_TIMEOUT = 900


def execute_run(run_id: str, store: RunStore | None = None) -> RunRecord:
    """Run every task of a stored run in order and mark the run completed (or failed if the executor crashes)."""
    store = store or RunStore()
    run = store.get_run(run_id)
    if run is None:
        raise ValueError(f"Run {run_id} not found")
    store.update_run(run_id, status=RunStatus.RUNNING, started_at=time.time(), pid=os.getpid())
    restore_sigterm = _sigterm_as_interrupt()
    try:
        ensure_docker()
        benchmark, agent = load_benchmark(run.benchmark), load_agent(run.agent)
        timeout = run.config.get("task_timeout", DEFAULT_TASK_TIMEOUT)
        for task in benchmark.get_tasks(run.task_ids):
            run_task(task, benchmark, agent, store, run_id, timeout)
    except BaseException as e:
        reason = "interrupted" if isinstance(e, KeyboardInterrupt) else f"{type(e).__name__}: {e}"
        store.update_run(run_id, status=RunStatus.FAILED, finished_at=time.time(), error=reason)
        raise
    finally:
        restore_sigterm()
    store.update_run(run_id, status=RunStatus.COMPLETED, finished_at=time.time())
    return store.get_run(run_id)


def run_task(task: Task, benchmark: Benchmark, agent: Agent, store: RunStore, run_id: str, timeout: float) -> TaskResult:
    """Run one task in a fresh workspace and container, then save its result."""
    task_dir = store.artifacts_dir(run_id, task.id)
    workspace = task_dir / "workspace"
    shutil.rmtree(workspace, ignore_errors=True)
    workspace.mkdir()
    started = time.time()
    store.save_task_result(run_id, TaskResult(task.id, TaskStatus.RUNNING, started_at=started))
    sandbox = Sandbox(task.docker_image, workspace, label=f"{run_id}-{task.id}")
    try:
        result = _run_phases(task, benchmark, agent, sandbox, task_dir, timeout, started)
    except Exception as e:
        result = TaskResult.from_error(task.id, ErrorPhase.INTERNAL, f"{type(e).__name__}: {e}", started, time.time())
    finally:
        sandbox.cleanup()
    store.save_task_result(run_id, result)
    (task_dir / "result.json").write_text(json.dumps(result.to_dict(), indent=2))
    return result


def _run_phases(
    task: Task, benchmark: Benchmark, agent: Agent, sandbox: Sandbox, task_dir, timeout: float, started: float
) -> TaskResult:
    try:
        benchmark.setup(task, sandbox.workspace, task_dir)
        prompt = benchmark.render_prompt(task)
    except BenchmarkError as e:
        return TaskResult.from_error(task.id, ErrorPhase.SETUP, str(e), started, time.time())
    (task_dir / "prompt.txt").write_text(prompt)
    try:
        sandbox.prepare()  # image pull happens outside the agent's timeout
    except SandboxError as e:
        return TaskResult.from_error(task.id, ErrorPhase.SANDBOX, str(e), started, time.time())
    out = agent.run(prompt, task, sandbox, task_dir, timeout)
    if out.error:
        return TaskResult.from_error(task.id, ErrorPhase.AGENT, out.error, started, time.time(), agent=out)
    outcome = benchmark.evaluate(task, sandbox.workspace, task_dir)
    return TaskResult.from_outcome(task.id, outcome, out, started, time.time())


def _sigterm_as_interrupt():
    # `kill <pid>` should mark the run failed just like Ctrl-C does. Signals can only be set from the main thread.
    if threading.current_thread() is not threading.main_thread():
        return lambda: None

    def handler(signum, frame):
        raise KeyboardInterrupt

    previous = signal.signal(signal.SIGTERM, handler)
    return lambda: signal.signal(signal.SIGTERM, previous)


def main() -> None:
    """Command-line entry point: `python -m agentic_harness.executor <run_id>`."""
    parser = argparse.ArgumentParser(description="Execute a stored benchmark run.")
    parser.add_argument("run_id")
    execute_run(parser.parse_args().run_id)


if __name__ == "__main__":
    main()
