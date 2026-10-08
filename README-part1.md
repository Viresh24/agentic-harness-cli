# Agentic Harness: Part 1

Run **any agent** against **any benchmark** from one CLI. Each task gets a fresh workspace and its own Docker container; the agent works inside it, the benchmark grades the result, and the results are stored and aggregated into accuracy metrics.

```
harness run      Run an agent against a benchmark
harness status   Check the status of a benchmark run
harness results  Get results from a completed run
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



## Running a benchmark

```bash
# Start a run (in the background by default); prints a run ID
harness run --agent agents/mini-swe-agent --benchmark bash-operations
harness run --agent agents/mini-swe-agent --benchmark python-tasks --task_ids py-001,py-002

# Check progress
harness status --run_id <run_id>

# Get results: json (default), table, or summary
harness results --run_id <run_id>
harness results --run_id <run_id> --format table
harness results --run_id <run_id> --format summary
```


| `harness run` option | Meaning                                                                                                |
| -------------------- | ------------------------------------------------------------------------------------------------------ |
| `--agent`            | Agent directory, e.g. `agents/mini-swe-agent`                                                          |
| `--benchmark`        | Benchmark name under `benchmarks/` (`bash-operations`, `python-tasks`) or a path to a benchmark folder |
| `--task_ids`         | Comma-separated task IDs. Omit to run every task.                                                      |
| `--wait`             | Run in the foreground, printing each task's result as it finishes, then the summary                    |
| `--task-timeout`     | Seconds allowed per task (default 900)                                                                 |


Unknown benchmarks, agents or task IDs are rejected up front, with the valid options listed.

### Example output

The following is real output from a run of the scripted agent on all 5 bash tasks. It only knows how to solve `bash-001`, so 1/5 is the correct result.

```
$ harness run --agent tests/fixtures/agents/scripted --benchmark bash-operations
Run ID: 9cc0b62d
Benchmark run submitted
Check progress: harness status --run_id 9cc0b62d

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
- A run that shows `stale` in `status` has lost its background process (e.g. it was killed). Its results stay partial.



### Where everything is saved

Under `runs/`, or the folder in `$HARNESS_HOME`:

```
runs/
  harness.db                       # SQLite: runs and per-task results
  <run_id>/executor.log            # background run log
  <run_id>/tasks/<task_id>/
    workspace/                     # the files the agent worked on
    prompt.txt                     # exact prompt sent to the agent
    agent.log                      # agent console output
    trajectory.json                # mini-swe-agent's full transcript (messages, commands, outputs)
    setup.* / evaluate.*           # benchmark script output and exit codes
    result.json                    # this task's result
```

To debug a failed task, start with its `trajectory.json` and `agent.log`.

## Results: mini-swe-agent on Claude Sonnet 5.5

