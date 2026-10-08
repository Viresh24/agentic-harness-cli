# Agentic Harness: Guide

Run **any agent** against **any benchmark** from one CLI:

- Runs are **submitted to a queue**, and background **workers** execute them, with a cap on how many run at once.
- Each task gets a fresh workspace and its own Docker container; the agent works inside it, and the benchmark grades the result.
- Every result is stored in a database and aggregated into accuracy metrics.

```
harness run      Submit a run to the queue (or run it immediately with --wait)
harness worker   Execute queued runs, at most --concurrency at a time
harness list     Show active runs (--all for every run)
harness status   Check the status of one run
harness results  Get results from a run (json, table, or summary)
```



## Setup

**Prerequisites:** Python 3.11+, [uv](https://docs.astral.sh/uv/), Docker (running), and an LLM API key (for mini-swe-agent).

```bash
make init        # fetch the mini-swe-agent git submodule into agents/mini-swe-agent
make install     # uv sync: installs the harness and mini-swe-agent into .venv
source .venv/bin/activate        # or prefix every command below with `uv run`
```

Configure mini-swe-agent's model and API key once:

```bash
# interactive: model + API key
mini-extra config setup
# change the model later
mini-extra config set MSWEA_MODEL_NAME anthropic/claude-sonnet-5-5
```

Use a model ID that exists, without a date suffix (e.g. `anthropic/claude-sonnet-5-5`). For Anthropic, use an API key scoped to a workspace.

**Check your setup for free** (no LLM): this runs a scripted agent that just writes `hello.txt`, so it only solves `bash-001`:

```bash
harness run --agent tests/fixtures/agents/scripted --benchmark bash-operations --task_ids bash-001 --wait
```



## Running benchmarks

```bash
# 1. Submit as many runs as you like; each returns immediately with a run ID
harness run --agent agents/mini-swe-agent --benchmark bash-operations
harness run --agent agents/mini-swe-agent --benchmark python-tasks --task_ids py-001,py-002

# 2. Start a worker (in another terminal); it executes up to 2 runs at once
harness worker --concurrency 2

# 3. Watch progress, then get results
harness list
harness status  --run_id <run_id>
harness results --run_id <run_id>                    # json (default)
harness results --run_id <run_id> --format table
harness results --run_id <run_id> --format summary
```

```
$ harness run --agent tests/fixtures/agents/scripted --benchmark bash-operations
Run ID: c33aec84
Benchmark run queued
A worker executes queued runs; start one with: harness worker
Check progress: harness status --run_id c33aec84
```


| `harness run` option | Meaning                                                                                                |
| -------------------- | ------------------------------------------------------------------------------------------------------ |
| `--agent`            | Agent directory, e.g. `agents/mini-swe-agent`                                                          |
| `--benchmark`        | Benchmark name under `benchmarks/` (`bash-operations`, `python-tasks`, `python-bugfix`) or a path to a benchmark folder |
| `--task_ids`         | Comma-separated task IDs. Omit to run every task.                                                      |
| `--wait`             | Skip the queue: run now in the foreground, printing each task's result, then the summary               |
| `--task-timeout`     | Seconds allowed per task (default 900)                                                                 |



| `harness worker` option | Meaning                                              |
| ----------------------- | ---------------------------------------------------- |
| `--concurrency`         | Maximum number of runs executing at once (default 2) |


Things to know:

- **Bad input is rejected up front.** Unknown benchmarks, agents or task IDs are rejected before anything is queued, with the valid options listed.
- **Queued runs wait for a worker.** If none is running, `harness list` keeps showing them as `queued`.
- **An idle worker waits.** With an empty queue it checks about once a second (effectively no CPU), and picks up new runs within a second of submission.
- **Stopping a worker:** the first Ctrl-C or SIGTERM stops it claiming new runs and waits for running runs to finish (with nothing running, it exits at once). A second one aborts the runs, which are marked `failed` (`interrupted`).
- **Several workers can run at once.** Each run is claimed by exactly one worker.



### Example output

From a run of the scripted agent on all 5 bash tasks. It only knows how to solve `bash-001`, so 1/5 is the correct result.

```
$ harness status --run_id 9cc0b62d          # while running
Run 9cc0b62d: running
Agent:     /…/tests/fixtures/agents/scripted
Benchmark: /…/benchmarks/bash-operations
Progress:  3/5
  bash-001  passed
  bash-002  failed
  bash-003  failed
  bash-004  running
  bash-005  pending

$ harness results --run_id 9cc0b62d --format table
TASK      STATUS  SCORE  DURATION  AGENT_EXIT  ERROR
bash-001  passed  1.00   0.3s      Submitted
bash-002  failed  0.00   0.3s      Submitted
bash-003  failed  0.00   0.2s      Submitted
bash-004  failed  0.00   0.2s      Submitted
bash-005  failed  0.00   0.2s      Submitted

passed 1/5 (20.0%), errored 0, pending 0

$ harness results --run_id 9cc0b62d --format summary
Run 9cc0b62d  completed
Agent:      /…/tests/fixtures/agents/scripted
Benchmark:  /…/benchmarks/bash-operations
Accuracy:              1/5 (20.0%)
Accuracy excl. errors: 1/5 (20.0%)
Mean score:            0.20
Errored: 0   Pending: 0
```

`--format json` returns `{"run": {...}, "summary": {...}, "tasks": [...]}`, which is the format to use for scripts and further analysis.

### Reading results


| Task status           | Meaning                                                                                                                                                                                        |
| --------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `passed` / `failed`   | The benchmark's grader judged the agent's work correct or incorrect                                                                                                                            |
| `error`               | The harness couldn't judge it: setup, Docker, the agent process or the grader broke. The `ERROR` column shows the phase (`setup`, `sandbox`, `agent`, `evaluate`, `internal`) and the message. |
| `pending` / `running` | Not finished yet                                                                                                                                                                               |


- **Accuracy** = passed / all tasks.
- **Accuracy excl. errors** = passed / (passed + failed), so infrastructure problems aren't counted against the agent.
- **Run statuses:** `queued` → `running` → `completed`, or `failed` if its executor crashed or was aborted. `stale` in `status` or `list` means a running run's executor process has died. A worker marks such runs `failed` when it starts.



### Where everything is saved

Under `runs/`, or the folder in `$HARNESS_HOME`:

```
runs/
  harness.db                       # SQLite: the queue, run state, and per-task results
  <run_id>/executor.log            # executor output for the run
  <run_id>/tasks/<task_id>/
    workspace/                     # the files the agent worked on
    prompt.txt                     # exact prompt sent to the agent
    agent.log                      # agent console output
    trajectory.json                # mini-swe-agent's full transcript (messages, commands, outputs)
    setup.* / evaluate.*           # benchmark script output and exit codes
    result.json                    # this task's result
```

To debug a failed task, start with its `trajectory.json` and `agent.log`.

## How it works

```
harness run ──validate──► runs table (status=queued) ◄── claim (atomic UPDATE … RETURNING) ── harness worker --concurrency N
     │ returns run_id               ▲                                                                │ keeps ≤ N children
     │                              │ writes progress/results                                        ▼
harness list / status / results ────┘ (read only)                         python -m agentic_harness.executor <run_id>
                                                                                                     │ for each task
       benchmarks/<name>/harness.yaml                    agent config                                ▼
                    │                                         │                                  run_task
            ┌───────▼───────┐                        ┌────────▼────────┐
            │   Benchmark   │                        │      Agent      │
            └──┬─────────┬──┘                        └────────┬────────┘
     get_tasks │         │ setup() / evaluate()               │ run(prompt, task, sandbox)
               │         │ (on the host, in the workspace)    │
          Task ▼         ▼ EvalOutcome                        ▼ AgentOutput
      ┌───────────────────────────────────────────────────────────────────┐
      │ run_task: setup → prompt → pull image → agent → grade → cleanup    │
      └───────────────────────────────────────────────────────────────────┘
      Sandbox: one Docker container per task (image from the task's dataset row),
               workspace mounted at /workspace, labelled so it is always removed.
```

**Submitting and scheduling:**

1. `harness run` validates its input and stores the run in SQLite as `queued`, with the resolved task list, then returns.
2. `harness worker` repeatedly claims the oldest queued run with one atomic SQL update, so two workers can never take the same run.
3. For each claimed run, the worker starts the executor as a separate child process, never more than `--concurrency` at once. One run's crash can't affect the others.

**Executing a run:** the executor runs the run's tasks one at a time. For each task:

1. Creates a fresh workspace.
2. Runs the **benchmark's setup** script.
3. Gives the **agent** the task prompt. The agent works in a container from the task's `docker_image`, with the workspace mounted.
4. Runs the **benchmark's grader** on the workspace.
5. Saves a `TaskResult` and removes the container.

One task's failure never stops the run, and a task that times out is still graded.

The code (`src/agentic_harness/`) is split into four abstractions that only meet through shared types in `models.py`:


| Abstraction   | Code          | Role                                                                                                                     |
| ------------- | ------------- | ------------------------------------------------------------------------------------------------------------------------ |
| **Benchmark** | `benchmarks/` | Lists tasks, sets up a workspace, grades it. One generic `ScriptBenchmark` is driven by each benchmark's `harness.yaml`. |
| **Agent**     | `agents/`     | `run(prompt, task, sandbox, …) -> AgentOutput`. Adapters: `MiniSweAgent` and `CommandAgent` (scripted, no LLM).          |
| **Sandbox**   | `sandbox.py`  | The per-task Docker container: mount, host user, cleanup label, image download                                           |
| **Run store** | `store.py`    | SQLite queue, run and task state, plus the per-task artifact folders                                                     |


How the other modules fit in:

- `executor.py` runs one run's tasks.
- `worker.py` pulls runs from the queue.
- `report.py` computes the metrics and output formats.
- `cli.py` is the `harness` command.

The harness core never names a specific benchmark or agent.

**mini-swe-agent** runs as a subprocess on the host, so the API key stays on the host. It uses mini's built-in Docker environment, so every shell command it issues runs inside the task container.

### How the spec is covered


| SPECS.md requirement                       | How it's met                                                                                               |
| ------------------------------------------ | ---------------------------------------------------------------------------------------------------------- |
| `run` / `status` / `results` CLI           | `cli.py`, plus `worker` and `list` for the queue                                                           |
| Environment setup per task                 | The benchmark's setup script prepares a fresh workspace; `Sandbox` gives the task its own Docker container |
| Agent execution inside the environment     | The `Agent` contract; mini-swe-agent's actions run in the task container                                   |
| Evaluation                                 | The benchmark's grader → `passed` / `failed` / `error`                                                     |
| Aggregation in a uniform structured format | `results --format json` with accuracy (with and without errors) and mean score                             |
| Submit without blocking                    | `run` only enqueues and returns                                                                            |
| Workers pull from a queue                  | `harness worker` claims runs atomically from the SQLite queue                                              |
| Isolated containers                        | One Docker container per task, always removed afterwards                                                   |
| Resource management                        | At most `--concurrency` runs execute at once per worker                                                    |
| Results persisted in a database            | SQLite `runs/harness.db`                                                                                   |
| CLI for viewing active runs                | `harness list`                                                                                             |




## Results: mini-swe-agent on Claude Sonnet 5.5

All runs were on 2026-10-08 with mini-swe-agent and `anthropic/claude-sonnet-5-5` (mini's default limits; harness task timeout 900s).

### Single runs


| Benchmark       | Run ID     | Mode                                           | Accuracy       | Errored | Wall time |
| --------------- | ---------- | ---------------------------------------------- | -------------- | ------- | --------- |
| bash-operations | `6a33a8d3` | `--wait` (foreground)                          | **5/5 (100%)** | 0       | ~29s      |
| python-tasks    | `cc9259f6` | background, before the queue (`status` polled) | **3/3 (100%)** | 0       | ~20s      |


```
$ harness run --agent agents/mini-swe-agent --benchmark bash-operations --wait
Run ID: 6a33a8d3
  bash-001  passed
  bash-002  passed
  bash-003  passed
  bash-004  passed
  bash-005  passed

Run 6a33a8d3  completed
Agent:      /…/agents/mini-swe-agent
Benchmark:  /…/benchmarks/bash-operations
Accuracy:              5/5 (100.0%)
Accuracy excl. errors: 5/5 (100.0%)
Mean score:            1.00
Errored: 0   Pending: 0

$ harness results --run_id 6a33a8d3 --format table
TASK      STATUS  SCORE  DURATION  AGENT_EXIT  ERROR
bash-001  passed  1.00   7.1s      Submitted
bash-002  passed  1.00   4.1s      Submitted
bash-003  passed  1.00   5.7s      Submitted
bash-004  passed  1.00   8.5s      Submitted
bash-005  passed  1.00   3.3s      Submitted

passed 5/5 (100.0%), errored 0, pending 0

$ harness results --run_id cc9259f6 --format table
TASK    STATUS  SCORE  DURATION  AGENT_EXIT  ERROR
py-001  passed  1.00   7.7s      Submitted
py-002  passed  1.00   6.5s      Submitted
py-003  passed  1.00   6.0s      Submitted

passed 3/3 (100.0%), errored 0, pending 0
```

The `py-002` trajectory confirms mini's commands ran in mini's `DockerEnvironment`, using `python:3.11-slim` with the workspace at `/workspace`. The agent finished in 4 model turns and wrote an iterative `fibonacci` in `solution.py`.

### Through the queue

Three runs were submitted back to back, then one worker was started with `--concurrency 2`, and `harness list` was polled about once a second (snapshots condensed):

```
$ harness list                      # before starting the worker
RUN_ID    STATUS  PROGRESS  BENCHMARK        AGENT           CREATED
26dd5619  queued  0/5       bash-operations  mini-swe-agent  2026-10-08 03:02:18
70c3187e  queued  0/3       python-tasks     mini-swe-agent  2026-10-08 03:02:18
8d5f20f8  queued  0/5       bash-operations  mini-swe-agent  2026-10-08 03:02:18

$ harness worker --concurrency 2    # list snapshots while it worked:
[03:02:18] 26dd5619 queued  0/5 | 70c3187e running 0/3 | 8d5f20f8 running 0/5
[03:02:33] 26dd5619 queued  0/5 | 70c3187e running 2/3 | 8d5f20f8 running 2/5
[03:02:41] 26dd5619 running 0/5 |                        8d5f20f8 running 3/5   ← slot freed, third run starts
[03:03:07] 26dd5619 running 4/5
[03:03:10] No active runs

Worker log:
Worker started (concurrency 2)
Started 8d5f20f8
Started 70c3187e
Finished 70c3187e: completed
Started 26dd5619
Finished 8d5f20f8: completed
Finished 26dd5619: completed
Stopping: waiting for running runs to finish (signal again to abort them)
```


| Run        | Benchmark       | Accuracy       |
| ---------- | --------------- | -------------- |
| `8d5f20f8` | bash-operations | **5/5 (100%)** |
| `70c3187e` | python-tasks    | **3/3 (100%)** |
| `26dd5619` | bash-operations | **5/5 (100%)** |


**Checks after all runs:**

- Never more than 2 runs were running at once, and the third waited until a slot freed up.
- The queue drained in about 52 seconds, and SIGTERM stopped the worker cleanly (exit code 0).
- `results` JSON was valid for every run.
- `docker ps -a --filter label=agentic-harness` was empty, so no containers were left behind.
- The full artifacts are in `runs/<run_id>/`. They aren't committed, because `runs/` is git-ignored.



## Included benchmarks

| Benchmark       | Tasks | What the agent does                                                        | Verdict                                         |
| --------------- | ----- | -------------------------------------------------------------------------- | ----------------------------------------------- |
| `bash-operations` | 5   | Simple file and shell tasks in `alpine`                                    | Grader exit code                                |
| `python-tasks`    | 3   | Write a small function in `solution.py`                                    | `passed` in the grader's JSON                   |
| `python-bugfix`   | 5   | Fix a planted bug in a module without editing its tests (see `benchmarks/python-bugfix/README.md`) | **Partial credit:** fraction of tests passing; editing the tests scores 0 |



## Adding a benchmark

Add a folder under `benchmarks/` with a `harness.yaml` that tells the harness how to read the dataset and call the scripts. The benchmark's own code doesn't change. For example, `benchmarks/python-tasks/harness.yaml`:

```yaml
name: python-tasks
dataset: dataset.json                       # JSON list of tasks
fields: {id: id, prompt: prompt, docker_image: docker_image}   # which dataset fields hold these
setup:    ["{python}", "prepare.py", "{task_id}", "--workspace", "{workspace}"]
evaluate: ["{python}", "grade.py",   "{task_id}", "--workspace", "{workspace}"]
pass_from: json.passed                      # or exit_code (0 = pass, 1 = fail)
prompt_template: "{prompt}\n\nWrite your solution in `{solution_file}` in the current working directory. ..."
timeout: 120                                # seconds per setup/evaluate call
```

- **Placeholders:** `{python}` (the harness's Python), `{workspace}` (absolute path), `{task_id}`, `{benchmark_dir}`.
- **Prompt template:** can use any field from the task's dataset row.
- **Error handling:** a grader that crashes or prints no valid verdict gives `error`, not `failed`.
- **Other kinds of benchmark:** if one isn't "dataset + scripts", set `class: "your_pkg.module:YourBenchmark"` in its manifest and subclass `agentic_harness.benchmarks.Benchmark`.



## Adding an agent

1. Subclass `agentic_harness.agents.Agent` and implement:
  ```python
   run(prompt, task, sandbox, artifacts_dir, timeout) -> AgentOutput
  ```
  - Run the agent's actions in the sandbox container using `sandbox.image` and `sandbox.run_args()`.
  - Write logs to `artifacts_dir`.
  - Return `exit_status="Timeout"` on timeout.
  - Set `AgentOutput.error` only when the agent couldn't run at all.
2. Register it in `ADAPTERS` in `agents/__init__.py`.
3. Give the agent's folder a `harness-agent.yaml` with `adapter: <name>` plus its own settings. Alternatively, put the config in `src/agentic_harness/agent_configs/<folder name>.yaml`; that's how `agents/mini-swe-agent` works, since it's a submodule.

Then: `harness run --agent agents/<your-agent> --benchmark …`.

## Design trade-offs

- **The queue is the existing SQLite** `runs` **table.** There's no broker to install, and one database holds the queue, the state and the results. Postgres (`SKIP LOCKED`) is the step up for workers on several machines; only `store.py` would change.
- **Each run executes in its own process.** A crash or hang is contained to that run, and `kill <pid>` still marks just that run `failed`.
- **The concurrency cap counts runs; tasks within a run execute one at a time.** It's a single number that bounds containers, CPU and API calls. A global pool of task slots would use resources better for very large runs.
- **Setup and grading run on the host,** against the mounted workspace. That's how the provided scripts were written, and `alpine` has no Python. The cost is that `prepare.py` installs packages into the harness venv.
- **The agent loop runs on the host; only its actions run in Docker.** This keeps API keys out of containers and works on minimal images.
- **No cost or step limits are imposed by the harness.** The only harness limit is the per-task timeout; mini-swe-agent keeps its own defaults.
- **The Docker image comes only from each task's dataset row,** because a benchmark's environment is part of its definition.



## Tests

```bash
make test                       # 99 tests, Docker required for most; LLM test skipped
HARNESS_RUN_LLM=1 make test     # also runs mini-swe-agent on Sonnet against bash-001
```

Tests use a temporary `HARNESS_HOME`. Docker tests are skipped automatically if Docker isn't running.

Highlights:

- Both real benchmarks are graded against hand-written solutions.
- Every agent and executor path runs in real Docker using the scripted agent.
- **3 processes racing over 30 queued runs claim each exactly once.**
- **4 runs with concurrency 2 execute exactly 2 at a time.**
- SIGTERM handling and stale-run detection are covered.

The key failure paths were mutation-checked: breaking the code on purpose made its test fail. This covers the no-JSON error rule, container cleanup, SIGTERM handling, stale detection and the concurrency cap.