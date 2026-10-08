import json
from pathlib import Path

import pytest

from agentic_harness.benchmarks import (
    BenchmarkError,
    BenchmarkNotFoundError,
    ScriptBenchmark,
    UnknownTaskError,
    load_benchmark,
)
from agentic_harness.models import TaskStatus

TOY = Path(__file__).parent / "fixtures" / "benchmarks" / "toy"


def _task(bench, task_id):
    return bench.get_tasks([task_id])[0]


@pytest.mark.parametrize(
    ("name", "first_id", "count", "image"),
    [("bash-operations", "bash-001", 5, "alpine:latest"), ("python-tasks", "py-001", 3, "python:3.11-slim")],
)
def test_list_tasks_normalizes_fields(name, first_id, count, image):
    tasks = load_benchmark(name).list_tasks()
    assert (tasks[0].id, len(tasks), tasks[0].docker_image) == (first_id, count, image)
    assert tasks[0].prompt and tasks[0].raw


def test_get_tasks_unknown_id_raises():
    with pytest.raises(UnknownTaskError) as exc:
        load_benchmark("bash-operations").get_tasks(["bash-001", "bash-999"])
    assert exc.value.missing == ["bash-999"]
    assert "bash-001" in exc.value.valid


def test_get_tasks_none_returns_all_in_order():
    assert [t.id for t in load_benchmark("python-tasks").get_tasks(None)] == ["py-001", "py-002", "py-003"]


def test_bash_setup_then_handwritten_solution_passes(tmp_path):
    bench = load_benchmark("bash-operations")
    task, ws = _task(bench, "bash-003"), tmp_path / "ws"
    bench.setup(task, ws, tmp_path / "logs")
    assert (ws / "input.txt").exists()
    (ws / "count.txt").write_text("5")
    outcome = bench.evaluate(task, ws, tmp_path / "logs")
    assert (outcome.status, outcome.passed, outcome.score) == (TaskStatus.PASSED, True, 1.0)


def test_bash_unsolved_fails(tmp_path):
    bench = load_benchmark("bash-operations")
    task, ws = _task(bench, "bash-001"), tmp_path / "ws"
    bench.setup(task, ws, tmp_path / "logs")
    outcome = bench.evaluate(task, ws, tmp_path / "logs")
    assert (outcome.status, outcome.passed, outcome.score) == (TaskStatus.FAILED, False, 0.0)
    assert "hello.txt" in outcome.details["details"]["error"]


def test_python_setup_then_solution_passes(tmp_path):
    bench = load_benchmark("python-tasks")
    task, ws = _task(bench, "py-001"), tmp_path / "ws"
    bench.setup(task, ws, tmp_path / "logs")
    assert (ws / "test_solution.py").exists()
    (ws / "solution.py").write_text("def add():\n    return 4\n")
    assert bench.evaluate(task, ws, tmp_path / "logs").status == TaskStatus.PASSED


def test_python_wrong_solution_fails(tmp_path):
    bench = load_benchmark("python-tasks")
    task, ws = _task(bench, "py-001"), tmp_path / "ws"
    bench.setup(task, ws, tmp_path / "logs")
    (ws / "solution.py").write_text("def add():\n    return 5\n")
    outcome = bench.evaluate(task, ws, tmp_path / "logs")
    assert (outcome.status, outcome.passed) == (TaskStatus.FAILED, False)
    assert "assert 5 == 4" in outcome.details["details"]["stdout"]


def test_python_prompt_mentions_solution_file():
    bench = load_benchmark("python-tasks")
    prompt = bench.render_prompt(_task(bench, "py-001"))
    assert prompt.startswith("Write a function called add()")
    assert "solution.py" in prompt


def test_bash_prompt_is_dataset_text():
    bench = load_benchmark("bash-operations")
    task = _task(bench, "bash-001")
    assert bench.render_prompt(task) == task.prompt


def test_evaluate_unparsable_output_is_error(tmp_path):
    bench = load_benchmark(str(TOY))
    task, ws = _task(bench, "toy-badjson"), tmp_path / "ws"
    bench.setup(task, ws, tmp_path / "logs")
    outcome = bench.evaluate(task, ws, tmp_path / "logs")
    assert (outcome.status, outcome.passed) == (TaskStatus.ERROR, False)
    assert "Traceback" in outcome.details["raw_stdout"]
    assert outcome.error


def test_setup_failure_raises_with_stderr(tmp_path):
    bench = load_benchmark(str(TOY))
    with pytest.raises(BenchmarkError, match="setup exploded"):
        bench.setup(_task(bench, "toy-badsetup"), tmp_path / "ws", tmp_path / "logs")


def test_evaluate_writes_logs(tmp_path):
    bench = load_benchmark(str(TOY))
    task, ws, logs = _task(bench, "toy-ok"), tmp_path / "ws", tmp_path / "logs"
    bench.setup(task, ws, logs)
    assert bench.evaluate(task, ws, logs).status == TaskStatus.PASSED
    meta = json.loads((logs / "evaluate.json").read_text())
    assert meta["returncode"] == 0 and str(ws.resolve()) in meta["argv"]
    assert "passed" in (logs / "evaluate.stdout").read_text()
    assert (logs / "setup.stdout").read_text().strip() == "ok"


def test_render_prompt_missing_template_key_raises(tmp_path):
    manifest = (TOY / "harness.yaml").read_text() + 'prompt_template: "{prompt} into {nope}"\n'
    (tmp_path / "harness.yaml").write_text(manifest.replace("dataset.json", str(TOY / "dataset.json")))
    bench = ScriptBenchmark.from_manifest(tmp_path / "harness.yaml")
    with pytest.raises(BenchmarkError, match="nope"):
        bench.render_prompt(_task(bench, "toy-ok"))


def test_load_benchmark_not_found_lists_available():
    with pytest.raises(BenchmarkNotFoundError, match="bash-operations"):
        load_benchmark("nope")


def test_load_benchmark_class_override():
    bench = load_benchmark(str(TOY.parent / "custom-class"))
    assert isinstance(bench, ScriptBenchmark) and bench.name == "custom-class"
    assert [t.id for t in bench.list_tasks()][0] == "toy-ok"
