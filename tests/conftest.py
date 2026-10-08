import os
import subprocess

import pytest


@pytest.fixture(autouse=True)
def harness_home(tmp_path, monkeypatch):
    home = tmp_path / "runs"
    monkeypatch.setenv("HARNESS_HOME", str(home))
    return home


def _docker_available() -> bool:
    try:
        return subprocess.run(["docker", "info"], capture_output=True, timeout=15).returncode == 0
    except (OSError, subprocess.TimeoutExpired):
        return False


def pytest_collection_modifyitems(config, items):
    has_docker = any("docker" in item.keywords for item in items) and _docker_available()
    run_llm = os.environ.get("HARNESS_RUN_LLM") == "1"
    for item in items:
        if "docker" in item.keywords and not has_docker:
            item.add_marker(pytest.mark.skip(reason="docker daemon not reachable"))
        if "llm" in item.keywords and not run_llm:
            item.add_marker(pytest.mark.skip(reason="set HARNESS_RUN_LLM=1 to run LLM tests"))
