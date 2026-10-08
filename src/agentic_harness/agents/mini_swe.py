"""mini-swe-agent adapter: the agent loop runs on the host, every shell action runs in the task's container."""

import json
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any

from agentic_harness.agents.base import Agent, AgentConfigError
from agentic_harness.models import AgentOutput, Task
from agentic_harness.sandbox import Sandbox

LOG_TAIL_LINES = 20


class MiniSweAgent(Agent):
    """Runs the `mini` CLI as a subprocess, pointed at the task's Docker sandbox."""

    def __init__(self, agent_dir: Path, config: dict[str, Any]):
        """Load the model override and locate the `mini` executable."""
        super().__init__(agent_dir, config)
        self.model: str | None = config.get("model")
        self.executable = _resolve_executable(config.get("executable", "mini"))

    def build_command(self, prompt: str, sandbox: Sandbox, traj_path: Path) -> list[str]:
        """Build the `mini` command that solves one task inside the sandbox's container."""
        specs = {
            "environment.environment_class": "docker",
            "environment.image": sandbox.image,
            "environment.cwd": sandbox.mount_point,
            "environment.interpreter": json.dumps(["sh", "-c"]),  # alpine has no bash
            "environment.run_args": json.dumps(sandbox.run_args()),
        }
        cmd = [
            self.executable,
            "--exit-immediately",
            "-y",
            "-o", str(traj_path),
            "-t", prompt,
            # Passing any -c drops mini's default config, so name it first.
            "-c", "mini.yaml",
        ]
        for key, value in specs.items():
            cmd += ["-c", f"{key}={value}"]
        if self.model:
            cmd += ["-m", self.model]
        return cmd

    def parse_trajectory(self, path: Path, log_path: Path) -> AgentOutput:
        """Read mini's exit status from its trajectory file."""
        info = json.loads(path.read_text()).get("info", {})
        return AgentOutput(exit_status=info.get("exit_status") or "Unknown", trajectory_path=path, log_path=log_path)

    def run(self, prompt: str, task: Task, sandbox: Sandbox, artifacts_dir: Path, timeout: float) -> AgentOutput:
        """Run mini on one task and report how it ended; error is set only if mini couldn't run."""
        artifacts_dir.mkdir(parents=True, exist_ok=True)
        log, traj = artifacts_dir / "agent.log", artifacts_dir / "trajectory.json"
        try:
            with log.open("w") as f:
                proc = subprocess.run(
                    self.build_command(prompt, sandbox, traj),
                    stdin=subprocess.DEVNULL,  # never block on a prompt
                    stdout=f,
                    stderr=subprocess.STDOUT,
                    timeout=timeout,
                )
        except subprocess.TimeoutExpired:
            return AgentOutput("Timeout", trajectory_path=traj if traj.is_file() else None, log_path=log)
        if traj.is_file():
            return self.parse_trajectory(traj, log)
        tail = "\n".join(log.read_text(errors="replace").strip().splitlines()[-LOG_TAIL_LINES:])
        error = (
            f"mini exited {proc.returncode} without a trajectory "
            f"(if mini isn't set up, run: mini-extra config setup):\n{tail}"
        )
        return AgentOutput("NoTrajectory", log_path=log, error=error)


def _resolve_executable(name: str) -> str:
    """Find the `mini` executable, preferring the harness venv's copy."""
    venv_bin = Path(sys.executable).parent / name
    if venv_bin.is_file():
        return str(venv_bin)
    if found := shutil.which(name):
        return found
    raise AgentConfigError(f"mini-swe-agent executable {name!r} not found next to {sys.executable} or on PATH")
