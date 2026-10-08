"""ScriptBenchmark: a benchmark made of a dataset file plus setup/evaluate scripts, described by harness.yaml."""

import json
import os
import subprocess
import sys
import time
from pathlib import Path
from typing import Any, Self

import yaml

from agentic_harness.benchmarks.base import Benchmark, BenchmarkError
from agentic_harness.models import EvalOutcome, Task, TaskStatus

PASS_FROM = ("exit_code", "json.passed")


class ScriptBenchmark(Benchmark):
    def __init__(self, manifest_dir: Path, manifest: dict[str, Any]):
        self.dir = manifest_dir.resolve()
        self.manifest = manifest
        self.name = manifest.get("name") or self.dir.name
        for key in ("dataset", "fields", "setup", "evaluate"):
            if key not in manifest:
                raise BenchmarkError(f"{self.dir / 'harness.yaml'}: missing required key {key!r}")
        self.pass_from = manifest.get("pass_from", "exit_code")
        if self.pass_from not in PASS_FROM:
            raise BenchmarkError(f"{self.dir / 'harness.yaml'}: pass_from must be one of {PASS_FROM}")
        self.timeout = manifest.get("timeout", 120)
        self.prompt_template = manifest.get("prompt_template", "{prompt}")

    @classmethod
    def from_manifest(cls, path: Path) -> Self:
        return cls(path.parent, yaml.safe_load(path.read_text()))

    def list_tasks(self) -> list[Task]:
        fields = self.manifest["fields"]
        rows = json.loads((self.dir / self.manifest["dataset"]).read_text())
        return [
            Task(
                id=str(row.get(fields["id"], "")),
                prompt=row.get(fields["prompt"], ""),
                docker_image=row.get(fields["docker_image"], ""),
                raw=row,
            )
            for row in rows
        ]

    def render_prompt(self, task: Task) -> str:
        try:
            return self.prompt_template.format_map({**task.raw, "prompt": task.prompt})
        except KeyError as e:
            raise BenchmarkError(f"prompt_template references unknown task field {e}") from e

    def setup(self, task: Task, workspace: Path, log_dir: Path) -> None:
        try:
            proc = self._run("setup", task, workspace, log_dir)
        except subprocess.TimeoutExpired as e:
            raise BenchmarkError(f"setup timed out after {self.timeout}s") from e
        if proc.returncode != 0:
            tail = "\n".join(proc.stderr.strip().splitlines()[-20:])
            raise BenchmarkError(f"setup exited {proc.returncode}: {tail}")

    def evaluate(self, task: Task, workspace: Path, log_dir: Path) -> EvalOutcome:
        try:
            proc = self._run("evaluate", task, workspace, log_dir)
        except subprocess.TimeoutExpired:
            return _error(f"evaluate timed out after {self.timeout}s", {})
        result = _parse_json(proc.stdout)
        details = result if result is not None else {"raw_stdout": proc.stdout, "raw_stderr": proc.stderr}

        if self.pass_from == "exit_code":
            if proc.returncode not in (0, 1):
                return _error(f"evaluate exited {proc.returncode}", details)
            passed = proc.returncode == 0
        else:
            if proc.returncode != 0:
                return _error(f"evaluate exited {proc.returncode}", details)
            if result is None:
                return _error("evaluate printed no JSON object", details)
            if not isinstance(result.get("passed"), bool):
                return _error("evaluate JSON has no boolean 'passed'", details)
            passed = result["passed"]

        score = result.get("score") if result else None
        return EvalOutcome(
            status=TaskStatus.PASSED if passed else TaskStatus.FAILED,
            passed=passed,
            score=float(score) if isinstance(score, (int, float)) else float(passed),
            details=details,
        )

    def _run(self, phase: str, task: Task, workspace: Path, log_dir: Path) -> subprocess.CompletedProcess:
        values = {
            "python": sys.executable,
            "workspace": str(workspace.resolve()),
            "task_id": task.id,
            "benchmark_dir": str(self.dir),
        }
        argv = [part.format(**values) for part in self.manifest[phase]]
        # Scripts may call a bare `python`/`pip`; make those resolve to the harness venv.
        env = {**os.environ, "PATH": f"{Path(sys.executable).parent}{os.pathsep}{os.environ.get('PATH', '')}"}
        log_dir.mkdir(parents=True, exist_ok=True)
        start = time.monotonic()
        try:
            proc = subprocess.run(
                argv, cwd=self.dir, env=env, capture_output=True, text=True, timeout=self.timeout, stdin=subprocess.DEVNULL
            )
        except subprocess.TimeoutExpired as e:
            _write_logs(log_dir, phase, argv, None, _text(e.stdout), _text(e.stderr), time.monotonic() - start)
            raise
        _write_logs(log_dir, phase, argv, proc.returncode, proc.stdout, proc.stderr, time.monotonic() - start)
        return proc


def _error(message: str, details: dict) -> EvalOutcome:
    return EvalOutcome(TaskStatus.ERROR, passed=False, score=0.0, details=details, error=message)


def _parse_json(stdout: str) -> dict | None:
    candidates = [stdout]
    if (start := stdout.find("{")) != -1 and (end := stdout.rfind("}")) > start:
        candidates.append(stdout[start : end + 1])
    for text in candidates:
        try:
            parsed = json.loads(text)
        except json.JSONDecodeError:
            continue
        if isinstance(parsed, dict):
            return parsed
    return None


def _text(data: str | bytes | None) -> str:
    return data.decode(errors="replace") if isinstance(data, bytes) else (data or "")


def _write_logs(log_dir: Path, phase: str, argv: list[str], returncode: int | None, stdout: str, stderr: str, duration: float):
    (log_dir / f"{phase}.stdout").write_text(stdout)
    (log_dir / f"{phase}.stderr").write_text(stderr)
    meta = {"argv": argv, "returncode": returncode, "duration": duration, "timed_out": returncode is None}
    (log_dir / f"{phase}.json").write_text(json.dumps(meta, indent=2))
