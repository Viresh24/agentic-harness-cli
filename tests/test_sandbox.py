import subprocess
import uuid
from pathlib import Path

import pytest

from agentic_harness.sandbox import Sandbox, SandboxError


def _labeled_containers(label: str) -> list[str]:
    out = subprocess.run(
        ["docker", "ps", "-aq", "--filter", f"label=agentic-harness={label}"],
        capture_output=True,
        text=True,
        check=True,
    )
    return out.stdout.split()


def test_run_args_absolute_mount_and_user():
    args = Sandbox("alpine:latest", Path("rel/ws"), "r1-t1").run_args()
    mount = args[args.index("-v") + 1]
    assert mount.startswith("/") and mount.endswith("rel/ws:/workspace")
    assert "--user" in args and "--rm" in args
    assert args[args.index("--label") + 1] == "agentic-harness=r1-t1"


@pytest.mark.docker
def test_exec_once_runs_in_workspace(tmp_path):
    ws, log = tmp_path / "ws", tmp_path / "exec.log"
    ws.mkdir()
    (ws / "in.txt").write_text("from host")
    sandbox = Sandbox("alpine:latest", ws, f"t-{uuid.uuid4().hex[:8]}")
    sandbox.prepare()  # pull happens here, so its progress output stays out of the agent's log
    rc = sandbox.exec_once("pwd; cat in.txt; exit 3", 120, log)
    assert rc == 3
    assert log.read_text().splitlines() == ["/workspace", "from host"]


@pytest.mark.docker
def test_cleanup_removes_labeled_containers():
    label = f"t-{uuid.uuid4().hex[:8]}"
    subprocess.run(
        ["docker", "run", "-d", "--label", f"agentic-harness={label}", "alpine:latest", "sleep", "60"],
        capture_output=True,
        check=True,
    )
    assert len(_labeled_containers(label)) == 1
    Sandbox("alpine:latest", Path("ws"), label).cleanup()
    assert _labeled_containers(label) == []


def test_cleanup_never_raises_when_nothing_to_clean():
    Sandbox("alpine:latest", Path("ws"), f"none-{uuid.uuid4().hex}").cleanup()


@pytest.mark.docker
def test_prepare_pulls_or_finds_image():
    Sandbox("alpine:latest", Path("ws"), "unused").prepare()
    inspect = subprocess.run(["docker", "image", "inspect", "alpine:latest"], capture_output=True)
    assert inspect.returncode == 0


@pytest.mark.docker
def test_prepare_missing_image_raises():
    with pytest.raises(SandboxError, match="agentic-harness-does-not-exist:nope"):
        Sandbox("agentic-harness-does-not-exist:nope", Path("ws"), "unused").prepare()
