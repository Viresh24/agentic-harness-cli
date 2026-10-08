"""Agent loading: `--agent <dir>` -> Agent."""

from pathlib import Path

import yaml

from agentic_harness.agents.base import Agent, AgentConfigError, AgentNotFoundError
from agentic_harness.agents.command import CommandAgent

AGENT_CONFIG = "harness-agent.yaml"
BUILTIN_CONFIGS = Path(__file__).parent.parent / "agent_configs"

ADAPTERS: dict[str, type[Agent]] = {"command": CommandAgent}

__all__ = ["ADAPTERS", "Agent", "AgentConfigError", "AgentNotFoundError", "CommandAgent", "load_agent"]


def load_agent(path: str) -> Agent:
    agent_dir = Path(path).resolve()
    candidates = [agent_dir / AGENT_CONFIG, BUILTIN_CONFIGS / f"{agent_dir.name}.yaml"]
    config_path = next((c for c in candidates if c.is_file()), None)
    if config_path is None:
        raise AgentNotFoundError(f"No agent config for {path!r}: looked for {' and '.join(map(str, candidates))}")
    config = yaml.safe_load(config_path.read_text()) or {}
    adapter = config.get("adapter")
    if adapter not in ADAPTERS:
        raise AgentConfigError(f"{config_path}: unknown adapter {adapter!r}; known: {', '.join(ADAPTERS)}")
    return ADAPTERS[adapter](agent_dir, config)
