import json

from agentic_harness.models import ErrorPhase, RunRecord, RunStatus, RunSummary, TaskResult, TaskStatus
from agentic_harness.report import render_json, render_summary, render_table, summarize

RUN = RunRecord("abc12345", "/abs/agents/mini-swe-agent", "/abs/benchmarks/bash-operations", ["t1"], RunStatus.COMPLETED)


def _result(task_id: str, status: TaskStatus, **kw) -> TaskResult:
    passed = status == TaskStatus.PASSED
    return TaskResult(task_id, status, passed=passed, score=1.0 if passed else 0.0, **kw)


MIXED = [
    _result("t1", TaskStatus.PASSED, duration=2.0, agent_exit_status="Submitted"),
    _result("t2", TaskStatus.PASSED),
    _result("t3", TaskStatus.FAILED),
    _result("t4", TaskStatus.ERROR, error="docker pull failed:\nnot found", error_phase=ErrorPhase.SANDBOX),
    _result("t5", TaskStatus.PASSED),
]


def test_summarize_counts_and_accuracies():
    s = summarize(MIXED)
    assert isinstance(s, RunSummary)
    assert (s.total, s.passed, s.failed, s.errored, s.pending) == (5, 3, 1, 1, 0)
    assert (s.accuracy, s.accuracy_excluding_errors, s.mean_score) == (0.6, 0.75, 0.75)


def test_summarize_empty_all_error_and_pending():
    assert summarize([]).accuracy is None
    all_error = summarize([_result("t1", TaskStatus.ERROR)])
    assert (all_error.accuracy, all_error.accuracy_excluding_errors, all_error.mean_score) == (0.0, None, None)
    assert summarize([TaskResult("t1"), TaskResult("t2", TaskStatus.RUNNING)]).pending == 2


def test_render_json_is_parseable():
    data = json.loads(render_json(RUN, MIXED))
    assert data["run"]["run_id"] == "abc12345"
    assert (data["summary"]["passed"], data["summary"]["accuracy"]) == (3, 0.6)
    assert [t["task_id"] for t in data["tasks"]] == ["t1", "t2", "t3", "t4", "t5"]


def test_render_table_rows():
    lines = render_table(RUN, MIXED).splitlines()
    assert lines[0].split() == ["TASK", "STATUS", "SCORE", "DURATION", "AGENT_EXIT", "ERROR"]
    t4 = next(line for line in lines if line.startswith("t4"))
    assert "error" in t4 and "sandbox: docker pull failed: not found" in t4
    assert "2.0s" in next(line for line in lines if line.startswith("t1"))
    assert "3/5 (60.0%)" in lines[-1]


def test_render_summary_contains_percentages():
    text = render_summary(RUN, MIXED)
    assert "abc12345" in text and "completed" in text
    assert "3/5 (60.0%)" in text and "3/4 (75.0%)" in text
    assert "n/a" in render_summary(RUN, [])
