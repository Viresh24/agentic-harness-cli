import json
import uuid
from pathlib import Path

import pytest

from agentic_harness.agents import load_agent
from agentic_harness.agents.mini_swe import MiniSweAgent
from agentic_harness.benchmarks import load_benchmark
from agentic_harness.models import TaskStatus
from agentic_harness.sandbox import Sandbox

REPO = Path(__file__).parent.parent
MINI_DIR = str(REPO / "agents" / "mini-swe-agent")


def _value(cmd: list[str], key: str) -> str:
    """Value of the `-c key=value` spec for `key`."""
    specs = [cmd[i + 1] for i, part in enumerate(cmd) if part == "-c"]
    return next(s.split("=", 1)[1] for s in specs if s.startswith(f"{key}="))


def test_load_agent_resolves_builtin_config():
    agent = load_agent(MINI_DIR)
    assert isinstance(agent, MiniSweAgent)
    assert agent.name == "mini-swe-agent"
    assert Path(agent.executable).name == "mini"


def test_build_command_targets_docker_sandbox(tmp_path):
    agent = load_agent(MINI_DIR)
    sandbox = Sandbox("alpine:latest", tmp_path / "ws", "run1-bash-001")
    cmd = agent.build_command("Create hello.txt", sandbox, tmp_path / "trajectory.json")
    assert cmd[0] == agent.executable
    assert {"--exit-immediately", "-y"} <= set(cmd)
    assert cmd[cmd.index("-t") + 1] == "Create hello.txt"
    assert cmd[cmd.index("-o") + 1] == str(tmp_path / "trajectory.json")
    first_config = cmd[cmd.index("-c") + 1]
    assert first_config == "mini.yaml"
    assert _value(cmd, "environment.environment_class") == "docker"
    assert _value(cmd, "environment.image") == "alpine:latest"
    assert _value(cmd, "environment.cwd") == "/workspace"
    assert json.loads(_value(cmd, "environment.interpreter")) == ["sh", "-c"]
    assert json.loads(_value(cmd, "environment.run_args")) == sandbox.run_args()
    # No harness-imposed limits: mini keeps its own defaults.
    assert "-l" not in cmd
    assert not any(s.startswith(("agent.step_limit=", "environment.timeout=")) for s in cmd)
    assert "-m" not in cmd  # model: null -> mini's configured default


def test_build_command_model_override(tmp_path):
    agent = MiniSweAgent(Path(MINI_DIR), {"adapter": "mini-swe-agent", "model": "anthropic/claude-haiku-5-5"})
    cmd = agent.build_command("p", Sandbox("alpine:latest", tmp_path, "l"), tmp_path / "t.json")
    assert cmd[cmd.index("-m") + 1] == "anthropic/claude-haiku-5-5"


def test_parse_trajectory(tmp_path):
    traj = tmp_path / "trajectory.json"
    traj.write_text(json.dumps({"info": {"exit_status": "Submitted", "model_stats": {"instance_cost": 0.02, "api_calls": 3}}}))
    out = load_agent(MINI_DIR).parse_trajectory(traj, tmp_path / "agent.log")
    assert (out.exit_status, out.error) == ("Submitted", None)
    assert out.trajectory_path == traj


def test_unconfigured_mini_is_error_with_setup_hint(tmp_path, monkeypatch):
    for var in ("MSWEA_CONFIGURED", "MSWEA_MODEL_NAME", "ANTHROPIC_API_KEY"):
        monkeypatch.delenv(var, raising=False)
    monkeypatch.setenv("MSWEA_GLOBAL_CONFIG_DIR", str(tmp_path / "empty-config"))
    out = load_agent(MINI_DIR).run("p", None, Sandbox("alpine:latest", tmp_path, "l"), tmp_path / "art", 60)
    assert out.exit_status == "NoTrajectory"
    assert "mini-extra config setup" in out.error


def test_run_without_trajectory_is_infra_error(tmp_path):
    fake_mini = tmp_path / "fake-mini"
    fake_mini.write_text("#!/bin/sh\necho 'litellm.NotFoundError: model not found' >&2\nexit 1\n")
    fake_mini.chmod(0o755)
    agent = MiniSweAgent(Path(MINI_DIR), {"adapter": "mini-swe-agent", "executable": str(fake_mini)})
    out = agent.run("p", None, Sandbox("alpine:latest", tmp_path, "l"), tmp_path / "art", 10)
    assert out.exit_status == "NoTrajectory"
    assert "exited 1" in out.error and "NotFoundError" in out.error


def test_run_timeout_is_not_error(tmp_path):
    fake_mini = tmp_path / "slow-mini"
    fake_mini.write_text("#!/bin/sh\nsleep 30\n")
    fake_mini.chmod(0o755)
    agent = MiniSweAgent(Path(MINI_DIR), {"adapter": "mini-swe-agent", "executable": str(fake_mini)})
    out = agent.run("p", None, Sandbox("alpine:latest", tmp_path, "l"), tmp_path / "art", 1)
    assert (out.exit_status, out.error) == ("Timeout", None)


@pytest.mark.llm
@pytest.mark.docker
def test_mini_solves_bash_001(tmp_path):
    bench = load_benchmark("bash-operations")
    task = bench.get_tasks(["bash-001"])[0]
    ws, art = tmp_path / "ws", tmp_path / "art"
    bench.setup(task, ws, art)
    sandbox = Sandbox(task.docker_image, ws, f"llm-{uuid.uuid4().hex[:8]}")
    try:
        sandbox.prepare()
        out = load_agent(MINI_DIR).run(bench.render_prompt(task), task, sandbox, art, 300)
    finally:
        sandbox.cleanup()
    assert out.error is None, (art / "agent.log").read_text()[-2000:]
    assert bench.evaluate(task, ws, art).status == TaskStatus.PASSED
