"""Shared data models. Every type crossing a module boundary lives here."""

import dataclasses
import time
from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path
from typing import Any, Self


class TaskStatus(StrEnum):
    PENDING = "pending"
    RUNNING = "running"
    PASSED = "passed"
    FAILED = "failed"
    ERROR = "error"


class RunStatus(StrEnum):
    QUEUED = "queued"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"


class ErrorPhase(StrEnum):
    SETUP = "setup"
    AGENT = "agent"
    EVALUATE = "evaluate"
    SANDBOX = "sandbox"
    INTERNAL = "internal"


TERMINAL_TASK_STATUSES = frozenset({TaskStatus.PASSED, TaskStatus.FAILED, TaskStatus.ERROR})
TERMINAL_RUN_STATUSES = frozenset({RunStatus.COMPLETED, RunStatus.FAILED})


def _to_jsonable(obj: Any) -> Any:
    if isinstance(obj, StrEnum):
        return obj.value
    if isinstance(obj, Path):
        return str(obj)
    if isinstance(obj, dict):
        return {k: _to_jsonable(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_to_jsonable(v) for v in obj]
    return obj


class _Serializable:
    """to_dict/from_dict for dataclasses; from_dict ignores unknown keys so old rows load in new code."""

    _enum_fields: dict[str, type[StrEnum]] = {}

    def to_dict(self) -> dict[str, Any]:
        return {f.name: _to_jsonable(getattr(self, f.name)) for f in dataclasses.fields(self)}

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> Self:
        names = {f.name for f in dataclasses.fields(cls)}
        kwargs = {k: v for k, v in d.items() if k in names}
        for name, enum_cls in cls._enum_fields.items():
            if kwargs.get(name) is not None:
                kwargs[name] = enum_cls(kwargs[name])
        return cls(**kwargs)


@dataclass(frozen=True)
class Task:
    id: str
    prompt: str  # dataset text, not the rendered agent prompt
    docker_image: str
    raw: dict[str, Any]

    def __post_init__(self):
        for name in ("id", "prompt", "docker_image"):
            if not getattr(self, name):
                raise ValueError(f"Task field {name!r} is empty (raw row: {self.raw!r:.200})")


@dataclass
class EvalOutcome:
    status: TaskStatus
    passed: bool
    score: float
    details: dict[str, Any] = field(default_factory=dict)
    error: str | None = None

    def __post_init__(self):
        if self.status not in TERMINAL_TASK_STATUSES:
            raise ValueError(f"EvalOutcome status must be terminal, got {self.status!r}")
        if self.passed != (self.status == TaskStatus.PASSED):
            raise ValueError(f"EvalOutcome passed={self.passed} contradicts status={self.status!r}")


@dataclass
class AgentOutput(_Serializable):
    exit_status: str
    trajectory_path: Path | None = None
    log_path: Path | None = None
    error: str | None = None  # infra failure only: task becomes ERROR and evaluation is skipped


@dataclass
class TaskResult(_Serializable):
    task_id: str
    status: TaskStatus = TaskStatus.PENDING
    passed: bool = False
    score: float = 0.0
    error: str | None = None
    error_phase: ErrorPhase | None = None
    duration: float = 0.0
    agent_exit_status: str | None = None
    started_at: float | None = None
    finished_at: float | None = None
    details: dict[str, Any] = field(default_factory=dict)

    _enum_fields = {"status": TaskStatus, "error_phase": ErrorPhase}

    def __post_init__(self):
        self.passed = bool(self.passed)  # SQLite stores 0/1

    @classmethod
    def from_outcome(
        cls, task_id: str, outcome: EvalOutcome, agent: AgentOutput, started_at: float, finished_at: float
    ) -> Self:
        return cls(
            task_id=task_id,
            status=outcome.status,
            passed=outcome.passed,
            score=outcome.score,
            error=outcome.error,
            error_phase=ErrorPhase.EVALUATE if outcome.status == TaskStatus.ERROR else None,
            duration=finished_at - started_at,
            agent_exit_status=agent.exit_status,
            started_at=started_at,
            finished_at=finished_at,
            details=outcome.details,
        )

    @classmethod
    def from_error(
        cls,
        task_id: str,
        phase: ErrorPhase,
        error: str,
        started_at: float,
        finished_at: float,
        agent: AgentOutput | None = None,
    ) -> Self:
        return cls(
            task_id=task_id,
            status=TaskStatus.ERROR,
            error=error,
            error_phase=phase,
            duration=finished_at - started_at,
            agent_exit_status=agent.exit_status if agent else None,
            started_at=started_at,
            finished_at=finished_at,
        )


@dataclass
class RunRecord(_Serializable):
    run_id: str
    agent: str  # absolute agent dir
    benchmark: str  # absolute benchmark manifest dir
    task_ids: list[str]  # resolved at submit time, never "all"
    status: RunStatus = RunStatus.QUEUED
    config: dict[str, Any] = field(default_factory=dict)
    created_at: float = field(default_factory=time.time)
    started_at: float | None = None
    finished_at: float | None = None
    pid: int | None = None  # executor pid, used only for stale detection
    error: str | None = None

    _enum_fields = {"status": RunStatus}


@dataclass
class RunSummary(_Serializable):
    total: int
    passed: int
    failed: int
    errored: int
    pending: int
    accuracy: float | None
    accuracy_excluding_errors: float | None
    mean_score: float | None
    total_duration: float
