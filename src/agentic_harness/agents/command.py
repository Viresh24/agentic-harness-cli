"""CommandAgent: runs one fixed shell command in the sandbox. No LLM; used for tests and Docker smoke checks."""

import subprocess
from pathlib import Path
from typing import Any

from agentic_harness.agents.base import Agent, AgentConfigError
from agentic_harness.models import AgentOutput, Task
from agentic_harness.sandbox import DOCKER_RUN_FAILED, Sandbox


class CommandAgent(Agent):
    def __init__(self, agent_dir: Path, config: dict[str, Any]):
        super().__init__(agent_dir, config)
        if not isinstance(config.get("command"), str) or not config["command"]:
            raise AgentConfigError(f"{agent_dir}: command adapter needs a non-empty 'command' string")
        self.command = config["command"]

    def run(self, prompt: str, task: Task, sandbox: Sandbox, artifacts_dir: Path, timeout: float) -> AgentOutput:
        log = artifacts_dir / "agent.log"
        try:
            rc = sandbox.exec_once(self.command, timeout, log)
        except subprocess.TimeoutExpired:
            return AgentOutput("Timeout", log_path=log)
        if rc == DOCKER_RUN_FAILED:
            tail = "\n".join(log.read_text(errors="replace").strip().splitlines()[-20:])
            return AgentOutput("SandboxError", log_path=log, error=f"docker run failed (exit {rc}): {tail}")
        return AgentOutput("Submitted" if rc == 0 else "NonZeroExit", log_path=log)
