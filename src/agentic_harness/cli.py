"""CLI for the agentic harness system."""

import os
from datetime import datetime

import click

from agentic_harness.agents import AgentConfigError, AgentNotFoundError, load_agent
from agentic_harness.benchmarks import BenchmarkError, load_benchmark, resolve_benchmark_dir
from agentic_harness.executor import DEFAULT_TASK_TIMEOUT, execute_run
from agentic_harness.models import TERMINAL_TASK_STATUSES, RunRecord, RunStatus, TaskResult
from agentic_harness.report import render_json, render_summary, render_table
from agentic_harness.store import RunStore
from agentic_harness.worker import pid_alive, run_worker

RENDERERS = {"json": render_json, "table": render_table, "summary": render_summary}


@click.group(
    epilog="""\b
Examples:
  harness run --agent agents/mini-swe-agent --benchmark bash-operations --task_ids bash-001
  harness worker --concurrency 2
  harness list
  harness status --run_id abc123
  harness results --run_id abc123"""
)
def cli():
    """Agentic Harness: run any agent against any benchmark."""


@cli.command()
@click.option("--agent", required=True, help="Path to the agent directory or configuration file")
@click.option("--benchmark", required=True, help="Name of the benchmark to run (e.g., bash-operations), or its path")
@click.option(
    "--task_ids",
    default=None,
    help="Comma-separated list of task IDs to run (runs all tasks if not provided)",
)
@click.option("--wait", is_flag=True, help="Run now in the foreground instead of queueing for a worker")
@click.option("--task-timeout", default=DEFAULT_TASK_TIMEOUT, show_default=True, help="Seconds allowed per task")
def run(agent: str, benchmark: str, task_ids: str | None, wait: bool, task_timeout: int):
    """Run an agent against a benchmark."""
    ids = [t.strip() for t in task_ids.split(",") if t.strip()] if task_ids else None
    try:
        tasks = load_benchmark(benchmark).get_tasks(ids)
        load_agent(agent)
    except (BenchmarkError, AgentNotFoundError, AgentConfigError) as e:
        raise click.ClickException(str(e)) from e

    store = RunStore()
    record = store.create_run(
        agent=str(os.path.abspath(agent)),
        benchmark=str(resolve_benchmark_dir(benchmark)),
        task_ids=[t.id for t in tasks],
        config={"task_timeout": task_timeout},
        status=RunStatus.RUNNING if wait else RunStatus.QUEUED,  # --wait runs never enter the queue
    )
    click.echo(f"Run ID: {record.run_id}")

    if wait:
        width = max(len(t.id) for t in tasks)
        execute_run(record.run_id, store, on_task_done=lambda r: click.echo(_task_line(r, width)))
        click.echo()
        click.echo(render_summary(store.get_run(record.run_id), store.get_task_results(record.run_id)))
        return

    click.secho("Benchmark run queued", fg="green")
    click.echo("A worker executes queued runs; start one with: harness worker")
    click.echo(f"Check progress: harness status --run_id {record.run_id}")


@cli.command()
@click.option("--concurrency", default=2, show_default=True, help="Maximum number of runs executing at once")
def worker(concurrency: int):
    """Execute queued runs until stopped (Ctrl-C waits for running runs; press again to abort them)."""
    run_worker(concurrency, log=click.echo)


@cli.command(name="list")
@click.option("--all", "show_all", is_flag=True, help="Include finished runs")
def list_runs(show_all: bool):
    """List active runs (queued or running)."""
    store = RunStore()
    runs = store.list_runs(None if show_all else [RunStatus.QUEUED, RunStatus.RUNNING])
    if not runs:
        click.echo("No runs" if show_all else "No active runs")
        return
    rows = [["RUN_ID", "STATUS", "PROGRESS", "BENCHMARK", "AGENT", "CREATED"]]
    for r in runs:
        results = store.get_task_results(r.run_id)
        done = sum(t.status in TERMINAL_TASK_STATUSES for t in results)
        rows.append([
            r.run_id,
            _run_state(r),
            f"{done}/{len(results)}",
            os.path.basename(r.benchmark),
            os.path.basename(r.agent),
            datetime.fromtimestamp(r.created_at).strftime("%Y-%m-%d %H:%M:%S"),
        ])
    widths = [max(len(row[i]) for row in rows) for i in range(len(rows[0]))]
    for row in rows:
        click.echo("  ".join(cell.ljust(w) for cell, w in zip(row, widths)).rstrip())


@cli.command()
@click.option("--run_id", required=True, help="The unique identifier for the benchmark run")
def status(run_id: str):
    """Check the status of a benchmark run."""
    store = RunStore()
    record = _get_run(store, run_id)
    results = store.get_task_results(run_id)
    done = sum(r.status in TERMINAL_TASK_STATUSES for r in results)

    click.echo(f"Run {run_id}: {_run_state(record)}")
    click.echo(f"Agent:     {record.agent}")
    click.echo(f"Benchmark: {record.benchmark}")
    click.echo(f"Progress:  {done}/{len(results)}")
    if record.error:
        click.echo(f"Error:     {record.error}")
    width = max((len(r.task_id) for r in results), default=0)
    for r in results:
        click.echo(_task_line(r, width))


@cli.command()
@click.option("--run_id", required=True, help="The unique identifier for the benchmark run")
@click.option(
    "--format",
    type=click.Choice(["json", "table", "summary"], case_sensitive=False),
    default="json",
    help="Output format for results (default: json)",
)
def results(run_id: str, format: str):
    """Get results from a completed run."""
    store = RunStore()
    record = _get_run(store, run_id)
    if record.status != RunStatus.COMPLETED:
        click.echo(f"Run {run_id} is {_run_state(record)}; results are partial", err=True)
    click.echo(RENDERERS[format.lower()](record, store.get_task_results(run_id)))


def _task_line(result: TaskResult, width: int) -> str:
    """One indented `<task_id>  <status>` line, with task IDs padded to `width`."""
    return f"  {result.task_id.ljust(width)}  {result.status.value}"


def _get_run(store: RunStore, run_id: str) -> RunRecord:
    record = store.get_run(run_id)
    if record is None:
        raise click.ClickException(f"Run {run_id} not found")
    return record


def _run_state(record: RunRecord) -> str:
    """The run's status, or 'stale' if it claims to be running but its executor process is gone."""
    active = record.status in (RunStatus.QUEUED, RunStatus.RUNNING)
    if active and record.pid and not pid_alive(record.pid):
        return f"stale (executor process {record.pid} not running)"
    return record.status.value


def main():
    """Main entry point for the CLI."""
    cli()


if __name__ == "__main__":
    main()
