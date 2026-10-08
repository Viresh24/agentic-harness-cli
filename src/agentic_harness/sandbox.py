"""Docker sandbox for one task: the container settings every agent must use, plus label-based cleanup."""

import os
import subprocess
from dataclasses import dataclass
from pathlib import Path

LABEL_KEY = "agentic-harness"
DOCKER_RUN_FAILED = 125  # `docker run` exit code when the container itself could not start


class SandboxError(Exception):
    pass


def ensure_docker() -> None:
    try:
        proc = subprocess.run(["docker", "info"], capture_output=True, text=True, timeout=30)
    except (OSError, subprocess.TimeoutExpired) as e:
        raise SandboxError(f"Docker daemon not reachable: {e}") from e
    if proc.returncode != 0:
        raise SandboxError(f"Docker daemon not reachable: {proc.stderr.strip()}")


@dataclass
class Sandbox:
    image: str
    workspace: Path
    label: str  # "<run_id>-<task_id>"; every container for this task carries it
    mount_point: str = "/workspace"

    def run_args(self) -> list[str]:
        return [
            "--rm",
            "-v",
            f"{self.workspace.resolve()}:{self.mount_point}",
            # Files the agent creates stay owned by the host user, so grading and cleanup can touch them.
            "--user",
            f"{os.getuid()}:{os.getgid()}",
            "-e",
            "HOME=/tmp",
            "--label",
            f"{LABEL_KEY}={self.label}",
        ]

    def prepare(self, pull_timeout: float = 600) -> None:
        """Make sure the image is local, so pull time and output never count against the agent."""
        if subprocess.run(["docker", "image", "inspect", self.image], capture_output=True).returncode == 0:
            return
        try:
            proc = subprocess.run(["docker", "pull", self.image], capture_output=True, text=True, timeout=pull_timeout)
        except subprocess.TimeoutExpired as e:
            raise SandboxError(f"docker pull {self.image} timed out after {pull_timeout}s") from e
        if proc.returncode != 0:
            raise SandboxError(f"docker pull {self.image} failed: {proc.stderr.strip()}")

    def exec_once(self, command: str, timeout: float, log_path: Path) -> int:
        """Run `command` with `sh -c` in a fresh container; stdout+stderr go to log_path.

        Raises subprocess.TimeoutExpired on timeout; the container may still be running, so call cleanup().
        """
        argv = ["docker", "run", *self.run_args(), "-w", self.mount_point, self.image, "sh", "-c", command]
        log_path.parent.mkdir(parents=True, exist_ok=True)
        with log_path.open("w") as log:
            return subprocess.run(
                argv, stdout=log, stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL, timeout=timeout
            ).returncode

    def cleanup(self) -> None:
        """Force-remove every container carrying this task's label. Never raises."""
        try:
            ids = subprocess.run(
                ["docker", "ps", "-aq", "--filter", f"label={LABEL_KEY}={self.label}"],
                capture_output=True,
                text=True,
                timeout=30,
            ).stdout.split()
            if ids:
                subprocess.run(["docker", "rm", "-f", *ids], capture_output=True, timeout=60)
        except Exception:
            pass
