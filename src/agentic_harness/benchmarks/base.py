"""Benchmark contract the executor depends on."""

from abc import ABC, abstractmethod
from pathlib import Path
from typing import Self

from agentic_harness.models import EvalOutcome, Task


class BenchmarkError(Exception):
    """Setup failed, or the benchmark is misconfigured."""


class BenchmarkNotFoundError(BenchmarkError):
    pass


class UnknownTaskError(BenchmarkError):
    def __init__(self, missing: list[str], valid: list[str]):
        self.missing, self.valid = missing, valid
        super().__init__(f"Unknown task id(s): {', '.join(missing)}. Valid ids: {', '.join(valid)}")


class Benchmark(ABC):
    name: str

    @classmethod
    @abstractmethod
    def from_manifest(cls, path: Path) -> Self: ...

    @abstractmethod
    def list_tasks(self) -> list[Task]: ...

    @abstractmethod
    def setup(self, task: Task, workspace: Path, log_dir: Path) -> None:
        """Prepare the workspace. Raises BenchmarkError on failure."""

    @abstractmethod
    def evaluate(self, task: Task, workspace: Path, log_dir: Path) -> EvalOutcome: ...

    def render_prompt(self, task: Task) -> str:
        return task.prompt

    def get_tasks(self, ids: list[str] | None) -> list[Task]:
        tasks = self.list_tasks()
        if ids is None:
            return tasks
        by_id = {t.id: t for t in tasks}
        if missing := [i for i in ids if i not in by_id]:
            raise UnknownTaskError(missing, list(by_id))
        return [by_id[i] for i in ids]
