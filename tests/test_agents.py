import os
import subprocess
import uuid
from pathlib import Path

import pytest

from agentic_harness.agents import AgentConfigError, AgentNotFoundError, CommandAgent, load_agent
from agentic_harness.models import Task
from agentic_harness.sandbox import Sandbox

SCRIPTED = Path(__file__).parent / "fixtures" / "agents" / "scripted"
TASK = Task("t1", "unused", "alpine:latest", {})


def _agent_dir(tmp_path: Path, yaml_text: str) -> Path:
    d = tmp_path / "agent"
    d.mkdir()
    (d / "harness-agent.yaml").write_text(yaml_text)
    return d


def _run(agent, tmp_path, image="alpine:latest", timeout=120):
    ws = tmp_path / "ws"
    ws.mkdir(exist_ok=True)
    sandbox = Sandbox(image, ws, f"t-{uuid.uuid4().hex[:8]}")
    try:
        return agent.run("unused", TASK, sandbox, tmp_path / "artifacts", timeout), ws, sandbox
    finally:
        sandbox.cleanup()


def test_load_agent_resolves_dir_config():
    agent = load_agent(str(SCRIPTED))
    assert isinstance(agent, CommandAgent)
    assert agent.name == "scripted"


def test_load_agent_unknown():
    with pytest.raises(AgentNotFoundError, match="harness-agent.yaml"):
        load_agent("/nope")


def test_load_agent_unknown_adapter(tmp_path):
    with pytest.raises(AgentConfigError, match="command"):
        load_agent(str(_agent_dir(tmp_path, "adapter: telepathy\n")))


def test_command_agent_requires_command(tmp_path):
    with pytest.raises(AgentConfigError, match="command"):
        load_agent(str(_agent_dir(tmp_path, "adapter: command\n")))


@pytest.mark.docker
def test_command_agent_writes_into_workspace_on_alpine(tmp_path):
    out, ws, _ = _run(load_agent(str(SCRIPTED)), tmp_path)
    assert (out.exit_status, out.error) == ("Submitted", None)
    assert (ws / "hello.txt").read_text().strip() == "Hello World"
    assert (ws / "hello.txt").stat().st_uid == os.getuid()
    assert out.log_path == tmp_path / "artifacts" / "agent.log"


@pytest.mark.docker
def test_command_agent_nonzero_exit_is_not_infra_error(tmp_path):
    out, _, _ = _run(load_agent(str(_agent_dir(tmp_path, "adapter: command\ncommand: 'exit 4'\n"))), tmp_path)
    assert (out.exit_status, out.error) == ("NonZeroExit", None)


@pytest.mark.docker
def test_command_agent_timeout_then_cleanup_leaves_no_container(tmp_path):
    agent = load_agent(str(_agent_dir(tmp_path, "adapter: command\ncommand: 'echo partial > p.txt; sleep 60'\n")))
    out, ws, sandbox = _run(agent, tmp_path, timeout=5)
    assert (out.exit_status, out.error) == ("Timeout", None)
    assert (ws / "p.txt").read_text().strip() == "partial"
    leftover = subprocess.run(
        ["docker", "ps", "-aq", "--filter", f"label=agentic-harness={sandbox.label}"], capture_output=True, text=True
    )
    assert leftover.stdout.split() == []


@pytest.mark.docker
def test_command_agent_missing_image_is_infra_error(tmp_path):
    out, _, _ = _run(load_agent(str(SCRIPTED)), tmp_path, image="agentic-harness-does-not-exist:nope")
    assert out.exit_status == "SandboxError"
    assert out.error and "docker" in out.error.lower()
