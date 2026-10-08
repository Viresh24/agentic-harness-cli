"""Aggregate a run's task results into metrics and render them as json, table, or summary text."""

import json

from agentic_harness.models import RunRecord, RunSummary, TaskResult, TaskStatus

ERROR_WIDTH = 60


def summarize(results: list[TaskResult]) -> RunSummary:
    """Count outcomes and compute accuracy over a run's task results."""
    count = {status: sum(r.status == status for r in results) for status in TaskStatus}
    passed, failed = count[TaskStatus.PASSED], count[TaskStatus.FAILED]
    graded = [r.score for r in results if r.status in (TaskStatus.PASSED, TaskStatus.FAILED)]
    return RunSummary(
        total=len(results),
        passed=passed,
        failed=failed,
        errored=count[TaskStatus.ERROR],
        pending=count[TaskStatus.PENDING] + count[TaskStatus.RUNNING],
        accuracy=_ratio(passed, len(results)),
        accuracy_excluding_errors=_ratio(passed, passed + failed),
        mean_score=sum(graded) / len(graded) if graded else None,
    )


def render_json(run: RunRecord, results: list[TaskResult]) -> str:
    """Full run, summary, and per-task results as JSON."""
    data = {"run": run.to_dict(), "summary": summarize(results).to_dict(), "tasks": [r.to_dict() for r in results]}
    return json.dumps(data, indent=2)


def render_table(run: RunRecord, results: list[TaskResult]) -> str:
    """One row per task, followed by a one-line summary."""
    header = ["TASK", "STATUS", "SCORE", "DURATION", "AGENT_EXIT", "ERROR"]
    rows = [header] + [
        [
            r.task_id,
            r.status.value,
            f"{r.score:.2f}",
            f"{r.duration:.1f}s",
            r.agent_exit_status or "-",
            _error_cell(r),
        ]
        for r in results
    ]
    widths = [max(len(row[i]) for row in rows) for i in range(len(header) - 1)]
    lines = ["  ".join([*(cell.ljust(w) for cell, w in zip(row, widths)), row[-1]]).rstrip() for row in rows]
    s = summarize(results)
    lines.append(f"\npassed {_fraction(s.passed, s.total, s.accuracy)}, errored {s.errored}, pending {s.pending}")
    return "\n".join(lines)


def render_summary(run: RunRecord, results: list[TaskResult]) -> str:
    """Short human-readable report of a run's metrics."""
    s = summarize(results)
    mean = f"{s.mean_score:.2f}" if s.mean_score is not None else "n/a"
    return "\n".join(
        [
            f"Run {run.run_id}  {run.status.value}",
            f"Agent:      {run.agent}",
            f"Benchmark:  {run.benchmark}",
            f"Accuracy:              {_fraction(s.passed, s.total, s.accuracy)}",
            f"Accuracy excl. errors: {_fraction(s.passed, s.passed + s.failed, s.accuracy_excluding_errors)}",
            f"Mean score:            {mean}",
            f"Errored: {s.errored}   Pending: {s.pending}",
        ]
    )


def _ratio(numerator: int, denominator: int) -> float | None:
    return numerator / denominator if denominator else None


def _fraction(numerator: int, denominator: int, value: float | None) -> str:
    return f"{numerator}/{denominator} ({value:.1%})" if value is not None else "n/a"


def _error_cell(r: TaskResult) -> str:
    if not r.error:
        return ""
    text = " ".join(f"{r.error_phase.value}: {r.error}".split()) if r.error_phase else " ".join(r.error.split())
    return text if len(text) <= ERROR_WIDTH else text[: ERROR_WIDTH - 1] + "…"
