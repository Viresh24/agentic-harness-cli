"""Worker: pulls queued runs from the store and executes up to N of them at once, each in its own process."""

import os
import signal
import subprocess
import sys
import time
from collections.abc import Callable

from agentic_harness.models import RunStatus
from agentic_harness.store import RunStore

POLL_INTERVAL = 1.0


def run_worker(concurrency: int, store: RunStore | None = None, log: Callable[[str], None] = print) -> None:
    """Process the queue until stopped: first SIGINT/SIGTERM stops claiming and waits, a second one aborts runs."""
    store = store or RunStore()
    fail_stale_runs(store)
    children: dict[str, subprocess.Popen] = {}
    stopping = False

    def on_signal(signum, frame):
        nonlocal stopping
        if stopping:
            for child in children.values():
                child.terminate()  # the executor marks its run failed ("interrupted")
        stopping = True
        log("Stopping: waiting for running runs to finish (signal again to abort them)")

    signal.signal(signal.SIGINT, on_signal)
    signal.signal(signal.SIGTERM, on_signal)
    log(f"Worker started (concurrency {concurrency})")
    while True:
        for run_id, child in list(children.items()):
            if child.poll() is not None:
                del children[run_id]
                log(f"Finished {run_id}: {store.get_run(run_id).status.value}")
        if stopping and not children:
            return
        while not stopping and len(children) < concurrency and (run := store.claim_next_run()):
            children[run.run_id] = _spawn_executor(store, run.run_id)
            log(f"Started {run.run_id}")
        time.sleep(POLL_INTERVAL)


def fail_stale_runs(store: RunStore) -> None:
    """Mark runs whose executor process has died as failed."""
    for run in store.list_runs([RunStatus.RUNNING]):
        if run.pid and not pid_alive(run.pid):
            store.update_run(run.run_id, status=RunStatus.FAILED, error=f"executor process {run.pid} died")


def pid_alive(pid: int) -> bool:
    """Whether a process with this pid exists."""
    try:
        os.kill(pid, 0)  # signal 0 only checks the process exists
    except ProcessLookupError:
        return False
    except PermissionError:  # exists, owned by another user
        pass
    return True


def _spawn_executor(store: RunStore, run_id: str) -> subprocess.Popen:
    with (store.artifacts_dir(run_id) / "executor.log").open("w") as log:
        # A new session keeps Ctrl-C in the worker's terminal from reaching the executors directly.
        return subprocess.Popen(
            [sys.executable, "-m", "agentic_harness.executor", run_id],
            stdout=log,
            stderr=subprocess.STDOUT,
            start_new_session=True,
        )