Both provided benchmarks, run through the harness on 2026-10-08 with mini-swe-agent and `anthropic/claude-sonnet-5-5` (mini's default limits; harness task timeout 900s).

| Benchmark       | Run ID     | Mode                   | Accuracy        | Errored | Wall time |
| --------------- | ---------- | ---------------------- | --------------- | ------- | --------- |
| bash-operations | `6a33a8d3` | `--wait` (foreground)  | **5/5 (100%)**  | 0       | ~29s      |
| python-tasks    | `cc9259f6` | background + `status`  | **3/3 (100%)**  | 0       | ~20s      |

**bash-operations**

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
```

**python-tasks** (submitted in the background; `status` polled about once a second)

```
$ harness run --agent agents/mini-swe-agent --benchmark python-tasks
Run ID: cc9259f6
Benchmark run submitted
Check progress: harness status --run_id cc9259f6

$ harness status --run_id cc9259f6        # polled repeatedly; first line + Progress of each, condensed
Run cc9259f6: running     Progress: 0/3
Run cc9259f6: running     Progress: 1/3
Run cc9259f6: running     Progress: 2/3
Run cc9259f6: completed   Progress: 3/3

$ harness results --run_id cc9259f6 --format table
TASK    STATUS  SCORE  DURATION  AGENT_EXIT  ERROR
py-001  passed  1.00   7.7s      Submitted
py-002  passed  1.00   6.5s      Submitted
py-003  passed  1.00   6.0s      Submitted

passed 3/3 (100.0%), errored 0, pending 0
```

**Checks after the runs:**
- `harness results --run_id <id>` returned valid JSON for both runs.
- `docker ps -a --filter label=agentic-harness` was empty, so no containers were left behind.
- The `py-002` trajectory confirms mini's commands ran in mini's `DockerEnvironment`, using `python:3.11-slim` with the workspace at `/workspace`. The agent finished in 4 model turns and wrote an iterative `fibonacci` in `solution.py`.

The full artifacts (prompts, trajectories, agent logs, workspaces) are in `runs/6a33a8d3/` and `runs/cc9259f6/`, which aren't committed (`runs/` is git-ignored).

## How it works

```
  harness run ──validate──► RunStore.create_run ──► spawn: python -m agentic_harness.executor <run_id>
                            (SQLite: run queued)              │
  harness status  ◄─ reads ─ RunStore ◄─ writes ─  execute_run: for each task, run_task
  harness results ◄─ reads ─┘                                 │
                                                              ▼
       benchmarks/<name>/harness.yaml                    agent config
                    │                                         │
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

For each task, the executor does the following:

1. Creates a fresh workspace.
2. Runs the **benchmark's setup** script.
3. Gives the **agent** the task prompt; the agent works in a container from the task's `docker_image`, with the workspace mounted.
4. Runs the **benchmark's grader** on the workspace.
5. Saves a `TaskResult` and removes the container.

One task's failure never stops the run, and a task that times out is still graded.

The code (`src/agentic_harness/`) is split into four abstractions that only meet through shared types in `models.py`:


| Abstraction   | Code          | Role                                                                                                                     |
| ------------- | ------------- | ------------------------------------------------------------------------------------------------------------------------ |
| **Benchmark** | `benchmarks/` | Lists tasks, sets up a workspace, grades it. One generic `ScriptBenchmark` is driven by each benchmark's `harness.yaml`. |
| **Agent**     | `agents/`     | `run(prompt, task, sandbox, …) -> AgentOutput`. Adapters: `MiniSweAgent` and `CommandAgent` (scripted, no LLM).          |
| **Sandbox**   | `sandbox.py`  | The per-task Docker container: mount, host user, cleanup label, image download                                           |
| **Run store** | `store.py`    | SQLite run and task state, plus the per-task artifact folders                                                            |


`executor.py` connects them, `report.py` computes the metrics and output formats, and `cli.py` is the `harness` command. The harness core never names a specific benchmark or agent.

**mini-swe-agent** runs as a subprocess on the host, so the API key stays on the host. It uses mini's built-in Docker environment, so every shell command it issues runs inside the task container.

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

- **Setup and grading run on the host,** against the mounted workspace. That's how the provided scripts were written, and `alpine` has no Python. The cost is that `prepare.py` installs packages into the harness venv.
- **The agent loop runs on the host; only its actions run in Docker.** This keeps API keys out of containers and works on minimal images. Future work: run the whole agent inside the container for stronger isolation of proprietary agents.
- **Tasks within a run execute one at a time.** Concurrency and queueing are Part 2.
- **No cost or step limits are imposed by the harness.** The only harness limit is the per-task timeout; mini-swe-agent keeps its own defaults.
- **The Docker image comes only from each task's dataset row,** because a benchmark's environment is part of its definition.



## Tests

```bash
make test                       # 76 tests, Docker required for most; LLM test skipped
HARNESS_RUN_LLM=1 make test     # also runs mini-swe-agent on Sonnet against bash-001 (costs a few cents)
```

Tests use a temporary `HARNESS_HOME`. Docker tests are skipped automatically if Docker isn't running.

## Project layout

```
benchmarks/<name>/harness.yaml      # benchmark adapters (bash-operations, python-tasks)
agents/mini-swe-agent/              # mini-swe-agent (git submodule)
src/agentic_harness/
  cli.py  executor.py  store.py  report.py  sandbox.py  models.py
  benchmarks/  agents/  agent_configs/
tests/                              # pytest suite + fixtures (toy benchmark, scripted agent)
```

