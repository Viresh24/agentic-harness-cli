import dataclasses
import json
from pathlib import Path

import pytest

from agentic_harness.models import (
    AgentOutput,
    ErrorPhase,
    EvalOutcome,
    RunRecord,
    RunStatus,
    RunSummary,
    Task,
    TaskResult,
    TaskStatus,
)


@pytest.mark.parametrize(("field",), [("id",), ("prompt",), ("docker_image",)])
def test_task_rejects_empty_required_fields(field):
    kwargs = {"id": "t1", "prompt": "do it", "docker_image": "alpine:latest", "raw": {}}
    with pytest.raises(ValueError, match=field):
        Task(**{**kwargs, field: ""})


def test_eval_outcome_invariants():
    with pytest.raises(ValueError):
        EvalOutcome(TaskStatus.PASSED, passed=False, score=1.0)
    with pytest.raises(ValueError):
        EvalOutcome(TaskStatus.RUNNING, passed=False, score=0.0)
    assert EvalOutcome(TaskStatus.FAILED, passed=False, score=0.0).details == {}


def test_task_result_from_outcome_copies_agent_exit_status():
    r = TaskResult.from_outcome(
        "t1",
        EvalOutcome(TaskStatus.FAILED, passed=False, score=0.0, details={"k": "v"}),
        AgentOutput("LimitsExceeded"),
        started_at=100.0,
        finished_at=112.5,
    )
    assert (r.status, r.passed, r.score, r.details) == (TaskStatus.FAILED, False, 0.0, {"k": "v"})
    assert r.agent_exit_status == "LimitsExceeded"
    assert r.duration == 12.5
    assert r.error_phase is None


def test_task_result_from_outcome_eval_error_sets_phase():
    r = TaskResult.from_outcome(
        "t1",
        EvalOutcome(TaskStatus.ERROR, passed=False, score=0.0, error="bad json"),
        AgentOutput("Submitted"),
        started_at=0.0,
        finished_at=1.0,
    )
    assert (r.status, r.error_phase, r.error) == (TaskStatus.ERROR, ErrorPhase.EVALUATE, "bad json")


def test_task_result_from_error():
    r = TaskResult.from_error("t", ErrorPhase.SETUP, "boom", 0, 1)
    assert (r.status, r.passed, r.error_phase, r.error, r.duration) == (TaskStatus.ERROR, False, "setup", "boom", 1)
    assert r.agent_exit_status is None
    with_agent = TaskResult.from_error("t", ErrorPhase.AGENT, "no key", 0, 2, agent=AgentOutput("NoTrajectory"))
    assert with_agent.agent_exit_status == "NoTrajectory"


def test_task_result_roundtrip_json():
    r = TaskResult(
        task_id="t1",
        status=TaskStatus.ERROR,
        passed=False,
        score=0.0,
        error="x",
        error_phase=ErrorPhase.SANDBOX,
        duration=3.0,
        agent_exit_status="Timeout",
        started_at=10.0,
        finished_at=13.0,
        details={"nested": {"a": [1, 2]}},
    )
    d = r.to_dict()
    assert (d["status"], d["error_phase"]) == ("error", "sandbox")
    assert TaskResult.from_dict(json.loads(json.dumps(d))) == r
    restored = TaskResult.from_dict(json.loads(json.dumps(d)))
    assert type(restored.status) is TaskStatus and type(restored.error_phase) is ErrorPhase


def test_task_result_from_dict_coerces_sqlite_bool():
    assert TaskResult.from_dict({"task_id": "t", "status": "passed", "passed": 1}).passed is True


def test_run_record_roundtrip_and_ignores_unknown_keys():
    rec = RunRecord(
        run_id="abc12345",
        agent="/abs/agent",
        benchmark="/abs/bench",
        task_ids=["a", "b"],
        status=RunStatus.RUNNING,
        config={"task_timeout": 900},
        pid=123,
    )
    d = json.loads(json.dumps(rec.to_dict()))
    assert d["status"] == "running"
    assert RunRecord.from_dict(d) == rec
    assert RunRecord.from_dict({**d, "future_field": 1}) == rec
    assert set(d) == {f.name for f in dataclasses.fields(RunRecord)}


def test_agent_output_paths_serialize():
    assert AgentOutput("Submitted", trajectory_path=Path("/x/t.json")).to_dict()["trajectory_path"] == "/x/t.json"


def test_run_summary_to_dict_keys():
    s = RunSummary(
        total=1, passed=1, failed=0, errored=0, pending=0, accuracy=1.0,
        accuracy_excluding_errors=1.0, mean_score=1.0,
    )
    assert set(s.to_dict()) == {
        "total", "passed", "failed", "errored", "pending", "accuracy",
        "accuracy_excluding_errors", "mean_score",
    }
