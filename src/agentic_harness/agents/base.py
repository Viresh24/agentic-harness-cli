"""Agent contract the executor depends on."""

from abc import ABC, abstractmethod
from pathlib import Path
from typing import Any

from agentic_harness.models import AgentOutput, Task
from agentic_harness.sandbox import Sandbox


class AgentNotFoundError(Exception):
    pass


class AgentConfigError(Exception):
    pass


class Agent(ABC):
    def __init__(self, agent_dir: Path, config: dict[str, Any]):
        self.agent_dir = agent_dir
        self.config = config
        self.name = config.get("name") or agent_dir.name

    @abstractmethod
    def run(self, prompt: str, task: Task, sandbox: Sandbox, artifacts_dir: Path, timeout: float) -> AgentOutput:
        """Solve `task` inside `sandbox`, writing logs to artifacts_dir.

        Handle your own timeout and return exit_status="Timeout". Set AgentOutput.error only for
        infrastructure failures; anything else still gets evaluated.
        """
